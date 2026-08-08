"""Stripe webhook event processing (SOLUSDEV-83 / SOLUS-FND-03).

Signature verification lives in the router; this module is the pure-ish dispatch,
unit-testable with plain event dicts. Every effect is idempotent so a duplicate
or out-of-order delivery converges to the correct final state:

- dedupe by Stripe event id (`processed_stripe_events`);
- subscription state is last-write-wins by the event's `created` time
  (`Subscription.stripe_event_at`), so a replayed older event never overrides a
  newer one;
- credit-pack grants use the event id as the credit idempotency key.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing import credits
from solus_api.billing.plans import plan_for_price_id
from solus_api.models import (
    CreditTxnType,
    NotificationType,
    ProcessedStripeEvent,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
)
from solus_api.services.notifications import notify_user

logger = logging.getLogger("solus.billing.stripe")

_SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
)

# Stripe subscription.status → our SubscriptionStatus. Unknown/unpaid states are
# treated as past_due (dunning), which the app surfaces as "action needed".
_STATUS_MAP: dict[str, SubscriptionStatus] = {
    "active": SubscriptionStatus.ACTIVE,
    "trialing": SubscriptionStatus.TRIALING,
    "past_due": SubscriptionStatus.PAST_DUE,
    "unpaid": SubscriptionStatus.PAST_DUE,
    "incomplete": SubscriptionStatus.PAST_DUE,
    "paused": SubscriptionStatus.PAST_DUE,
    "canceled": SubscriptionStatus.CANCELED,
    "incomplete_expired": SubscriptionStatus.CANCELED,
}


def _event_dt(created: int) -> datetime:
    return datetime.fromtimestamp(created, tz=UTC)


async def _sub_by(
    session: AsyncSession, *, customer: str | None, sub_id: str | None
) -> Subscription | None:
    if sub_id:
        row: Subscription | None = await session.scalar(
            select(Subscription).where(
                Subscription.stripe_subscription_id == sub_id, Subscription.deleted_at.is_(None)
            )
        )
        if row is not None:
            return row
    if customer:
        by_customer: Subscription | None = await session.scalar(
            select(Subscription).where(
                Subscription.stripe_customer_id == customer, Subscription.deleted_at.is_(None)
            )
        )
        return by_customer
    return None


def _subscription_price_id(obj: dict[str, Any]) -> str | None:
    """The first line item's Stripe Price id on a subscription object, or None."""
    items = (obj.get("items") or {}).get("data") or []
    if not items:
        return None
    price = items[0].get("price") or {}
    pid = price.get("id")
    return str(pid) if pid else None


async def _apply_subscription(
    session: AsyncSession,
    obj: dict[str, Any],
    etype: str,
    created: datetime,
    plan_prices: dict[str, str],
) -> None:
    sub_id = obj.get("id")
    customer = obj.get("customer")
    local = await _sub_by(session, customer=customer, sub_id=sub_id)
    if local is None:
        logger.warning(
            "stripe subscription event with no local match sub=%s cus=%s", sub_id, customer
        )
        return
    # Out-of-order guard: ignore an event older than the last one applied.
    if local.stripe_event_at is not None and created < local.stripe_event_at:
        return
    old_plan, old_status = local.plan, local.status
    if sub_id:
        local.stripe_subscription_id = sub_id
    if customer:
        local.stripe_customer_id = customer
    if etype == "customer.subscription.deleted":
        local.status = SubscriptionStatus.CANCELED
    else:
        local.status = _STATUS_MAP.get(str(obj.get("status")), local.status)
        # Entitlement is derived from what was actually purchased (the Stripe
        # Price on the subscription) — never from a client-supplied plan name.
        price_id = _subscription_price_id(obj)
        if price_id:
            plan = plan_for_price_id(plan_prices, price_id)
            if plan is not None:
                local.plan = plan
                local.limits = default_limits(plan)
    local.stripe_event_at = created
    _notify_if_entitlement_changed(session, local, old_plan=old_plan, old_status=old_status)


_LIVE_STATUSES = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING})


def _notify_if_entitlement_changed(
    session: AsyncSession,
    local: Subscription,
    *,
    old_plan: object,
    old_status: SubscriptionStatus,
) -> None:
    """One in-app notification when a payment takes effect: entering a live
    (active/trialing) status, or switching plans while live. Routine renewals
    (same plan, still live) stay silent; the event-id dedupe and out-of-order
    guards upstream make this at-most-once per Stripe event."""
    if local.status not in _LIVE_STATUSES:
        return
    became_live = old_status not in _LIVE_STATUSES
    plan_changed = local.plan != old_plan
    if not (became_live or plan_changed):
        return
    plan_label = local.plan.value.capitalize()
    notify_user(
        session,
        user_id=local.user_id,
        notification_type=NotificationType.PAYMENT_SUCCEEDED,
        title="Payment successful" if became_live else "Plan updated",
        body=f"You're on the {plan_label} plan.",
        attrs={"plan": local.plan.value, "subscription": local.stripe_subscription_id},
    )


async def _apply_checkout(
    session: AsyncSession, obj: dict[str, Any], event_id: str, pack_credits: dict[str, int]
) -> None:
    metadata = obj.get("metadata") or {}
    raw_user = obj.get("client_reference_id") or metadata.get("solus_user_id")
    if not raw_user:
        logger.warning("checkout.session.completed with no user reference")
        return
    try:
        user_id = uuid.UUID(str(raw_user))
    except ValueError:
        logger.warning("checkout.session.completed with bad user reference %r", raw_user)
        return
    # Guard against a spoofed/stale user reference: never touch credits for a user
    # that doesn't exist (also avoids an FK crash from the grant).
    if await session.get(User, user_id) is None:
        logger.warning("checkout.session.completed for unknown user %s", user_id)
        return

    if obj.get("mode") == "subscription":
        await _link_subscription_customer(session, obj, user_id)
    elif obj.get("mode") == "payment":
        await _grant_credit_pack(session, obj, event_id, user_id, metadata, pack_credits)


async def _link_subscription_customer(
    session: AsyncSession, obj: dict[str, Any], user_id: uuid.UUID
) -> None:
    local = await session.scalar(
        select(Subscription).where(
            Subscription.user_id == user_id, Subscription.deleted_at.is_(None)
        )
    )
    if local is None:
        return
    if obj.get("customer"):
        local.stripe_customer_id = str(obj["customer"])
    if obj.get("subscription"):
        local.stripe_subscription_id = str(obj["subscription"])


async def _grant_credit_pack(
    session: AsyncSession,
    obj: dict[str, Any],
    event_id: str,
    user_id: uuid.UUID,
    metadata: dict[str, Any],
    pack_credits: dict[str, int],
) -> None:
    # Only fulfill once the money has actually settled. Stripe fires
    # checkout.session.completed for delayed-payment methods while payment_status
    # is still "unpaid" — granting then would be a revenue leak if the payment
    # later fails (SOLUSDEV-83 sec review H1).
    if obj.get("payment_status") != "paid":
        logger.info("checkout payment not settled (status=%r); no grant", obj.get("payment_status"))
        return
    price_id = metadata.get("price_id")
    amount = pack_credits.get(price_id) if price_id else None
    if not amount:
        logger.warning("checkout payment with unknown credit pack price=%r", price_id)
        return
    # Idempotent by event id — a replayed purchase never double-grants.
    result = await credits.add_credits(
        session,
        user_id,
        amount,
        CreditTxnType.PURCHASE,
        idempotency_key=f"stripe:{event_id}",
        attrs={"price_id": price_id, "checkout": obj.get("id")},
    )
    # Notify only when the grant actually applied (never on a deduped replay).
    if result.applied:
        notify_user(
            session,
            user_id=user_id,
            notification_type=NotificationType.PAYMENT_SUCCEEDED,
            title="Credits added",
            body=f"{amount:,} credits were added to your balance.",
            attrs={"credits": amount, "price_id": price_id},
        )


async def _apply_invoice_failed(session: AsyncSession, obj: dict[str, Any]) -> None:
    customer = obj.get("customer")
    if not customer:
        return
    local = await session.scalar(
        select(Subscription).where(
            Subscription.stripe_customer_id == customer, Subscription.deleted_at.is_(None)
        )
    )
    if local is None:
        return
    local.status = SubscriptionStatus.PAST_DUE
    notify_user(
        session,
        user_id=local.user_id,
        notification_type=NotificationType.PAYMENT_FAILED,
        title="Payment failed",
        body="We couldn't process your latest payment. Update your billing to avoid interruption.",
        attrs={"invoice": obj.get("id")},
    )


@dataclass(frozen=True)
class _EventMeta:
    """Everything a handler may need beyond the event object itself."""

    event_id: str
    etype: str
    created: datetime
    pack_credits: dict[str, int]
    plan_prices: dict[str, str]


async def _on_subscription(session: AsyncSession, obj: dict[str, Any], meta: _EventMeta) -> None:
    await _apply_subscription(session, obj, meta.etype, meta.created, meta.plan_prices)


async def _on_checkout(session: AsyncSession, obj: dict[str, Any], meta: _EventMeta) -> None:
    await _apply_checkout(session, obj, meta.event_id, meta.pack_credits)


async def _on_invoice_failed(session: AsyncSession, obj: dict[str, Any], meta: _EventMeta) -> None:
    await _apply_invoice_failed(session, obj)


type _Handler = Callable[[AsyncSession, dict[str, Any], _EventMeta], Awaitable[None]]

# The dispatch table is the single source of truth for what we handle.
_HANDLERS: dict[str, _Handler] = {
    **dict.fromkeys(_SUBSCRIPTION_EVENTS, _on_subscription),
    "checkout.session.completed": _on_checkout,
    "invoice.payment_failed": _on_invoice_failed,
}

# Every event type process_event() handles — derived from the dispatch table so
# the two can never drift. `stripe-setup webhook` registers exactly this list on
# the production endpoint: an event handled here but not subscribed there would
# silently break billing.
WEBHOOK_EVENT_TYPES: frozenset[str] = frozenset(_HANDLERS)


async def process_event(
    session: AsyncSession,
    event: dict[str, Any],
    *,
    pack_credits: dict[str, int],
    plan_prices: dict[str, str] | None = None,
) -> bool:
    """Dispatch one Stripe event. Returns True if newly processed, False if it was
    a duplicate (already recorded). Idempotent and out-of-order safe. `plan_prices`
    maps Stripe Price ids → plan (for deriving entitlement from a subscription)."""
    plan_prices = plan_prices or {}
    event_id = str(event["id"])
    etype = str(event["type"])

    seen = await session.scalar(
        select(ProcessedStripeEvent.id).where(ProcessedStripeEvent.stripe_event_id == event_id)
    )
    if seen is not None:
        return False

    obj = event.get("data", {}).get("object", {})
    created = _event_dt(int(event.get("created") or 0))

    handler = _HANDLERS.get(etype)
    if handler is not None:
        meta = _EventMeta(
            event_id=event_id,
            etype=etype,
            created=created,
            pack_credits=pack_credits,
            plan_prices=plan_prices,
        )
        await handler(session, obj, meta)
    else:
        logger.info("stripe event ignored type=%s", etype)

    session.add(ProcessedStripeEvent(stripe_event_id=event_id, event_type=etype))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if not _is_duplicate_event_race(exc):
            # Any OTHER integrity failure (e.g. a CHECK violation because the
            # schema is behind the code) must propagate: a swallowed error here
            # returns 200 to Stripe, which never retries — the customer would be
            # charged with the entitlement silently lost (sec review H1).
            raise
        # A concurrent delivery recorded the same event id first — treat as dup.
        return False
    return True


# The unique index on processed_stripe_events.stripe_event_id — the ONLY
# constraint whose violation is the benign concurrent-delivery race.
_EVENT_ID_CONSTRAINT = "ix_processed_stripe_events_stripe_event_id"
_UNIQUE_VIOLATION_SQLSTATE = "23505"


def _is_duplicate_event_race(exc: IntegrityError) -> bool:
    """True only for a unique violation on the processed-events event id."""
    # The asyncpg driver wraps the real error; walk to it for its fields.
    cause = getattr(exc.orig, "__cause__", None) or exc.orig
    sqlstate = getattr(cause, "sqlstate", None)
    if sqlstate is not None and sqlstate != _UNIQUE_VIOLATION_SQLSTATE:
        return False
    constraint = getattr(cause, "constraint_name", None)
    if constraint is not None:
        return bool(constraint == _EVENT_ID_CONSTRAINT)
    return _EVENT_ID_CONSTRAINT in str(exc)
