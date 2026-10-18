"""SOLUSDEV-216 T7 - invites by GitHub id and accept-time identity proof (ADR-039)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
import respx
from conftest import TEST_AUDIENCE, TEST_JWT_SECRET, bearer
from fastapi import FastAPI
from fixtures.github_app_fake import FakeGitHubApp, app_settings, generate_key_pair
from fixtures.team_installation_seed import SeededTeam, seed_installation, seed_team, seed_user
from httpx import AsyncClient
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.github_app import (
    GitHubAppClient,
    clear_installation_tokens,
    configure_github_app,
)
from solus_api.core.config import Settings
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
    DataEvent,
    InstallationStatus,
    Invite,
    InviteStatus,
    Membership,
    Role,
    SourceType,
    Subscription,
    Team,
    TeamKind,
    User,
    utcnow,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

ROSTER = [
    {"id": 5001, "login": "octocat", "avatar_url": "https://a/5001"},
    {"id": 5002, "login": "hubot", "avatar_url": "https://a/5002"},
]


def headers_for(user: User) -> dict[str, str]:
    return bearer(user.supabase_user_id, user.email)


def invites_url(team: SeededTeam) -> str:
    return f"/api/v1/teams/{team.team.id}/invites"


def gh_body(gid: int = 5001, login: str = "octocat", **extra: Any) -> dict[str, Any]:
    return {"github_user_id": gid, "github_login": login, **extra}


@pytest.fixture
async def gh(settings: Settings, app: FastAPI, engine: Any) -> AsyncIterator[FakeGitHubApp]:
    private, _ = generate_key_pair()
    configure_github_app(
        app_settings(settings, private), async_sessionmaker(engine, expire_on_commit=False)
    )
    clear_installation_tokens()
    with respx.mock(assert_all_called=False) as router:
        fake = FakeGitHubApp(router)
        fake.member_pages = [list(ROSTER)]
        yield fake
    clear_installation_tokens()
    configure_github_app(settings)


@pytest.fixture
async def org(db: AsyncSession) -> SeededTeam:
    seeded = await seed_team(db, name="Acme")
    await seed_installation(db, seeded, external_id=5150, login="acme")
    seeded.users[Role.OWNER].data_collection_consent = True
    await db.commit()
    return seeded


async def link_github(db: AsyncSession, user: User, gid: int | str, **kw: Any) -> None:
    db.add(
        AccountConnection(
            user_id=user.id,
            provider=SourceType.GITHUB,
            status=kw.get("status", ConnectionStatus.CONNECTED),
            account_external_id=str(gid),
            account_login="x",
        )
    )
    await db.commit()


async def invite(client: AsyncClient, org: SeededTeam, body: dict[str, Any] | None = None) -> Any:
    return await client.post(
        invites_url(org),
        json=gh_body() if body is None else body,
        headers=headers_for(org.users[Role.OWNER]),
    )


# ---------------------------------------------------------------- create


async def test_github_invite_is_created(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    resp = await invite(client, org, gh_body(role="viewer"))

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["github_user_id"] == 5001
    assert data["github_login"] == "octocat"
    assert data["email"] is None
    assert data["role"] == "viewer"
    assert data["status"] == "pending"
    assert data["token"]
    row = await db.scalar(select(Invite).where(Invite.github_user_id == 5001))
    assert row is not None
    assert row.email is None
    assert row.team_id == org.team.id
    assert row.invited_by == org.users[Role.OWNER].id


async def test_listing_shows_github_invites_without_token(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    await invite(client, org)
    resp = await client.get(invites_url(org), headers=headers_for(org.users[Role.OWNER]))
    [item] = resp.json()["data"]
    assert item["github_user_id"] == 5001 and item["email"] is None
    assert "token" not in item


@pytest.mark.parametrize(
    "body",
    [
        {"email": "a@example.com", "github_user_id": 5001, "github_login": "octocat"},
        {"email": "a@example.com", "github_user_id": 5001},
        {},
        {"role": "member"},
        {"github_user_id": 5001},
        {"github_login": "octocat"},
        {"github_user_id": 0, "github_login": "octocat"},
        {"github_user_id": -4, "github_login": "octocat"},
        {"github_user_id": True, "github_login": "octocat"},
        {"github_user_id": "5001", "github_login": "octocat"},
        {"github_user_id": 5001.5, "github_login": "octocat"},
        {"github_user_id": 5001, "github_login": ""},
        {"github_user_id": 5001, "github_login": "-lead"},
        {"github_user_id": 5001, "github_login": "trail-"},
        {"github_user_id": 5001, "github_login": "dou--ble"},
        {"github_user_id": 5001, "github_login": "has space"},
        {"github_user_id": 5001, "github_login": "a" * 40},
        {"github_user_id": 5001, "github_login": "oc<script>"},
        {"github_user_id": 5001, "github_login": "octocat", "role": "owner"},
        {"github_user_id": 5001, "github_login": "octocat", "extra": 1},
    ],
)
async def test_invalid_targets_are_422(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp, body: dict[str, Any]
) -> None:
    resp = await invite(client, org, body)
    assert resp.status_code == 422, resp.text
    assert gh.list_requests == []


async def test_a_39_char_login_is_accepted(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    login = "a" * 39
    gh.member_pages = [[{"id": 9, "login": login, "avatar_url": "x"}]]
    assert (await invite(client, org, gh_body(9, login))).status_code == 201


async def test_login_is_display_only(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    resp = await invite(client, org, gh_body(5001, "someone-else"))
    assert resp.status_code == 201  # membership is decided by the id alone
    assert resp.json()["data"]["github_user_id"] == 5001


async def test_no_installation_is_not_an_org_member(
    client: AsyncClient, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    bare = await seed_team(db)
    await db.commit()
    resp = await invite(client, bare)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "not_an_org_member"


async def test_user_installation_is_not_an_org_member(
    client: AsyncClient, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    inst.account_type = "User"
    await db.commit()
    resp = await invite(client, seeded)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "not_an_org_member"
    assert gh.list_requests == []


async def test_suspended_installation_is_refused(
    client: AsyncClient, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    seeded = await seed_team(db)
    await seed_installation(db, seeded, status=InstallationStatus.SUSPENDED)
    await db.commit()
    resp = await invite(client, seeded)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "installation_suspended"


async def test_personal_team_never_spawns_a_team_for_a_github_invite(
    client: AsyncClient, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    personal = await seed_team(db, kind=TeamKind.PERSONAL)
    await db.commit()
    before = await db.scalar(select(func.count()).select_from(Team))

    resp = await invite(client, personal)

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "not_an_org_member"
    assert await db.scalar(select(func.count()).select_from(Team)) == before
    assert await db.scalar(select(func.count()).select_from(Invite)) == 0


async def test_id_outside_the_org_is_refused(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    resp = await invite(client, org, gh_body(9999, "stranger"))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "not_an_org_member"
    assert await db.scalar(select(func.count()).select_from(Invite)) == 0
    assert len(gh.list_requests) == 1  # cold cache: one fresh listing, no pointless retry


async def test_a_miss_on_a_warm_cache_refreshes_once(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    assert (await invite(client, org)).status_code == 201  # warms the roster cache
    assert len(gh.list_requests) == 1
    resp = await invite(client, org, gh_body(9999, "stranger"))
    assert resp.status_code == 400
    assert len(gh.list_requests) == 2  # refreshed exactly once, then refused


async def test_a_new_org_member_is_found_by_the_refresh(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    assert (await invite(client, org)).status_code == 201
    gh.member_pages = [[*ROSTER, {"id": 5003, "login": "newbie", "avatar_url": "x"}]]
    resp = await invite(client, org, gh_body(5003, "newbie"))
    assert resp.status_code == 201, resp.text
    assert len(gh.list_requests) == 2


async def test_github_outage_blocks_the_invite(
    client: AsyncClient,
    org: SeededTeam,
    db: AsyncSession,
    gh: FakeGitHubApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise ConnectorError("github_error", "scripted")

    monkeypatch.setattr(GitHubAppClient, "list_org_members", boom)
    resp = await invite(client, org)
    assert resp.status_code == 502
    assert await db.scalar(select(func.count()).select_from(Invite)) == 0


async def test_duplicate_pending_github_invite_conflicts(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    assert (await invite(client, org)).status_code == 201
    resp = await invite(client, org, gh_body(5001, "renamed"))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "invite_pending"


async def test_revoked_invite_can_be_reissued(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    first = (await invite(client, org)).json()["data"]
    revoke = await client.delete(
        f"{invites_url(org)}/{first['id']}", headers=headers_for(org.users[Role.OWNER])
    )
    assert revoke.status_code == 204
    assert (await invite(client, org)).status_code == 201


async def test_existing_member_by_verified_id_conflicts(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    await link_github(db, org.users[Role.MEMBER], 5001)
    resp = await invite(client, org)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "already_member"


async def test_removed_member_can_be_invited_again(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    await link_github(db, org.users[Role.MEMBER], 5001)
    membership = await db.scalar(
        select(Membership).where(
            Membership.team_id == org.team.id, Membership.user_id == org.users[Role.MEMBER].id
        )
    )
    assert membership is not None
    membership.deleted_at = utcnow()
    await db.commit()
    assert (await invite(client, org)).status_code == 201


async def test_member_role_cannot_invite(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    resp = await client.post(
        invites_url(org), json=gh_body(), headers=headers_for(org.users[Role.MEMBER])
    )
    assert resp.status_code == 403


async def test_other_teams_admin_gets_404(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    other = await seed_team(db, name="Other")
    await db.commit()
    resp = await client.post(
        invites_url(org), json=gh_body(), headers=headers_for(other.users[Role.OWNER])
    )
    assert resp.status_code == 404


async def test_unverified_email_cannot_invite(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    owner = org.users[Role.OWNER]
    resp = await client.post(
        invites_url(org),
        json=gh_body(),
        headers=bearer(owner.supabase_user_id, owner.email, email_verified=False),
    )
    assert resp.status_code == 403


async def test_invite_suggested_event_is_emitted(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    assert (await invite(client, org)).status_code == 201
    events = (
        await db.scalars(
            select(DataEvent).where(DataEvent.event_type == "github_org.invite_suggested")
        )
    ).all()
    assert len(events) == 1
    assert events[0].team_id == org.team.id
    assert events[0].user_id == org.users[Role.OWNER].id


# ---------------------------------------------------------------- email regression


async def test_email_invite_is_unchanged(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    resp = await client.post(
        invites_url(org),
        json={"email": "New.Person@Example.com", "role": "admin"},
        headers=headers_for(org.users[Role.OWNER]),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["email"] == "new.person@example.com"
    assert data["github_user_id"] is None and data["github_login"] is None
    assert gh.list_requests == []


async def test_email_invite_for_a_removed_member_is_allowed(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    member = org.users[Role.MEMBER]
    membership = await db.scalar(
        select(Membership).where(Membership.team_id == org.team.id, Membership.user_id == member.id)
    )
    assert membership is not None
    membership.deleted_at = utcnow()
    await db.commit()
    resp = await client.post(
        invites_url(org), json={"email": member.email}, headers=headers_for(org.users[Role.OWNER])
    )
    assert resp.status_code == 201, resp.text


async def test_email_invite_for_a_live_member_still_conflicts(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    resp = await client.post(
        invites_url(org),
        json={"email": org.users[Role.MEMBER].email},
        headers=headers_for(org.users[Role.OWNER]),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "already_member"


# ---------------------------------------------------------------- accept


class FakeAdmin:
    def __init__(self, value: int | None) -> None:
        self.value = value
        self.calls = 0

    async def github_identity(self, _user_supabase_id: str) -> int | None:
        self.calls += 1
        return self.value


async def issue(client: AsyncClient, org: SeededTeam) -> str:
    resp = await invite(client, org)
    assert resp.status_code == 201, resp.text
    token: str = resp.json()["data"]["token"]
    return token


async def accept(client: AsyncClient, token: str, user: User) -> Any:
    return await client.post(f"/api/v1/invites/{token}/accept", headers=headers_for(user))


async def live_member(db: AsyncSession, org: SeededTeam, user: User) -> bool:
    row = await db.scalar(
        select(Membership).where(
            Membership.team_id == org.team.id,
            Membership.user_id == user.id,
            Membership.deleted_at.is_(None),
        )
    )
    return row is not None


async def test_matching_connection_joins(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    token = await issue(client, org)
    joiner = await seed_user(db, "joiner")
    await db.commit()
    await link_github(db, joiner, 5001)

    resp = await accept(client, token, joiner)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["role"] == "member"
    assert await live_member(db, org, joiner)
    invite_row = await db.scalar(select(Invite))
    assert invite_row is not None and invite_row.status is InviteStatus.ACCEPTED


async def test_mismatched_connection_is_refused(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    token = await issue(client, org)
    joiner = await seed_user(db, "joiner")
    await db.commit()
    await link_github(db, joiner, 6666)

    resp = await accept(client, token, joiner)

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "github_identity_mismatch"
    assert not await live_member(db, org, joiner)


async def test_no_identity_is_refused(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    token = await issue(client, org)
    joiner = await seed_user(db, "joiner")
    await db.commit()
    resp = await accept(client, token, joiner)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "github_identity_mismatch"


async def test_revoked_connection_is_refused(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    token = await issue(client, org)
    joiner = await seed_user(db, "joiner")
    await db.commit()
    await link_github(db, joiner, 5001, status=ConnectionStatus.REVOKED)
    resp = await accept(client, token, joiner)
    assert resp.status_code == 403


async def test_user_metadata_spoofing_does_not_pass(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    token = await issue(client, org)
    joiner = await seed_user(db, "joiner")
    await db.commit()
    forged = jwt.encode(
        {
            "sub": joiner.supabase_user_id,
            "email": joiner.email,
            "aud": TEST_AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "user_metadata": {"provider_id": "5001", "user_name": "octocat", "sub": "5001"},
            "app_metadata": {"provider": "github", "provider_id": "5001"},
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    resp = await client.post(
        f"/api/v1/invites/{token}/accept", headers={"Authorization": f"Bearer {forged}"}
    )
    assert resp.status_code == 403
    assert not await live_member(db, org, joiner)


async def test_supabase_admin_identity_path(
    client: AsyncClient, app: FastAPI, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    token = await issue(client, org)
    joiner = await seed_user(db, "joiner")
    await db.commit()
    app.state.supabase_admin = FakeAdmin(5001)

    resp = await accept(client, token, joiner)

    assert resp.status_code == 200, resp.text
    assert await live_member(db, org, joiner)


async def test_supabase_admin_identity_mismatch_or_missing_is_refused(
    client: AsyncClient, app: FastAPI, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    token = await issue(client, org)
    joiner = await seed_user(db, "joiner")
    await db.commit()
    for value in (7777, None):
        app.state.supabase_admin = FakeAdmin(value)
        resp = await accept(client, token, joiner)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "github_identity_mismatch"


async def test_accept_ignores_the_email_for_github_invites(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    token = await issue(client, org)
    joiner = await seed_user(db, "joiner")
    await db.commit()
    await link_github(db, joiner, 5001)
    assert (await accept(client, token, joiner)).status_code == 200


async def test_invitee_plan_limit_still_applies(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    token = await issue(client, org)
    joiner = await seed_user(db, "joiner")
    await db.commit()
    await link_github(db, joiner, 5001)
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == joiner.id))
    assert sub is not None
    sub.limits = {"max_teams": 0}
    await db.commit()

    resp = await accept(client, token, joiner)

    assert resp.status_code == 409
    assert resp.json()["error"]["details"][0]["limit"] == "max_teams"
    assert not await live_member(db, org, joiner)


async def test_existing_accept_errors_still_apply(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    token = await issue(client, org)
    joiner = await seed_user(db, "joiner")
    await db.commit()
    await link_github(db, joiner, 5001)
    assert (await accept(client, token, joiner)).status_code == 200
    again = await accept(client, token, joiner)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invite_already_accepted"
    assert (await accept(client, "nope", joiner)).status_code == 404

    row = await db.scalar(select(Invite))
    assert row is not None
    row.status = InviteStatus.PENDING
    row.expires_at = utcnow() - timedelta(days=1)
    await db.commit()
    expired = await accept(client, token, joiner)
    assert expired.status_code == 410


async def test_email_invite_accept_is_unchanged(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    joiner = await seed_user(db, "joiner")
    await db.commit()
    await db.commit()
    created = await client.post(
        invites_url(org),
        json={"email": joiner.email},
        headers=headers_for(org.users[Role.OWNER]),
    )
    token = created.json()["data"]["token"]
    other = await seed_user(db, "other")
    await db.commit()
    wrong = await accept(client, token, other)
    assert wrong.status_code == 403 and wrong.json()["error"]["code"] == "forbidden"
    assert (await accept(client, token, joiner)).status_code == 200


async def test_accept_notifies_the_inviter_with_the_github_login(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    from solus_api.models import Notification

    token = await issue(client, org)
    joiner = await seed_user(db, "joiner")
    await db.commit()
    await link_github(db, joiner, 5001)
    assert (await accept(client, token, joiner)).status_code == 200
    note = await db.scalar(select(Notification).where(Notification.type == "invite.accepted"))
    assert note is not None
    assert "None" not in note.title
