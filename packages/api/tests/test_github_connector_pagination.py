"""Link-header pagination for GitHub repo listing (SOLUSDEV-216, docs/api/github-orgs.md s5).

Covers both the OAuth `/user/repos` path (regression: it used to stop at 100 repos) and
the installation `/installation/repositories` path, including the same-host guard that
keeps the bearer token from following a `Link` header to another origin.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fixtures.github_sample import installation_metadata, many_repos, next_link
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.github import MAX_REPO_PAGES, GitHubConnector

API = "https://api.github.com"
OAUTH_CREDS = Credentials(token="ghu_test")
INSTALL_CREDS = Credentials(token="ghs_test", metadata=installation_metadata())

# (label, listing path, response body wrapper, credentials)
MODES = [
    pytest.param("/user/repos", False, OAUTH_CREDS, id="oauth"),
    pytest.param("/installation/repositories", True, INSTALL_CREDS, id="installation"),
]


def _body(repos: list[dict[str, object]], wrapped: bool) -> object:
    return {"total_count": len(repos), "repositories": repos} if wrapped else repos


def _paged_route(path: str, wrapped: bool, pages: list[list[dict[str, object]]]) -> respx.Route:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        headers = {}
        if page < len(pages):
            headers["Link"] = next_link(f"{API}{path}?per_page=100&page={page + 1}")
        return httpx.Response(200, json=_body(pages[page - 1], wrapped), headers=headers)

    return respx.get(url__regex=rf"{API}{path}(\?.*)?$").mock(side_effect=handler)


@pytest.mark.parametrize(("path", "wrapped", "creds"), MODES)
@pytest.mark.asyncio
@respx.mock
async def test_follows_next_links_across_pages(
    path: str, wrapped: bool, creds: Credentials
) -> None:
    pages = [many_repos(100, "a"), many_repos(100, "b"), many_repos(7, "c")]
    route = _paged_route(path, wrapped, pages)

    repos = await GitHubConnector().list_repositories(creds)

    assert len(repos) == 207
    assert route.call_count == 3
    assert repos[0]["full_name"] == "a/repo-000"
    assert repos[-1]["full_name"] == "c/repo-006"


@pytest.mark.parametrize(("path", "wrapped", "creds"), MODES)
@pytest.mark.asyncio
@respx.mock
async def test_stops_at_the_page_cap(path: str, wrapped: bool, creds: Credentials) -> None:
    endless = [many_repos(2, f"p{i}") for i in range(MAX_REPO_PAGES + 10)]
    route = _paged_route(path, wrapped, endless)

    repos = await GitHubConnector().list_repositories(creds)

    assert route.call_count == MAX_REPO_PAGES
    assert len(repos) == 2 * MAX_REPO_PAGES


def test_page_cap_is_bounded() -> None:
    assert 1 < MAX_REPO_PAGES <= 50


@pytest.mark.parametrize(("path", "wrapped", "creds"), MODES)
@pytest.mark.asyncio
@respx.mock
async def test_malformed_link_header_is_ignored(
    path: str, wrapped: bool, creds: Credentials
) -> None:
    route = respx.get(url__regex=rf"{API}{path}(\?.*)?$").mock(
        return_value=httpx.Response(
            200,
            json=_body(many_repos(3), wrapped),
            headers={"Link": "this is <not a link header; rel=next"},
        )
    )

    repos = await GitHubConnector().list_repositories(creds)

    assert len(repos) == 3
    assert route.call_count == 1


@pytest.mark.parametrize(("path", "wrapped", "creds"), MODES)
@pytest.mark.parametrize(
    "foreign",
    [
        "https://evil.example/user/repos?page=2",
        "http://api.github.com/user/repos?page=2",
        "https://api.github.com.evil.example/user/repos?page=2",
        "https://user:pw@api.github.com/user/repos?page=2",
    ],
)
@pytest.mark.asyncio
@respx.mock
async def test_foreign_next_url_is_refused_and_never_called(
    path: str, wrapped: bool, creds: Credentials, foreign: str
) -> None:
    respx.get(url__regex=rf"{API}{path}(\?.*)?$").mock(
        return_value=httpx.Response(
            200, json=_body(many_repos(2), wrapped), headers={"Link": next_link(foreign)}
        )
    )
    repos = await GitHubConnector().list_repositories(creds)

    assert [r["full_name"] for r in repos] == ["octo/repo-000", "octo/repo-001"]
    # Exactly one request went out: the token was never sent to the foreign URL.
    assert len(respx.calls) == 1
    assert str(respx.calls[0].request.url).startswith(API)


@pytest.mark.asyncio
@respx.mock
async def test_oauth_listing_is_not_capped_at_100_repos() -> None:
    """Regression: `/user/repos` previously returned only the first 100 repositories."""
    _paged_route("/user/repos", False, [many_repos(100, "a"), many_repos(30, "b")])
    repos = await GitHubConnector().list_repositories(OAUTH_CREDS)
    assert len(repos) == 130


@pytest.mark.asyncio
@respx.mock
async def test_non_list_page_still_raises_clean_error() -> None:
    respx.get(f"{API}/user/repos").mock(return_value=httpx.Response(200, json={"message": "x"}))
    with pytest.raises(ConnectorError) as exc:
        await GitHubConnector().list_repositories(OAUTH_CREDS)
    assert exc.value.code == "github_error"


@pytest.mark.asyncio
@respx.mock
async def test_error_on_a_later_page_surfaces() -> None:
    respx.get(url__regex=rf"{API}/user/repos\?per_page=100&page=2").mock(
        return_value=httpx.Response(500)
    )
    respx.get(url__regex=rf"{API}/user/repos(\?(?!.*page=2).*)?$").mock(
        return_value=httpx.Response(
            200,
            json=many_repos(1),
            headers={"Link": next_link(f"{API}/user/repos?per_page=100&page=2")},
        )
    )
    with pytest.raises(ConnectorError) as exc:
        await GitHubConnector().list_repositories(OAUTH_CREDS)
    assert exc.value.code == "github_error"
