"""Staff subscription operations — the core service layer (SOLUSDEV-313).

SECURITY CONTRACT: this layer TRUSTS ITS CALLER. It performs no staff authentication
or authorization; it must only be called from staff-authorized code (the SOLUSDEV-314
admin app). Every operation is scoped strictly to the target user's own live
subscription (loaded by `target_user_id` with FOR UPDATE). Stripe-backed operations
additionally verify that the Stripe subscription's customer is the target's own
`stripe_customer_id` before any write.

Backing modes (decided per call):
  * Stripe-backed = `stripe_subscription_id` set and status != CANCELED. Stripe is the
    source of truth: the local row is NOT written; the webhook converges it, and the
    result's `after` view is PROJECTED from the Stripe snapshot
    (`converges_via_webhook=True`).
  * Local = everything else. The service writes the row itself.

The service COMMITS its own local writes (and the data-collection event). Stripe only
ever receives `audit_action_id` and `actor="staff:<uuid>"` — never the free-text
`reason` (it is for the caller's audit log) and never PII.

IDEMPOTENCY CONTRACT FOR SOLUSDEV-314: `audit_action_id` is the Stripe idempotency
token. 314 MUST mint a UNIQUE id per staff action and PERSIST it BEFORE calling this
layer, then reuse the same id only to retry that same action. Stripe remembers an
idempotency key for 24 hours only; after that a reused id is no longer deduplicated
there. Retrying the same id with different parameters raises the gateway's
`StripeIdempotencyConflictError`. Local operations ignore the id for deduplication
(they are naturally idempotent: same target state -> `noop=True`, no duplicate event or
credit).

Comps on Stripe-backed subscriptions: `change_plan` REFUSES while a comp coupon is
attached (a forever comp would make the new price free, and a later `remove_comp`
would silently undo the plan change) — call `remove_comp` first. `remove_comp` needs
both a `solus-comp-*` coupon and the previous-price marker; markers alone (left behind
after a comp ended naturally) never re-price a customer.

Every operation runs under `OPERATION_TIMEOUT_SECONDS`; on expiry the transaction is
rolled back, the row lock released and the retryable `AdminOperationTimeoutError` is
raised.

Errors are `AdminOperationError` subclasses with a stable `code`; the gateway's own
typed errors (`StripeOperationError`, `StripeIdempotencyConflictError`, ...) pass
through unchanged.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing.admin_projection import (
    bare_snapshot,
    comp_prev_price,
    detached,
    epoch_to_datetime,
    has_comp_coupon,
    is_stripe_backed,
    local_outcome,
    stripe_outcome,
    view,
)
from solus_api.billing.admin_types import (
    AdminOperationError,
    AdminOperationTimeoutError,
    AdminOpResult,
    AdminStripeGateway,
    AuditContext,
    InvalidOperation,
    NotCompedError,
    Outcome,
    SubscriptionView,
    Target,
    TargetNotFound,
    UnsupportedForNonStripe,
)
from solus_api.billing.admin_validation import (
    add_months,
    check_bools,
    check_comp_terms,
    check_interval,
    check_override,
    check_plan,
    check_proration,
    same_expiry,
    validate_audit,
)
from solus_api.billing.plan_grants import grant_plan_credits
from solus_api.billing.plans import plan_price_id
from solus_api.billing.stripe_gateway import (
    ADMIN_ACTION_METADATA_KEY,
    COMP_PLAN_METADATA_KEY,
    COMP_PREV_PRICE_METADATA_KEY,
    CancelMode,
    CompDuration,
    Proration,
    ScheduleResult,
    StripeResourceMissingError,
    SubscriptionSnapshot,
)
from solus_api.core.config import Settings
from solus_api.models import (
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

__all__ = [
    "AdminBillingOperations",
    "AdminOpResult",
    "AdminOperationError",
    "AdminOperationTimeoutError",
    "AdminStripeGateway",
    "InvalidOperation",
    "NotCompedError",
    "SubscriptionView",
    "TargetNotFound",
    "UnsupportedForNonStripe",
]

logger = logging.getLogger("solus.billing.admin_operations")

EVENT_TYPE = "subscription.admin_changed"
# Worst case of one operation is ~6 sequential Stripe calls (retrieve, coupon, release,
# price change, schedule find/create/modify); the per-call bound is the gateway's own
# timeout, assumed here to be 20 s. The whole run (and so the FOR UPDATE lock) is capped.
_ASSUMED_STRIPE_CALL_TIMEOUT_SECONDS = 20.0
_WORST_CASE_SEQUENTIAL_CALLS = 6
OPERATION_TIMEOUT_SECONDS = _ASSUMED_STRIPE_CALL_TIMEOUT_SECONDS * _WORST_CASE_SEQUENTIAL_CALLS
_CLEARED_COMP_MARKERS = {COMP_PREV_PRICE_METADATA_KEY: "", COMP_PLAN_METADATA_KEY: ""}


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
        """Set the target's plan. Stripe-backed: swap the price (interval required;
        refused while comped); local: set plan + default limits and clear any comp.
        No credit grant."""
        audit = validate_audit(actor_staff_user_id, audit_action_id, reason)
        check_plan(plan)
        check_proration(proration)
        check_interval(interval, required=False)
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
        audit = validate_audit(actor_staff_user_id, audit_action_id, reason)
        check_plan(plan)
        check_proration(proration)
        check_interval(interval, required=False)
        terms = check_comp_terms(duration, months)
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
        audit = validate_audit(actor_staff_user_id, audit_action_id, reason)
        check_proration(proration)
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
        audit = validate_audit(actor_staff_user_id, audit_action_id, reason)
        clean = check_override(limits)
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
        audit = validate_audit(actor_staff_user_id, audit_action_id, reason)
        check_bools(immediate=immediate, invoice_now=invoice_now, prorate=prorate)
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
        audit: AuditContext,
        run: Callable[[Target], Awaitable[Outcome]],
    ) -> AdminOpResult:
        """Load + lock the target, run the operation, and always release the lock."""
        try:
            target = await self._load(target_user_id, audit)
            outcome = await self._run_bounded(operation, target, run)
            result = AdminOpResult(
                operation=operation,
                target_user_id=target_user_id,
                audit_action_id=audit.audit_action_id,
                before=target.before,
                after=outcome.after,
                stripe_refs=dict(outcome.refs),
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
        await self._run_after_commit(outcome, operation, target_user_id, audit)
        logger.info(
            "admin op=%s target=%s audit=%s noop=%s",
            operation,
            target_user_id,
            audit.audit_action_id,
            result.noop,
        )
        return result

    async def _run_bounded(
        self,
        operation: str,
        target: Target,
        run: Callable[[Target], Awaitable[Outcome]],
    ) -> Outcome:
        """Run under the operation deadline so no hung call can pin the row lock."""
        try:
            async with asyncio.timeout(OPERATION_TIMEOUT_SECONDS) as scope:
                return await run(target)
        except TimeoutError as exc:
            if not scope.expired():
                raise  # a timeout raised by something else, not our deadline
            raise AdminOperationTimeoutError(
                "the operation timed out and was rolled back; retry with the same audit id",
                operation=operation,
                target_user_id=str(target.sub.user_id),
                audit_action_id=target.audit.audit_action_id,
            ) from exc

    async def _run_after_commit(
        self,
        outcome: Outcome,
        operation: str,
        target_user_id: uuid.UUID,
        audit: AuditContext,
    ) -> None:
        """Post-commit work (credit grant). The change is already durable, so a failure
        here is logged with context and NOT raised; a retry of the same action is a
        noop that re-runs the (idempotent) grant."""
        if outcome.after_commit is None:
            return
        try:
            await outcome.after_commit()
        except Exception:
            await self._session.rollback()
            logger.exception(
                "admin op=%s credit grant failed after commit target=%s audit=%s",
                operation,
                target_user_id,
                audit.audit_action_id,
            )

    async def _load(self, target_user_id: uuid.UUID, audit: AuditContext) -> Target:
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
        return Target(user, sub, audit, view(sub, self._now()))

    def _emit(self, target: Target, result: AdminOpResult) -> None:
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
        self,
        sub: Subscription,
        *,
        noop: bool,
        after_commit: Callable[[], Awaitable[None]] | None = None,
    ) -> Outcome:
        return local_outcome(sub, self._now(), noop=noop, after_commit=after_commit)

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
    ) -> Outcome:
        return stripe_outcome(
            sub,
            snap,
            self._now(),
            self._settings.stripe_plan_prices,
            plan=plan,
            status=status,
            cancel_at=cancel_at,
            noop=noop,
            schedule_id=schedule_id,
            extra_refs=extra_refs,
        )

    async def _retrieve_owned(self, t: Target) -> SubscriptionSnapshot:
        """Retrieve the target's Stripe subscription and prove it belongs to the
        target's own Stripe customer, BEFORE anything is written."""
        snap = await self._gateway.retrieve_subscription(str(t.sub.stripe_subscription_id))
        self._verify_customer(t, snap)
        return snap

    @staticmethod
    def _verify_customer(t: Target, snap: SubscriptionSnapshot) -> None:
        if snap.customer_id != t.sub.stripe_customer_id:
            raise InvalidOperation(
                "the Stripe subscription does not belong to the target's customer",
                target_user_id=str(t.sub.user_id),
            )

    async def _release_schedule(
        self, target: Target, snap: SubscriptionSnapshot | None, replay: bool
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
    def _is_replay(snap: SubscriptionSnapshot, audit: AuditContext) -> bool:
        return snap.metadata.get(ADMIN_ACTION_METADATA_KEY) == audit.audit_action_id

    # ---------------------------------------------------------- change_plan
    async def _change_plan(
        self, t: Target, plan: PlanType, interval: str | None, proration: Proration
    ) -> Outcome:
        if not is_stripe_backed(t.sub):
            return self._local_change_plan(t.sub, plan)
        price = self._stripe_price(plan, interval)
        sid = str(t.sub.stripe_subscription_id)
        snap = await self._retrieve_owned(t)
        if has_comp_coupon(snap):
            raise InvalidOperation(
                "the subscription is comped; remove the comp first",
                target_user_id=str(t.sub.user_id),
            )
        replay = self._is_replay(snap, t.audit)
        released = await self._release_schedule(t, snap, replay)
        if snap.price_id == price and not replay:
            return self._stripe_outcome(t.sub, snap, plan=plan, noop=not released)
        stale = bool(
            snap.metadata.get(COMP_PREV_PRICE_METADATA_KEY)
            or snap.metadata.get(COMP_PLAN_METADATA_KEY)
        )
        new = await self._gateway.change_subscription_price(
            sid,
            price,
            proration=proration,
            audit_action_id=t.audit.audit_action_id,
            actor=t.audit.actor,
            # comp markers left by a naturally ended comp must not outlive this change
            extra_metadata=_CLEARED_COMP_MARKERS if stale else None,
        )
        return self._stripe_outcome(t.sub, new, plan=plan)

    def _local_change_plan(self, sub: Subscription, plan: PlanType) -> Outcome:
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
        checked = check_interval(interval, required=True)
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
        t: Target,
        plan: PlanType,
        terms: tuple[CompDuration, int | None],
        interval: str | None,
        proration: Proration,
    ) -> Outcome:
        duration, months = terms
        if not is_stripe_backed(t.sub):
            return self._local_comp(t, plan, duration, months)
        price = self._stripe_price(plan, interval)
        sid = str(t.sub.stripe_subscription_id)
        snap = await self._retrieve_owned(t)
        replay = self._is_replay(snap, t.audit)
        # A re-comp keeps the ORIGINAL previous price; stale markers are not trusted.
        prev = comp_prev_price(snap) or snap.price_id
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
        self, t: Target, plan: PlanType, duration: CompDuration, months: int | None
    ) -> Outcome:
        sub = t.sub
        expires = (
            None
            if duration == "forever"
            else add_months(self._now(), 1 if duration == "once" else int(months or 1))
        )
        already = sub.comp_plan is plan and same_expiry(sub.comp_expires_at, expires)
        grant = self._grant_after_commit(sub, plan)
        if already:
            return self._local_outcome(sub, noop=True, after_commit=grant)
        sub.comp_plan = plan
        sub.comp_expires_at = expires
        return self._local_outcome(sub, noop=False, after_commit=grant)

    def _grant_after_commit(
        self, sub: Subscription, plan: PlanType
    ) -> Callable[[], Awaitable[None]]:
        """The comp plan's starting credits. `grant_plan_credits` commits mid-flow, so
        this runs only after our own write is durable; it keys on `local.plan`, hence
        the transient copy carrying the comp plan. Idempotent per (user, plan)."""
        local = detached(sub, plan=plan)
        grants = self._settings.plan_credit_grants

        async def run() -> None:
            await grant_plan_credits(self._session, local, grants)
            await self._session.commit()

        return run

    # ------------------------------------------------------------- remove_comp
    async def _remove_comp(self, t: Target, proration: Proration) -> Outcome:
        sub = t.sub
        if not is_stripe_backed(sub):
            if sub.comp_plan is None:
                raise NotCompedError("target has no comp", target_user_id=str(sub.user_id))
            sub.comp_plan = None
            sub.comp_expires_at = None
            return self._local_outcome(sub, noop=False)
        sid = str(sub.stripe_subscription_id)
        snap = await self._retrieve_owned(t)
        prev = comp_prev_price(snap)  # needs the comp coupon AND the marker
        if prev is None:
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
            extra_metadata=_CLEARED_COMP_MARKERS,
        )
        return await self._finish_remove(t, restored, noop_if_clean=False)

    async def _finish_remove(
        self, t: Target, snap: SubscriptionSnapshot, *, noop_if_clean: bool
    ) -> Outcome:
        had_coupon = has_comp_coupon(snap)
        if had_coupon:
            snap = await self._gateway.remove_comp_coupon(
                str(t.sub.stripe_subscription_id), t.audit.audit_action_id, t.audit.actor
            )
        return self._stripe_outcome(t.sub, snap, noop=noop_if_clean and not had_coupon)

    # ---------------------------------------------------------------- override
    async def _set_override(self, t: Target, clean: dict[str, int | None] | None) -> Outcome:
        sub = t.sub
        if (sub.limits_override or None) == clean:
            return self._local_outcome(sub, noop=True)
        sub.limits_override = clean
        return self._local_outcome(sub, noop=False)

    # ------------------------------------------------------------------ cancel
    async def _cancel(
        self, t: Target, immediate: bool, invoice_now: bool, prorate: bool
    ) -> Outcome:
        if is_stripe_backed(t.sub):
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
        self, t: Target, immediate: bool, invoice_now: bool, prorate: bool
    ) -> Outcome:
        sid = str(t.sub.stripe_subscription_id)
        try:
            snap: SubscriptionSnapshot | None = await self._retrieve_owned(t)
        except StripeResourceMissingError:
            snap = None  # already gone: cancel_subscription treats it as success
        replay = snap is not None and self._is_replay(snap, t.audit)
        await self._release_schedule(t, snap, replay)
        mode: CancelMode = "immediate" if immediate else "period_end"
        res = await self._gateway.cancel_subscription(
            sid,
            mode=mode,
            invoice_now=invoice_now,
            prorate=prorate,
            audit_action_id=t.audit.audit_action_id,
            actor=t.audit.actor,
        )
        final = res.subscription or snap or bare_snapshot(sid)
        status = SubscriptionStatus.CANCELED if immediate or final.status == "canceled" else None
        cancel_at = (
            None if status else epoch_to_datetime(final.cancel_at or final.current_period_end)
        )
        return self._stripe_outcome(
            t.sub, final, status=status, cancel_at=cancel_at, noop=res.already_canceled
        )
