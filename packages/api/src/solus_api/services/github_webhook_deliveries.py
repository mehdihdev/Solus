"""Idempotency ledger for GitHub App webhook deliveries (SOLUSDEV-216)."""

import re
from datetime import timedelta
from typing import cast

from sqlalchemy import CursorResult, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import GitHubWebhookDelivery, utcnow

DELIVERY_RETENTION = timedelta(days=7)
_MAX_DELIVERY_ID = 64
_DELIVERY_ID = re.compile(r"[A-Za-z0-9-]+", re.ASCII)


async def claim_delivery(session: AsyncSession, delivery_id: str) -> bool:
    """Record `delivery_id`; True only for the first claim (a redelivery returns False)."""
    if len(delivery_id) > _MAX_DELIVERY_ID or _DELIVERY_ID.fullmatch(delivery_id) is None:
        raise ValueError("invalid delivery id")
    result = await session.execute(
        insert(GitHubWebhookDelivery)
        .values(delivery_id=delivery_id, received_at=utcnow())
        .on_conflict_do_nothing(index_elements=["delivery_id"])
    )
    return cast(CursorResult[object], result).rowcount > 0


async def prune_deliveries(
    session: AsyncSession, older_than: timedelta = DELIVERY_RETENTION
) -> int:
    """Delete delivery records older than `older_than`; returns how many were removed."""
    result = await session.execute(
        delete(GitHubWebhookDelivery).where(
            GitHubWebhookDelivery.received_at < utcnow() - older_than
        )
    )
    await session.commit()
    return cast(CursorResult[object], result).rowcount
