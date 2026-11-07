"""Invitations to me (SOLUSDEV-319, multi-team Home): list, accept by id, decline.

docs/api/API-implementation.md §4 "Invitations to me". Only EMAIL invites addressed to the
caller's verified email; anyone else's invite is a 404 on every route.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from conftest import BOB, bearer, create_team, me
from httpx import AsyncClient
from solus_api.models import Invite
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

CAROL = {"sub": "00000000-0000-0000-0000-0000000c0a01", "email": "carol@example.com"}
MINE = "/api/v1/users/me/invites"


async def _invite(
    client: AsyncClient, headers: dict[str, str], team_id: str, email: str, role: str = "member"
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/teams/{team_id}/invites", json={"email": email, "role": role}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def _bracket_invites_bob(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    await me(client, bob_headers)
    team = await create_team(client, alice_headers, "Bracket Labs")
    return team, await _invite(client, alice_headers, team["id"], BOB["email"], "admin")


async def test_lists_the_invites_addressed_to_me_without_token_or_email(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team, invite = await _bracket_invites_bob(client, alice_headers, bob_headers)

    resp = await client.get(MINE, headers=bob_headers)

    assert resp.status_code == 200, resp.text
    [row] = resp.json()["data"]
    assert row["id"] == invite["id"]
    assert row["team"] == {"id": team["id"], "name": "Bracket Labs"}
    assert row["role"] == "admin"
    assert row["invited_by"] == {"name": "alice"}
    assert row["expires_at"] and row["created_at"]
    assert "token" not in row and "email" not in row


async def test_the_list_leaves_out_what_is_not_waiting_for_me(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    await me(client, bob_headers)
    # Alice's plan allows two collaborative teams: one holds every closed or foreign invite.
    team = await create_team(client, alice_headers, "Closed invites")
    await _invite(client, alice_headers, team["id"], CAROL["email"])
    revoked = await _invite(client, alice_headers, team["id"], BOB["email"])
    await client.delete(
        f"/api/v1/teams/{team['id']}/invites/{revoked['id']}", headers=alice_headers
    )
    expired = await _invite(client, alice_headers, team["id"], BOB["email"])
    await db.execute(
        update(Invite)
        .where(Invite.id == expired["id"])
        .values(expires_at=datetime.now(UTC) - timedelta(days=1))
    )
    await db.commit()
    accepted_team = await create_team(client, alice_headers, "Accepted")
    accepted = await _invite(client, alice_headers, accepted_team["id"], BOB["email"])
    await client.post(f"/api/v1/invites/{accepted['token']}/accept", headers=bob_headers)

    resp = await client.get(MINE, headers=bob_headers)

    assert resp.status_code == 200
    assert resp.json()["data"] == []


async def test_every_route_needs_a_verified_email(
    client: AsyncClient, alice_headers: dict[str, str], unverified_headers: dict[str, str]
) -> None:
    await me(client, unverified_headers)
    team = await create_team(client, alice_headers)
    invite = await _invite(client, alice_headers, team["id"], "unverified@example.com")

    for resp in (
        await client.get(MINE, headers=unverified_headers),
        await client.post(f"{MINE}/{invite['id']}/accept", headers=unverified_headers),
        await client.post(f"{MINE}/{invite['id']}/decline", headers=unverified_headers),
    ):
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "email_not_verified"


async def test_every_route_needs_a_signed_in_caller(client: AsyncClient) -> None:
    some_id = "019ebe61-ae9e-776e-b01e-4a8f2af10bf5"
    assert (await client.get(MINE)).status_code == 401
    assert (await client.post(f"{MINE}/{some_id}/accept")).status_code == 401
    assert (await client.post(f"{MINE}/{some_id}/decline")).status_code == 401


async def test_accepting_by_id_joins_the_team_with_the_invited_role(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team, invite = await _bracket_invites_bob(client, alice_headers, bob_headers)

    resp = await client.post(f"{MINE}/{invite['id']}/accept", headers=bob_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"team_id": team["id"], "role": "admin"}
    teams = await client.get("/api/v1/teams", headers=bob_headers)
    assert team["id"] in {t["id"] for t in teams.json()["data"]}
    assert (await client.get(MINE, headers=bob_headers)).json()["data"] == []


async def test_someone_elses_invite_is_not_found_on_accept_and_decline(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    carol_headers = bearer(CAROL["sub"], CAROL["email"])
    _, invite = await _bracket_invites_bob(client, alice_headers, bob_headers)
    await me(client, carol_headers)

    for path in (f"{MINE}/{invite['id']}/accept", f"{MINE}/{invite['id']}/decline"):
        resp = await client.post(path, headers=carol_headers)
        assert resp.status_code == 404, resp.text
    # Bob's invite is untouched by Carol's attempts.
    assert len((await client.get(MINE, headers=bob_headers)).json()["data"]) == 1


async def test_a_github_invite_is_not_reachable_by_id(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    _, invite = await _bracket_invites_bob(client, alice_headers, bob_headers)
    await db.execute(
        update(Invite)
        .where(Invite.id == invite["id"])
        .values(email=None, github_user_id=4242, github_login="bob")
    )
    await db.commit()

    assert (await client.get(MINE, headers=bob_headers)).json()["data"] == []
    resp = await client.post(f"{MINE}/{invite['id']}/accept", headers=bob_headers)
    assert resp.status_code == 404


async def test_an_unknown_or_malformed_id_is_not_found(
    client: AsyncClient, bob_headers: dict[str, str]
) -> None:
    await me(client, bob_headers)
    resp = await client.post(
        f"{MINE}/019ebe61-ae9e-776e-b01e-4a8f2af10bf5/accept", headers=bob_headers
    )
    assert resp.status_code == 404
    assert (await client.post(f"{MINE}/not-a-uuid/decline", headers=bob_headers)).status_code in (
        404,
        422,
    )


async def test_accepting_an_expired_or_revoked_invite_by_id_is_refused(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team, invite = await _bracket_invites_bob(client, alice_headers, bob_headers)
    await db.execute(
        update(Invite)
        .where(Invite.id == invite["id"])
        .values(expires_at=datetime.now(UTC) - timedelta(days=1))
    )
    await db.commit()
    assert (
        await client.post(f"{MINE}/{invite['id']}/accept", headers=bob_headers)
    ).status_code == 410

    second = await _invite(
        client, alice_headers, (await create_team(client, alice_headers, "Two"))["id"], BOB["email"]
    )
    await client.delete(
        f"/api/v1/teams/{second['team_id']}/invites/{second['id']}", headers=alice_headers
    )
    resp = await client.post(f"{MINE}/{second['id']}/accept", headers=bob_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "invite_revoked"


async def test_declining_marks_it_declined_and_tells_the_inviter(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team, invite = await _bracket_invites_bob(client, alice_headers, bob_headers)

    resp = await client.post(f"{MINE}/{invite['id']}/decline", headers=bob_headers)

    assert resp.status_code == 204, resp.text
    status = await db.scalar(select(Invite.status).where(Invite.id == invite["id"]))
    assert status is not None and status.value == "declined"
    assert (await client.get(MINE, headers=bob_headers)).json()["data"] == []
    pending = await client.get(f"/api/v1/teams/{team['id']}/invites", headers=alice_headers)
    assert pending.json()["data"] == []
    notes = (await client.get("/api/v1/users/me/notifications", headers=alice_headers)).json()
    declined = [n for n in notes["data"] if n["type"] == "invite.declined"]
    assert len(declined) == 1
    assert BOB["email"] in declined[0]["title"]


async def test_a_declined_invite_cannot_be_used_or_declined_again(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    _, invite = await _bracket_invites_bob(client, alice_headers, bob_headers)
    await client.post(f"{MINE}/{invite['id']}/decline", headers=bob_headers)

    by_token = await client.post(f"/api/v1/invites/{invite['token']}/accept", headers=bob_headers)
    by_id = await client.post(f"{MINE}/{invite['id']}/accept", headers=bob_headers)
    again = await client.post(f"{MINE}/{invite['id']}/decline", headers=bob_headers)

    for resp in (by_token, by_id, again):
        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "invite_declined"


async def test_an_invite_to_a_team_i_already_joined_is_not_listed(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team, invite = await _bracket_invites_bob(client, alice_headers, bob_headers)
    await client.post(f"{MINE}/{invite['id']}/accept", headers=bob_headers)
    # A stale second pending row for the same team (e.g. created before the join).
    db.add(
        Invite(
            team_id=team["id"],
            email=BOB["email"],
            expires_at=datetime.now(UTC) + timedelta(days=3),
        )
    )
    await db.commit()

    assert (await client.get(MINE, headers=bob_headers)).json()["data"] == []


async def test_matching_uses_the_tokens_verified_email_not_the_stored_one(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """`users.email` is set once at sign-up and never refreshed, so it can name an address the
    caller no longer proves (sign up as someone, then switch the account to your own address).
    Only the verified email in the token may match an invite."""
    from solus_api.models import User

    await me(client, bob_headers)
    await db.execute(update(User).where(User.email == BOB["email"]).values(email=CAROL["email"]))
    await db.commit()
    team = await create_team(client, alice_headers, "Carol's invite")
    invite = await _invite(client, alice_headers, team["id"], CAROL["email"])

    assert (await client.get(MINE, headers=bob_headers)).json()["data"] == []
    assert (await client.post(f"{MINE}/{invite['id']}/accept", headers=bob_headers)).status_code == 404
    by_token = await client.post(f"/api/v1/invites/{invite['token']}/accept", headers=bob_headers)
    assert by_token.status_code == 403


async def test_a_token_without_an_email_cannot_reach_invites(client: AsyncClient) -> None:
    no_email = {"Authorization": "Bearer " + __import__("conftest").make_token("no-email-sub", "")}
    resp = await client.get(MINE, headers=no_email)
    assert resp.status_code in (401, 403)


class _Admin:
    """A configured Supabase admin whose auth user has `confirmed` (None = not confirmed)."""

    configured = True

    def __init__(self, confirmed: str | None) -> None:
        self.confirmed = confirmed

    async def confirmed_email(self, _user_supabase_id: str) -> str | None:
        return self.confirmed


async def test_with_an_admin_the_address_must_be_confirmed_in_supabase(
    client: AsyncClient,
    app: Any,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    """Supabase tokens rarely carry `email_verified`, and an absent claim reads as verified —
    so with a service-role key the auth user's `email_confirmed_at` is the proof."""
    _, invite = await _bracket_invites_bob(client, alice_headers, bob_headers)

    app.state.supabase_admin = _Admin(BOB["email"])
    assert (await client.get(MINE, headers=bob_headers)).status_code == 200

    for refused in (_Admin(None), _Admin(CAROL["email"])):
        app.state.supabase_admin = refused
        for resp in (
            await client.get(MINE, headers=bob_headers),
            await client.post(f"{MINE}/{invite['id']}/accept", headers=bob_headers),
            await client.post(f"{MINE}/{invite['id']}/decline", headers=bob_headers),
        ):
            assert resp.status_code == 403, resp.text
            assert resp.json()["error"]["code"] == "email_not_verified"


async def test_outside_dev_no_admin_means_no_invitations_by_email(
    client: AsyncClient, app: Any, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    await _bracket_invites_bob(client, alice_headers, bob_headers)
    app.state.settings = app.state.settings.model_copy(update={"app_env": "production"})

    resp = await client.get(MINE, headers=bob_headers)

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "email_not_verified"


async def test_a_mixed_case_sign_in_email_matches(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    shouty = bearer(BOB["sub"], "Bob@Example.COM")
    await me(client, shouty)
    team = await create_team(client, alice_headers, "Case")
    invite = await _invite(client, alice_headers, team["id"], BOB["email"])

    assert [r["id"] for r in (await client.get(MINE, headers=shouty)).json()["data"]] == [
        invite["id"]
    ]
    assert (await client.post(f"{MINE}/{invite['id']}/accept", headers=shouty)).status_code == 200


async def test_a_github_invite_cannot_be_declined_by_id(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    _, invite = await _bracket_invites_bob(client, alice_headers, bob_headers)
    await db.execute(
        update(Invite)
        .where(Invite.id == invite["id"])
        .values(email=None, github_user_id=4242, github_login="bob")
    )
    await db.commit()
    resp = await client.post(f"{MINE}/{invite['id']}/decline", headers=bob_headers)
    assert resp.status_code == 404


async def test_invite_notifications_never_carry_the_token(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    _, invite = await _bracket_invites_bob(client, alice_headers, bob_headers)
    await client.post(f"{MINE}/{invite['id']}/decline", headers=bob_headers)

    for headers in (bob_headers, alice_headers):
        notes = (await client.get("/api/v1/users/me/notifications", headers=headers)).json()
        for note in notes["data"]:
            assert "token" not in (note.get("attrs") or {}), note


async def test_racing_answers_settle_on_one_outcome(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """Accept-by-token racing decline-by-id, then two accepts: the invite row is locked on both
    paths, so exactly one answer wins and the invite's status agrees with membership."""
    import asyncio

    from solus_api.models import Membership

    team, invite = await _bracket_invites_bob(client, alice_headers, bob_headers)
    by_token, by_id = await asyncio.gather(
        client.post(f"/api/v1/invites/{invite['token']}/accept", headers=bob_headers),
        client.post(f"{MINE}/{invite['id']}/decline", headers=bob_headers),
    )
    codes = sorted([by_token.status_code, by_id.status_code])
    assert codes in ([200, 409], [204, 409]), (by_token.text, by_id.text)

    status = await db.scalar(select(Invite.status).where(Invite.id == invite["id"]))
    joined = await db.scalar(
        select(Membership.id).where(
            Membership.team_id == team["id"], Membership.deleted_at.is_(None),
            Membership.role != "owner",
        )
    )
    assert status is not None
    assert (status.value == "accepted") == (joined is not None)
