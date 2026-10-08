"""Staff subscription operations — the core service layer (SOLUSDEV-313).

SECURITY CONTRACT: this layer TRUSTS ITS CALLER. It performs no staff authentication
or authorization; it must only be called from staff-authorized code (the SOLUSDEV-314
admin app). Every operation is scoped strictly to the target user's own live
subscription (loaded by `target_user_id` with FOR UPDATE).

Backing modes (decided per call):
  * Stripe-backed = `stripe_subscription_id` set and status != CANCELED. Stripe is the
    source of truth: the local row is NOT written; the webhook converges it, and the
    result's `after` view is PROJECTED from the Stripe snapshot
    (`converges_via_webhook=True`).
  * Local = everything else. The service writes the row itself.

The service COMMITS its own local writes (and the data-collection event). Stripe only
ever receives `audit_action_id` and `actor="staff:<uuid>"` — never the free-text
`reason` (it is for the caller's audit log) and never PII. Stripe writes are keyed off
`audit_action_id`, so retrying the same id is safe; a retry of a half-finished Stripe
operation resumes it. Local operations are naturally idempotent (same target state ->
`noop=True`, no duplicate event or credit).

Errors are `AdminOperationError` subclasses with a stable `code`; the gateway's own
typed errors (`StripeOperationError`, `StripeIdempotencyConflictError`, ...) pass
through unchanged.
"""

import calendar
import inspect
import logging
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing.entitlements import effective_limits, effective_plan
from solus_api.billing.plan_grants import grant_plan_credits
from solus_api.billing.plans import VALID_INTERVALS, plan_for_price_id, plan_price_id
from solus_api.billing.stripe_gateway import (
    ADMIN_ACTION_METADATA_KEY,
    COMP_PLAN_METADATA_KEY,
    COMP_PREV_PRICE_METADATA_KEY,
    MAX_COMP_MONTHS,
    MIN_COMP_MONTHS,
    CancelResult,
    CompDuration,
    Proration,
    ScheduleResult,
    StripeResourceMissingError,
    SubscriptionSnapshot,
)
from solus_api.core.config import Settings
from solus_api.models import (
    PLAN_LIMITS,
    NotificationType,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
    utcnow,
)
from solus_api.services.events import emit_event
from solus_api.services.notifications import notify_user

logger = logging.getLogger("solus.billing.admin_operations")

EVENT_TYPE = "subscription.admin_changed"
VALID_PRORATIONS = ("create_prorations", "none", "always_invoice")
VALID_DURATIONS = ("once", "repeating", "forever")
MAX_REASON_LEN = 2000
# Limit keys enforcement reads (services/limits.py) — plus every key any plan defines.
ENFORCED_LIMIT_KEYS = frozenset({"max_integrations", "max_projects", "max_teams", "byo_paid_tools"})
KNOWN_LIMIT_KEYS = ENFORCED_LIMIT_KEYS | frozenset(k for p in PLAN_LIMITS.values() for k in p)
# A same-plan comp whose expiry differs by less than this is a retry, not a change.
COMP_RETRY_TOLERANCE = timedelta(hours=1)
_AUDIT_ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,64}")  # mirrors the gateway's token rule
_COMP_PLANS = frozenset(PlanType)


# --------------------------------------------------------------------- errors
class AdminOperationError(Exception):
    """Base error: a stable machine `code`, a human `message`, and `context`."""

    code = "admin_operation_error"

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context


class TargetNotFound(AdminOperationError):  # noqa: N818 - name fixed by the 314 contract
    code = "target_not_found"


class InvalidOperation(AdminOperationError):  # noqa: N818 - name fixed by the 314 contract
    code = "invalid_operation"


class NotCompedError(AdminOperationError):
    code = "not_comped"


class UnsupportedForNonStripe(AdminOperationError):  # noqa: N818 - name fixed by the 314 contract
    code = "unsupported_for_non_stripe"


# -------------------------------------------------------------------- results
@dataclass(frozen=True)
class SubscriptionView:
    """Frozen, JSON-friendly snapshot of one subscription (plain str/int/None values)."""

    plan: str
    effective_plan: str
    status: str
    effective_limits: dict[str, int | None]
    limits_override: dict[str, int | None] | None
    comp_plan: str | None
    comp_expires_at: str | None
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    cancel_at: str | None
    expires_at: str | None
    stripe_price_id: str | None = None
    stripe_coupon_id: str | None = None
    stripe_schedule_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdminOpResult:
    """What 314 records in its audit log. `before`/`after` are Stripe-projected for
    Stripe-backed operations; `noop` means nothing changed (and nothing was emitted)."""

    operation: str
    target_user_id: uuid.UUID
    audit_action_id: str
    before: SubscriptionView
    after: SubscriptionView
    stripe_refs: dict[str, str] = field(default_factory=dict)
    converges_via_webhook: bool = False
    noop: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "target_user_id": str(self.target_user_id),
            "audit_action_id": self.audit_action_id,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "stripe_refs": dict(self.stripe_refs),
            "converges_via_webhook": self.converges_via_webhook,
            "noop": self.noop,
        }


class AdminStripeGateway(Protocol):
    """The slice of `StripeGateway` this layer uses (satisfied by the real gateway and
    by `tests/fixtures/stripe_fake.FakeStripeGateway`)."""

    async def retrieve_subscription(self, sub_id: str) -> SubscriptionSnapshot: ...

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
    ) -> SubscriptionSnapshot: ...

    async def ensure_comp_coupon(
        self, duration: CompDuration, months: int | None = None
    ) -> str: ...

    async def remove_comp_coupon(
        self, sub_id: str, audit_action_id: str, actor: str
    ) -> SubscriptionSnapshot: ...

    async def cancel_subscription(
        self,
        sub_id: str,
        *,
        mode: Any,
        invoice_now: bool,
        prorate: bool,
        audit_action_id: str,
        actor: str | None,
    ) -> CancelResult: ...

    async def create_revert_schedule(
        self,
        sub_id: str,
        revert_price_id: str,
        *,
        comp_months: int,
        audit_action_id: str,
        actor: str,
    ) -> ScheduleResult: ...

    async def release_subscription_schedule(
        self, sub_or_schedule_id: str, audit_action_id: str, actor: str
    ) -> ScheduleResult: ...


# ------------------------------------------------------------- pure helpers
def add_months(moment: datetime, months: int) -> datetime:
    """Calendar-correct month arithmetic (Jan 31 + 1 month = Feb 28/29)."""
    index = moment.year * 12 + (moment.month - 1) + months
    year, month = divmod(index, 12)
    day = min(moment.day, calendar.monthrange(year, month + 1)[1])
    return moment.replace(year=year, month=month + 1, day=day)


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def _detached(sub: Subscription, **changes: Any) -> Subscription:
    """A transient copy of `sub` with `changes` applied; never added to a session."""
    fields: dict[str, Any] = {
        "user_id": sub.user_id,
        "plan": sub.plan,
        "status": sub.status,
        "limits": dict(sub.limits or {}),
        "expires_at": sub.expires_at,
        "cancel_at": sub.cancel_at,
        "stripe_customer_id": sub.stripe_customer_id,
        "stripe_subscription_id": sub.stripe_subscription_id,
        "limits_override": sub.limits_override,
        "comp_plan": sub.comp_plan,
        "comp_expires_at": sub.comp_expires_at,
    }
    return Subscription(**{**fields, **changes})


def _view(
    sub: Subscription,
    now: datetime,
    snap: SubscriptionSnapshot | None = None,
    schedule_id: str | None = None,
) -> SubscriptionView:
    override = dict(sub.limits_override) if sub.limits_override is not None else None
    return SubscriptionView(
        plan=sub.plan.value,
        effective_plan=effective_plan(sub, now).value,
        status=sub.status.value,
        effective_limits=effective_limits(sub, now),
        limits_override=override,
        comp_plan=sub.comp_plan.value if sub.comp_plan else None,
        comp_expires_at=_iso(sub.comp_expires_at),
        stripe_customer_id=sub.stripe_customer_id,
        stripe_subscription_id=sub.stripe_subscription_id,
        cancel_at=_iso(sub.cancel_at),
        expires_at=_iso(sub.expires_at),
        stripe_price_id=snap.price_id if snap else None,
        stripe_coupon_id=snap.coupon_id if snap else None,
        stripe_schedule_id=schedule_id or (snap.schedule_id if snap else None),
    )


def _is_stripe_backed(sub: Subscription) -> bool:
    return bool(sub.stripe_subscription_id) and sub.status is not SubscriptionStatus.CANCELED


def _ts(epoch: int | None) -> datetime | None:
    return datetime.fromtimestamp(epoch, tz=UTC) if epoch else None


def _check_proration(proration: object) -> Proration:
    if proration not in VALID_PRORATIONS:
        raise InvalidOperation("proration must be one of " + ", ".join(VALID_PRORATIONS))
    return proration  # type: ignore[return-value]


def _check_interval(interval: object, *, required: bool) -> str | None:
    if interval is None and not required:
        return None
    if interval not in VALID_INTERVALS:
        raise InvalidOperation("interval must be 'month' or 'year' for a Stripe subscription")
    return str(interval)


def _check_plan(plan: object) -> PlanType:
    if not isinstance(plan, PlanType):
        raise InvalidOperation("plan must be a PlanType")
    return plan


def _check_comp_terms(duration: object, months: object) -> tuple[CompDuration, int | None]:
    if duration not in VALID_DURATIONS:
        raise InvalidOperation("duration must be 'once', 'repeating' or 'forever'")
    if duration == "repeating":
        if type(months) is not int or not MIN_COMP_MONTHS <= months <= MAX_COMP_MONTHS:
            raise InvalidOperation(
                f"months must be an int in {MIN_COMP_MONTHS}..{MAX_COMP_MONTHS} when repeating"
            )
        return "repeating", months
    if months is not None:
        raise InvalidOperation("months is only valid with duration='repeating'")
    return duration, None  # type: ignore[return-value]


def _check_override(limits: object) -> dict[str, int | None] | None:
    if limits is None:
        return None
    if not isinstance(limits, Mapping) or not limits:
        raise InvalidOperation("limits must be a non-empty mapping (use None to clear)")
    clean: dict[str, int | None] = {}
    for key, value in limits.items():
        if key not in KNOWN_LIMIT_KEYS:
            raise InvalidOperation(f"unknown limit key {key!r}", known=sorted(KNOWN_LIMIT_KEYS))
        if value is not None and (type(value) is not int or value < 0):
            raise InvalidOperation(f"limit {key!r} must be an int >= 0 or None (unlimited)")
        clean[key] = value
    return clean


@dataclass(frozen=True)
class _Audit:
    actor_staff_user_id: uuid.UUID
    audit_action_id: str
    reason: str

    @classmethod
    def validated(cls, actor: object, audit_action_id: object, reason: object) -> "_Audit":
        if not isinstance(actor, uuid.UUID):
            raise InvalidOperation("actor_staff_user_id must be a UUID")
        if not isinstance(audit_action_id, str) or not _AUDIT_ID_RE.fullmatch(audit_action_id):
            raise InvalidOperation("audit_action_id must match [A-Za-z0-9_.:-]{1,64}")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_LEN:
            raise InvalidOperation(f"reason must be 1..{MAX_REASON_LEN} characters")
        return cls(actor, audit_action_id, reason)

    @property
    def actor(self) -> str:
        return f"staff:{self.actor_staff_user_id}"


@dataclass(frozen=True)
class _Target:
    user: User
    sub: Subscription
    audit: _Audit
    before: SubscriptionView


# --------------------------------------------------------------------- service
class AdminBillingOperations:
    """Staff billing operations over one `AsyncSession` and one Stripe gateway.

    Construct per request/unit of work. Every public method is keyword-only after
    `target_user_id` and takes `actor_staff_user_id`, `audit_action_id`, `reason`."""

    def __init__(
        self,
        session: AsyncSession,
        gateway: AdminStripeGateway,
        settings: Settings,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._session = session
        self._gateway = gateway
        self._settings = settings
        self._now = now

    # ------------------------------------------------------------ public ops
    async def change_plan(
        self,
        target_user_id: uuid.UUID,
        *,
        plan: PlanType,
        actor_staff_user_id: uuid.UUID,
        audit_action_id: str,
        reason: str,
        interval: str | None = None,
        proration: Proration = "create_prorations",
    ) -> AdminOpResult:
        """Set the target's plan. Stripe-backed: swap the price (interval required);
        local: set plan + default limits and clear any comp. No credit grant."""
        audit = _Audit.validated(actor_staff_user_id, audit_action_id, reason)
        _check_plan(plan)
        _check_proration(proration)
        _check_interval(interval, required=False)
        return await self._guarded(
            "change_plan",
            target_user_id,
            audit,
            lambda t: self._change_plan(t, plan, interval, proration),
        )

    async def comp_upgrade(
        self,
        target_user_id: uuid.UUID,
        *,
        plan: PlanType,
        duration: CompDuration,
        actor_staff_user_id: uuid.UUID,
        audit_action_id: str,
        reason: str,
        months: int | None = None,
        interval: str | None = None,
        proration: Proration = "none",
    ) -> AdminOpResult:
        """Complimentary upgrade. Stripe-backed: 100%-off coupon + revert schedule (the
        comp end reverts to the previous price). Local: comp_plan/comp_expires_at, then
        the plan's one-time starting credits (idempotent per user+plan)."""
        audit = _Audit.validated(actor_staff_user_id, audit_action_id, reason)
        _check_plan(plan)
        _check_proration(proration)
        _check_interval(interval, required=False)
        terms = _check_comp_terms(duration, months)
        return await self._guarded(
            "comp_upgrade",
            target_user_id,
            audit,
            lambda t: self._comp_upgrade(t, plan, terms, interval, proration),
        )

    async def remove_comp(
        self,
        target_user_id: uuid.UUID,
        *,
        actor_staff_user_id: uuid.UUID,
        audit_action_id: str,
        reason: str,
        proration: Proration = "none",
    ) -> AdminOpResult:
        """End a comp now: Stripe-backed restores the previous price and removes the
        coupon; local clears the comp fields. `NotCompedError` if there is no comp."""
        audit = _Audit.validated(actor_staff_user_id, audit_action_id, reason)
        _check_proration(proration)
        return await self._guarded(
            "remove_comp", target_user_id, audit, lambda t: self._remove_comp(t, proration)
        )

    async def set_limits_override(
        self,
        target_user_id: uuid.UUID,
        *,
        limits: Mapping[str, int | None] | None,
        actor_staff_user_id: uuid.UUID,
        audit_action_id: str,
        reason: str,
    ) -> AdminOpResult:
        """Set (or, with `limits=None`, clear) the per-key limit override. Local write
        only; Stripe is never involved and `sub.limits` is never touched."""
        audit = _Audit.validated(actor_staff_user_id, audit_action_id, reason)
        clean = _check_override(limits)
        return await self._guarded(
            "set_limits_override", target_user_id, audit, lambda t: self._set_override(t, clean)
        )

    async def cancel_subscription(
        self,
        target_user_id: uuid.UUID,
        *,
        immediate: bool,
        actor_staff_user_id: uuid.UUID,
        audit_action_id: str,
        reason: str,
        invoice_now: bool = False,
        prorate: bool = False,
    ) -> AdminOpResult:
        """Cancel now (`immediate=True`) or at period end (Stripe-backed only)."""
        audit = _Audit.validated(actor_staff_user_id, audit_action_id, reason)
        if not all(isinstance(v, bool) for v in (immediate, invoice_now, prorate)):
            raise InvalidOperation("immediate, invoice_now and prorate must be bool")
        return await self._guarded(
            "cancel_subscription",
            target_user_id,
            audit,
            lambda t: self._cancel(t, immediate, invoice_now, prorate),
        )

    # -------------------------------------------------------------- plumbing
    async def _guarded(
        self,
        operation: str,
        target_user_id: uuid.UUID,
        audit: _Audit,
        run: Callable[[_Target], Any],
    ) -> AdminOpResult:
        """Load + lock the target, run the operation, and always release the lock."""
        try:
            target = await self._load(target_user_id, audit)
            produced = run(target)
            outcome: _Outcome = await produced if inspect.isawaitable(produced) else produced
            result = AdminOpResult(
                operation=operation,
                target_user_id=target_user_id,
                audit_action_id=audit.audit_action_id,
                before=target.before,
                after=outcome.after,
                stripe_refs=outcome.refs,
                converges_via_webhook=outcome.converges,
                noop=outcome.noop,
            )
            if result.noop:
                await self._session.rollback()
            else:
                self._emit(target, result)
                await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise
        if outcome.after_commit is not None:
            await outcome.after_commit()
        logger.info(
            "admin op=%s target=%s audit=%s noop=%s",
            operation,
            target_user_id,
            audit.audit_action_id,
            result.noop,
        )
        return result

    async def _load(self, target_user_id: uuid.UUID, audit: _Audit) -> _Target:
        sub = await self._session.scalar(
            select(Subscription)
            .where(Subscription.user_id == target_user_id, Subscription.deleted_at.is_(None))
            .with_for_update()
        )
        user = await self._session.get(User, target_user_id) if sub else None
        if sub is None or user is None:
            raise TargetNotFound(
                "no live subscription for the target user", target_user_id=str(target_user_id)
            )
        return _Target(user, sub, audit, _view(sub, self._now()))

    def _emit(self, target: _Target, result: AdminOpResult) -> None:
        emit_event(
            self._session,
            user=target.user,
            event_type=EVENT_TYPE,
            payload={
                "operation": result.operation,
                "audit_action_id": result.audit_action_id,
                "actor_staff_user_id": str(target.audit.actor_staff_user_id),
                "target_user_id": str(result.target_user_id),
            },
        )

    def _local_outcome(
        self, sub: Subscription, *, noop: bool, after_commit: Callable[[], Any] | None = None
    ) -> "_Outcome":
        return _Outcome(_view(sub, self._now()), noop=noop, after_commit=after_commit)

    def _stripe_outcome(
        self,
        sub: Subscription,
        snap: SubscriptionSnapshot,
        *,
        plan: PlanType | None = None,
        status: SubscriptionStatus | None = None,
        cancel_at: datetime | None = None,
        noop: bool = False,
        schedule_id: str | None = None,
        extra_refs: Mapping[str, str] | None = None,
    ) -> "_Outcome":
        """Project the post-write state from the Stripe snapshot (no local write)."""
        projected_plan = (
            plan
            or plan_for_price_id(self._settings.stripe_plan_prices, snap.price_id or "")
            or sub.plan
        )
        shadow = _detached(
            sub,
            plan=projected_plan,
            limits=default_limits(projected_plan),
            status=status or sub.status,
            cancel_at=cancel_at if cancel_at is not None else sub.cancel_at,
        )
        refs = {**snap.stripe_refs(), **(extra_refs or {})}
        return _Outcome(
            _view(shadow, self._now(), snap, schedule_id),
            refs=refs,
            converges=True,
            noop=noop,
        )

    async def _release_schedule(
        self, target: _Target, snap: SubscriptionSnapshot | None, replay: bool
    ) -> bool:
        """Release an attached schedule (price/cancel changes must not fight it).
        Skipped on a replay of this same audit action: the schedule then IS our own
        revert schedule, not one to remove."""
        if snap is None or not snap.schedule_id or replay:
            return False
        await self._gateway.release_subscription_schedule(
            snap.schedule_id, target.audit.audit_action_id, target.audit.actor
        )
        return True

    @staticmethod
    def _is_replay(snap: SubscriptionSnapshot, audit: _Audit) -> bool:
        return snap.metadata.get(ADMIN_ACTION_METADATA_KEY) == audit.audit_action_id

    # ---------------------------------------------------------- change_plan
    async def _change_plan(
        self, t: _Target, plan: PlanType, interval: str | None, proration: Proration
    ) -> "_Outcome":
        if not _is_stripe_backed(t.sub):
            return self._local_change_plan(t.sub, plan)
        price = self._stripe_price(plan, interval)
        sid = str(t.sub.stripe_subscription_id)
        snap = await self._gateway.retrieve_subscription(sid)
        replay = self._is_replay(snap, t.audit)
        released = await self._release_schedule(t, snap, replay)
        if snap.price_id == price and not replay:
            return self._stripe_outcome(t.sub, snap, plan=plan, noop=not released, extra_refs={})
        new = await self._gateway.change_subscription_price(
            sid,
            price,
            proration=proration,
            audit_action_id=t.audit.audit_action_id,
            actor=t.audit.actor,
        )
        return self._stripe_outcome(t.sub, new, plan=plan)

    def _local_change_plan(self, sub: Subscription, plan: PlanType) -> "_Outcome":
        unchanged = (
            sub.plan is plan
            and dict(sub.limits or {}) == default_limits(plan)
            and sub.comp_plan is None
            and sub.comp_expires_at is None
        )
        if unchanged:
            return self._local_outcome(sub, noop=True)
        sub.plan = plan
        sub.limits = default_limits(plan)
        sub.comp_plan = None
        sub.comp_expires_at = None
        return self._local_outcome(sub, noop=False)

    def _stripe_price(self, plan: PlanType, interval: str | None) -> str:
        checked = _check_interval(interval, required=True)
        price = plan_price_id(self._settings, plan, str(checked))
        if price is None:
            raise InvalidOperation(
                f"no Stripe price is configured for {plan.value}:{checked}",
                plan=plan.value,
                interval=checked,
            )
        return price

    # ------------------------------------------------------------ comp_upgrade
    async def _comp_upgrade(
        self,
        t: _Target,
        plan: PlanType,
        terms: tuple[CompDuration, int | None],
        interval: str | None,
        proration: Proration,
    ) -> "_Outcome":
        duration, months = terms
        if not _is_stripe_backed(t.sub):
            return self._local_comp(t, plan, duration, months)
        price = self._stripe_price(plan, interval)
        sid = str(t.sub.stripe_subscription_id)
        snap = await self._gateway.retrieve_subscription(sid)
        replay = self._is_replay(snap, t.audit)
        prev = snap.metadata.get(COMP_PREV_PRICE_METADATA_KEY) or snap.price_id
        if not prev:
            raise InvalidOperation("subscription has no current price to revert to")
        coupon = await self._gateway.ensure_comp_coupon(duration, months)
        await self._release_schedule(t, snap, replay)
        new = await self._gateway.change_subscription_price(
            sid,
            price,
            proration=proration,
            audit_action_id=t.audit.audit_action_id,
            actor=t.audit.actor,
            coupon_id=coupon,
            extra_metadata={COMP_PREV_PRICE_METADATA_KEY: prev, COMP_PLAN_METADATA_KEY: plan.value},
        )
        schedule: ScheduleResult | None = None
        if duration != "forever":
            schedule = await self._gateway.create_revert_schedule(
                sid,
                prev,
                comp_months=1 if duration == "once" else int(months or 1),
                audit_action_id=t.audit.audit_action_id,
                actor=t.audit.actor,
            )
        return self._stripe_outcome(
            t.sub,
            new,
            plan=plan,
            schedule_id=schedule.schedule_id if schedule else None,
            extra_refs=schedule.stripe_refs() if schedule else None,
        )

    def _local_comp(
        self, t: _Target, plan: PlanType, duration: CompDuration, months: int | None
    ) -> "_Outcome":
        sub = t.sub
        now = self._now()
        expires = (
            None
            if duration == "forever"
            else add_months(now, 1 if duration == "once" else int(months or 1))
        )
        already = (
            sub.comp_plan is plan
            and _same_expiry(sub.comp_expires_at, expires)
            and sub.comp_plan is not None
        )
        grant = self._grant_after_commit(sub, plan)
        if already:
            return self._local_outcome(sub, noop=True, after_commit=grant)
        sub.comp_plan = plan
        sub.comp_expires_at = expires
        return self._local_outcome(sub, noop=False, after_commit=grant)

    def _grant_after_commit(self, sub: Subscription, plan: PlanType) -> Callable[[], Any]:
        """The comp plan's starting credits. `grant_plan_credits` commits mid-flow, so
        this runs only after our own write is durable; it keys on `local.plan`, hence
        the transient copy carrying the comp plan. Idempotent per (user, plan)."""
        local = _detached(sub, plan=plan)
        grants = self._settings.plan_credit_grants

        async def run() -> None:
            await grant_plan_credits(self._session, local, grants)
            await self._session.commit()

        return run

    # ------------------------------------------------------------- remove_comp
    async def _remove_comp(self, t: _Target, proration: Proration) -> "_Outcome":
        sub = t.sub
        if not _is_stripe_backed(sub):
            if sub.comp_plan is None:
                raise NotCompedError("target has no comp", target_user_id=str(sub.user_id))
            sub.comp_plan = None
            sub.comp_expires_at = None
            return self._local_outcome(sub, noop=False)
        sid = str(sub.stripe_subscription_id)
        snap = await self._gateway.retrieve_subscription(sid)
        prev = snap.metadata.get(COMP_PREV_PRICE_METADATA_KEY)
        if not prev:
            if self._is_replay(snap, t.audit):  # a retry that finds the work done
                return await self._finish_remove(t, snap, noop_if_clean=True)
            raise NotCompedError(
                "target's Stripe subscription is not comped", target_user_id=str(sub.user_id)
            )
        await self._release_schedule(t, snap, replay=False)
        restored = await self._gateway.change_subscription_price(
            sid,
            prev,
            proration=proration,
            audit_action_id=t.audit.audit_action_id,
            actor=t.audit.actor,
            extra_metadata={COMP_PREV_PRICE_METADATA_KEY: "", COMP_PLAN_METADATA_KEY: ""},
        )
        return await self._finish_remove(t, restored, noop_if_clean=False)

    async def _finish_remove(
        self, t: _Target, snap: SubscriptionSnapshot, *, noop_if_clean: bool
    ) -> "_Outcome":
        had_coupon = bool(snap.coupon_id)
        if had_coupon:
            snap = await self._gateway.remove_comp_coupon(
                str(t.sub.stripe_subscription_id), t.audit.audit_action_id, t.audit.actor
            )
        return self._stripe_outcome(t.sub, snap, noop=noop_if_clean and not had_coupon)

    # ---------------------------------------------------------------- override
    def _set_override(self, t: _Target, clean: dict[str, int | None] | None) -> "_Outcome":
        sub = t.sub
        if (sub.limits_override or None) == clean:
            return self._local_outcome(sub, noop=True)
        sub.limits_override = clean
        return self._local_outcome(sub, noop=False)

    # ------------------------------------------------------------------ cancel
    async def _cancel(
        self, t: _Target, immediate: bool, invoice_now: bool, prorate: bool
    ) -> "_Outcome":
        if _is_stripe_backed(t.sub):
            return await self._stripe_cancel(t, immediate, invoice_now, prorate)
        if not immediate:
            raise UnsupportedForNonStripe(
                "period-end cancellation needs a Stripe subscription (trials are not enforced)",
                target_user_id=str(t.sub.user_id),
            )
        sub = t.sub
        if sub.status is SubscriptionStatus.CANCELED:
            return self._local_outcome(sub, noop=True)
        label = sub.plan.value.capitalize()
        sub.status = SubscriptionStatus.CANCELED
        sub.cancel_at = None
        sub.limits = default_limits(PlanType.BASIC)
        sub.comp_plan = None
        sub.comp_expires_at = None
        notify_user(
            self._session,
            user_id=sub.user_id,
            notification_type=NotificationType.SUBSCRIPTION_ENDED,
            title="Subscription ended",
            body=(
                f"Your {label} plan has ended — limits now match the Basic tier. "
                "You can resubscribe anytime from Billing."
            ),
            attrs={"plan": sub.plan.value},
        )
        return self._local_outcome(sub, noop=False)

    async def _stripe_cancel(
        self, t: _Target, immediate: bool, invoice_now: bool, prorate: bool
    ) -> "_Outcome":
        sid = str(t.sub.stripe_subscription_id)
        try:
            snap: SubscriptionSnapshot | None = await self._gateway.retrieve_subscription(sid)
        except StripeResourceMissingError:
            snap = None  # already gone: cancel_subscription treats it as success
        replay = snap is not None and self._is_replay(snap, t.audit)
        await self._release_schedule(t, snap, replay)
        res = await self._gateway.cancel_subscription(
            sid,
            mode="immediate" if immediate else "period_end",
            invoice_now=invoice_now,
            prorate=prorate,
            audit_action_id=t.audit.audit_action_id,
            actor=t.audit.actor,
        )
        final = res.subscription or snap or _bare_snapshot(sid)
        status = SubscriptionStatus.CANCELED if immediate or final.status == "canceled" else None
        cancel_at = None if status else _ts(final.cancel_at or final.current_period_end)
        outcome = self._stripe_outcome(
            t.sub, final, status=status, cancel_at=cancel_at, noop=res.already_canceled
        )
        return outcome


def _same_expiry(existing: datetime | None, requested: datetime | None) -> bool:
    if existing is None or requested is None:
        return existing is None and requested is None
    if existing.tzinfo is None:
        existing = existing.replace(tzinfo=UTC)
    return abs(requested - existing) <= COMP_RETRY_TOLERANCE


def _bare_snapshot(sub_id: str) -> SubscriptionSnapshot:
    return SubscriptionSnapshot(
        subscription_id=sub_id,
        status="canceled",
        price_id=None,
        item_id=None,
        item_count=0,
        quantity=1,
        customer_id=None,
        cancel_at=None,
        cancel_at_period_end=False,
        current_period_end=None,
        coupon_id=None,
        schedule_id=None,
        latest_invoice_id=None,
    )


@dataclass
class _Outcome:
    after: SubscriptionView
    refs: dict[str, str] = field(default_factory=dict)
    converges: bool = False
    noop: bool = False
    after_commit: Callable[[], Any] | None = None
