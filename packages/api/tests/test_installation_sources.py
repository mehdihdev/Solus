"""Installation-backed sources (SOLUSDEV-216 S216-T6, ADR-039 s4, docs/api/github-orgs.md s2).

`POST /projects/{id}/sources` with `installation: true` binds one repo the team's GitHub
App installation can see. The team comes from the PROJECT, never from input; binding is
free (no plan check); the credential is the reserved ref, never a stored token.
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
from fixtures.github_sample import COMMIT_BODY, HEAD_SHA, REPO_BODY, TREE_BODY, repo_record
from fixtures.team_installation_seed import (
    SeededTeam,
    seed_installation,
    seed_team,
    seed_user,
)
from httpx import AsyncClient
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.github import GitHubConnector
from solus_api.connectors.github_app import (
    clear_installation_tokens,
    installation_secret_ref,
    resolve_installation_credentials,
)
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.core.config import Settings
from solus_api.models import (
    Activity,
    DataEvent,
    InstallationStatus,
    Membership,
    Role,
    Source,
    SourceStatus,
    Subscription,
    TeamInstallation,
    TeamKind,
    User,
)
from solus_api.services.team_installations import get_live_installation
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

API = "https://api.github.com"
INSTALL_EXT_ID = 880011
REPO = "acme/robot"
OTHER_REPO = "acme/firmware"
OUTSIDE_REPO = "acme/not-shared"


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
        gh.repo_pages = [[repo_record(REPO), repo_record(OTHER_REPO, "develop", private=False)]]
        yield gh


def headers_for(user: User) -> dict[str, str]:
    return bearer(user.supabase_user_id, user.email)


async def world(
    db: AsyncSession,
    *,
    installation: bool = True,
    status: InstallationStatus = InstallationStatus.ACTIVE,
    kind: TeamKind = TeamKind.COLLABORATIVE,
    external_id: int = INSTALL_EXT_ID,
) -> tuple[SeededTeam, User]:
    """A team (owner, member, project), an optional installation, and a viewer."""
    seeded = await seed_team(db, kind=kind)
    if installation:
        await seed_installation(db, seeded, external_id=external_id, status=status)
    viewer = await seed_user(db, "viewer")
    db.add(Membership(team_id=seeded.team.id, user_id=viewer.id, role=Role.VIEWER))
    await db.commit()
    return seeded, viewer


def bind_body(repo: str = REPO, **extra: Any) -> dict[str, Any]:
    return {
        "type": "github",
        "name": repo,
        "config": {"repo": repo, "branch": "main"},
        "installation": True,
        **extra,
    }


async def bind(
    client: AsyncClient, seeded: SeededTeam, user: User, body: dict[str, Any] | None = None
) -> httpx.Response:
    return await client.post(
        f"/api/v1/projects/{seeded.project.id}/sources",
        json=body or bind_body(),
        headers=headers_for(user),
    )


async def sources_of(db: AsyncSession, seeded: SeededTeam) -> list[Source]:
    rows = await db.scalars(
        select(Source)
        .where(Source.project_id == seeded.project.id)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


# --------------------------------------------------------------------- binding


async def test_binding_without_a_branch_uses_the_repos_default_branch(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    member = seeded.users[Role.MEMBER]
    body = bind_body(OTHER_REPO)
    body["config"] = {"repo": OTHER_REPO}  # no branch; the listing says `develop`

    resp = await bind(client, seeded, member, body)

    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["config"] == {"repo": OTHER_REPO, "branch": "develop"}


async def test_an_explicit_branch_is_kept_at_bind(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    body = bind_body(OTHER_REPO)
    body["config"] = {"repo": OTHER_REPO, "branch": "release"}

    resp = await bind(client, seeded, seeded.users[Role.MEMBER], body)

    assert resp.json()["data"]["config"]["branch"] == "release"


async def test_member_binds_with_the_reserved_ref(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    member = seeded.users[Role.MEMBER]

    resp = await bind(client, seeded, member)

    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["status"] == "connected"
    assert data["connection_id"] is None
    assert data["account_login"] == "acme"
    assert "secret_ref" not in data and "installation_id" not in data
    (source,) = await sources_of(db, seeded)
    inst = seeded.installation
    assert inst is not None
    assert source.installation_id == inst.id
    assert source.secret_ref == installation_secret_ref(inst.id)
    assert source.connection_id is None
    assert source.account_external_id == f"installation:{INSTALL_EXT_ID}"
    assert source.account_login == "acme"
    assert source.team_id == seeded.team.id
    assert source.created_by == member.id
    assert source.config == {"repo": REPO, "branch": "main"}


async def test_binding_is_free_at_zero_integrations(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    member = seeded.users[Role.MEMBER]
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == member.id))
    assert sub is not None
    sub.limits = {"max_integrations": 0}
    await db.commit()

    resp = await bind(client, seeded, member)

    assert resp.status_code == 201, resp.text


async def test_binding_emits_repo_bound_event(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    member = seeded.users[Role.MEMBER]
    member.data_collection_consent = True
    await db.commit()

    resp = await bind(client, seeded, member)

    assert resp.status_code == 201, resp.text
    events = (
        await db.scalars(select(DataEvent).where(DataEvent.event_type == "github_org.repo_bound"))
    ).all()
    assert len(events) == 1
    assert events[0].team_id == seeded.team.id
    assert events[0].project_id == seeded.project.id
    assert events[0].user_id == member.id


async def test_rebinding_the_same_repo_is_idempotent(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    member = seeded.users[Role.MEMBER]
    member.data_collection_consent = True
    await db.commit()

    first = await bind(client, seeded, member)
    second = await bind(client, seeded, seeded.users[Role.OWNER])

    assert first.status_code == second.status_code == 201
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert len(await sources_of(db, seeded)) == 1
    events = (
        await db.scalars(select(DataEvent).where(DataEvent.event_type == "github_org.repo_bound"))
    ).all()
    assert len(events) == 1


async def test_two_repos_make_two_sources(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    member = seeded.users[Role.MEMBER]
    await bind(client, seeded, member, bind_body(REPO))
    resp = await bind(client, seeded, member, bind_body(OTHER_REPO))
    assert resp.status_code == 201
    assert len(await sources_of(db, seeded)) == 2


async def test_viewer_cannot_bind(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, viewer = await world(db)
    resp = await bind(client, seeded, viewer)
    assert resp.status_code == 403
    assert await sources_of(db, seeded) == []


async def test_non_member_gets_404(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    outsider = await seed_user(db, "outsider")
    await db.commit()
    resp = await bind(client, seeded, outsider)
    assert resp.status_code == 404
    assert await sources_of(db, seeded) == []


async def test_no_installation_is_409_installation_missing(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db, installation=False)
    resp = await bind(client, seeded, seeded.users[Role.MEMBER])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "installation_missing"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (InstallationStatus.SUSPENDED, "installation_suspended"),
        (InstallationStatus.REVOKED, "installation_revoked"),
    ],
)
async def test_inactive_installation_is_409(
    client: AsyncClient,
    db: AsyncSession,
    fake: FakeGitHubApp,
    status: InstallationStatus,
    code: str,
) -> None:
    seeded, _ = await world(db, status=status)
    resp = await bind(client, seeded, seeded.users[Role.MEMBER])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == code
    assert fake.mint_calls == []


async def test_personal_team_cannot_bind(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db, kind=TeamKind.PERSONAL)
    resp = await bind(client, seeded, seeded.users[Role.MEMBER])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "installation_missing"


async def test_repo_outside_the_installation_is_400(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    resp = await bind(client, seeded, seeded.users[Role.MEMBER], bind_body(OUTSIDE_REPO))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "repo_not_in_installation"
    assert await sources_of(db, seeded) == []


async def test_repo_check_ignores_case(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    resp = await bind(client, seeded, seeded.users[Role.MEMBER], bind_body("ACME/Robot"))
    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("config", [{}, {"repo": 5}, {"repo": ""}, {"repo": ["acme/robot"]}])
async def test_missing_or_malformed_repo_is_400(
    client: AsyncClient,
    db: AsyncSession,
    fake: FakeGitHubApp,
    config: dict[str, Any],
) -> None:
    seeded, _ = await world(db)
    body = {**bind_body(), "config": config}
    resp = await bind(client, seeded, seeded.users[Role.MEMBER], body)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] in {"validation_error", "repo_not_in_installation"}


@pytest.mark.parametrize("extra", [{"token": "ghp_x"}, {"connection_id": "abc"}])
async def test_mixing_with_a_credential_is_credential_conflict(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp, extra: dict[str, Any]
) -> None:
    seeded, _ = await world(db)
    resp = await bind(client, seeded, seeded.users[Role.MEMBER], bind_body(**extra))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "credential_conflict"
    assert await sources_of(db, seeded) == []


async def test_installation_flag_on_a_non_github_type_is_unsupported(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _ = await world(db)
    body = {"type": "kicad", "name": "k", "config": {}, "installation": True}
    resp = await bind(client, seeded, seeded.users[Role.MEMBER], body)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unsupported"


# ------------------------------------------------------------- cross tenant


async def test_project_of_team_a_never_resolves_team_bs_installation(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    """B's installation covers the very repo name A asks for. A has none: A gets
    installation_missing, even for a user who belongs to BOTH teams, and B's token is
    never minted on A's behalf."""
    team_a, _ = await world(db, installation=False)
    team_b, _ = await world(db, external_id=INSTALL_EXT_ID + 1)
    both = team_b.users[Role.MEMBER]
    db.add(Membership(team_id=team_a.team.id, user_id=both.id, role=Role.MEMBER))
    await db.commit()
    # B lists its repos first, so B's listing is cached and warm.
    warm = await bind(client, team_b, both)
    assert warm.status_code == 201

    resp = await bind(client, team_a, both)

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "installation_missing"
    assert await sources_of(db, team_a) == []
    (b_source,) = await sources_of(db, team_b)
    assert b_source.installation_id == team_b.installation.id  # type: ignore[union-attr]


async def test_team_is_taken_from_the_project_not_the_request(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    """An extra team/installation field in the body is rejected, never honoured."""
    team_a, _ = await world(db, installation=False)
    team_b, _ = await world(db, external_id=INSTALL_EXT_ID + 2)
    assert team_b.installation is not None
    body = {**bind_body(), "installation_id": str(team_b.installation.id)}
    resp = await bind(client, team_a, team_a.users[Role.MEMBER], body)
    assert resp.status_code == 422
    assert await sources_of(db, team_a) == []


# -------------------------------------------------------------------- PATCH


async def _bound(
    client: AsyncClient, db: AsyncSession
) -> tuple[SeededTeam, User, dict[str, Any], str]:
    seeded, _ = await world(db)
    member = seeded.users[Role.MEMBER]
    created = (await bind(client, seeded, member)).json()["data"]
    return seeded, member, created, f"/api/v1/projects/{seeded.project.id}/sources/{created['id']}"


@pytest.mark.parametrize("field", ["secret_ref", "installation_id", "connection_id"])
async def test_credential_fields_are_not_patchable(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp, field: str
) -> None:
    seeded, member, _, url = await _bound(client, db)
    before = (await sources_of(db, seeded))[0]
    snapshot = (before.secret_ref, before.installation_id, before.connection_id)

    resp = await client.patch(
        url, json={field: "00000000-0000-0000-0000-000000000000"}, headers=headers_for(member)
    )

    assert resp.status_code == 422
    after = (await sources_of(db, seeded))[0]
    assert (after.secret_ref, after.installation_id, after.connection_id) == snapshot


async def test_credential_keys_smuggled_in_config_do_not_reach_the_columns(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, member, _, url = await _bound(client, db)
    before = (await sources_of(db, seeded))[0]
    snapshot = (before.secret_ref, before.installation_id, before.connection_id)

    resp = await client.patch(
        url,
        json={"config": {"branch": "dev", "secret_ref": "evil", "installation_id": "x"}},
        headers=headers_for(member),
    )

    assert resp.status_code == 200, resp.text
    after = (await sources_of(db, seeded))[0]
    assert (after.secret_ref, after.installation_id, after.connection_id) == snapshot
    assert after.config == {"repo": REPO, "branch": "dev"}


async def test_patch_drops_unknown_config_keys_on_a_bound_source(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, member, _, url = await _bound(client, db)

    resp = await client.patch(
        url,
        json={"config": {"branch": "dev", "extra_setting": "x", "token": "t"}},
        headers=headers_for(member),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["config"] == {"repo": REPO, "branch": "dev"}
    assert (await sources_of(db, seeded))[0].config == {"repo": REPO, "branch": "dev"}


@pytest.mark.parametrize("config", [{"branch": 5}, {"branch": ""}, {"repo": 7}, {"repo": "  "}])
async def test_patch_validates_the_bound_keys(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp, config: dict[str, Any]
) -> None:
    seeded, member, _, url = await _bound(client, db)

    resp = await client.patch(url, json={"config": config}, headers=headers_for(member))

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "validation_error"
    assert (await sources_of(db, seeded))[0].config == {"repo": REPO, "branch": "main"}


async def test_patch_repo_to_another_visible_repo_is_allowed(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, member, _, url = await _bound(client, db)
    resp = await client.patch(
        url, json={"config": {"repo": OTHER_REPO}}, headers=headers_for(member)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["config"]["repo"] == OTHER_REPO


async def test_patch_repo_outside_the_installation_is_rechecked(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, member, _, url = await _bound(client, db)
    resp = await client.patch(
        url, json={"config": {"repo": OUTSIDE_REPO}}, headers=headers_for(member)
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "repo_not_in_installation"
    assert (await sources_of(db, seeded))[0].config["repo"] == REPO


async def test_patch_repo_on_a_suspended_installation_is_409(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, member, _, url = await _bound(client, db)
    assert seeded.installation is not None
    seeded.installation.status = InstallationStatus.SUSPENDED
    await db.commit()

    repo_change = await client.patch(
        url, json={"config": {"repo": OTHER_REPO}}, headers=headers_for(member)
    )
    rename = await client.patch(url, json={"name": "renamed"}, headers=headers_for(member))

    assert repo_change.status_code == 409
    assert repo_change.json()["error"]["code"] == "installation_suspended"
    assert rename.status_code == 200  # no repo change, no check


async def test_viewer_cannot_patch(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, _, _, url = await _bound(client, db)
    viewer = (
        await db.scalars(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.team_id == seeded.team.id, Membership.role == Role.VIEWER)
        )
    ).one()
    resp = await client.patch(url, json={"name": "x"}, headers=headers_for(viewer))
    assert resp.status_code == 403


# ---------------------------------------------------------- end-to-end sync


async def test_sync_runs_through_the_minted_token_and_builds_the_graph(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, member, created, _ = await _bound(client, db)
    fake.router.get(f"{API}/repos/{REPO}").mock(return_value=httpx.Response(200, json=REPO_BODY))
    commits = fake.router.get(f"{API}/repos/{REPO}/commits/main").mock(
        return_value=httpx.Response(200, json=COMMIT_BODY)
    )
    fake.router.get(f"{API}/repos/{REPO}/git/trees/{HEAD_SHA}").mock(
        return_value=httpx.Response(200, json=TREE_BODY)
    )
    base = f"/api/v1/projects/{seeded.project.id}"

    resp = await client.post(f"{base}/sources/{created['id']}/sync", headers=headers_for(member))

    assert resp.status_code == 202, resp.text
    assert commits.call_count >= 1
    sent = {c.request.headers["authorization"] for c in commits.calls}
    assert sent == {f"Bearer {fake.minted_tokens[-1]}"}
    entities = (await client.get(f"{base}/entities", headers=headers_for(member))).json()["data"]
    names = {e["name"] for e in entities}
    assert {"main.py", "motor.py", "chassis.step", "board.gbr"} <= names
    detail = (
        await client.get(f"{base}/sources/{created['id']}", headers=headers_for(member))
    ).json()["data"]
    assert detail["status"] == SourceStatus.CONNECTED.value
    assert detail["entity_count"] > 0
    # The token is minted, never persisted or echoed.
    assert fake.minted_tokens[-1] not in resp.text


# ------------------------------------------- mint revocation is a full revoke (B1)


async def test_mint_404_runs_the_full_revoke_and_leaves_no_zombie_link(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, member, _, _ = await _bound(client, db)
    assert seeded.installation is not None
    inst_id, team_id = seeded.installation.id, seeded.team.id
    project_id = seeded.project.id
    member_headers = headers_for(member)
    fake.mint_status[INSTALL_EXT_ID] = 404  # GitHub says the installation is gone
    clear_installation_tokens()

    with pytest.raises(ConnectorError) as exc:
        await resolve_installation_credentials(installation_secret_ref(inst_id))
    assert exc.value.code == "installation_unavailable"

    db.expire_all()
    row = await db.get(TeamInstallation, inst_id)
    assert row is not None
    assert row.deleted_at is not None and row.status is InstallationStatus.REVOKED
    assert row.revoked_at is not None
    source = (await db.scalars(select(Source).where(Source.project_id == project_id))).one()
    assert source.status is SourceStatus.DISCONNECTED
    assert source.secret_ref is None
    assert (source.last_error or {}).get("code") == "installation_deleted"
    acts = (
        await db.scalars(
            select(Activity).where(
                Activity.team_id == team_id, Activity.type == "github_org.unlinked"
            )
        )
    ).all()
    assert len(acts) == 1 and acts[0].actor_id is None
    assert await get_live_installation(db, team_id) is None
    got = await client.get(f"/api/v1/teams/{team_id}/github/installation", headers=member_headers)
    assert got.json()["data"]["installation"] is None


async def test_team_can_link_again_after_a_mint_revocation(
    client: AsyncClient, db: AsyncSession, fake: FakeGitHubApp
) -> None:
    seeded, member, created, _ = await _bound(client, db)
    base = f"/api/v1/projects/{seeded.project.id}"
    fake.mint_status[INSTALL_EXT_ID] = 404
    clear_installation_tokens()
    await client.post(f"{base}/sources/{created['id']}/sync", headers=headers_for(member))

    started = await client.post(
        f"/api/v1/teams/{seeded.team.id}/github/install/start",
        json={},
        headers=headers_for(seeded.users[Role.OWNER]),
    )

    assert started.status_code == 201, started.text
