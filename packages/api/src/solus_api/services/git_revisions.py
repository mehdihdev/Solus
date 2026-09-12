"""Bounded branch discovery through the attached repository's configured client."""

from typing import Any
from urllib.parse import quote

from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.github import GITHUB_API, GitHubConnector
from solus_api.connectors.github import _safe_repo as github_repo
from solus_api.connectors.gitlab import GitLabConnector, _safe_branch
from solus_api.connectors.gitlab import _safe_repo as gitlab_repo

GitConnector = GitHubConnector | GitLabConnector


def validate_branch(branch: str) -> str:
    _safe_branch(branch)
    if (
        len(branch) > 255
        or branch.startswith("-")
        or "@{" in branch
        or branch.endswith((".lock", "."))
        or any(ord(c) < 32 or ord(c) == 127 for c in branch)
    ):
        raise ConnectorError("invalid_branch", "Invalid branch name")
    return branch


def _base(connector: GitConnector, repo: str) -> str:
    if isinstance(connector, GitHubConnector):
        return f"{GITHUB_API}/repos/{github_repo(repo)}"
    return f"{connector._api}/projects/{quote(gitlab_repo(repo), safe='')}/repository"


def _commit(value: Any) -> str:
    import re

    if not isinstance(value, str) or not re.fullmatch(
        r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", value
    ):
        raise ConnectorError("invalid_revision", "Provider returned an invalid commit")
    return value.lower()


async def list_branches(
    connector: GitConnector, credentials: Credentials, repo: str, *, page: int
) -> dict[str, Any]:
    if not 1 <= page <= 1000:
        raise ConnectorError("invalid_page", "Branch page is out of bounds")
    async with connector._http(credentials) as client:
        response = await client.get(
            f"{_base(connector, repo)}/branches", params={"page": page, "per_page": 100}
        )
    GitHubConnector._raise_for_error(response)
    try:
        rows = response.json()
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError
        items = [
            {
                "name": validate_branch(row["name"]),
                "commit": _commit(row["commit"].get("sha", row["commit"].get("id"))),
            }
            for row in rows
        ]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ConnectorError("invalid_revision", "Provider returned invalid branches") from exc
    return {
        "supported": True,
        "kind": "git_branch",
        "items": items,
        "next_page": page + 1 if len(items) == 100 and page < 1000 else None,
    }


async def resolve_branch(
    connector: GitConnector, credentials: Credentials, repo: str, branch: str
) -> str:
    ref = quote(validate_branch(branch), safe="")
    async with connector._http(credentials) as client:
        response = await client.get(f"{_base(connector, repo)}/commits/{ref}")
    GitHubConnector._raise_for_error(response)
    try:
        body = response.json()
        return _commit(body.get("sha", body.get("id")))
    except (ValueError, AttributeError) as exc:
        raise ConnectorError("invalid_revision", "Provider returned an invalid commit") from exc
