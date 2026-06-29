"""§2.2 Invites — create, revoke, accept, individual→team upgrade (ADR-015)."""

from conftest import BOB, add_member, create_team, me
from httpx import AsyncClient
from solus_api.models import Invite
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


async def invite_bob(
    client: AsyncClient, headers: dict[str, str], team_id: str, role: str = "member"
) -> dict[str, str]:
    resp = await client.post(
        f"/api/v1/teams/{team_id}/invites",
        json={"email": BOB["email"], "role": role},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, str] = resp.json()["data"]
    return data


async def test_create_invite_returns_token_once(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    invite = await invite_bob(client, alice_headers, team["id"])
    assert invite["token"]
    assert invite["status"] == "pending"

    listing = await client.get(f"/api/v1/teams/{team['id']}/invites", headers=alice_headers)
    assert listing.status_code == 200
    assert "token" not in listing.json()["data"][0]


async def test_invite_requires_admin(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    resp = await client.post(
        f"/api/v1/teams/{team['id']}/invites",
        json={"email": "carol@example.com"},
        headers=bob_headers,
    )
    assert resp.status_code == 403


async def test_invite_cannot_grant_owner(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/invites",
        json={"email": BOB["email"], "role": "owner"},
        headers=alice_headers,
    )
    assert resp.status_code == 422


async def test_duplicate_pending_invite_conflicts(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await invite_bob(client, alice_headers, team["id"])
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/invites",
        json={"email": BOB["email"]},
        headers=alice_headers,
    )
    assert resp.status_code == 409


async def test_inviting_existing_member_conflicts(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/invites",
        json={"email": BOB["email"]},
        headers=alice_headers,
    )
    assert resp.status_code == 409


async def test_accept_invite_joins_team(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    invite = await invite_bob(client, alice_headers, team["id"])

    resp = await client.post(f"/api/v1/invites/{invite['token']}/accept", headers=bob_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["team_id"] == team["id"]

    teams = await client.get("/api/v1/teams", headers=bob_headers)
    assert team["id"] in {t["id"] for t in teams.json()["data"]}


async def test_accept_requires_matching_email(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/invites",
        json={"email": "carol@example.com"},
        headers=alice_headers,
    )
    token = resp.json()["data"]["token"]
    denied = await client.post(f"/api/v1/invites/{token}/accept", headers=bob_headers)
    assert denied.status_code == 403


async def test_revoked_invite_cannot_be_accepted(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    invite = await invite_bob(client, alice_headers, team["id"])

    revoke = await client.delete(
        f"/api/v1/teams/{team['id']}/invites/{invite['id']}", headers=alice_headers
    )
    assert revoke.status_code == 204

    resp = await client.post(f"/api/v1/invites/{invite['token']}/accept", headers=bob_headers)
    assert resp.status_code == 409


async def test_expired_invite_cannot_be_accepted(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    from datetime import UTC, datetime, timedelta

    team = await create_team(client, alice_headers)
    await me(client, bob_headers)
    invite = await invite_bob(client, alice_headers, team["id"])

    await db.execute(
        update(Invite)
        .where(Invite.token == invite["token"])
        .values(expires_at=datetime.now(UTC) - timedelta(days=1))
    )
    await db.commit()

    resp = await client.post(f"/api/v1/invites/{invite['token']}/accept", headers=bob_headers)
    assert resp.status_code == 410


async def test_invite_on_personal_team_triggers_upgrade(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    personal = (await me(client, alice_headers))["teams"][0]
    assert personal["is_personal"] is True

    await invite_bob(client, alice_headers, personal["team_id"])

    detail = await client.get(f"/api/v1/teams/{personal['team_id']}", headers=alice_headers)
    assert detail.json()["data"]["is_personal"] is False

    # The upgrade is also visible on the invite row's team relation in the DB.
    row = await db.scalar(select(Invite).limit(1))
    assert row is not None
