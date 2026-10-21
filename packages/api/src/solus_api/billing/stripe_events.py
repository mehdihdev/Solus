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
from solus_api.billing.plan_grants import LIVE_STATUSES, grant_plan_credits
from solus_api.billing.stripe_gateway import ADMIN_ACTION_METADATA_KEY
from solus_api.billing.stripe_state import (
    STATUS_MAP,
    StripeSubscriptionState,
    as_dict,
    derive_subscription_state,
)
from solus_api.models import (
    CreditTxnType,
    NotificationType,
    PlanType,
    ProcessedStripeEvent,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
)
from solus_api.services.notifications import notify_user
from solus_api.services.stripe_cancel import enqueue_stripe_cancel, is_tombstoned_customer

logger = logging.getLogger("solus.billing.stripe")

_SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
)

# Subscription statuses that mean "this subscription is over" — never worth cancelling.
_TERMINAL_STRIPE_STATUSES = frozenset({"canceled", "incomplete_expired"})


_as_dict = as_dict


def _as_id(value: object) -> str | None:
    """A non-empty string id, else None (Stripe ids are strings; anything else is junk)."""
    return value if isinstance(value, str) and value else None


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


def _is_admin_originated(obj: dict[str, Any], previous: dict[str, Any]) -> bool:
    """True only when THIS event changed the staff-action marker in subscription metadata.

    Metadata persists on the subscription, so a stale marker on a later customer-initiated
    change must not count: the marker has to appear in `previous_attributes.metadata`
    (Stripe lists only changed keys there) with a different current value. Used for
    notification wording ONLY — never for authorization or entitlement."""
    previous_meta = _as_dict(previous.get("metadata"))
    if ADMIN_ACTION_METADATA_KEY not in previous_meta:
        return False
    current = _as_id(_as_dict(obj.get("metadata")).get(ADMIN_ACTION_METADATA_KEY))
    return current is not None and current != previous_meta[ADMIN_ACTION_METADATA_KEY]


async def _cancel_if_tombstoned(
    session: AsyncSession, customer: object, subscription: object
) -> None:
    """Late-checkout race: a live subscription arrived for a customer whose account is
    already deleted. Enqueue the durable cancel (the runner calls Stripe, never this
    handler) for the subscription id in the SIGNED payload only; non-tombstoned customers
    are untouched, so a spoofed customer id cannot cancel anyone else's subscription."""
    customer_id = _as_id(customer)
    if customer_id is None or not await is_tombstoned_customer(session, customer_id):
        return
    try:
        await enqueue_stripe_cancel(
            session, customer_id=customer_id, subscription_id=_as_id(subscription)
        )
    except ValueError:
        logger.warning(
            "tombstoned customer %s: malformed Stripe id; no cancel enqueued", customer_id
        )
        return
    logger.warning("late Stripe subscription for deleted customer %s; cancel enqueued", customer_id)


async def _refuses_tombstoned_customer(
    session: AsyncSession, local: Subscription, customer: str | None
) -> bool:
    """True when `customer` is a deleted account's tombstoned Stripe customer that the live
    local row does not already own. A live user's own customer is never tombstoned, so this
    only trips on a mis-attributed signed event (Dashboard/Payment Link checkout, staff
    error).

    What the refusal does and does NOT do: it only stops the live user's LOCAL row being
    relinked to the dead customer (so the row is never canceled or redacted along with it).
    The dead customer's subscription is canceled through its own
    `customer.subscription.created` event (`_handle_unmatched`), and the live user was
    therefore billed for a first period without getting entitlement: that needs a MANUAL
    refund. Hence the ERROR log with a stable marker for operator alerting (ids only, no PII).
    """
    if not customer or customer == local.stripe_customer_id:
        return False
    if not await is_tombstoned_customer(session, customer):
        return False
    logger.error(
        "billing.tombstoned_customer_refused: not attaching tombstoned customer %s to live "
        "subscription row %s; the live user may have been charged without entitlement and "
        "need a manual refund",
        customer,
        local.id,
    )
    return True


async def _handle_unmatched(
    session: AsyncSession, obj: dict[str, Any], etype: str, customer: str | None, sub_id: str | None
) -> None:
    """A subscription event with no live local row: a safe no-op, except that a LIVE
    subscription for an already-tombstoned customer is queued for cancellation."""
    if etype == "customer.subscription.deleted":
        return
    if str(obj.get("status")) in _TERMINAL_STRIPE_STATUSES:
        return
    await _cancel_if_tombstoned(session, customer, sub_id)


async def _matched_subscription(
    session: AsyncSession, obj: dict[str, Any], etype: str, customer: str | None, sub_id: str | None
) -> Subscription | None:
    """The live local row this event applies to, or None when it must be ignored (no match,
    or a match whose customer is a refused tombstoned one)."""
    local = await _sub_by(session, customer=customer, sub_id=sub_id)
    if local is None:
        logger.warning(
            "stripe subscription event with no local match sub=%s cus=%s", sub_id, customer
        )
        await _handle_unmatched(session, obj, etype, customer, sub_id)
        return None
    if await _refuses_tombstoned_customer(session, local, customer):
        return None
    return local


async def _apply_subscription(
    session: AsyncSession, obj: dict[str, Any], meta: "_EventMeta"
) -> None:
    etype, created, previous = meta.etype, meta.created, meta.previous_attributes
    plan_prices, plan_credit_grants = meta.plan_prices, meta.plan_credit_grants
    sub_id = _as_id(obj.get("id"))
    customer = _as_id(obj.get("customer"))
    local = await _matched_subscription(session, obj, etype, customer, sub_id)
    if local is None:
        return
    # Out-of-order guard: ignore an event older than the last one applied.
    if local.stripe_event_at is not None and created < local.stripe_event_at:
        return
    new_link = _is_new_link(local.stripe_subscription_id, sub_id)
    if sub_id:
        local.stripe_subscription_id = sub_id
    if customer:
        local.stripe_customer_id = customer
    apply_subscription_state(
        session,
        local,
        obj,
        plan_prices,
        deleted=etype == "customer.subscription.deleted",
        by_support=_is_admin_originated(obj, previous),
    )
    local.stripe_event_at = created
    if new_link and local.status is not SubscriptionStatus.CANCELED:
        _clear_comp(local)
    await grant_plan_credits(session, local, plan_credit_grants)


def apply_subscription_state(
    session: AsyncSession,
    local: Subscription,
    obj: dict[str, Any],
    plan_prices: dict[str, str],
    *,
    deleted: bool = False,
    by_support: bool = False,
) -> None:
    """Converge `local` onto a Stripe subscription object and queue the user notifications
    the transition warrants. Shared by the webhook and the SOLUSDEV-236 reconciler so both
    paths derive entitlement identically. Does not touch link ids, `stripe_event_at`, comps
    or plan credits: those belong to the caller (event ordering is the caller's concern)."""
    old_plan, old_status, old_cancel_at = local.plan, local.status, local.cancel_at
    state = derive_subscription_state(obj, plan_prices, deleted=deleted)
    if deleted:
        local.status = SubscriptionStatus.CANCELED
    else:
        _apply_live_state(local, obj, state)
    if local.status is SubscriptionStatus.CANCELED and old_status in LIVE_STATUSES:
        _apply_term_end(session, local)
    else:
        _notify_cancel_transition(session, local, old_cancel_at)
    _notify_if_entitlement_changed(
        session, local, old_plan=old_plan, old_status=old_status, by_support=by_support
    )


def _apply_live_state(
    local: Subscription, obj: dict[str, Any], state: StripeSubscriptionState
) -> None:
    """Write a non-deleted event's derived state onto the row. Entitlement comes from what
    was actually purchased (the Stripe Price), never a client-supplied plan name. Period
    mirrors are only overwritten by a value Stripe actually sent (`expires_at`)."""
    if str(obj.get("status")) in STATUS_MAP:  # unknown Stripe status keeps the local one
        local.status = state.status
    if state.plan is not None:
        local.plan = state.plan
        local.limits = default_limits(state.plan)
    local.cancel_at = state.cancel_at
    local.billing_interval = state.interval
    local.current_period_end = state.current_period_end
    if state.expires_at is not None:
        local.expires_at = state.expires_at


def _is_new_link(stored_sub_id: str | None, incoming_sub_id: str | None) -> bool:
    """True when an incoming subscription id differs from the one stored (or none is
    stored): a resubscribe after cancellation gets a NEW id, so it counts; replays of
    the already-linked id do not."""
    return incoming_sub_id is not None and incoming_sub_id != stored_sub_id


def _clear_comp(local: Subscription) -> None:
    """A paid Stripe subscription was linked (a new subscription id): it supersedes any local
    staff comp (plan/limits come from what was bought). `limits_override` is untouched."""
    local.comp_plan = None
    local.comp_expires_at = None


def _apply_term_end(session: AsyncSession, local: Subscription) -> None:
    """A live subscription actually ended (deletion at term end, or an updated
    event landing `canceled`): the account stops being entitled — limits clamp
    to the BASIC tier (the smallest paid plan's caps, ADR-023), the pending
    cancel marker clears (the billing-page bar goes away), and the user is told.
    The out-of-order guard upstream makes this fire once per real transition."""
    local.cancel_at = None
    local.limits = default_limits(PlanType.BASIC)
    plan_label = local.plan.value.capitalize()
    notify_user(
        session,
        user_id=local.user_id,
        notification_type=NotificationType.SUBSCRIPTION_ENDED,
        title="Subscription ended",
        body=(
            f"Your {plan_label} plan has ended — limits now match the Basic tier. "
            "You can resubscribe anytime from Billing."
        ),
        attrs={"plan": local.plan.value},
    )


def _notify_cancel_transition(
    session: AsyncSession, local: Subscription, old_cancel_at: datetime | None
) -> None:
    """Notify when a LIVE subscription's scheduled cancellation appears or is
    undone. Same-state replays/renewals stay silent."""
    if local.status not in LIVE_STATUSES:
        return
    plan_label = local.plan.value.capitalize()
    if local.cancel_at is not None and old_cancel_at is None:
        notify_user(
            session,
            user_id=local.user_id,
            notification_type=NotificationType.SUBSCRIPTION_CANCELED,
            title="Subscription canceled",
            body=(
                f"Your {plan_label} plan ends on {local.cancel_at:%B %d, %Y} — "
                "you keep full access until then."
            ),
            attrs={"plan": local.plan.value, "cancel_at": local.cancel_at.isoformat()},
        )
    elif local.cancel_at is None and old_cancel_at is not None:
        notify_user(
            session,
            user_id=local.user_id,
            notification_type=NotificationType.SUBSCRIPTION_RESUMED,
            title="Subscription resumed",
            body=f"The scheduled cancellation was undone — your {plan_label} plan continues.",
            attrs={"plan": local.plan.value},
        )


def _notify_if_entitlement_changed(
    session: AsyncSession,
    local: Subscription,
    *,
    old_plan: object,
    old_status: SubscriptionStatus,
    by_support: bool = False,
) -> None:
    """One in-app notification when a payment takes effect: entering a live
    (active/trialing) status, or switching plans while live. Routine renewals
    (same plan, still live) stay silent; the event-id dedupe and out-of-order
    guards upstream make this at-most-once per Stripe event."""
    if local.status not in LIVE_STATUSES:
        return
    became_live = old_status not in LIVE_STATUSES
    plan_changed = local.plan != old_plan
    if not (became_live or plan_changed):
        return
    plan_label = local.plan.value.capitalize()
    body = f"You're on the {plan_label} plan."
    if by_support and plan_changed and not became_live:
        # Honest wording only; no staff identity or action id leaves the server.
        body = f"Your plan was changed by Solus support. {body}"
    notify_user(
        session,
        user_id=local.user_id,
        notification_type=NotificationType.PAYMENT_SUCCEEDED,
        title="Payment successful" if became_live else "Plan updated",
        body=body,
        attrs={"plan": local.plan.value, "subscription": local.stripe_subscription_id},
    )


async def _apply_checkout(
    session: AsyncSession, obj: dict[str, Any], event_id: str, pack_credits: dict[str, int]
) -> None:
    metadata = _as_dict(obj.get("metadata"))
    is_subscription = obj.get("mode") == "subscription"
    user_id = _checkout_user_id(obj, metadata)
    # Guard against a spoofed/stale user reference: never touch credits for a user
    # that doesn't exist (also avoids an FK crash from the grant).
    if user_id is None or await session.get(User, user_id) is None:
        if user_id is not None:
            logger.warning("checkout.session.completed for unknown user %s", user_id)
        if is_subscription:
            await _cancel_if_tombstoned(session, obj.get("customer"), obj.get("subscription"))
        return

    if is_subscription:
        if not await _link_subscription_customer(session, obj, user_id):
            await _cancel_if_tombstoned(session, obj.get("customer"), obj.get("subscription"))
    elif obj.get("mode") == "payment":
        await _grant_credit_pack(session, obj, event_id, user_id, metadata, pack_credits)


def _checkout_user_id(obj: dict[str, Any], metadata: dict[str, Any]) -> uuid.UUID | None:
    raw_user = obj.get("client_reference_id") or metadata.get("solus_user_id")
    if not raw_user:
        logger.warning("checkout.session.completed with no user reference")
        return None
    try:
        return uuid.UUID(str(raw_user))
    except ValueError:
        logger.warning("checkout.session.completed with bad user reference %r", raw_user)
        return None


async def _link_subscription_customer(
    session: AsyncSession, obj: dict[str, Any], user_id: uuid.UUID
) -> bool:
    """Link the Stripe customer/subscription to the user's local row. Returns False when
    there is no live local subscription to link."""
    local = await session.scalar(
        select(Subscription).where(
            Subscription.user_id == user_id, Subscription.deleted_at.is_(None)
        )
    )
    if local is None:
        return False
    customer, stripe_sub = _as_id(obj.get("customer")), _as_id(obj.get("subscription"))
    if await _refuses_tombstoned_customer(session, local, customer):
        # Handled (ignored): the local row stays as it was. The dead customer's own
        # subscription is canceled via its subscription event, not here.
        return True
    if customer:
        local.stripe_customer_id = customer
    if stripe_sub:
        if _is_new_link(local.stripe_subscription_id, stripe_sub):
            _clear_comp(local)  # a new paid link supersedes a local comp
        local.stripe_subscription_id = stripe_sub
    return True


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
    price_id = _as_id(metadata.get("price_id"))
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
    customer = _as_id(obj.get("customer"))
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
    plan_credit_grants: dict[str, int]
    # `data.previous_attributes` of the (signed) event; {} when absent/malformed.
    previous_attributes: dict[str, Any]


async def _on_subscription(session: AsyncSession, obj: dict[str, Any], meta: _EventMeta) -> None:
    await _apply_subscription(session, obj, meta)


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
    plan_credit_grants: dict[str, int] | None = None,
) -> bool:
    """Dispatch one Stripe event. Returns True if newly processed, False if it was
    a duplicate (already recorded). Idempotent and out-of-order safe. `plan_prices`
    maps Stripe Price ids → plan (for deriving entitlement from a subscription);
    `plan_credit_grants` maps plan value → its one-time starting credits."""
    plan_prices = plan_prices or {}
    plan_credit_grants = plan_credit_grants or {}
    event_id = str(event["id"])
    etype = str(event["type"])

    seen = await session.scalar(
        select(ProcessedStripeEvent.id).where(ProcessedStripeEvent.stripe_event_id == event_id)
    )
    if seen is not None:
        return False

    data = _as_dict(event.get("data"))
    obj = _as_dict(data.get("object"))
    created = _event_dt(int(event.get("created") or 0))

    handler = _HANDLERS.get(etype)
    if handler is not None:
        meta = _EventMeta(
            event_id=event_id,
            etype=etype,
            created=created,
            pack_credits=pack_credits,
            plan_prices=plan_prices,
            plan_credit_grants=plan_credit_grants,
            previous_attributes=_as_dict(data.get("previous_attributes")),
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
