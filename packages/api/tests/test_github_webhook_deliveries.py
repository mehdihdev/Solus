"""Webhook delivery idempotency claims and pruning."""

from datetime import timedelta

import pytest
from solus_api.models import GitHubWebhookDelivery, utcnow
from solus_api.services.github_webhook_deliveries import claim_delivery, prune_deliveries
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

VALID = "72d3162e-cc78-11e3-81ab-4c9367dc0958"


async def test_first_claim_wins_and_duplicate_is_refused(db: AsyncSession) -> None:
    assert await claim_delivery(db, VALID) is True
    assert await claim_delivery(db, VALID) is False
    assert await claim_delivery(db, "another-1") is True


@pytest.mark.parametrize("bad", ["", "a" * 65, "bad id", "x;drop", "a/b", "é", "id\n"])
async def test_invalid_delivery_id_is_rejected(db: AsyncSession, bad: str) -> None:
    with pytest.raises(ValueError, match="delivery"):
        await claim_delivery(db, bad)


async def test_64_char_id_is_accepted(db: AsyncSession) -> None:
    assert await claim_delivery(db, "a" * 64) is True


async def test_prune_removes_only_rows_older_than_seven_days(db: AsyncSession) -> None:
    now = utcnow()
    db.add_all(
        [
            GitHubWebhookDelivery(delivery_id="old", received_at=now - timedelta(days=8)),
            GitHubWebhookDelivery(delivery_id="edge", received_at=now - timedelta(days=6)),
            GitHubWebhookDelivery(delivery_id="new", received_at=now),
        ]
    )
    await db.flush()
    assert await prune_deliveries(db) == 1
    left = (await db.execute(select(GitHubWebhookDelivery.delivery_id))).scalars().all()
    assert sorted(left) == ["edge", "new"]


async def test_prune_honours_a_custom_window(db: AsyncSession) -> None:
    db.add(GitHubWebhookDelivery(delivery_id="d", received_at=utcnow() - timedelta(hours=2)))
    await db.flush()
    assert await prune_deliveries(db, older_than=timedelta(hours=1)) == 1


async def test_claim_sets_received_at(db: AsyncSession) -> None:
    await claim_delivery(db, VALID)
    row = (await db.execute(select(GitHubWebhookDelivery))).scalar_one()
    assert abs((utcnow() - row.received_at).total_seconds()) < 60
