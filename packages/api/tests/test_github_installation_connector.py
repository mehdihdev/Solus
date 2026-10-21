"""GitHubConnector in installation (GitHub App) mode (SOLUSDEV-216, ADR-039).

Installation credentials carry `metadata.kind == "github_app_installation"`. The connector
must then never touch `/user` (an installation token has no user), must list through
`/installation/repositories`, and must honour the installation's own API base (GHES-ready).
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fixtures.github_sample import (
    COMMIT_BODY,
    DEFAULT_BRANCH,
    HEAD_SHA,
    INJECTION_TEXT,
    INJECTION_TREE_BODY,
    INSTALLATION_ID,
    INSTALLATION_TOKEN,
    ORG_LOGIN,
    REPO_BODY,
    REPO_FULL_NAME,
    TREE_BODY,
    installation_metadata,
    repo_record,
)
from solus_api.connectors import assert_connector_contract
from solus_api.connectors.contracts import ConnectorError, Credentials, SyncContext
from solus_api.connectors.github import GitHubConnector

API = "https://api.github.com"
GHES = "https://ghe.example.com/api/v3"


def _creds(api_base: str = API) -> Credentials:
    return Credentials(token=INSTALLATION_TOKEN, metadata=installation_metadata(api_base))


def _ctx(api_base: str = API, cursor: dict[str, str] | None = None) -> SyncContext:
    return SyncContext(
        credentials=_creds(api_base),
        config={"repo": REPO_FULL_NAME, "branch": DEFAULT_BRANCH},
        cursor=cursor or {},
    )


def _mock_repo_endpoints(base: str, tree: dict[str, object] = TREE_BODY) -> None:
    respx.get(f"{base}/repos/{REPO_FULL_NAME}").mock(
        return_value=httpx.Response(200, json=REPO_BODY)
    )
    respx.get(f"{base}/repos/{REPO_FULL_NAME}/commits/{DEFAULT_BRANCH}").mock(
        return_value=httpx.Response(200, json=COMMIT_BODY)
    )
    respx.get(f"{base}/repos/{REPO_FULL_NAME}/git/trees/{HEAD_SHA}").mock(
        return_value=httpx.Response(200, json=tree)
    )


def _mock_installation_repos(base: str = API) -> respx.Route:
    return respx.get(url__regex=rf"{base}/installation/repositories(\?.*)?$").mock(
        return_value=httpx.Response(
            200,
            json={
                "total_count": 2,
                "repositories": [repo_record(REPO_FULL_NAME), repo_record("octo/other", "dev")],
            },
        )
    )


@pytest.mark.asyncio
@respx.mock
async def test_passes_connector_contract_with_installation_credentials() -> None:
    _mock_installation_repos()
    _mock_repo_endpoints(API)

    result = await assert_connector_contract(GitHubConnector(), _ctx())

    assert result.cursor == {"branch": DEFAULT_BRANCH, "sha": HEAD_SHA}
    assert all("/user" not in str(c.request.url.path).replace("/users", "") for c in respx.calls)
    assert {c.request.headers["authorization"] for c in respx.calls} == {
        f"Bearer {INSTALLATION_TOKEN}"
    }


@pytest.mark.asyncio
@respx.mock
async def test_validate_credentials_uses_installation_listing_never_user() -> None:
    user = respx.get(f"{API}/user").mock(return_value=httpx.Response(200, json={}))
    listing = _mock_installation_repos()

    account = await GitHubConnector().validate_credentials(_creds())

    assert account.external_id == f"installation:{INSTALLATION_ID}"
    assert account.login == ORG_LOGIN
    assert listing.call_count == 1
    assert user.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_validate_credentials_rejects_a_dead_installation_token() -> None:
    respx.get(url__regex=rf"{API}/installation/repositories(\?.*)?$").mock(
        return_value=httpx.Response(401)
    )
    with pytest.raises(ConnectorError) as exc:
        await GitHubConnector().validate_credentials(_creds())
    assert exc.value.code == "invalid_credentials"


@pytest.mark.asyncio
@respx.mock
async def test_list_repositories_uses_installation_endpoint_never_user() -> None:
    user_repos = respx.get(url__regex=rf"{API}/user/repos.*").mock(
        return_value=httpx.Response(200, json=[])
    )
    listing = _mock_installation_repos()

    repos = await GitHubConnector().list_repositories(_creds())

    assert [r["full_name"] for r in repos] == [REPO_FULL_NAME, "octo/other"]
    assert repos[1] == {"full_name": "octo/other", "default_branch": "dev", "private": True}
    assert listing.call_count == 1
    assert user_repos.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_list_selectable_in_installation_mode_has_picker_shape() -> None:
    _mock_installation_repos()
    items = await GitHubConnector().list_selectable(_creds())
    assert items[0] == {
        "id": REPO_FULL_NAME,
        "name": REPO_FULL_NAME,
        "subtitle": "private",
        "config": {"repo": REPO_FULL_NAME, "branch": DEFAULT_BRANCH},
    }


@pytest.mark.asyncio
@respx.mock
async def test_installation_listing_rejects_unwrapped_body() -> None:
    respx.get(url__regex=rf"{API}/installation/repositories(\?.*)?$").mock(
        return_value=httpx.Response(200, json=[{"full_name": "x/y"}])
    )
    with pytest.raises(ConnectorError) as exc:
        await GitHubConnector().list_repositories(_creds())
    assert exc.value.code == "github_error"


@pytest.mark.asyncio
@respx.mock
async def test_sync_and_detect_changes_use_the_installation_api_base() -> None:
    """GHES-ready: the base comes from the installation record, not api.github.com."""
    _mock_repo_endpoints(GHES)

    result = await GitHubConnector().sync(_ctx(GHES))
    changed = await GitHubConnector().detect_changes(_ctx(GHES, {"sha": "old"}))

    assert result.cursor["sha"] == HEAD_SHA
    assert changed is True
    hosts = {c.request.url.host for c in respx.calls}
    assert hosts == {"ghe.example.com"}


@pytest.mark.asyncio
@respx.mock
async def test_default_base_is_api_github_com_without_metadata() -> None:
    _mock_repo_endpoints(API)
    ctx = SyncContext(
        credentials=Credentials(token="ghu_x"),
        config={"repo": REPO_FULL_NAME, "branch": DEFAULT_BRANCH},
    )
    await GitHubConnector().sync(ctx)
    assert {c.request.url.host for c in respx.calls} == {"api.github.com"}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_base", ["http://insecure.example/api", "ftp://x/y", "", "not a url"])
async def test_non_https_installation_base_is_refused(bad_base: str) -> None:
    """A tampered base must never get the token sent in clear or to a non-HTTP scheme."""
    creds = Credentials(token=INSTALLATION_TOKEN, metadata=installation_metadata(bad_base))
    with pytest.raises(ConnectorError) as exc:
        await GitHubConnector().list_repositories(creds)
    assert exc.value.code == "invalid_api_base"


@pytest.mark.asyncio
@respx.mock
async def test_unknown_kind_metadata_is_treated_as_plain_oauth() -> None:
    user = respx.get(f"{API}/user").mock(
        return_value=httpx.Response(200, json={"id": 1, "login": "octo"})
    )
    creds = Credentials(token="ghu_x", metadata={"kind": "something_else", "api_base": GHES})
    account = await GitHubConnector().validate_credentials(creds)
    assert account.external_id == "1"
    assert user.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_injection_in_file_names_lands_as_inert_data() -> None:
    """CLAUDE.md s7: ingested names are data. An instruction in a path becomes an entity
    name and a property, nothing more: no extra entity types, no behaviour change."""
    _mock_installation_repos()
    _mock_repo_endpoints(API, INJECTION_TREE_BODY)

    result = await assert_connector_contract(GitHubConnector(), _ctx())

    poisoned = [e for e in result.entities if INJECTION_TEXT in e.source_key]
    assert len(poisoned) == 1
    assert poisoned[0].type == "code_file"
    assert poisoned[0].name == f"{INJECTION_TEXT}.md"
    # No request left the API host and none carried the injected text.
    assert {c.request.url.host for c in respx.calls} == {"api.github.com"}
    assert all("evil.example" not in str(c.request.url) for c in respx.calls)
    assert {e.type for e in result.entities} <= {"code_repo", "code_module", "code_file"}
