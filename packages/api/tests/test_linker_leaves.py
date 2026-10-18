"""SOLUSDEV-216 Phase 4 (B2): the team's link outlives the person who made it (ADR-039 s8).

The installation belongs to the TEAM. When the linking admin leaves the team (membership
soft-deleted) or their account is gone (`linked_by` NULL), minting and syncing keep working.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx
from conftest import bearer
from fastapi import FastAPI
from fixtures.github_app_fake import FakeGitHubApp, app_settings, generate_key_pair
from fixtures.github_sample import COMMIT_BODY, HEAD_SHA, REPO_BODY, TREE_BODY, repo_record
from fixtures.team_installation_seed import (
    SeededTeam,
    seed_installation,
    seed_installation_source,
    seed_team,
)
from httpx import AsyncClient
from solus_api.connectors.github import GitHubConnector
from solus_api.connectors.github_app import (
    clear_installation_tokens,
    installation_secret_ref,
    resolve_installation_credentials,
)
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.core.config import Settings
from solus_api.models import Membership, Role, SourceStatus, utcnow
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

API = "https://api.github.com"
EXT_ID = 990011
REPO = "acme/robot"


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
        gh.repo_pages = [[repo_record(REPO)]]
        router.get(f"{API}/repos/{REPO}").mock(return_value=httpx.Response(200, json=REPO_BODY))
        router.get(f"{API}/repos/{REPO}/commits/main").mock(
            return_value=httpx.Response(200, json=COMMIT_BODY)
        )
        router.get(f"{API}/repos/{REPO}/git/trees/{HEAD_SHA}").mock(
            return_value=httpx.Response(200, json=TREE_BODY)
        )
        yield gh


async def _world(db: AsyncSession) -> SeededTeam:
    """An installation linked by the OWNER, one bound source created by the MEMBER."""
    seeded = await seed_team(db)
    await seed_installation(db, seeded, external_id=EXT_ID, linked_by=seeded.users[Role.OWNER])
    await seed_installation_source(db, seeded, repo=REPO)
    await db.commit()
    return seeded


async def _linker_leaves_team(db: AsyncSession, seeded: SeededTeam) -> None:
    await db.execute(
        update(Membership)
        .where(
            Membership.team_id == seeded.team.id,
            Membership.user_id == seeded.users[Role.OWNER].id,
        )
        .values(deleted_at=utcnow())
    )
    await db.commit()


async def _linker_account_gone(db: AsyncSession, seeded: SeededTeam) -> None:
    assert seeded.installation is not None
    seeded.installation.linked_by = None
    await db.commit()


@pytest.fixture(params=["membership_removed", "linked_by_null"])
async def departed(request: pytest.FixtureRequest, db: AsyncSession) -> SeededTeam:
    seeded = await _world(db)
    if request.param == "membership_removed":
        await _linker_leaves_team(db, seeded)
    else:
        await _linker_account_gone(db, seeded)
    return seeded


async def test_resolver_still_mints_after_the_linker_leaves(
    departed: SeededTeam, fake: FakeGitHubApp
) -> None:
    assert departed.installation is not None

    credentials = await resolve_installation_credentials(
        installation_secret_ref(departed.installation.id)
    )

    assert credentials.token == fake.minted_tokens[-1]
    assert credentials.metadata["installation_id"] == EXT_ID


async def test_sync_still_succeeds_after_the_linker_leaves(
    client: AsyncClient, db: AsyncSession, departed: SeededTeam, fake: FakeGitHubApp
) -> None:
    member = departed.users[Role.MEMBER]
    source = departed.sources[0]
    project_id = departed.project.id
    source_id = source.id

    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources/{source_id}/sync",
        headers=bearer(member.supabase_user_id, member.email),
    )

    assert resp.status_code == 202, resp.text
    assert fake.minted_tokens, "the sync minted an installation token"
    detail = (
        await client.get(
            f"/api/v1/projects/{project_id}/sources/{source_id}",
            headers=bearer(member.supabase_user_id, member.email),
        )
    ).json()["data"]
    assert detail["status"] == SourceStatus.CONNECTED.value
    assert detail["entity_count"] > 0
