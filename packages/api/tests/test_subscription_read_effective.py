"""SubscriptionRead serves EFFECTIVE limits (SOLUSDEV-313, ADR-023 clarification)."""

import uuid

from conftest import me
from httpx import AsyncClient
from solus_api.models import PlanType, Subscription, default_limits
from solus_api.schemas import SubscriptionRead
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _sub(db: AsyncSession, user_id: str) -> Subscription:
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == uuid.UUID(user_id)))
    assert sub is not None
    return sub


async def test_read_shows_stored_limits_without_override(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    resp = await client.get("/api/v1/users/me/subscription", headers=alice_headers)
    assert resp.json()["data"]["limits"] == default_limits(PlanType.BASIC)


async def test_read_merges_override_per_key(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    sub = await _sub(db, alice["id"])
    sub.limits_override = {"max_teams": None, "max_projects": 9}
    await db.commit()
    resp = await client.get("/api/v1/users/me/subscription", headers=alice_headers)
    data = resp.json()["data"]
    assert data["limits"]["max_teams"] is None
    assert data["limits"]["max_projects"] == 9
    assert data["limits"]["max_integrations"] == 4  # absent key falls through
    assert "limits_override" not in data
    assert "comp_plan" not in data


async def test_read_shows_active_comp_defaults(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    sub = await _sub(db, alice["id"])
    sub.comp_plan = PlanType.PRO
    await db.commit()
    resp = await client.get("/api/v1/users/me/subscription", headers=alice_headers)
    data = resp.json()["data"]
    assert data["limits"] == default_limits(PlanType.PRO)
    assert data["plan"] == "basic"  # stored plan unchanged; only limits are effective


async def test_model_validate_keeps_existing_fields_and_does_not_mutate(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    sub = await _sub(db, alice["id"])
    sub.limits_override = {"max_teams": 7}
    await db.commit()
    read = SubscriptionRead.model_validate(sub)
    assert read.limits["max_teams"] == 7
    assert sub.limits["max_teams"] == 2  # stored column untouched
    assert read.user_id == sub.user_id
    assert read.stripe_subscription_id is None
    assert read.seat_count == sub.seat_count
