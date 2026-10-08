"""One-time plan starting credits (ADR-023/024, amended 2026-08-08).

Extracted unchanged from `stripe_events` (SOLUSDEV-313) so other billing paths can
reuse it without importing the webhook dispatcher."""

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing import credits
from solus_api.models import (
    CreditTxnType,
    NotificationType,
    Subscription,
    SubscriptionStatus,
)
from solus_api.services.notifications import notify_user

LIVE_STATUSES = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING})


async def grant_plan_credits(
    session: AsyncSession, local: Subscription, grants: dict[str, int]
) -> None:
    """One-time starting credits when a paid plan is live (ADR-023/024, amended
    2026-08-08). Idempotent per (user, plan): renewals/replays never re-grant;
    an upgrade grants the new plan's amount exactly once.

    The credit primitive owns its transaction and ROLLS BACK on a duplicate key
    (every renewal after the first), which would discard this event's pending
    subscription updates — so those are committed first, and `local` is not
    touched afterward (the instance expires on commit)."""
    if local.status not in LIVE_STATUSES:
        return
    plan_value = local.plan.value
    amount = grants.get(plan_value)
    if not amount:
        return
    user_id = local.user_id
    await session.commit()
    result = await credits.add_credits(
        session,
        user_id,
        amount,
        CreditTxnType.PLAN_GRANT,
        idempotency_key=credits.plan_grant_key(user_id, plan_value),
        attrs={"reason": "plan_grant", "plan": plan_value},
    )
    if result.applied:
        notify_user(
            session,
            user_id=user_id,
            notification_type=NotificationType.PAYMENT_SUCCEEDED,
            title="Credits added",
            body=f"{amount:,} credits are included with your {plan_value.capitalize()} plan.",
            attrs={"credits": amount, "plan": plan_value},
        )
