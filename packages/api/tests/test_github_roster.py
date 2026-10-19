"""SOLUSDEV-216 T7 - GET /api/v1/teams/{id}/github/members (docs/api/github-orgs.md)."""

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
from fixtures.team_installation_seed import (
    SeededTeam,
    seed_installation,
    seed_team,
    seed_user,
)
from httpx import AsyncClient
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.github_app import (
    DEFAULT_MAX_PAGES,
    GitHubAppClient,
    clear_installation_tokens,
    configure_github_app,
)
from solus_api.core.config import Settings
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
    InstallationStatus,
    Invite,
    Membership,
    Role,
    SourceType,
    TeamKind,
    User,
    utcnow,
)
from solus_api.routers.team_github_members import MEMBERS_PER_MINUTE_PER_USER
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def headers_for(user: User) -> dict[str, str]:
    headers: dict[str, str] = bearer(user.supabase_user_id, user.email)
    return headers


def gh_member(gid: int, login: str | None = None) -> dict[str, Any]:
    return {
        "id": gid,
        "login": login or f"user{gid}",
        "avatar_url": f"https://avatars.githubusercontent.com/u/{gid}",
        "type": "User",
        "site_admin": False,
    }


@pytest.fixture
async def gh(settings: Settings, app: FastAPI, engine: Any) -> AsyncIterator[FakeGitHubApp]:
    private, _ = generate_key_pair()
    configure_github_app(
        app_settings(settings, private), async_sessionmaker(engine, expire_on_commit=False)
    )
    clear_installation_tokens()
    with respx.mock(assert_all_called=False) as router:
        yield FakeGitHubApp(router)
    clear_installation_tokens()
    configure_github_app(settings)


@pytest.fixture
async def org(db: AsyncSession) -> SeededTeam:
    seeded = await seed_team(db, name="Acme")
    await seed_installation(db, seeded, external_id=5150, login="acme")
    await db.commit()
    return seeded


def url(team: SeededTeam, query: str = "") -> str:
    return f"/api/v1/teams/{team.team.id}/github/members{query}"


async def link_github(db: AsyncSession, user: User, gid: int, login: str = "x") -> None:
    db.add(
        AccountConnection(
            user_id=user.id,
            provider=SourceType.GITHUB,
            status=ConnectionStatus.CONNECTED,
            account_external_id=str(gid),
            account_login=login,
        )
    )
    await db.commit()


# ---------------------------------------------------------------- authorization


async def test_member_role_is_forbidden(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    resp = await client.get(url(org), headers=headers_for(org.users[Role.MEMBER]))
    assert resp.status_code == 403
    assert gh.list_requests == []


async def test_non_member_gets_404(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    stranger = await seed_user(db, "stranger")
    await db.commit()
    resp = await client.get(url(org), headers=headers_for(stranger))
    assert resp.status_code == 404
    assert gh.list_requests == []


async def test_admin_of_another_team_cannot_read_this_roster(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    other = await seed_team(db, name="Other")
    await seed_installation(db, other, external_id=6160, login="other")
    await db.commit()
    gh.member_pages = [[gh_member(1)]]

    resp = await client.get(url(org), headers=headers_for(other.users[Role.OWNER]))

    assert resp.status_code == 404
    assert gh.list_requests == []


async def test_admin_role_is_enough(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    admin = await seed_user(db, "adm")
    db.add(Membership(team_id=org.team.id, user_id=admin.id, role=Role.ADMIN))
    await db.commit()
    gh.member_pages = [[gh_member(1)]]
    resp = await client.get(url(org), headers=headers_for(admin))
    assert resp.status_code == 200


# ---------------------------------------------------------------- gates


async def test_personal_team_is_unsupported(
    client: AsyncClient, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    personal = await seed_team(db, kind=TeamKind.PERSONAL)
    await db.commit()
    resp = await client.get(url(personal), headers=headers_for(personal.users[Role.OWNER]))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "personal_team_unsupported"


async def test_team_without_installation_is_refused(
    client: AsyncClient, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    bare = await seed_team(db)
    await db.commit()
    resp = await client.get(url(bare), headers=headers_for(bare.users[Role.OWNER]))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "installation_missing"


async def test_suspended_installation_is_refused(
    client: AsyncClient, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    seeded = await seed_team(db)
    await seed_installation(db, seeded, status=InstallationStatus.SUSPENDED)
    await db.commit()
    resp = await client.get(url(seeded), headers=headers_for(seeded.users[Role.OWNER]))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "installation_suspended"


async def test_user_installation_is_not_an_organization(
    client: AsyncClient, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    seeded = await seed_team(db)
    inst = await seed_installation(db, seeded)
    inst.account_type = "User"
    await db.commit()
    resp = await client.get(url(seeded), headers=headers_for(seeded.users[Role.OWNER]))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "not_an_organization"
    assert gh.list_requests == []


# ---------------------------------------------------------------- statuses


async def test_statuses_member_invited_not_on_solus(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    gh.member_pages = [[gh_member(101, "alice-gh"), gh_member(102, "bob-gh"), gh_member(103)]]
    await link_github(db, org.users[Role.MEMBER], 101)
    db.add(
        Invite(
            team_id=org.team.id,
            github_user_id=102,
            github_login="bob-gh",
            role=Role.MEMBER,
            invited_by=org.users[Role.OWNER].id,
            expires_at=utcnow() + timedelta(days=7),
        )
    )
    await db.commit()

    resp = await client.get(url(org), headers=headers_for(org.users[Role.OWNER]))

    assert resp.status_code == 200, resp.text
    items = {i["github_id"]: i for i in resp.json()["data"]}
    assert {k: v["solus_status"] for k, v in items.items()} == {
        101: "member",
        102: "invited",
        103: "not_on_solus",
    }
    assert items[101] == {
        "github_id": 101,
        "github_login": "alice-gh",
        "avatar_url": "https://avatars.githubusercontent.com/u/101",
        "solus_status": "member",
    }
    assert resp.json()["meta"]["has_next"] is False


async def test_same_login_with_a_different_id_is_not_on_solus(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    # The member's linked account is "octocat" with id 555; the org roster has a DIFFERENT
    # account that also calls itself "octocat". Matching is by numeric id only.
    await link_github(db, org.users[Role.MEMBER], 555, login="octocat")
    gh.member_pages = [[gh_member(777, "octocat")]]
    resp = await client.get(url(org), headers=headers_for(org.users[Role.OWNER]))
    assert [i["solus_status"] for i in resp.json()["data"]] == ["not_on_solus"]


async def test_email_never_matches(client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp) -> None:
    gh.member_pages = [[{**gh_member(88), "email": org.users[Role.MEMBER].email}]]
    resp = await client.get(url(org), headers=headers_for(org.users[Role.OWNER]))
    assert [i["solus_status"] for i in resp.json()["data"]] == ["not_on_solus"]


async def test_jwt_user_metadata_github_claims_are_ignored(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    owner = org.users[Role.OWNER]
    forged = jwt.encode(
        {
            "sub": owner.supabase_user_id,
            "email": owner.email,
            "aud": TEST_AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "user_metadata": {"provider_id": "103", "user_name": "user103", "sub": "103"},
            "app_metadata": {"provider": "github", "provider_id": "103"},
            "identities": [{"provider": "github", "id": "103"}],
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    gh.member_pages = [[gh_member(103)]]

    resp = await client.get(url(org), headers={"Authorization": f"Bearer {forged}"})

    assert resp.status_code == 200
    assert [i["solus_status"] for i in resp.json()["data"]] == ["not_on_solus"]


async def test_removed_member_and_revoked_connection_do_not_count(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    ghost = await seed_user(db, "ghost")
    row = Membership(team_id=org.team.id, user_id=ghost.id, role=Role.MEMBER, deleted_at=utcnow())
    db.add(row)
    await link_github(db, ghost, 201)
    revoked = org.users[Role.MEMBER]
    db.add(
        AccountConnection(
            user_id=revoked.id,
            provider=SourceType.GITHUB,
            status=ConnectionStatus.REVOKED,
            account_external_id="202",
        )
    )
    await db.commit()
    gh.member_pages = [[gh_member(201), gh_member(202)]]

    resp = await client.get(url(org), headers=headers_for(org.users[Role.OWNER]))

    assert [i["solus_status"] for i in resp.json()["data"]] == ["not_on_solus"] * 2


async def test_a_member_of_another_team_is_not_a_member_here(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    other = await seed_team(db, name="Other")
    await link_github(db, other.users[Role.MEMBER], 301)
    gh.member_pages = [[gh_member(301)]]
    resp = await client.get(url(org), headers=headers_for(org.users[Role.OWNER]))
    assert [i["solus_status"] for i in resp.json()["data"]] == ["not_on_solus"]


async def test_invites_of_another_team_or_non_pending_do_not_show(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    other = await seed_team(db, name="Other")
    expiry = utcnow() + timedelta(days=7)
    from solus_api.models import InviteStatus

    db.add(Invite(team_id=other.team.id, github_user_id=401, github_login="a", expires_at=expiry))
    db.add(
        Invite(
            team_id=org.team.id,
            github_user_id=402,
            github_login="b",
            status=InviteStatus.REVOKED,
            expires_at=expiry,
        )
    )
    await db.commit()
    gh.member_pages = [[gh_member(401), gh_member(402)]]
    resp = await client.get(url(org), headers=headers_for(org.users[Role.OWNER]))
    assert [i["solus_status"] for i in resp.json()["data"]] == ["not_on_solus"] * 2


# ---------------------------------------------------------------- pagination, bounds, cache


async def test_cursor_pagination_covers_every_member_once(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    gh.member_pages = [[gh_member(i) for i in (50, 10, 40)], [gh_member(i) for i in (30, 20)]]
    headers = headers_for(org.users[Role.OWNER])
    seen: list[int] = []
    cursor: str | None = None
    for _ in range(5):
        query = "?limit=2" + (f"&cursor={cursor}" if cursor else "")
        resp = await client.get(url(org, query), headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["data"]) <= 2
        seen += [i["github_id"] for i in body["data"]]
        cursor = body["meta"]["next_cursor"]
        if not body["meta"]["has_next"]:
            break
    assert sorted(seen) == [10, 20, 30, 40, 50]
    assert len(seen) == len(set(seen))


async def test_bad_cursor_and_limit_are_rejected(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    headers = headers_for(org.users[Role.OWNER])
    assert (await client.get(url(org, "?cursor=!!!"), headers=headers)).status_code == 400
    assert (await client.get(url(org, "?limit=0"), headers=headers)).status_code == 422
    assert (await client.get(url(org, "?limit=101"), headers=headers)).status_code == 422


async def test_the_github_walk_is_bounded(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    gh.member_pages = [[gh_member(i + 1)] for i in range(DEFAULT_MAX_PAGES + 15)]
    resp = await client.get(url(org), headers=headers_for(org.users[Role.OWNER]))
    assert resp.status_code == 200
    assert len(gh.list_requests) == DEFAULT_MAX_PAGES


async def test_the_roster_is_cached_per_installation(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    gh.member_pages = [[gh_member(1), gh_member(2)]]
    headers = headers_for(org.users[Role.OWNER])
    first = await client.get(url(org), headers=headers)
    second = await client.get(url(org, "?limit=1"), headers=headers)
    assert first.status_code == second.status_code == 200
    assert len(gh.list_requests) == 1
    assert gh.mint_calls == [5150]


async def test_cached_statuses_are_recomputed_each_request(
    client: AsyncClient, org: SeededTeam, db: AsyncSession, gh: FakeGitHubApp
) -> None:
    gh.member_pages = [[gh_member(61)]]
    headers = headers_for(org.users[Role.OWNER])
    before = await client.get(url(org), headers=headers)
    await link_github(db, org.users[Role.MEMBER], 61)
    after = await client.get(url(org), headers=headers)
    assert before.json()["data"][0]["solus_status"] == "not_on_solus"
    assert after.json()["data"][0]["solus_status"] == "member"
    assert len(gh.list_requests) == 1


async def test_roster_never_leaks_the_installation_token(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp
) -> None:
    gh.member_pages = [[gh_member(1)]]
    resp = await client.get(url(org), headers=headers_for(org.users[Role.OWNER]))
    assert gh.minted_tokens
    assert all(t not in resp.text for t in gh.minted_tokens)


def fail_listing(monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    async def boom(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise ConnectorError(code, "scripted")

    monkeypatch.setattr(GitHubAppClient, "list_org_members", boom)


async def test_github_outage_is_a_gateway_error(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    fail_listing(monkeypatch, "github_error")
    resp = await client.get(url(org), headers=headers_for(org.users[Role.OWNER]))
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "github_error"


async def test_github_rate_limit_maps_to_429(
    client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    fail_listing(monkeypatch, "rate_limited")
    resp = await client.get(url(org), headers=headers_for(org.users[Role.OWNER]))
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"


async def test_per_user_rate_limit(client: AsyncClient, org: SeededTeam, gh: FakeGitHubApp) -> None:
    gh.member_pages = [[gh_member(1)]]
    headers = headers_for(org.users[Role.OWNER])
    codes = [
        (await client.get(url(org), headers=headers)).status_code
        for _ in range(MEMBERS_PER_MINUTE_PER_USER + 1)
    ]
    assert codes[:-1] == [200] * MEMBERS_PER_MINUTE_PER_USER
    assert codes[-1] == 429
