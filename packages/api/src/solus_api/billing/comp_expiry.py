"""Materialise expired staff comps (SOLUSDEV-313, ADR-023 clarification 2026-10-07).

Read paths already ignore an expired comp (`billing/entitlements.py`), so entitlement
is correct without this job. The sweep only makes the revert durable: it clears the
stale comp fields and tells the user. Stripe-backed rows are never touched (their comps
live in Stripe and revert through the subscription schedule + webhook).
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import NotificationType, Subscription, SubscriptionStatus, utcnow
from solus_api.services.notifications import notify_user

logger = logging.getLogger("solus.billing.comp_expiry")

DEFAULT_SWEEP_BATCH = 100
# Bounds one run so a flood of expiries cannot monopolise the worker; the next cron
# tick resumes where this one stopped.
MAX_SWEEP_BATCHES = 50


async def _sweep_batch(session: AsyncSession, moment: datetime, limit: int) -> list[uuid.UUID]:
    """Clear and commit ONE batch (oldest expiry first); returns the affected user ids."""
    rows = (
        await session.scalars(
            select(Subscription)
            .where(
                Subscription.deleted_at.is_(None),
                Subscription.comp_plan.is_not(None),
                Subscription.comp_expires_at.is_not(None),
                Subscription.comp_expires_at <= moment,
                or_(
                    Subscription.stripe_subscription_id.is_(None),
                    Subscription.status == SubscriptionStatus.CANCELED,
                ),
            )
            .order_by(Subscription.comp_expires_at, Subscription.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    swept: list[uuid.UUID] = []
    for sub in rows:
        label = sub.comp_plan.value.capitalize() if sub.comp_plan else "plan"
        sub.comp_plan = None
        sub.comp_expires_at = None
        notify_user(
            session,
            user_id=sub.user_id,
            notification_type=NotificationType.SUBSCRIPTION_ENDED,
            title="Complimentary access ended",
            body=f"Your complimentary {label} access ended — your plan limits now apply.",
            attrs={"comp_plan": label.lower()},
        )
        swept.append(sub.user_id)
    await session.commit()
    return swept


async def sweep_expired_comps(
    session: AsyncSession,
    now: datetime | None = None,
    limit: int = DEFAULT_SWEEP_BATCH,
    max_batches: int = MAX_SWEEP_BATCHES,
) -> list[uuid.UUID]:
    """Clear every expired comp (oldest expiry first, `limit` rows per batch, at most
    `max_batches` batches) and notify each user.

    Each batch is committed before the next. Idempotent: a cleared row no longer
    matches. `FOR UPDATE SKIP LOCKED` lets concurrent sweeps and admin operations
    coexist without blocking or double notifying. Returns the affected user ids."""
    if limit < 1 or max_batches < 1:
        raise ValueError("limit and max_batches must be >= 1")
    moment = now or utcnow()
    swept: list[uuid.UUID] = []
    for _ in range(max_batches):
        batch = await _sweep_batch(session, moment, limit)
        swept.extend(batch)
        if len(batch) < limit:
            break
    if swept:
        logger.info("comp expiry swept count=%d", len(swept))
    return swept
