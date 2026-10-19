"""GET /api/v1/teams/{team_id}/github/repos (SOLUSDEV-216 S216-T6, docs/api/github-orgs.md s2).

Lists the repos the team's GitHub App installation can see, from the per-installation
integration cache, in the same SelectableItem shape as the OAuth picker.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from conftest import bearer
from fastapi import FastAPI
from fixtures.github_app_fake import FakeGitHubApp, app_settings, generate_key_pair
from fixtures.github_sample import repo_record
from fixtures.team_installation_seed import SeededTeam, seed_installation, seed_team, seed_user
from httpx import AsyncClient
from solus_api.connectors.github import GitHubConnector
from solus_api.connectors.github_app import clear_installation_tokens
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.core.config import Settings
from solus_api.models import InstallationStatus, Membership, Role, TeamKind, User
from solus_api.routers.team_github_repos import REPOS_PER_MINUTE
from sqlalchemy.ext.asyncio import AsyncSession

EXT_ID = 990022
NAMES = ["acme/alpha", "acme/Beta-bot", "acme/gamma", "acme/delta", "acme/epsilon"]


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return app_settings(settings, generate_key_pair()[0])


@pytest.fixture(autouse=True)
def _real_github_connector(app: FastAPI) -> None:
    registry = ConnectorRegistry()
    registry.register("github", GitHubConnector)
    app.state.connector_registry = registry


@pytest.fixture(autouse=True)
def _fresh_token_cache() -> Iterator[None]:
    clear_installation_tokens()
    yield
    clear_installation_tokens()


@pytest.fixture
def fake() -> Iterator[FakeGitHubApp]:
    with respx.mock(assert_all_called=False) as router:
        gh = FakeGitHubApp(router)
        gh.repo_pages = [[repo_record(n, "main", private=i % 2 == 0) for i, n in enumerate(NAMES)]]
        yield gh


async def world(
    db: AsyncSession,
    *,
    installation: bool = True,
    status: InstallationStatus = InstallationStatus.ACTIVE,
    kind: TeamKind = TeamKind.COLLABORATIVE,
    external_id: int = EXT_ID,
) -> tuple[SeededTeam, User]:
    seeded = await seed_team(db, kind=kind)
    if installation:
        await seed_installation(db, seeded, external_id=external_id, status=status)
    viewer = await seed_user(db, "viewer")
    db.add(Membership(team_id=seeded.team.id, user_id=viewer.id, role=Role.VIEWER))
    await db.commit()
    return seeded, viewer


def headers_for(user: User) -> dict[str, str]:
    headers: dict[str, str] = bearer(user.supabase_user_id, user.email)
    return headers


async def get_repos(
    client: AsyncClient, seeded: SeededTeam, user: User, **params: Any
) -> httpx.Response:
    return await client.get(
        f"/api/v1/teams/{seeded.team.id}/github/repos", params=params, headers=headers_for(user)
    )


async def test_member_lists_repos_in_the_picker_shape(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)

    resp = await get_repos(client, seeded, seeded.users[Role.MEMBER])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"][0] == {
        "id": "acme/alpha",
        "name": "acme/alpha",
        "subtitle": "private",
        "config": {"repo": "acme/alpha", "branch": "main"},
    }
    assert body["data"][1]["subtitle"] == "public"
    assert [i["id"] for i in body["data"]] == NAMES
    assert body["meta"]["total"] == 5
    assert body["meta"]["next_cursor"] is None
    assert fake.minted_tokens[-1] not in resp.text


async def test_viewer_cannot_list(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, viewer = await world(db)
    resp = await get_repos(client, seeded, viewer)
    assert resp.status_code == 403
    assert not fake.mint_calls and not fake.list_requests  # refused before any GitHub call


async def test_cursor_and_limit_page_through_the_list(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    member = seeded.users[Role.MEMBER]
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        resp = await get_repos(client, seeded, member, **params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        seen += [i["id"] for i in body["data"]]
        assert body["meta"]["total"] == 5
        pages += 1
        cursor = body["meta"]["next_cursor"]
        if cursor is None:
            break
    assert seen == NAMES
    assert pages == 3


async def test_q_filters_case_insensitively_by_substring(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    resp = await get_repos(client, seeded, seeded.users[Role.MEMBER], q="BETA")
    assert [i["id"] for i in resp.json()["data"]] == ["acme/Beta-bot"]
    assert resp.json()["meta"]["total"] == 1
    nothing = await get_repos(client, seeded, seeded.users[Role.MEMBER], q="zzz")
    assert nothing.json()["data"] == []
    assert nothing.json()["meta"]["total"] == 0


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"limit": "x"}, {"q": "a" * 101}],
)
async def test_bad_query_params_are_422(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp, params: dict[str, Any]
) -> None:
    seeded, _ = await world(db)
    resp = await get_repos(client, seeded, seeded.users[Role.MEMBER], **params)
    assert resp.status_code == 422


@pytest.mark.parametrize("cursor", ["abc", "-1", "1.5", "9" * 40])
async def test_invalid_cursor_is_400(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp, cursor: str
) -> None:
    seeded, _ = await world(db)
    resp = await get_repos(client, seeded, seeded.users[Role.MEMBER], cursor=cursor)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_cursor"


async def test_second_call_is_served_from_cache(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    first = await get_repos(client, seeded, seeded.users[Role.MEMBER])
    walks = len(fake.list_requests)
    second = await get_repos(client, seeded, seeded.users[Role.MEMBER], q="alpha")
    third = await get_repos(client, seeded, seeded.users[Role.OWNER], limit=1)

    assert first.status_code == second.status_code == third.status_code == 200
    assert walks >= 1
    assert len(fake.list_requests) == walks
    assert len(fake.mint_calls) == 1


async def test_non_member_gets_404_and_nothing_is_listed(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    outsider = await seed_user(db, "outsider")
    await db.commit()
    resp = await get_repos(client, seeded, outsider)
    assert resp.status_code == 404
    assert fake.list_requests == [] and fake.mint_calls == []


async def test_other_teams_member_never_sees_this_teams_repos(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    team_a, _ = await world(db, installation=False)
    team_b, _ = await world(db, external_id=EXT_ID + 1)
    warm = await get_repos(client, team_b, team_b.users[Role.MEMBER])
    assert warm.status_code == 200

    resp = await get_repos(client, team_a, team_a.users[Role.MEMBER])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "installation_missing"
    cross = await client.get(
        f"/api/v1/teams/{team_b.team.id}/github/repos",
        headers=headers_for(team_a.users[Role.OWNER]),
    )
    assert cross.status_code == 404


async def test_personal_team_is_409(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db, kind=TeamKind.PERSONAL)
    resp = await get_repos(client, seeded, seeded.users[Role.OWNER])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "personal_team_unsupported"


async def test_no_installation_is_409(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db, installation=False)
    resp = await get_repos(client, seeded, seeded.users[Role.MEMBER])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "installation_missing"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (InstallationStatus.SUSPENDED, "installation_suspended"),
        (InstallationStatus.REVOKED, "installation_revoked"),
    ],
)
async def test_suspended_or_revoked_is_409(
    client: AsyncClient,
    db: AsyncSession,
    fake: FakeGitHubApp,
    status: InstallationStatus,
    code: str,
) -> None:
    seeded, _ = await world(db, status=status)
    resp = await get_repos(client, seeded, seeded.users[Role.MEMBER])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == code
    assert fake.mint_calls == []


async def test_a_dead_installation_at_github_surfaces_as_revoked(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    fake.mint_status[EXT_ID] = 404
    resp = await get_repos(client, seeded, seeded.users[Role.MEMBER])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "installation_revoked"


async def test_github_failure_is_502_and_not_cached(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    member = seeded.users[Role.MEMBER]
    fake.repo_pages = [[repo_record("acme/alpha")]]
    (listing,) = [r for r in fake.router.routes if "installation/repositories" in repr(r.pattern)]
    listing.mock(return_value=httpx.Response(500))
    failed = await get_repos(client, seeded, member)
    assert failed.status_code == 502

    listing.mock(side_effect=fake._repos)
    ok = await get_repos(client, seeded, member)
    assert ok.status_code == 200
    assert len(ok.json()["data"]) == 1


async def test_unauthenticated_is_401(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    resp = await client.get(f"/api/v1/teams/{seeded.team.id}/github/repos")
    assert resp.status_code == 401


async def test_listing_is_rate_limited(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    member = seeded.users[Role.MEMBER]
    for _ in range(REPOS_PER_MINUTE):
        assert (await get_repos(client, seeded, member)).status_code == 200
    limited = await get_repos(client, seeded, member)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"]
    assert limited.json()["error"]["code"] == "rate_limited"
