"""Read-only projections for staff billing operations (SOLUSDEV-313).

Free functions that turn a subscription row and/or a Stripe snapshot into the frozen
`SubscriptionView`/`Outcome` carriers, plus the snapshot predicates that decide whether
a Stripe subscription is currently comped. Nothing here writes or does I/O."""

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from solus_api.billing.admin_types import Outcome, SubscriptionView
from solus_api.billing.entitlements import effective_limits, effective_plan
from solus_api.billing.plans import plan_for_price_id
from solus_api.billing.stripe_gateway import (
    _COMP_COUPON_RE,
    COMP_PREV_PRICE_METADATA_KEY,
    SubscriptionSnapshot,
)
from solus_api.models import PlanType, Subscription, SubscriptionStatus, default_limits


def iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def epoch_to_datetime(epoch: int | None) -> datetime | None:
    return datetime.fromtimestamp(epoch, tz=UTC) if epoch else None


def is_stripe_backed(sub: Subscription) -> bool:
    return bool(sub.stripe_subscription_id) and sub.status is not SubscriptionStatus.CANCELED


def detached(sub: Subscription, **changes: Any) -> Subscription:
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


def view(
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
        comp_expires_at=iso(sub.comp_expires_at),
        stripe_customer_id=sub.stripe_customer_id,
        stripe_subscription_id=sub.stripe_subscription_id,
        cancel_at=iso(sub.cancel_at),
        expires_at=iso(sub.expires_at),
        stripe_price_id=snap.price_id if snap else None,
        stripe_coupon_id=snap.coupon_id if snap else None,
        stripe_schedule_id=schedule_id or (snap.schedule_id if snap else None),
    )


def local_outcome(
    sub: Subscription,
    now: datetime,
    *,
    noop: bool,
    after_commit: Callable[[], Awaitable[None]] | None = None,
) -> Outcome:
    return Outcome(view(sub, now), noop=noop, after_commit=after_commit)


def stripe_outcome(
    sub: Subscription,
    snap: SubscriptionSnapshot,
    now: datetime,
    plan_prices: dict[str, str],
    *,
    plan: PlanType | None = None,
    status: SubscriptionStatus | None = None,
    cancel_at: datetime | None = None,
    noop: bool = False,
    schedule_id: str | None = None,
    extra_refs: Mapping[str, str] | None = None,
) -> Outcome:
    """Project the post-write state from the Stripe snapshot (no local write)."""
    projected_plan = plan or plan_for_price_id(plan_prices, snap.price_id or "") or sub.plan
    shadow = detached(
        sub,
        plan=projected_plan,
        limits=default_limits(projected_plan),
        status=status or sub.status,
        cancel_at=cancel_at if cancel_at is not None else sub.cancel_at,
    )
    return Outcome(
        view(shadow, now, snap, schedule_id),
        refs={**snap.stripe_refs(), **(extra_refs or {})},
        converges=True,
        noop=noop,
    )


def bare_snapshot(sub_id: str) -> SubscriptionSnapshot:
    """Stand-in for a Stripe subscription that no longer exists."""
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


def has_comp_coupon(snap: SubscriptionSnapshot) -> bool:
    """Whether a Solus comp coupon (`solus-comp-*`) is attached right now. A customer's
    own promo code does not count."""
    return snap.coupon_id is not None and _COMP_COUPON_RE.fullmatch(snap.coupon_id) is not None


def comp_prev_price(snap: SubscriptionSnapshot) -> str | None:
    """The price to revert to, only while the subscription is genuinely comped. The
    metadata marker alone is not trusted: it can outlive a naturally ended comp."""
    prev = snap.metadata.get(COMP_PREV_PRICE_METADATA_KEY)
    return prev if prev and has_comp_coupon(snap) else None
