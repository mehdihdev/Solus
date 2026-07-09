"""Per-user plan-limit enforcement (SOLUSDEV-72 Decisions C-E, ADR-023/032).

Limits are per-user, read as DATA (not plan name), the personal team is exempt, the cross-plan
block fires at invite acceptance, and the count-then-create is race-safe.
"""

import asyncio
import uuid

from conftest import BOB, create_project, create_team, me
from httpx import AsyncClient
from solus_api.models import (
    PlanType,
    Project,
    Source,
    SourceStatus,
    SourceType,
    Subscription,
    SubscriptionStatus,
    User,
)
from solus_api.services.limits import check_can_add_integration
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _subscription(db: AsyncSession, user_id: str) -> Subscription:
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == uuid.UUID(user_id)))
    assert sub is not None
    return sub


async def test_signup_auto_provisions_basic_trial(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    sub = await _subscription(db, alice["id"])
    assert sub.plan is PlanType.BASIC
    assert sub.status is SubscriptionStatus.TRIALING
    assert sub.limits == {"max_integrations": 4, "max_projects": 3, "max_teams": 2}
    assert sub.expires_at is not None  # ~ now + 14 days


async def test_team_limit_blocks_and_personal_is_exempt(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    # BASIC max_teams == 2 COLLABORATIVE teams. Both succeed → the PERSONAL team (a 3rd team
    # by raw count) is NOT counted, or the second would already be blocked.
    await create_team(client, alice_headers, "T1")
    await create_team(client, alice_headers, "T2")
    resp = await client.post("/api/v1/teams", json={"name": "T3"}, headers=alice_headers)
    assert resp.status_code == 409, resp.text
    body = resp.json()["error"]
    assert body["code"] == "plan_limit_reached"
    assert body["details"][0]["limit"] == "max_teams"
    assert "upgrade" in body["details"][0]


async def test_enforcement_reads_limits_as_data_not_plan(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    sub = await _subscription(db, alice["id"])
    sub.limits = {"max_teams": 1}  # a CUSTOM limit, not BASIC's 2 — enforcement must honor it
    await db.commit()
    await create_team(client, alice_headers, "T1")
    resp = await client.post("/api/v1/teams", json={"name": "T2"}, headers=alice_headers)
    assert resp.status_code == 409  # blocked at the custom limit of 1, proving data-driven


async def test_unlimited_when_limit_is_null(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    sub = await _subscription(db, alice["id"])
    sub.limits = {"max_teams": None}  # null = unlimited
    await db.commit()
    for i in range(4):
        resp = await client.post("/api/v1/teams", json={"name": f"T{i}"}, headers=alice_headers)
        assert resp.status_code == 201, resp.text


async def test_project_limit_blocks_fourth(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    team = await create_team(client, alice_headers, "T")
    for i in range(3):  # BASIC max_projects == 3
        await create_project(client, alice_headers, team["id"], f"P{i}")
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/projects", json={"name": "P4"}, headers=alice_headers
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["details"][0]["limit"] == "max_projects"


async def test_integration_limit_via_helper(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    team = await create_team(client, alice_headers, "T")
    project = await create_project(client, alice_headers, team["id"], "P")
    # BASIC max_integrations == 4: seed 4 CONNECTED sources this user created.
    for i in range(4):
        db.add(
            Source(
                project_id=uuid.UUID(project["id"]),
                team_id=uuid.UUID(team["id"]),
                type=SourceType.GITHUB,
                name=f"s{i}",
                status=SourceStatus.CONNECTED,
                created_by=uuid.UUID(alice["id"]),
            )
        )
    await db.commit()
    user = await db.get(User, uuid.UUID(alice["id"]))
    assert user is not None
    try:
        await check_can_add_integration(db, user)
        raise AssertionError("expected the 5th integration to be blocked")
    except Exception as exc:  # noqa: BLE001 — asserting the limit error shape
        assert getattr(exc, "code", None) == "plan_limit_reached"


async def test_cross_plan_invite_blocked_at_acceptance(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    await me(client, alice_headers)
    bob = await me(client, bob_headers)
    bob_sub = await _subscription(db, bob["id"])
    bob_sub.limits = {"max_teams": 0}  # Bob is at (over) his collaborative-team limit
    await db.commit()
    team = await create_team(client, alice_headers, "Acme")
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/invites",
        json={"email": BOB["email"], "role": "member"},
        headers=alice_headers,
    )
    token = resp.json()["data"]["token"]
    accept = await client.post(f"/api/v1/invites/{token}/accept", headers=bob_headers)
    assert accept.status_code == 409, accept.text
    assert accept.json()["error"]["details"][0]["limit"] == "max_teams"


async def test_project_create_is_race_safe(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    """Two concurrent creates at the boundary must not both slip past the limit (FOR UPDATE)."""
    alice = await me(client, alice_headers)
    team = await create_team(client, alice_headers, "T")
    sub = await _subscription(db, alice["id"])
    sub.limits = {"max_projects": 1}  # room for exactly one more project
    await db.commit()
    r1, r2 = await asyncio.gather(
        client.post(
            f"/api/v1/teams/{team['id']}/projects", json={"name": "A"}, headers=alice_headers
        ),
        client.post(
            f"/api/v1/teams/{team['id']}/projects", json={"name": "B"}, headers=alice_headers
        ),
    )
    codes = sorted([r1.status_code, r2.status_code])
    assert codes == [201, 409], codes  # exactly one succeeds
    count = await db.scalar(
        select(func.count())
        .select_from(Project)
        .where(Project.created_by == uuid.UUID(alice["id"]))
    )
    assert count == 1


async def test_patch_subscription_changes_plan_and_limits(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    resp = await client.patch(
        "/api/v1/users/me/subscription", json={"plan": "pro"}, headers=alice_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["plan"] == "pro"
    assert data["status"] == "trialing"
    assert data["limits"] == {"max_integrations": None, "max_projects": None, "max_teams": None}
    assert data["expires_at"] is not None
