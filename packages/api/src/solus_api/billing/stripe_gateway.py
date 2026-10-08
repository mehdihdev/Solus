"""Outbound Stripe API — the money-in *initiation* surface (SOLUSDEV-83 follow-up).

Creates Stripe Customers, Checkout Sessions, and Billing Portal sessions. This is
the only place Solus calls Stripe outbound; the inbound webhook lives in
routers/billing.py + billing/stripe_events.py.

Security (CLAUDE.md §7): the Stripe SECRET key is sourced from the SecretStore
under `stripe_api_key` — never from config, env, or logs — and is passed per call
via the SDK's `api_key` option (no global mutable `stripe.api_key`, so concurrent
requests never race on it). Absent key ⇒ BillingUnconfiguredError, which the route
maps to 503, mirroring the webhook's `billing_unconfigured`.
"""

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import stripe

from solus_api.connectors.secrets import SecretNotFoundError, SecretStore

logger = logging.getLogger("solus.billing.stripe_gateway")

# SecretStore ref for the Stripe secret API key (sk_...). Provisioned by an
# operator into AWS Secrets Manager / the local Fernet store, like the LLM keys.
STRIPE_API_KEY_NAME = "stripe_api_key"

CheckoutMode = Literal["subscription", "payment"]
Proration = Literal["create_prorations", "none", "always_invoice"]
CompDuration = Literal["once", "repeating", "forever"]
CancelMode = Literal["immediate", "period_end"]

# Subscription metadata written on every staff-initiated write (SOLUSDEV-313).
ADMIN_ACTION_METADATA_KEY = "solus_admin_action_id"
ADMIN_ACTOR_METADATA_KEY = "solus_actor"
COMP_PREV_PRICE_METADATA_KEY = "solus_comp_prev_price"
COMP_PLAN_METADATA_KEY = "solus_comp_plan"

MIN_COMP_MONTHS = 1
MAX_COMP_MONTHS = 36
_MAX_METADATA_KEYS = 10
_MAX_METADATA_KEY_LEN = 40
_MAX_METADATA_VALUE_LEN = 500
_RESERVED_METADATA_KEYS = frozenset({ADMIN_ACTION_METADATA_KEY, ADMIN_ACTOR_METADATA_KEY})
_DEAD_SCHEDULE_STATUSES = frozenset({"released", "canceled", "completed"})

# Ids/actors flow into Stripe idempotency keys + metadata: safe charset only, no PII
# (no '@', spaces). Length bounded well under Stripe's 255-char key / 500-char value.
_AUDIT_TOKEN_RE = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_SUB_ID_RE = re.compile(r"sub_[A-Za-z0-9]{1,64}")
_SCHEDULE_ID_RE = re.compile(r"sub_sched_[A-Za-z0-9]{1,64}")
_PRICE_ID_RE = re.compile(r"price_[A-Za-z0-9]{1,64}")
_COMP_COUPON_RE = re.compile(r"solus-comp-(once|forever|repeating-([1-9][0-9]?))")


class BillingUnconfiguredError(RuntimeError):
    """No Stripe secret key is provisioned — Solus cannot call Stripe yet."""


class StripeOperationError(RuntimeError):
    """A Stripe call failed. Carries Stripe's error `code`/`http_status` and whether
    a retry could help. The message never includes Stripe's raw text (which can
    echo request data) and never the API key."""

    def __init__(
        self,
        operation: str,
        *,
        code: str | None = None,
        http_status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(f"Stripe {operation} failed ({code or 'no_code'})")
        self.operation = operation
        self.code = code
        self.http_status = http_status
        self.retryable = retryable


class StripeIdempotencyConflictError(StripeOperationError):
    """The idempotency key was already used with different parameters."""


class StripeResourceMissingError(StripeOperationError):
    """Stripe reported `resource_missing` (unknown/deleted id)."""


def _check_token(value: object, label: str) -> str:
    if not isinstance(value, str) or not _AUDIT_TOKEN_RE.fullmatch(value):
        raise ValueError(f"{label} must match [A-Za-z0-9_.:-]{{1,64}}")
    return value


def _check_id(value: object, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def _check_comp_coupon(coupon_id: object) -> str:
    return _check_id(coupon_id, _COMP_COUPON_RE, "comp coupon id")


def _check_months(months: object) -> int:
    if type(months) is not int or not MIN_COMP_MONTHS <= months <= MAX_COMP_MONTHS:
        raise ValueError(f"months must be an int in {MIN_COMP_MONTHS}..{MAX_COMP_MONTHS}")
    return months


def _check_extra_metadata(extra: Mapping[str, str] | None) -> dict[str, str]:
    if extra is None:
        return {}
    if len(extra) > _MAX_METADATA_KEYS:
        raise ValueError("too many metadata keys")
    for k, v in extra.items():
        if k in _RESERVED_METADATA_KEYS:
            raise ValueError(f"metadata key {k!r} is reserved")
        if not isinstance(k, str) or not 0 < len(k) <= _MAX_METADATA_KEY_LEN:
            raise ValueError("invalid metadata key")
        if not isinstance(v, str) or len(v) > _MAX_METADATA_VALUE_LEN:
            raise ValueError("invalid metadata value")
    return dict(extra)


def _audit_metadata(audit_action_id: str, actor: str | None) -> dict[str, str]:
    meta = {ADMIN_ACTION_METADATA_KEY: audit_action_id}
    if actor is not None:
        meta[ADMIN_ACTOR_METADATA_KEY] = actor
    return meta


def _idem(audit_action_id: str, op: str) -> str:
    return f"solus-admin-{audit_action_id}-{op}"


def _g(obj: Any, name: str, default: Any = None) -> Any:
    """Field access tolerant of StripeObject (a dict), plain dicts and attr objects.
    Mapping access first: `StripeObject.items` is the dict method, not the field."""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _id_of(ref: Any) -> str | None:
    """An expandable Stripe reference: either an id string or an object with `id`."""
    if ref is None:
        return None
    return ref if isinstance(ref, str) else (_g(ref, "id") or None)


def _coupon_ids(discounts: Any) -> list[str]:
    ids: list[str] = []
    for d in discounts or []:
        if isinstance(d, str):  # un-expanded discount id: coupon unknown
            continue
        coupon = _g(d, "coupon") or _g(_g(d, "source"), "coupon")
        cid = _id_of(coupon)
        if cid:
            ids.append(cid)
    return ids


@dataclass(frozen=True)
class SubscriptionSnapshot:
    """Stable projection of a Stripe Subscription for the service layer."""

    subscription_id: str
    status: str
    price_id: str | None
    item_id: str | None
    item_count: int
    quantity: int
    customer_id: str | None
    cancel_at: int | None
    cancel_at_period_end: bool
    current_period_end: int | None
    coupon_id: str | None
    schedule_id: str | None
    latest_invoice_id: str | None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def stripe_refs(self) -> dict[str, str]:
        refs = {
            "subscription": self.subscription_id,
            "customer": self.customer_id,
            "price": self.price_id,
            "coupon": self.coupon_id,
            "schedule": self.schedule_id,
            "invoice": self.latest_invoice_id,
        }
        return {k: v for k, v in refs.items() if v}


@dataclass(frozen=True)
class CancelResult:
    already_canceled: bool
    subscription: SubscriptionSnapshot | None
    subscription_id: str

    def stripe_refs(self) -> dict[str, str]:
        if self.subscription is not None:
            return self.subscription.stripe_refs()
        return {"subscription": self.subscription_id}


@dataclass(frozen=True)
class ScheduleResult:
    """Outcome of creating (revert schedule) or releasing a Subscription Schedule."""

    schedule_id: str | None
    subscription_id: str | None
    revert_price_id: str | None = None
    comp_months: int | None = None
    already_released: bool = False

    def stripe_refs(self) -> dict[str, str]:
        refs = {
            "subscription": self.subscription_id,
            "schedule": self.schedule_id,
            "price": self.revert_price_id,
        }
        return {k: v for k, v in refs.items() if v}


def snapshot_from_stripe(sub: Any) -> SubscriptionSnapshot:
    items = _g(_g(sub, "items"), "data") or []
    item = items[0] if items else None
    period_end = _g(sub, "current_period_end") or _g(item, "current_period_end")
    coupons = _coupon_ids(_g(sub, "discounts")) or _coupon_ids([_g(sub, "discount")])
    return SubscriptionSnapshot(
        subscription_id=str(_g(sub, "id")),
        status=str(_g(sub, "status", "")),
        price_id=_id_of(_g(_g(item, "price"), "id")),
        item_id=_g(item, "id"),
        item_count=len(items),
        quantity=int(_g(item, "quantity") or 1),
        customer_id=_id_of(_g(sub, "customer")),
        cancel_at=_g(sub, "cancel_at"),
        cancel_at_period_end=bool(_g(sub, "cancel_at_period_end", False)),
        current_period_end=period_end,
        coupon_id=coupons[0] if coupons else None,
        schedule_id=_id_of(_g(sub, "schedule")),
        latest_invoice_id=_id_of(_g(sub, "latest_invoice")),
        metadata=dict(_g(sub, "metadata") or {}),
    )


def _translate(operation: str, exc: stripe.StripeError) -> StripeOperationError:
    """Map an SDK error to a typed one without echoing Stripe's message text."""
    code = getattr(exc, "code", None)
    status = getattr(exc, "http_status", None)
    if isinstance(exc, stripe.IdempotencyError):
        return StripeIdempotencyConflictError(operation, code=code, http_status=status)
    if code == "resource_missing":
        return StripeResourceMissingError(operation, code=code, http_status=status)
    retryable = isinstance(exc, stripe.APIConnectionError | stripe.RateLimitError) or (
        isinstance(exc, stripe.APIError) and not isinstance(exc, stripe.InvalidRequestError)
    )
    return StripeOperationError(operation, code=code, http_status=status, retryable=retryable)


class StripeGateway:
    """Thin async wrapper over the Stripe SDK, keyed from the SecretStore."""

    def __init__(self, secret_store: SecretStore) -> None:
        self._secret_store = secret_store

    async def _api_key(self) -> str:
        try:
            return await self._secret_store.get(STRIPE_API_KEY_NAME)
        except SecretNotFoundError as exc:
            raise BillingUnconfiguredError(
                f"No Stripe API key; set {STRIPE_API_KEY_NAME!r} in Secrets Manager / SecretStore."
            ) from exc

    async def get_or_create_customer(
        self, *, existing: str | None, email: str, user_id: str
    ) -> str:
        """Reuse the user's Stripe customer id if we already have one, else create
        one tagged with the Solus user id. Returns the customer id."""
        if existing:
            return existing
        key = await self._api_key()
        # Stripe's SDK params are strict TypedDicts; build a dynamic dict and splat.
        # Idempotency key (per user) collapses a double-submit into one customer.
        params: dict[str, Any] = {
            "metadata": {"solus_user_id": user_id},
            "api_key": key,
            "idempotency_key": f"solus-customer-{user_id}",
        }
        if email:
            params["email"] = email
        customer = await stripe.Customer.create_async(**params)
        return str(customer.id)

    async def create_checkout_session(
        self,
        *,
        mode: CheckoutMode,
        price_id: str,
        customer: str,
        user_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int | None = None,
    ) -> str:
        """Create a hosted Checkout Session and return its redirect URL. The user
        id rides in both `client_reference_id` and `metadata.solus_user_id`, and
        the price id in `metadata.price_id`, so the webhook can attribute the
        purchase and (for packs) grant the right credits."""
        key = await self._api_key()
        params: dict[str, Any] = {
            "mode": mode,
            "line_items": [{"price": price_id, "quantity": 1}],
            "customer": customer,
            "client_reference_id": user_id,
            "metadata": {"solus_user_id": user_id, "price_id": price_id},
            "success_url": success_url,
            "cancel_url": cancel_url,
            "api_key": key,
        }
        if mode == "subscription" and trial_days:
            params["subscription_data"] = {"trial_period_days": trial_days}
        session = await stripe.checkout.Session.create_async(**params)
        return str(session.url)

    async def create_portal_session(self, *, customer: str, return_url: str) -> str:
        """Create a Stripe-hosted Billing Portal session (manage/cancel/update
        card) and return its URL."""
        key = await self._api_key()
        params: dict[str, Any] = {"customer": customer, "return_url": return_url, "api_key": key}
        session = await stripe.billing_portal.Session.create_async(**params)
        return str(session.url)

    # ------------------------------------------------------------------ #
    # SOLUSDEV-313: staff subscription operations. Every write validates all
    # arguments BEFORE the key is fetched or any network call is made, sends a
    # deterministic idempotency key `solus-admin-<audit_action_id>-<op>`, and
    # raises typed errors (StripeOperationError family).
    # ------------------------------------------------------------------ #

    async def _call(self, operation: str, fn: Any, *args: Any, **params: Any) -> Any:
        key = await self._api_key()
        try:
            return await fn(*args, api_key=key, **params)
        except stripe.StripeError as exc:
            logger.warning(
                "stripe %s failed code=%s status=%s type=%s",
                operation,
                getattr(exc, "code", None),
                getattr(exc, "http_status", None),
                type(exc).__name__,
            )
            raise _translate(operation, exc) from exc

    async def retrieve_subscription(self, sub_id: str) -> SubscriptionSnapshot:
        """Read a subscription (item id, price, coupon, schedule, metadata)."""
        _check_id(sub_id, _SUB_ID_RE, "subscription id")
        sub = await self._call(
            "subscription.retrieve",
            stripe.Subscription.retrieve_async,
            sub_id,
            expand=["discounts"],
        )
        return snapshot_from_stripe(sub)

    async def _modify_subscription(
        self, sub_id: str, op: str, audit_action_id: str, actor: str | None, **params: Any
    ) -> SubscriptionSnapshot:
        metadata = {**params.pop("metadata", {}), **_audit_metadata(audit_action_id, actor)}
        sub = await self._call(
            f"subscription.update[{op}]",
            stripe.Subscription.modify_async,
            sub_id,
            metadata=metadata,
            idempotency_key=_idem(audit_action_id, op),
            expand=["discounts"],
            **params,
        )
        return snapshot_from_stripe(sub)

    async def change_subscription_price(
        self,
        sub_id: str,
        price_id: str,
        *,
        proration: Proration,
        audit_action_id: str,
        actor: str,
        coupon_id: str | None = None,
        extra_metadata: Mapping[str, str] | None = None,
    ) -> SubscriptionSnapshot:
        """Swap the subscription's single item to `price_id` in ONE update call
        (optionally attaching a comp coupon in the same call). `proration` is passed
        straight to Stripe's `proration_behavior`.

        If a Subscription Schedule is attached (`snapshot.schedule_id`), price
        changes must go through the schedule: release it first
        (`release_subscription_schedule`) — the caller owns that ordering."""
        _check_id(sub_id, _SUB_ID_RE, "subscription id")
        _check_id(price_id, _PRICE_ID_RE, "price id")
        if proration not in ("create_prorations", "none", "always_invoice"):
            raise ValueError("invalid proration behavior")
        _check_token(audit_action_id, "audit_action_id")
        _check_token(actor, "actor")
        if coupon_id is not None:
            _check_comp_coupon(coupon_id)
        extra = _check_extra_metadata(extra_metadata)
        current = await self.retrieve_subscription(sub_id)
        if current.item_id is None or current.item_count != 1:
            raise StripeOperationError(
                "subscription.update[change-price]", code="unsupported_subscription_shape"
            )
        params: dict[str, Any] = {
            "items": [{"id": current.item_id, "price": price_id}],
            "proration_behavior": proration,
            "metadata": extra,
        }
        if coupon_id is not None:
            params["discounts"] = [{"coupon": coupon_id}]
        return await self._modify_subscription(
            sub_id, "change-price", audit_action_id, actor, **params
        )

    async def ensure_comp_coupon(self, duration: CompDuration, months: int | None = None) -> str:
        """Create (idempotently) the 100%-off comp coupon and return its
        deterministic id: `solus-comp-once`, `solus-comp-repeating-<N>` (N 1..36) or
        `solus-comp-forever`. `resource_already_exists` counts as success."""
        params: dict[str, Any] = {"percent_off": 100, "duration": duration}
        if duration == "repeating":
            coupon_id = f"solus-comp-repeating-{_check_months(months)}"
            params["duration_in_months"] = months
        elif duration in ("once", "forever") and months is None:
            coupon_id = f"solus-comp-{duration}"
        else:
            raise ValueError("invalid comp coupon duration/months combination")
        try:
            await self._call(
                "coupon.create",
                stripe.Coupon.create_async,
                id=coupon_id,
                name="Solus comp",
                idempotency_key=f"solus-coupon-{coupon_id}",
                **params,
            )
        except StripeOperationError as exc:
            if exc.code != "resource_already_exists":
                raise
        return coupon_id

    async def apply_comp_coupon(
        self, sub_id: str, coupon_id: str, audit_action_id: str, actor: str
    ) -> SubscriptionSnapshot:
        """Attach a comp coupon (replaces the subscription's discounts)."""
        _check_id(sub_id, _SUB_ID_RE, "subscription id")
        _check_comp_coupon(coupon_id)
        _check_token(audit_action_id, "audit_action_id")
        _check_token(actor, "actor")
        return await self._modify_subscription(
            sub_id, "apply-coupon", audit_action_id, actor, discounts=[{"coupon": coupon_id}]
        )

    async def remove_comp_coupon(
        self, sub_id: str, audit_action_id: str, actor: str
    ) -> SubscriptionSnapshot:
        """Clear all discounts from the subscription."""
        _check_id(sub_id, _SUB_ID_RE, "subscription id")
        _check_token(audit_action_id, "audit_action_id")
        _check_token(actor, "actor")
        return await self._modify_subscription(
            sub_id, "remove-coupon", audit_action_id, actor, discounts=""
        )

    async def cancel_subscription(
        self,
        sub_id: str,
        *,
        mode: CancelMode,
        invoice_now: bool,
        prorate: bool,
        audit_action_id: str,
        actor: str | None,
    ) -> CancelResult:
        """`immediate` -> subscriptions.cancel(invoice_now, prorate) (Stripe's cancel
        endpoint accepts no metadata, so the audit trail is the idempotency key);
        `period_end` -> update(cancel_at_period_end=True) with audit metadata
        (invoice_now/prorate are validated but not applicable). Already-canceled or
        missing subscriptions are success with `already_canceled=True`.
        Release any attached schedule first (see `find_schedule_for_subscription`)."""
        _check_id(sub_id, _SUB_ID_RE, "subscription id")
        if mode not in ("immediate", "period_end"):
            raise ValueError("invalid cancel mode")
        if not isinstance(invoice_now, bool) or not isinstance(prorate, bool):
            raise ValueError("invoice_now and prorate must be bool")
        _check_token(audit_action_id, "audit_action_id")
        if actor is not None:
            _check_token(actor, "actor")
        try:
            if mode == "immediate":
                sub = await self._call(
                    "subscription.cancel",
                    stripe.Subscription.cancel_async,
                    sub_id,
                    invoice_now=invoice_now,
                    prorate=prorate,
                    idempotency_key=_idem(audit_action_id, "cancel"),
                )
                return CancelResult(False, snapshot_from_stripe(sub), sub_id)
            snap = await self._modify_subscription(
                sub_id, "cancel", audit_action_id, actor, cancel_at_period_end=True
            )
            return CancelResult(False, snap, sub_id)
        except StripeResourceMissingError:
            return CancelResult(True, None, sub_id)
        except StripeIdempotencyConflictError:
            raise
        except StripeOperationError:
            if (existing := await self._canceled_snapshot(sub_id)) is None:
                raise
            return CancelResult(True, existing, sub_id)

    async def _canceled_snapshot(self, sub_id: str) -> SubscriptionSnapshot | None:
        """After a failed cancel: the snapshot if the subscription is already
        canceled, else None (the original error should then propagate)."""
        try:
            snap = await self.retrieve_subscription(sub_id)
        except StripeOperationError:
            return None
        return snap if snap.status == "canceled" else None

    # -- Subscription Schedules (comp-end price revert) ------------------ #

    async def find_schedule_for_subscription(self, sub_id: str) -> str | None:
        """The id of the schedule attached to the subscription, if any. While one is
        attached, price changes must go through it — release it first."""
        return (await self.retrieve_subscription(sub_id)).schedule_id

    async def create_revert_schedule(
        self,
        sub_id: str,
        revert_price_id: str,
        *,
        comp_months: int,
        audit_action_id: str,
        actor: str,
    ) -> ScheduleResult:
        """Make (or reuse) a schedule from the subscription: phase 1 keeps the current
        items/discounts for `comp_months` months, phase 2 uses `revert_price_id`;
        `end_behavior=release` hands the subscription back afterwards. 'once' is
        comp_months=1. Phase 1 runs from the current phase start (Stripe's
        `from_subscription` phase), so a comp applied mid-cycle reverts at the end of
        the Nth month counted from that cycle's start. Two calls: create
        (from_subscription takes no other params) then modify."""
        _check_id(sub_id, _SUB_ID_RE, "subscription id")
        _check_id(revert_price_id, _PRICE_ID_RE, "price id")
        _check_months(comp_months)
        _check_token(audit_action_id, "audit_action_id")
        _check_token(actor, "actor")
        existing = await self.find_schedule_for_subscription(sub_id)
        if existing:
            schedule = await self._call(
                "subscription_schedule.retrieve",
                stripe.SubscriptionSchedule.retrieve_async,
                existing,
            )
        else:
            schedule = await self._call(
                "subscription_schedule.create",
                stripe.SubscriptionSchedule.create_async,
                from_subscription=sub_id,
                idempotency_key=_idem(audit_action_id, "schedule-create"),
            )
        phases = _g(schedule, "phases") or []
        if not phases:
            raise StripeOperationError("subscription_schedule.create", code="no_phases")
        current = phases[0]
        items = [
            {"price": _id_of(_g(i, "price")), "quantity": int(_g(i, "quantity") or 1)}
            for i in _g(current, "items") or []
        ]
        phase_one: dict[str, Any] = {
            "items": items,
            "start_date": _g(current, "start_date"),
            "duration": {"interval": "month", "interval_count": comp_months},
            "proration_behavior": "none",
        }
        if coupons := _coupon_ids(_g(current, "discounts")):
            phase_one["discounts"] = [{"coupon": c} for c in coupons]
        phase_two = {
            "items": [{"price": revert_price_id, "quantity": items[0]["quantity"] if items else 1}],
            "proration_behavior": "none",
        }
        schedule_id = str(_g(schedule, "id"))
        await self._call(
            "subscription_schedule.update",
            stripe.SubscriptionSchedule.modify_async,
            schedule_id,
            phases=[phase_one, phase_two],
            end_behavior="release",
            metadata=_audit_metadata(audit_action_id, actor),
            idempotency_key=_idem(audit_action_id, "schedule-modify"),
        )
        return ScheduleResult(
            schedule_id=schedule_id,
            subscription_id=sub_id,
            revert_price_id=revert_price_id,
            comp_months=comp_months,
        )

    async def release_subscription_schedule(
        self, sub_or_schedule_id: str, audit_action_id: str, actor: str
    ) -> ScheduleResult:
        """Release a schedule (the subscription keeps its current phase's config).
        Accepts a `sub_sched_...` or a `sub_...` id; no schedule / missing / already
        released is success with `already_released=True`."""
        _check_token(audit_action_id, "audit_action_id")
        _check_token(actor, "actor")
        if isinstance(sub_or_schedule_id, str) and _SCHEDULE_ID_RE.fullmatch(sub_or_schedule_id):
            schedule_id: str | None = sub_or_schedule_id
            sub_id = None
        else:
            sub_id = _check_id(sub_or_schedule_id, _SUB_ID_RE, "subscription or schedule id")
            schedule_id = await self.find_schedule_for_subscription(sub_id)
        if schedule_id is None:
            return ScheduleResult(None, sub_id, already_released=True)
        try:
            await self._call(
                "subscription_schedule.release",
                stripe.SubscriptionSchedule.release_async,
                schedule_id,
                idempotency_key=_idem(audit_action_id, "schedule-release"),
            )
        except StripeResourceMissingError:
            return ScheduleResult(schedule_id, sub_id, already_released=True)
        except StripeIdempotencyConflictError:
            raise
        except StripeOperationError:
            if not await self._schedule_is_dead(schedule_id):
                raise
            return ScheduleResult(schedule_id, sub_id, already_released=True)
        return ScheduleResult(schedule_id, sub_id)

    async def _schedule_is_dead(self, schedule_id: str) -> bool:
        try:
            schedule = await self._call(
                "subscription_schedule.retrieve",
                stripe.SubscriptionSchedule.retrieve_async,
                schedule_id,
            )
        except StripeOperationError:
            return False
        return _g(schedule, "status") in _DEAD_SCHEDULE_STATUSES
