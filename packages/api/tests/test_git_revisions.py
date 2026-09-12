"""Personal branch discovery uses configured clients and bounded provider pages."""

import httpx
import pytest
import respx
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.github import GitHubConnector
from solus_api.connectors.gitlab import GitLabConnector
from solus_api.services.git_revisions import list_branches, resolve_branch


@respx.mock
async def test_github_branch_page_is_bounded() -> None:
    route = respx.get(
        "https://api.github.com/repos/acme/robot/branches", params={"page": 2, "per_page": 100}
    ).mock(
        return_value=httpx.Response(
            200, json=[{"name": f"b{i}", "commit": {"sha": "a" * 40}} for i in range(100)]
        )
    )
    result = await list_branches(
        GitHubConnector(), Credentials(token="fixture"), "acme/robot", page=2
    )
    assert result["next_page"] == 3
    assert len(result["items"]) == 100
    assert route.call_count == 1


@respx.mock
async def test_gitlab_uses_configured_instance_and_encoded_repository() -> None:
    route = respx.get(
        "https://git.example/api/v4/projects/acme%2Frobot/repository/branches",
        params={"page": 1, "per_page": 100},
    ).mock(
        return_value=httpx.Response(200, json=[{"name": "feature/x", "commit": {"id": "b" * 40}}])
    )
    result = await list_branches(
        GitLabConnector(base_url="https://git.example"),
        Credentials(token="fixture"),
        "acme/robot",
        page=1,
    )
    assert result["items"] == [{"name": "feature/x", "commit": "b" * 40}]
    assert result["next_page"] is None
    assert route.call_count == 1


@respx.mock
async def test_branch_resolves_to_immutable_commit() -> None:
    respx.get("https://api.github.com/repos/acme/robot/commits/feature%2Fx").mock(
        return_value=httpx.Response(200, json={"sha": "c" * 40})
    )
    assert (
        await resolve_branch(
            GitHubConnector(), Credentials(token="fixture"), "acme/robot", "feature/x"
        )
        == "c" * 40
    )


@pytest.mark.parametrize("branch", ["", "../main", "main\n", "-option", "a.lock", "a@{b}"])
async def test_unsafe_branch_ref_is_rejected(branch: str) -> None:
    with pytest.raises(ConnectorError):
        await resolve_branch(GitHubConnector(), Credentials(token="fixture"), "acme/robot", branch)


@respx.mock
async def test_invalid_commit_width_is_refused() -> None:
    respx.get("https://api.github.com/repos/acme/robot/commits/main").mock(
        return_value=httpx.Response(200, json={"sha": "a" * 41})
    )
    with pytest.raises(ConnectorError):
        await resolve_branch(GitHubConnector(), Credentials(token="fixture"), "acme/robot", "main")
