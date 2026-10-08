"""PATCH /users/me/subscription is trial-only (SOLUSDEV-313 Phase 1 decision)."""

import uuid

import pytest
from conftest import me
from httpx import AsyncClient
from solus_api.models import PlanType, Subscription, SubscriptionStatus, default_limits
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

URL = "/api/v1/users/me/subscription"


async def _sub(db: AsyncSession, user_id: str) -> Subscription:
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == uuid.UUID(user_id)))
    assert sub is not None
    await db.refresh(sub)
    return sub


async def test_allowed_while_trialing_without_stripe_and_expiry_never_restarts(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    before = (await _sub(db, alice["id"])).expires_at
    for plan in ("pro", "basic", "pro"):
        resp = await client.patch(URL, json={"plan": plan}, headers=alice_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["plan"] == plan
        assert resp.json()["data"]["status"] == "trialing"
    sub = await _sub(db, alice["id"])
    assert sub.expires_at == before
    assert sub.limits == default_limits(PlanType.PRO)


@pytest.mark.parametrize(
    "status",
    [SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED, SubscriptionStatus.PAST_DUE],
)
async def test_blocked_unless_trialing(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str], status: SubscriptionStatus
) -> None:
    alice = await me(client, alice_headers)
    sub = await _sub(db, alice["id"])
    sub.status = status
    await db.commit()
    resp = await client.patch(URL, json={"plan": "pro"}, headers=alice_headers)
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "subscription_change_not_allowed"
    assert "Billing" in error["message"]
    after = await _sub(db, alice["id"])
    assert after.plan is PlanType.BASIC
    assert after.status is status


async def test_blocked_when_stripe_subscription_exists(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    sub = await _sub(db, alice["id"])
    sub.stripe_subscription_id = "sub_test_123"
    await db.commit()  # still TRIALING (Stripe trial) - must be blocked anyway
    resp = await client.patch(URL, json={"plan": "pro"}, headers=alice_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "subscription_change_not_allowed"
    assert (await _sub(db, alice["id"])).plan is PlanType.BASIC


async def test_requires_auth(client: AsyncClient) -> None:
    assert (await client.patch(URL, json={"plan": "pro"})).status_code == 401


async def test_only_affects_own_subscription(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    await me(client, alice_headers)
    bob = await me(client, bob_headers)
    resp = await client.patch(URL, json={"plan": "pro"}, headers=alice_headers)
    assert resp.status_code == 200
    bob_sub = await _sub(db, bob["id"])
    assert bob_sub.plan is PlanType.BASIC
    assert bob_sub.limits == default_limits(PlanType.BASIC)


@pytest.mark.parametrize("plan", ["enterprise", "free", "", None])
async def test_trial_cannot_self_select_non_checkoutable_plan(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str], plan: str | None
) -> None:
    alice = await me(client, alice_headers)
    resp = await client.patch(URL, json={"plan": plan}, headers=alice_headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
    after = await _sub(db, alice["id"])
    assert after.plan is PlanType.BASIC
    assert after.limits == default_limits(PlanType.BASIC)
