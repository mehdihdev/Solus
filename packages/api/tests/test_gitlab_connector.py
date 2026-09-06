"""Tests for the GitLab connector (SOLUSDEV-104) — the CON-01 mirror.

Same contract, same code-entity mapping and W0-08 export surfacing as GitHub,
against GitLab's v4 API shapes: nested namespaces, URL-encoded project paths,
and a paginated recursive tree. httpx is mocked with respx; no network.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
import pytest
import respx
from fixtures.gitlab_sample import (
    COMMIT_BODY,
    DEFAULT_BRANCH,
    FAKE_EXCHANGED_TOKEN,
    HEAD_SHA,
    PROJECT_BODY,
    PROJECTS_BODY,
    REPO_PATH,
    TOKEN_BODY,
    TOKEN_ERROR_BODY,
    TREE_PAGE_1,
    TREE_PAGE_2,
    USER_BODY,
)
from solus_api.connectors import assert_connector_contract
from solus_api.connectors.contracts import (
    ConnectorError,
    Credentials,
    Domain,
    SyncContext,
)
from solus_api.connectors.gitlab import GitLabConnector

BASE = "https://gitlab.com"
API = f"{BASE}/api/v4"
ENC = quote(REPO_PATH, safe="")

DUMMY_TOKEN = "glpat-dummy"  # placeholder, not a real secret


def _mock_gitlab_api() -> None:
    """Register the happy-path GitLab endpoints the connector calls."""
    respx.get(f"{API}/user").mock(return_value=httpx.Response(200, json=USER_BODY))
    respx.get(f"{API}/projects/{ENC}").mock(return_value=httpx.Response(200, json=PROJECT_BODY))
    respx.get(f"{API}/projects/{ENC}/repository/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(200, json=COMMIT_BODY)
    )
    respx.get(f"{API}/projects/{ENC}/repository/tree").mock(
        side_effect=[
            httpx.Response(200, json=TREE_PAGE_1, headers={"x-next-page": "2"}),
            httpx.Response(200, json=TREE_PAGE_2, headers={"x-next-page": ""}),
        ]
    )


def _ctx(branch: str | None = DEFAULT_BRANCH, cursor: dict[str, str] | None = None) -> SyncContext:
    config: dict[str, str] = {"repo": REPO_PATH}
    if branch is not None:
        config["branch"] = branch
    return SyncContext(
        credentials=Credentials(token=DUMMY_TOKEN),
        config=config,
        cursor=cursor or {},
    )


@pytest.mark.asyncio
@respx.mock
async def test_passes_connector_contract() -> None:
    _mock_gitlab_api()
    result = await assert_connector_contract(GitLabConnector(), _ctx())
    assert result.cursor == {"branch": DEFAULT_BRANCH, "sha": HEAD_SHA}
    roots = [e for e in result.entities if e.source_key == ":repo"]
    assert len(roots) == 1
    assert roots[0].type == "code_repo"
    assert roots[0].name == REPO_PATH


@pytest.mark.asyncio
@respx.mock
async def test_paginated_tree_fully_walked_with_design_exports() -> None:
    _mock_gitlab_api()
    result = await GitLabConnector().sync(_ctx())
    by_key = {e.source_key: e for e in result.entities}

    # Page 1 content.
    assert by_key["src/main.py"].type == "code_file"
    assert by_key["src/drivers/imu.py"].type == "code_file"
    # Page 2 content — same W0-08 mapping as GitHub.
    assert by_key["hardware/board.gbr"].type == "design_export"
    assert by_key["hardware/board.gbr"].domain == Domain.ELECTRICAL
    assert by_key["mech/chassis.step"].properties["export_kind"] == "step"
    assert by_key["mech/chassis.step"].domain == Domain.MECHANICAL
    assert by_key["elec/power.net"].properties["export_kind"] == "netlist"
    assert by_key["elec/filter.cir"].properties["export_kind"] == "spice"
    # Elided ancestor dirs are synthesized; submodule refs are skipped.
    assert by_key["hardware"].type == "code_module"
    assert by_key["elec"].type == "code_module"
    assert "vendor-module" not in by_key

    key_set = set(by_key)
    for relation in result.relations:
        assert relation.from_key in key_set
        assert relation.to_key in key_set


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_round_trip() -> None:
    respx.post(f"{BASE}/oauth/token").mock(return_value=httpx.Response(200, json=TOKEN_BODY))
    creds = await GitLabConnector(client_id="cid", client_secret="cs").exchange_code(
        code="good", redirect_uri="http://127.0.0.1:53682/auth/callback"
    )
    assert creds.token == FAKE_EXCHANGED_TOKEN
    assert creds.refresh_token is not None


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_failure_raises() -> None:
    respx.post(f"{BASE}/oauth/token").mock(return_value=httpx.Response(400, json=TOKEN_ERROR_BODY))
    with pytest.raises(ConnectorError) as exc:
        await GitLabConnector(client_id="cid", client_secret="cs").exchange_code(
            code="bad", redirect_uri="http://127.0.0.1:53682/auth/callback"
        )
    assert exc.value.code == "oauth_exchange_failed"


def test_authorize_url_carries_state_scope_redirect() -> None:
    url = GitLabConnector(client_id="cid").authorize_url(
        state="st4te", redirect_uri="http://127.0.0.1:53682/auth/callback"
    )
    assert url.startswith(f"{BASE}/oauth/authorize?")
    assert "client_id=cid" in url
    assert "state=st4te" in url
    assert "response_type=code" in url
    assert "read_api" in url


def test_authorize_url_requires_configuration() -> None:
    with pytest.raises(ConnectorError) as exc:
        GitLabConnector().authorize_url(state="s", redirect_uri="r")
    assert exc.value.code == "oauth_not_configured"


@pytest.mark.asyncio
@respx.mock
async def test_validate_credentials_rejects_bad_token() -> None:
    respx.get(f"{API}/user").mock(return_value=httpx.Response(401, json={"message": "401"}))
    with pytest.raises(ConnectorError) as exc:
        await GitLabConnector().validate_credentials(Credentials(token="bad"))
    assert exc.value.code == "invalid_credentials"


@pytest.mark.asyncio
@respx.mock
async def test_list_repositories_maps_fields() -> None:
    respx.get(f"{API}/projects").mock(return_value=httpx.Response(200, json=PROJECTS_BODY))
    repos = await GitLabConnector().list_repositories(Credentials(token=DUMMY_TOKEN))
    assert repos == [
        {"full_name": REPO_PATH, "default_branch": "main", "private": True},
        {"full_name": "strider-robotics/tools", "default_branch": "main", "private": False},
    ]


@pytest.mark.asyncio
@respx.mock
async def test_sync_repo_not_found() -> None:
    missing = quote("nope/gone", safe="")
    respx.get(f"{API}/projects/{missing}/repository/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(404, json={"message": "404 Project Not Found"})
    )
    ctx = SyncContext(
        credentials=Credentials(token=DUMMY_TOKEN),
        config={"repo": "nope/gone", "branch": DEFAULT_BRANCH},
    )
    with pytest.raises(ConnectorError) as exc:
        await GitLabConnector().sync(ctx)
    assert exc.value.code == "repo_not_found"


@pytest.mark.asyncio
async def test_sync_rejects_path_injection_in_repo() -> None:
    bad = SyncContext(credentials=Credentials(token=DUMMY_TOKEN), config={"repo": "../../etc"})
    with pytest.raises(ConnectorError) as exc:
        await GitLabConnector().sync(bad)
    assert exc.value.code == "invalid_repo"


@pytest.mark.asyncio
async def test_sync_accepts_nested_namespace_but_rejects_illegal_branch() -> None:
    ctx = SyncContext(
        credentials=Credentials(token=DUMMY_TOKEN),
        config={"repo": REPO_PATH, "branch": "main/../../x"},
    )
    with pytest.raises(ConnectorError) as exc:
        await GitLabConnector().sync(ctx)
    assert exc.value.code == "invalid_branch"


@pytest.mark.asyncio
@respx.mock
async def test_detect_changes_compares_head_sha() -> None:
    respx.get(f"{API}/projects/{ENC}/repository/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(200, json=COMMIT_BODY)
    )
    connector = GitLabConnector()
    assert await connector.detect_changes(_ctx(cursor={"sha": "old"})) is True
    assert await connector.detect_changes(_ctx(cursor={"sha": HEAD_SHA})) is False


@pytest.mark.asyncio
@respx.mock
async def test_detect_changes_true_on_probe_failure() -> None:
    respx.get(f"{API}/projects/{ENC}/repository/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(500, json={"message": "boom"})
    )
    assert await GitLabConnector().detect_changes(_ctx(cursor={"sha": HEAD_SHA})) is True


@pytest.mark.asyncio
@respx.mock
async def test_self_hosted_base_url() -> None:
    host = "https://gitlab.example.com"
    respx.get(f"{host}/api/v4/user").mock(return_value=httpx.Response(200, json=USER_BODY))
    account = await GitLabConnector(base_url=host).validate_credentials(
        Credentials(token=DUMMY_TOKEN)
    )
    assert account.login == "strider-bot"


@pytest.mark.asyncio
@respx.mock
async def test_tree_pagination_bounded_against_stuck_next_page() -> None:
    """A server that always answers x-next-page: 2 must not loop forever —
    the walk is bounded by iterations, not by the header's page number."""
    respx.get(f"{API}/projects/{ENC}").mock(return_value=httpx.Response(200, json=PROJECT_BODY))
    respx.get(f"{API}/projects/{ENC}/repository/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(200, json=COMMIT_BODY)
    )
    respx.get(f"{API}/projects/{ENC}/repository/tree").mock(
        return_value=httpx.Response(200, json=TREE_PAGE_1, headers={"x-next-page": "2"})
    )
    result = await GitLabConnector().sync(_ctx())
    # Terminates, and surfaces the truncation instead of hanging.
    assert any("not indexed" in e.message for e in result.errors)


# --------------------------------------------------------------------------
# SOLUSDEV-246 (STORE ST1): `.solus/project.toml` `[ext.<id>]` → one `solus_config` entity.

SOLUS_TOML = b"[ext.fixture-bundle]\nmax_notes = 3\n"
RAW_URL = f"{API}/projects/{ENC}/repository/files/{quote('.solus/project.toml', safe='')}/raw"


def _mock_with_solus(blob: bytes = SOLUS_TOML, *, status: int = 200) -> None:
    respx.get(f"{API}/projects/{ENC}").mock(return_value=httpx.Response(200, json=PROJECT_BODY))
    respx.get(f"{API}/projects/{ENC}/repository/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(200, json=COMMIT_BODY)
    )
    page: list[dict[str, Any]] = [
        *TREE_PAGE_1,
        {"path": ".solus", "type": "tree", "id": "ff00", "name": ".solus", "mode": "040000"},
        {
            "path": ".solus/project.toml",
            "type": "blob",
            "id": "ff01",
            "name": "project.toml",
            "mode": "100644",
        },
    ]
    respx.get(f"{API}/projects/{ENC}/repository/tree").mock(
        return_value=httpx.Response(200, json=page, headers={"x-next-page": ""})
    )
    respx.get(RAW_URL).mock(return_value=httpx.Response(status, content=blob))


@pytest.mark.asyncio
@respx.mock
async def test_solus_project_toml_lands_as_one_solus_config_entity() -> None:
    _mock_with_solus()
    result = await GitLabConnector().sync(_ctx())
    by_key = {e.source_key: e for e in result.entities}
    config = by_key[".solus/project.toml"]
    assert config.type == "solus_config"
    assert config.domain == Domain.CODE
    assert config.properties["ext"] == {"fixture-bundle": {"max_notes": 3}}
    assert result.errors == []


@pytest.mark.asyncio
@respx.mock
async def test_solus_project_toml_faults_are_sync_errors() -> None:
    _mock_with_solus(b"[ext.broken\n")
    result = await GitLabConnector().sync(_ctx())
    assert {e.source_key for e in result.entities} >= {".solus/project.toml"}
    assert any("project.toml" in err.message for err in result.errors)

    respx.reset()
    _mock_with_solus(b"x" * 70_000)
    result = await GitLabConnector().sync(_ctx())
    assert any("exceeds" in err.message for err in result.errors)

    respx.reset()
    _mock_with_solus(status=500)
    result = await GitLabConnector().sync(_ctx())
    assert any(err.item == ".solus/project.toml" for err in result.errors)
