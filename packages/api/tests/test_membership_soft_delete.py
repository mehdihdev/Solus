"""SOLUSDEV-216 ride-along: soft-deleted memberships are invisible to team listings,
member counts and the last-owner guard (ADR-027 soft delete)."""

import uuid

from conftest import BOB, add_member, create_team, me
from httpx import AsyncClient
from solus_api.models import Membership, utcnow
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession


async def _soft_delete(db: AsyncSession, team_id: str, user_id: str) -> None:
    await db.execute(
        update(Membership)
        .where(
            Membership.team_id == uuid.UUID(team_id),
            Membership.user_id == uuid.UUID(user_id),
        )
        .values(deleted_at=utcnow())
    )
    await db.commit()


async def test_list_teams_hides_a_soft_deleted_membership(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team = await create_team(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    await _soft_delete(db, team["id"], bob["id"])

    resp = await client.get("/api/v1/teams", headers=bob_headers)

    assert resp.status_code == 200
    assert team["id"] not in {t["id"] for t in resp.json()["data"]}


async def test_member_list_and_count_exclude_soft_deleted_rows(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team = await create_team(client, alice_headers)
    alice = await me(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    await _soft_delete(db, team["id"], bob["id"])

    members = await client.get(f"/api/v1/teams/{team['id']}/members", headers=alice_headers)
    detail = await client.get(f"/api/v1/teams/{team['id']}", headers=alice_headers)

    assert {m["user_id"] for m in members.json()["data"]} == {alice["id"]}
    assert detail.json()["data"]["member_count"] == 1


async def test_last_owner_guard_ignores_a_soft_deleted_owner(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team = await create_team(client, alice_headers)
    alice = await me(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="admin")
    promoted = await client.patch(
        f"/api/v1/teams/{team['id']}/members/{bob['id']}",
        json={"role": "owner"},
        headers=alice_headers,
    )
    assert promoted.status_code == 200
    await _soft_delete(db, team["id"], bob["id"])

    # Bob's tombstoned ownership must not count: Alice is the last live owner.
    resp = await client.patch(
        f"/api/v1/teams/{team['id']}/members/{alice['id']}",
        json={"role": "member"},
        headers=alice_headers,
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "last_owner"
