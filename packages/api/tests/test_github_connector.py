"""Tests for the GitHub connector (SOLUSDEV-103, W0-08).

The connector translates a repo's git tree into graph entities/relations and
detects committed design exports (Gerber/STEP/netlist/SPICE) across domains.
httpx calls are mocked with respx; no network access. Ingested tree content is
treated as untrusted data and parsed defensively (CLAUDE.md §7).
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest
import respx
from fixtures.github_sample import (
    COMMIT_BODY,
    DEFAULT_BRANCH,
    FAKE_EXCHANGED_TOKEN,
    HEAD_SHA,
    REPO_BODY,
    REPO_FULL_NAME,
    REPOS_BODY,
    TOKEN_BODY,
    TOKEN_ERROR_BODY,
    TREE_BODY,
    USER_BODY,
)
from solus_api.connectors import assert_connector_contract
from solus_api.connectors.contracts import (
    ConnectorError,
    Credentials,
    Domain,
    SyncContext,
)
from solus_api.connectors.github import GitHubConnector

API = "https://api.github.com"
OAUTH = "https://github.com/login/oauth"


def _mock_github_api() -> None:
    """Register the happy-path GitHub endpoints the connector calls."""
    respx.get(f"{API}/user").mock(return_value=httpx.Response(200, json=USER_BODY))
    respx.get(f"{API}/repos/{REPO_FULL_NAME}").mock(
        return_value=httpx.Response(200, json=REPO_BODY)
    )
    respx.get(f"{API}/repos/{REPO_FULL_NAME}/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(200, json=COMMIT_BODY)
    )
    respx.get(f"{API}/repos/{REPO_FULL_NAME}/git/trees/{HEAD_SHA}").mock(
        return_value=httpx.Response(200, json=TREE_BODY)
    )


def _ctx(branch: str | None = DEFAULT_BRANCH, cursor: dict[str, str] | None = None) -> SyncContext:
    config: dict[str, str] = {"repo": REPO_FULL_NAME}
    if branch is not None:
        config["branch"] = branch
    return SyncContext(
        credentials=Credentials(token="ghu_test"),
        config=config,
        cursor=cursor or {},
    )


@pytest.mark.asyncio
@respx.mock
async def test_passes_connector_contract() -> None:
    _mock_github_api()
    result = await assert_connector_contract(GitHubConnector(), _ctx())
    assert result.cursor == {"branch": DEFAULT_BRANCH, "sha": HEAD_SHA}
    # The repo root entity is always emitted.
    repo_entities = [e for e in result.entities if e.source_key == ":repo"]
    assert len(repo_entities) == 1
    assert repo_entities[0].type == "code_repo"
    assert repo_entities[0].properties == {"branch": DEFAULT_BRANCH, "commit": HEAD_SHA}


@pytest.mark.asyncio
@respx.mock
async def test_design_exports_detected_by_extension() -> None:
    _mock_github_api()
    result = await GitHubConnector().sync(_ctx())
    by_key = {e.source_key: e for e in result.entities}

    gerber = by_key["hardware/board.gbr"]
    assert gerber.type == "design_export"
    assert gerber.domain == Domain.ELECTRICAL
    assert gerber.properties["export_kind"] == "gerber"

    step = by_key["mech/chassis.step"]
    assert step.type == "design_export"
    assert step.domain == Domain.MECHANICAL
    assert step.properties["export_kind"] == "step"

    netlist = by_key["elec/power.net"]
    assert netlist.type == "design_export"
    assert netlist.domain == Domain.ELECTRICAL
    assert netlist.properties["export_kind"] == "netlist"

    spice = by_key["elec/filter.cir"]
    assert spice.type == "design_export"
    assert spice.domain == Domain.ELECTRICAL
    assert spice.properties["export_kind"] == "spice"

    # Ordinary source stays a code_file in the software domain.
    py = by_key["src/main.py"]
    assert py.type == "code_file"
    assert py.domain == Domain.CODE
    assert py.properties == {"size": 800, "sha": "bb02", "path": "src/main.py"}


@pytest.mark.asyncio
@respx.mock
async def test_relations_form_a_connected_tree() -> None:
    _mock_github_api()
    result = await GitHubConnector().sync(_ctx())
    key_set = {e.source_key for e in result.entities}

    # Contract invariant: every relation endpoint is an emitted entity.
    for rel in result.relations:
        assert rel.type == "contains"
        assert rel.from_key in key_set
        assert rel.to_key in key_set

    contains = {(r.from_key, r.to_key) for r in result.relations}
    # A nested file's parent is its directory.
    assert ("src", "src/main.py") in contains
    # A top-level path's parent is the repo root.
    assert (":repo", "README.md") in contains
    assert (":repo", "src") in contains


@pytest.mark.asyncio
@respx.mock
async def test_missing_parent_dir_is_synthesised() -> None:
    """hardware/ is absent from the tree; it must still be a graph node so the
    contains edge to hardware/board.gbr resolves."""
    _mock_github_api()
    result = await GitHubConnector().sync(_ctx())
    by_key = {e.source_key: e for e in result.entities}
    assert "hardware" in by_key
    assert by_key["hardware"].type == "code_module"
    contains = {(r.from_key, r.to_key) for r in result.relations}
    assert ("hardware", "hardware/board.gbr") in contains
    assert (":repo", "hardware") in contains


@pytest.mark.asyncio
@respx.mock
async def test_sync_resolves_default_branch_when_unset() -> None:
    respx.get(f"{API}/repos/{REPO_FULL_NAME}").mock(
        return_value=httpx.Response(200, json=REPO_BODY)
    )
    respx.get(f"{API}/repos/{REPO_FULL_NAME}/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(200, json=COMMIT_BODY)
    )
    respx.get(f"{API}/repos/{REPO_FULL_NAME}/git/trees/{HEAD_SHA}").mock(
        return_value=httpx.Response(200, json=TREE_BODY)
    )
    result = await GitHubConnector().sync(_ctx(branch=None))
    assert result.cursor == {"branch": DEFAULT_BRANCH, "sha": HEAD_SHA}


@pytest.mark.asyncio
@respx.mock
async def test_sync_repo_not_found_raises() -> None:
    respx.get(f"{API}/repos/{REPO_FULL_NAME}/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    with pytest.raises(ConnectorError) as exc:
        await GitHubConnector().sync(_ctx())
    assert exc.value.code == "repo_not_found"


@pytest.mark.asyncio
@respx.mock
async def test_sync_other_github_error_raises() -> None:
    respx.get(f"{API}/repos/{REPO_FULL_NAME}/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(500, json={"message": "boom"})
    )
    with pytest.raises(ConnectorError) as exc:
        await GitHubConnector().sync(_ctx())
    assert exc.value.code == "github_error"


@pytest.mark.asyncio
@respx.mock
async def test_validate_credentials_returns_account() -> None:
    respx.get(f"{API}/user").mock(return_value=httpx.Response(200, json=USER_BODY))
    account = await GitHubConnector().validate_credentials(Credentials(token="ghu_test"))
    assert account.external_id == "4242"
    assert account.login == "octo"
    assert account.name == "Octo Roboticist"


@pytest.mark.asyncio
@respx.mock
async def test_validate_credentials_401_raises() -> None:
    respx.get(f"{API}/user").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )
    with pytest.raises(ConnectorError) as exc:
        await GitHubConnector().validate_credentials(Credentials(token="bad"))
    assert exc.value.code == "invalid_credentials"


@pytest.mark.asyncio
@respx.mock
async def test_list_repositories() -> None:
    respx.get(f"{API}/user/repos").mock(return_value=httpx.Response(200, json=REPOS_BODY))
    repos = await GitHubConnector().list_repositories(Credentials(token="ghu_test"))
    assert {r["full_name"] for r in repos} == {REPO_FULL_NAME, "octo/sandbox"}
    assert all(set(r) == {"full_name", "default_branch", "private"} for r in repos)


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_happy_path() -> None:
    respx.post(f"{OAUTH}/access_token").mock(return_value=httpx.Response(200, json=TOKEN_BODY))
    creds = await GitHubConnector(client_id="cid", client_secret="sec").exchange_code(
        code="abc", redirect_uri="https://app.solus.dev/cb"
    )
    assert creds.token == FAKE_EXCHANGED_TOKEN
    assert creds.metadata == {"scope": "repo,read:user", "token_type": "bearer"}


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_error_body_raises() -> None:
    respx.post(f"{OAUTH}/access_token").mock(
        return_value=httpx.Response(200, json=TOKEN_ERROR_BODY)
    )
    with pytest.raises(ConnectorError) as exc:
        await GitHubConnector(client_id="cid", client_secret="sec").exchange_code(
            code="abc", redirect_uri="https://app.solus.dev/cb"
        )
    assert exc.value.code == "oauth_exchange_failed"
    assert "incorrect or expired" in exc.value.message


@pytest.mark.asyncio
@respx.mock
async def test_detect_changes_matches_and_differs() -> None:
    respx.get(f"{API}/repos/{REPO_FULL_NAME}/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(200, json=COMMIT_BODY)
    )
    connector = GitHubConnector()
    same = await connector.detect_changes(_ctx(cursor={"branch": DEFAULT_BRANCH, "sha": HEAD_SHA}))
    assert same is False
    differs = await connector.detect_changes(_ctx(cursor={"branch": DEFAULT_BRANCH, "sha": "old"}))
    assert differs is True


@pytest.mark.asyncio
@respx.mock
async def test_detect_changes_on_error_returns_true() -> None:
    respx.get(f"{API}/repos/{REPO_FULL_NAME}/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(500, json={"message": "boom"})
    )
    connector = GitHubConnector()
    assert await connector.detect_changes(_ctx(cursor={"sha": HEAD_SHA})) is True


def test_authorize_url_contains_required_params() -> None:
    url = GitHubConnector(client_id="cid").authorize_url(
        state="xyz", redirect_uri="https://app.solus.dev/cb"
    )
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=cid" in url
    assert "state=xyz" in url
    assert "scope=repo+read" in url or "scope=repo%20read" in url
    assert "redirect_uri=https" in url


def test_authorize_url_unconfigured_raises() -> None:
    with pytest.raises(ConnectorError) as exc:
        GitHubConnector().authorize_url(state="xyz", redirect_uri="https://app.solus.dev/cb")
    assert exc.value.code == "oauth_not_configured"


def test_classvars() -> None:
    assert GitHubConnector.provider == "github"
    assert GitHubConnector.scopes == ("repo", "read:user")
    assert GitHubConnector.config_fields == ("repo", "branch")


@pytest.mark.asyncio
async def test_sync_rejects_path_injection_in_repo() -> None:
    """repo/branch are interpolated into GitHub API URLs — a crafted value must
    be rejected at the boundary before any request is made (CLAUDE.md §7)."""
    connector = GitHubConnector()
    bad = SyncContext(credentials=Credentials(token="t"), config={"repo": "../../evil"})
    with pytest.raises(ConnectorError) as exc:
        await connector.sync(bad)
    assert exc.value.code == "invalid_repo"


@pytest.mark.asyncio
async def test_sync_rejects_illegal_branch() -> None:
    connector = GitHubConnector()
    ctx = SyncContext(
        credentials=Credentials(token="t"),
        config={"repo": "octocat/strider-fw", "branch": "main/../../x"},
    )
    with pytest.raises(ConnectorError) as exc:
        await connector.sync(ctx)
    assert exc.value.code == "invalid_branch"


@pytest.mark.asyncio
@respx.mock
async def test_list_repositories_rejects_non_list_body() -> None:
    """A malformed /user/repos body must raise a clean ConnectorError, not a 500."""
    respx.get(f"{API}/user/repos").mock(
        return_value=httpx.Response(200, json={"message": "unexpected"})
    )
    with pytest.raises(ConnectorError) as exc:
        await GitHubConnector().list_repositories(Credentials(token="ghu_test"))
    assert exc.value.code == "github_error"


@pytest.mark.asyncio
@respx.mock
async def test_sync_surfaces_tree_truncation() -> None:
    """A truncated GitHub tree must be flagged as a SyncError, not hidden."""
    _mock_github_api()
    truncated_tree = {**TREE_BODY, "truncated": True}
    respx.get(f"{API}/repos/{REPO_FULL_NAME}/git/trees/{HEAD_SHA}").mock(
        return_value=httpx.Response(200, json=truncated_tree)
    )
    result = await GitHubConnector().sync(_ctx())
    assert any("truncated" in e.message.lower() for e in result.errors)


@pytest.mark.asyncio
async def test_sync_rejects_dot_segment_repo() -> None:
    """`..` satisfies the repo charclass — dot-segments must still be rejected
    (single-slash traversal like '../evil' slipped past the regex alone)."""
    for bad_repo in ("../evil", "./evil", "evil/..", "evil/."):
        ctx = SyncContext(credentials=Credentials(token="t"), config={"repo": bad_repo})
        with pytest.raises(ConnectorError) as exc:
            await GitHubConnector().sync(ctx)
        assert exc.value.code == "invalid_repo", bad_repo


# ------------------------------------------------ SOLUSDEV-167: free probes


@respx.mock
async def test_a_304_probe_costs_nothing_and_reports_unchanged() -> None:
    """GitHub documents that a conditional request answered 304 does NOT count
    against the rate limit. So the common case — nothing changed — becomes free,
    which is strictly better than a webhook for this provider.
    """
    from solus_api.connectors.github import ETAG_KEY

    route = respx.get(f"{API}/repos/{REPO_FULL_NAME}/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(304)
    )
    ctx = SyncContext(
        credentials=Credentials(token="t"),
        config={"repo": REPO_FULL_NAME, "branch": DEFAULT_BRANCH},
        cursor={"branch": DEFAULT_BRANCH, "sha": "abc", ETAG_KEY: '"etag-1"'},
    )

    assert await GitHubConnector().detect_changes(ctx) is False
    assert route.calls[0].request.headers["if-none-match"] == '"etag-1"'


@respx.mock
async def test_a_probe_without_a_stored_etag_falls_back_to_a_normal_request() -> None:
    respx.get(f"{API}/repos/{REPO_FULL_NAME}/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(200, json={"sha": "abc"})
    )
    ctx = SyncContext(
        credentials=Credentials(token="t"),
        config={"repo": REPO_FULL_NAME, "branch": DEFAULT_BRANCH},
        cursor={"branch": DEFAULT_BRANCH, "sha": "abc"},
    )

    assert await GitHubConnector().detect_changes(ctx) is False


@respx.mock
async def test_a_stale_etag_for_another_branch_is_not_reused() -> None:
    """The validator is per-URL. Reusing one across branches would answer 304 for
    a branch nobody asked about."""
    from solus_api.connectors.github import ETAG_KEY

    respx.get(f"{API}/repos/{REPO_FULL_NAME}/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(200, json={"sha": "zzz"})
    )
    ctx = SyncContext(
        credentials=Credentials(token="t"),
        config={"repo": REPO_FULL_NAME, "branch": DEFAULT_BRANCH},
        cursor={"branch": "some-other-branch", "sha": "abc", ETAG_KEY: '"etag-1"'},
    )

    assert await GitHubConnector().detect_changes(ctx) is True


# --------------------------------------------------------------------------
# SOLUSDEV-246 (STORE ST1): the repo-committed `.solus/project.toml` `[ext.<id>]`
# tables land as ONE `solus_config` entity (ADR-035 §4 as amended; widget-bundles.md §6).

SOLUS_TOML = b"""
[ext.fixture-bundle]
max_notes = 3
prefix = "fx"

[ext.other-bundle]
enabled = true
"""


def _tree_with_solus(size: int = 120) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(json.dumps(TREE_BODY))
    body["tree"].append({"path": ".solus", "type": "tree", "sha": "ff00"})
    body["tree"].append(
        {"path": ".solus/project.toml", "type": "blob", "size": size, "sha": "ff01"}
    )
    return body


def _mock_with_solus(
    blob: bytes | None = SOLUS_TOML, *, size: int = 120, status: int = 200
) -> None:
    respx.get(f"{API}/repos/{REPO_FULL_NAME}").mock(
        return_value=httpx.Response(200, json=REPO_BODY)
    )
    respx.get(f"{API}/repos/{REPO_FULL_NAME}/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(200, json=COMMIT_BODY)
    )
    respx.get(f"{API}/repos/{REPO_FULL_NAME}/git/trees/{HEAD_SHA}").mock(
        return_value=httpx.Response(200, json=_tree_with_solus(size))
    )
    content = base64.b64encode(blob or b"").decode()
    respx.get(f"{API}/repos/{REPO_FULL_NAME}/git/blobs/ff01").mock(
        return_value=httpx.Response(status, json={"content": content, "encoding": "base64"})
    )


@pytest.mark.asyncio
@respx.mock
async def test_solus_project_toml_lands_as_one_solus_config_entity() -> None:
    _mock_with_solus()
    result = await GitHubConnector().sync(_ctx())
    by_key = {e.source_key: e for e in result.entities}
    config = by_key[".solus/project.toml"]
    assert config.type == "solus_config"
    assert config.domain == Domain.CODE
    assert config.properties["ext"] == {
        "fixture-bundle": {"max_notes": 3, "prefix": "fx"},
        "other-bundle": {"enabled": True},
    }
    assert config.properties["path"] == ".solus/project.toml"
    assert result.errors == []
    # The file is still a normal code_file for the tree? No — the config entity
    # REPLACES the plain blob so the graph holds one row for that path.
    assert config.type != "code_file"


@pytest.mark.asyncio
@respx.mock
async def test_malformed_solus_project_toml_is_a_sync_error_not_a_raise() -> None:
    _mock_with_solus(b"[ext.fixture-bundle\nmax_notes = ")
    result = await GitHubConnector().sync(_ctx())
    by_key = {e.source_key: e for e in result.entities}
    assert ".solus/project.toml" in by_key  # the blob itself is still indexed
    assert by_key[".solus/project.toml"].type == "code_file"
    assert any("project.toml" in err.message for err in result.errors)


@pytest.mark.asyncio
@respx.mock
async def test_oversized_solus_project_toml_is_never_fetched() -> None:
    _mock_with_solus(size=70_000)
    result = await GitHubConnector().sync(_ctx())
    assert not any("git/blobs" in str(call.request.url) for call in respx.calls)
    assert any("exceeds" in err.message for err in result.errors)


@pytest.mark.asyncio
@respx.mock
async def test_blob_fetch_failure_degrades_to_a_sync_error() -> None:
    _mock_with_solus(status=500)
    result = await GitHubConnector().sync(_ctx())
    assert any(".solus/project.toml" in err.item for err in result.errors)
    assert {e.source_key for e in result.entities} >= {"src/main.py", ".solus/project.toml"}
