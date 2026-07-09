"""§2.2 Invites — create, revoke, accept, individual→team upgrade (ADR-015)."""

from typing import Any

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


async def test_invite_from_personal_team_creates_collaborative_team(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    """ADR-032: personal teams stay solo-only. Inviting from one spins up a NEW collaborative
    team and issues the invite there; the personal team is untouched."""
    personal = (await me(client, alice_headers))["teams"][0]
    assert personal["is_personal"] is True

    invite = await invite_bob(client, alice_headers, personal["team_id"])

    # The personal team is untouched — still solo-only.
    detail = await client.get(f"/api/v1/teams/{personal['team_id']}", headers=alice_headers)
    assert detail.json()["data"]["is_personal"] is True

    # The invite belongs to a NEW collaborative team, not the personal one.
    assert invite["team_id"] != personal["team_id"]
    new_team = await client.get(f"/api/v1/teams/{invite['team_id']}", headers=alice_headers)
    assert new_team.status_code == 200
    assert new_team.json()["data"]["is_personal"] is False
    row = await db.scalar(select(Invite).limit(1))
    assert row is not None


async def _notifications(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    resp = await client.get("/api/v1/users/me/notifications", headers=headers)
    assert resp.status_code == 200, resp.text
    data: list[dict[str, Any]] = resp.json()["data"]
    return data


async def test_invite_notifies_existing_invitee(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """FND-01: the invitation rides the existing notification path — an invitee
    who already has an account gets an in-app notification carrying the token."""
    await me(client, bob_headers)  # Bob exists before the invite
    team = await create_team(client, alice_headers)
    invite = await invite_bob(client, alice_headers, team["id"])

    notes = await _notifications(client, bob_headers)
    invite_notes = [n for n in notes if n["type"] == "team.invite"]
    assert len(invite_notes) == 1
    assert invite_notes[0]["attrs"]["team_id"] == team["id"]
    assert invite_notes[0]["attrs"]["token"] == invite["token"]


async def test_invite_to_unregistered_email_creates_no_notification(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    await invite_bob(client, alice_headers, team["id"])  # Bob has no account yet

    await me(client, bob_headers)  # provisions after the fact
    notes = await _notifications(client, bob_headers)
    assert [n for n in notes if n["type"] == "team.invite"] == []


async def test_accept_notifies_inviter(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    await me(client, bob_headers)
    team = await create_team(client, alice_headers)
    invite = await invite_bob(client, alice_headers, team["id"])
    accept = await client.post(f"/api/v1/invites/{invite['token']}/accept", headers=bob_headers)
    assert accept.status_code == 200

    notes = await _notifications(client, alice_headers)
    accepted = [n for n in notes if n["type"] == "invite.accepted"]
    assert len(accepted) == 1
    assert accepted[0]["attrs"]["team_id"] == team["id"]
