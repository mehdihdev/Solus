"""In-memory stand-in for `StripeGateway` (SOLUSDEV-313), reusable by service tests
(admin_operations, stripe_cancel, account_deletion, webhook).

It implements the same public async interface, validates arguments with the real
gateway's validators, records every call, supports failure injection, and replays
results for a repeated idempotency key (raising `StripeIdempotencyConflictError`
when the key is reused with different parameters) exactly as Stripe does.

    fake = FakeStripeGateway()
    fake.seed_subscription("sub_1", price_id="price_pro")
    fake.fail_next("cancel_subscription", FakeStripeGateway.connection_error())
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from solus_api.billing.stripe_gateway import (
    _CUSTOMER_ID_RE,
    _PRICE_ID_RE,
    _SCHEDULE_ID_RE,
    _SUB_ID_RE,
    _TERMINAL_SUBSCRIPTION_STATUSES,
    CancelMode,
    CancelResult,
    CompDuration,
    Proration,
    ScheduleResult,
    StripeIdempotencyConflictError,
    StripeOperationError,
    StripeResourceMissingError,
    SubscriptionListTruncatedError,
    SubscriptionSnapshot,
    _check_comp_coupon,
    _check_extra_metadata,
    _check_id,
    _check_months,
    _check_token,
    _idem,
)

_DEFAULT_PERIOD_END = 1_900_000_000


@dataclass(frozen=True)
class FakeCall:
    method: str
    args: tuple[Any, ...]
    kwargs: Mapping[str, Any]


@dataclass(frozen=True)
class FakeCustomer:
    """The slice of a Stripe Customer that redaction may touch (or must leave alone)."""

    name: str = ""
    email: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass
class FakeStripeGateway:
    subscriptions: dict[str, SubscriptionSnapshot] = field(default_factory=dict)
    customers: dict[str, FakeCustomer] = field(default_factory=dict)
    coupons: set[str] = field(default_factory=set)
    schedules: dict[str, ScheduleResult] = field(default_factory=dict)
    calls: list[FakeCall] = field(default_factory=list)
    _failures: dict[str, list[Exception]] = field(default_factory=dict)
    _always: dict[str, Exception] = field(default_factory=dict)
    _idem_store: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    _hidden: set[str] = field(default_factory=set)
    _list_cap: int | None = None

    # ---- test helpers --------------------------------------------------- #

    def seed_subscription(
        self,
        sub_id: str,
        *,
        price_id: str = "price_seed",
        status: str = "active",
        customer_id: str | None = "cus_fake",
        coupon_id: str | None = None,
        coupon_ids: tuple[str, ...] = (),
        schedule_id: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> SubscriptionSnapshot:
        if coupon_id is not None and not coupon_ids:
            coupon_ids = (coupon_id,)
        elif coupon_ids and coupon_id is None:
            coupon_id = next((c for c in coupon_ids if c.startswith("solus-comp-")), coupon_ids[0])
        snap = SubscriptionSnapshot(
            subscription_id=sub_id,
            status=status,
            price_id=price_id,
            item_id=f"si_{sub_id}",
            item_count=1,
            quantity=1,
            customer_id=customer_id,
            cancel_at=None,
            cancel_at_period_end=False,
            current_period_end=_DEFAULT_PERIOD_END,
            coupon_id=coupon_id,
            schedule_id=schedule_id,
            latest_invoice_id=f"in_{sub_id}",
            metadata=dict(metadata or {}),
            coupon_ids=coupon_ids,
        )
        self.subscriptions[sub_id] = snap
        return snap

    def seed_customer(
        self,
        customer_id: str,
        *,
        name: str = "",
        email: str = "",
        metadata: Mapping[str, str] | None = None,
    ) -> FakeCustomer:
        """A Stripe Customer record, so tests can assert what redaction touched."""
        customer = FakeCustomer(name=name, email=email, metadata=dict(metadata or {}))
        self.customers[customer_id] = customer
        return customer

    def hide_from_listing(self, sub_id: str) -> None:
        """Retrievable but absent from `list_customer_subscriptions` (listing lag)."""
        self._hidden.add(sub_id)

    def truncate_listing_after(self, count: int) -> None:
        """Make `list_customer_subscriptions` hit its pagination cap after `count` ids."""
        self._list_cap = count

    def calls_to(self, method: str) -> list[FakeCall]:
        return [c for c in self.calls if c.method == method]

    def fail_next(self, method: str, exc: Exception, times: int = 1) -> None:
        self._failures.setdefault(method, []).extend([exc] * times)

    def fail_always(self, method: str, exc: Exception) -> None:
        self._always[method] = exc

    def clear_failures(self) -> None:
        self._failures.clear()
        self._always.clear()

    @staticmethod
    def connection_error() -> StripeOperationError:
        return StripeOperationError("fake", code=None, retryable=True)

    @staticmethod
    def idempotency_conflict() -> StripeIdempotencyConflictError:
        return StripeIdempotencyConflictError("fake", code="idempotency_error")

    @staticmethod
    def resource_missing() -> StripeResourceMissingError:
        return StripeResourceMissingError("fake", code="resource_missing")

    # ---- internals ------------------------------------------------------ #

    def _enter(self, method: str, args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> None:
        self.calls.append(FakeCall(method, args, dict(kwargs)))
        queue = self._failures.get(method)
        if queue:
            raise queue.pop(0)
        if method in self._always:
            raise self._always[method]

    def _once(self, key: str, fingerprint: Any, run: Callable[[], Any]) -> Any:
        if key in self._idem_store:
            seen, result = self._idem_store[key]
            if seen != fingerprint:
                raise self.idempotency_conflict()
            return result
        result = run()
        self._idem_store[key] = (fingerprint, result)
        return result

    def _get(self, sub_id: str) -> SubscriptionSnapshot:
        if sub_id not in self.subscriptions:
            raise self.resource_missing()
        return self.subscriptions[sub_id]

    def _put(self, sub_id: str, **changes: Any) -> SubscriptionSnapshot:
        snap = replace(self._get(sub_id), **changes)
        self.subscriptions[sub_id] = snap
        return snap

    def _audit(
        self, snap: SubscriptionSnapshot, audit: str, actor: str | None, extra: Mapping[str, str]
    ) -> dict[str, str]:
        meta = {**snap.metadata, **extra, "solus_admin_action_id": audit}
        if actor is not None:
            meta["solus_actor"] = actor
        return meta

    # ---- customer / checkout (parity with the real gateway) -------------- #

    async def get_or_create_customer(
        self, *, existing: str | None, email: str, user_id: str
    ) -> str:
        if existing:
            return existing
        self._enter("get_or_create_customer", (), {"email": email, "user_id": user_id})
        return f"cus_fake_{user_id}"

    async def create_checkout_session(self, **kwargs: Any) -> str:
        self._enter("create_checkout_session", (), kwargs)
        return "https://checkout.stripe.test/c/fake"

    async def create_portal_session(self, *, customer: str, return_url: str) -> str:
        self._enter("create_portal_session", (), {"customer": customer, "return_url": return_url})
        return "https://billing.stripe.test/p/fake"

    # ---- subscription operations ---------------------------------------- #

    async def retrieve_subscription(self, sub_id: str) -> SubscriptionSnapshot:
        _check_id(sub_id, _SUB_ID_RE, "subscription id")
        self._enter("retrieve_subscription", (sub_id,), {})
        return self._get(sub_id)

    async def list_customer_subscriptions(self, customer_id: str) -> list[str]:
        _check_id(customer_id, _CUSTOMER_ID_RE, "customer id")
        self._enter("list_customer_subscriptions", (customer_id,), {})
        live = [
            s.subscription_id
            for s in self.subscriptions.values()
            if s.customer_id == customer_id
            and s.status not in _TERMINAL_SUBSCRIPTION_STATUSES
            and s.subscription_id not in self._hidden
        ]
        if self._list_cap is not None and len(live) > self._list_cap:
            raise SubscriptionListTruncatedError(live[: self._list_cap])
        return live

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
        _check_id(sub_id, _SUB_ID_RE, "subscription id")
        _check_id(price_id, _PRICE_ID_RE, "price id")
        if proration not in ("create_prorations", "none", "always_invoice"):
            raise ValueError("invalid proration behavior")
        _check_token(audit_action_id, "audit_action_id")
        _check_token(actor, "actor")
        if coupon_id is not None:
            _check_comp_coupon(coupon_id)
        extra = _check_extra_metadata(extra_metadata)
        kwargs = {
            "proration": proration,
            "audit_action_id": audit_action_id,
            "actor": actor,
            "coupon_id": coupon_id,
            "extra_metadata": extra,
        }
        self._enter("change_subscription_price", (sub_id, price_id), kwargs)

        def run() -> SubscriptionSnapshot:
            snap = self._get(sub_id)
            changes: dict[str, Any] = {
                "price_id": price_id,
                "metadata": self._audit(snap, audit_action_id, actor, extra),
            }
            if coupon_id is not None:
                changes["coupon_id"] = coupon_id
                changes["coupon_ids"] = (coupon_id,)
            return self._put(sub_id, **changes)

        return self._once(_idem(audit_action_id, "change-price"), (sub_id, price_id, kwargs), run)  # type: ignore[no-any-return]

    async def ensure_comp_coupon(self, duration: CompDuration, months: int | None = None) -> str:
        if duration == "repeating":
            coupon_id = f"solus-comp-repeating-{_check_months(months)}"
        elif duration in ("once", "forever") and months is None:
            coupon_id = f"solus-comp-{duration}"
        else:
            raise ValueError("invalid comp coupon duration/months combination")
        self._enter("ensure_comp_coupon", (duration, months), {})
        self.coupons.add(coupon_id)
        return coupon_id

    async def apply_comp_coupon(
        self, sub_id: str, coupon_id: str, audit_action_id: str, actor: str
    ) -> SubscriptionSnapshot:
        _check_id(sub_id, _SUB_ID_RE, "subscription id")
        _check_comp_coupon(coupon_id)
        _check_token(audit_action_id, "audit_action_id")
        _check_token(actor, "actor")
        self._enter("apply_comp_coupon", (sub_id, coupon_id, audit_action_id, actor), {})

        def run() -> SubscriptionSnapshot:
            snap = self._get(sub_id)
            meta = self._audit(snap, audit_action_id, actor, {})
            return self._put(sub_id, coupon_id=coupon_id, coupon_ids=(coupon_id,), metadata=meta)

        return self._once(  # type: ignore[no-any-return]
            _idem(audit_action_id, "apply-coupon"), (sub_id, coupon_id), run
        )

    async def remove_comp_coupon(
        self, sub_id: str, audit_action_id: str, actor: str
    ) -> SubscriptionSnapshot:
        _check_id(sub_id, _SUB_ID_RE, "subscription id")
        _check_token(audit_action_id, "audit_action_id")
        _check_token(actor, "actor")
        self._enter("remove_comp_coupon", (sub_id, audit_action_id, actor), {})

        def run() -> SubscriptionSnapshot:
            snap = self._get(sub_id)
            meta = self._audit(snap, audit_action_id, actor, {})
            return self._put(sub_id, coupon_id=None, coupon_ids=(), metadata=meta)

        return self._once(  # type: ignore[no-any-return]
            _idem(audit_action_id, "remove-coupon"), (sub_id,), run
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
        _check_id(sub_id, _SUB_ID_RE, "subscription id")
        if mode not in ("immediate", "period_end"):
            raise ValueError("invalid cancel mode")
        if not isinstance(invoice_now, bool) or not isinstance(prorate, bool):
            raise ValueError("invoice_now and prorate must be bool")
        _check_token(audit_action_id, "audit_action_id")
        if actor is not None:
            _check_token(actor, "actor")
        kwargs = {"mode": mode, "invoice_now": invoice_now, "prorate": prorate}
        self._enter(
            "cancel_subscription",
            (sub_id,),
            {**kwargs, "audit_action_id": audit_action_id, "actor": actor},
        )

        def run() -> CancelResult:
            if sub_id not in self.subscriptions:
                return CancelResult(True, None, sub_id)
            snap = self.subscriptions[sub_id]
            if snap.status == "canceled":
                return CancelResult(True, snap, sub_id)
            if mode == "immediate":
                return CancelResult(False, self._put(sub_id, status="canceled"), sub_id)
            meta = self._audit(snap, audit_action_id, actor, {})
            return CancelResult(
                False, self._put(sub_id, cancel_at_period_end=True, metadata=meta), sub_id
            )

        return self._once(  # type: ignore[no-any-return]
            _idem(audit_action_id, "cancel"), (sub_id, kwargs), run
        )

    # ---- customer redaction --------------------------------------------- #

    async def redact_customer(self, customer_id: str, *, audit_action_id: str) -> None:
        _check_id(customer_id, _CUSTOMER_ID_RE, "customer id")
        _check_token(audit_action_id, "audit_action_id")
        try:
            self._enter("redact_customer", (customer_id,), {"audit_action_id": audit_action_id})
        except StripeResourceMissingError:
            return  # the real gateway treats an already-gone customer as success

        def run() -> None:
            current = self.customers.get(customer_id)
            if current is None:
                return
            meta = {k: v for k, v in current.metadata.items() if k != "solus_user_id"}
            self.customers[customer_id] = replace(current, name="", metadata=meta)

        self._once(_idem(audit_action_id, "redact-customer"), (customer_id,), run)

    # ---- schedules ------------------------------------------------------ #

    async def find_schedule_for_subscription(self, sub_id: str) -> str | None:
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
        _check_id(sub_id, _SUB_ID_RE, "subscription id")
        _check_id(revert_price_id, _PRICE_ID_RE, "price id")
        _check_months(comp_months)
        _check_token(audit_action_id, "audit_action_id")
        _check_token(actor, "actor")
        self._enter(
            "create_revert_schedule",
            (sub_id, revert_price_id),
            {"comp_months": comp_months, "audit_action_id": audit_action_id, "actor": actor},
        )

        def run() -> ScheduleResult:
            snap = self._get(sub_id)
            schedule_id = snap.schedule_id or f"sub_sched_{len(self.schedules) + 1}"
            result = ScheduleResult(schedule_id, sub_id, revert_price_id, comp_months)
            self.schedules[schedule_id] = result
            self._put(sub_id, schedule_id=schedule_id)
            return result

        return self._once(  # type: ignore[no-any-return]
            _idem(audit_action_id, "schedule-modify"),
            (sub_id, revert_price_id, comp_months),
            run,
        )

    async def release_subscription_schedule(
        self, sub_or_schedule_id: str, audit_action_id: str, actor: str
    ) -> ScheduleResult:
        _check_token(audit_action_id, "audit_action_id")
        _check_token(actor, "actor")
        is_schedule = isinstance(sub_or_schedule_id, str) and bool(
            _SCHEDULE_ID_RE.fullmatch(sub_or_schedule_id)
        )
        if not is_schedule:
            _check_id(sub_or_schedule_id, _SUB_ID_RE, "subscription or schedule id")
        self._enter(
            "release_subscription_schedule",
            (sub_or_schedule_id, audit_action_id, actor),
            {},
        )

        def run() -> ScheduleResult:
            if is_schedule:
                schedule_id: str | None = sub_or_schedule_id
                sub_id = next(
                    (
                        s.subscription_id
                        for s in self.subscriptions.values()
                        if s.schedule_id == sub_or_schedule_id
                    ),
                    None,
                )
            else:
                sub_id = sub_or_schedule_id
                schedule_id = self._get(sub_id).schedule_id
            if schedule_id is None or schedule_id not in self.schedules:
                return ScheduleResult(schedule_id, sub_id, already_released=True)
            del self.schedules[schedule_id]
            if sub_id in self.subscriptions:
                self._put(sub_id, schedule_id=None)
            return ScheduleResult(schedule_id, sub_id)

        return self._once(  # type: ignore[no-any-return]
            _idem(audit_action_id, "schedule-release"), (sub_or_schedule_id,), run
        )
