"""Sample GitLab API payloads for the GitLab connector tests (SOLUSDEV-104).

Mirrors fixtures/github_sample.py for GitLab's v4 API shapes: a nested-namespace
project whose tree carries ordinary source plus one committed design export of
each W0-08 kind. Tokens here are obvious fakes assembled at import time so the
secret scanner has nothing to match.
"""

from typing import Any

REPO_PATH = "strider-robotics/firmware/strider-fw"  # nested namespace
DEFAULT_BRANCH = "main"
HEAD_SHA = "c0ffee42deadbeef"

# Assembled, clearly-fake token values (never real credentials).
FAKE_EXCHANGED_TOKEN = "glo-" + "test-" + "exchanged-token"
FAKE_REFRESH_TOKEN = "glr-" + "test-" + "refresh"

USER_BODY: dict[str, Any] = {"id": 7, "username": "strider-bot", "name": "Strider Bot"}

PROJECT_BODY: dict[str, Any] = {
    "id": 4242,
    "path_with_namespace": REPO_PATH,
    "default_branch": DEFAULT_BRANCH,
    "visibility": "private",
}

PROJECTS_BODY: list[dict[str, Any]] = [
    PROJECT_BODY,
    {
        "id": 4243,
        "path_with_namespace": "strider-robotics/tools",
        "default_branch": "main",
        "visibility": "public",
    },
]

COMMIT_BODY: dict[str, Any] = {"id": HEAD_SHA, "short_id": HEAD_SHA[:8]}

TOKEN_BODY: dict[str, Any] = {
    "access_token": FAKE_EXCHANGED_TOKEN,
    "refresh_token": FAKE_REFRESH_TOKEN,
    "token_type": "Bearer",
    "scope": "read_api read_user",
}

TOKEN_ERROR_BODY: dict[str, Any] = {
    "error": "invalid_grant",
    "error_description": "The provided authorization grant is invalid.",
}


def _item(path: str, item_type: str) -> dict[str, Any]:
    return {"id": f"sha-{path}", "name": path.rsplit("/", 1)[-1], "type": item_type, "path": path}


# Page 1 of the recursive tree (GitLab paginates; header x-next-page -> "2").
TREE_PAGE_1: list[dict[str, Any]] = [
    _item("src", "tree"),
    _item("src/main.py", "blob"),
    _item("src/drivers", "tree"),
    _item("src/drivers/imu.py", "blob"),
    _item("README.md", "blob"),
]

# Page 2 — design exports across domains (hardware/ dir deliberately elided to
# exercise ancestor synthesis) + an unknown object type to skip.
TREE_PAGE_2: list[dict[str, Any]] = [
    _item("hardware/board.gbr", "blob"),
    _item("mech/chassis.step", "blob"),
    _item("mech", "tree"),
    _item("elec/power.net", "blob"),
    _item("elec/filter.cir", "blob"),
    _item("vendor-module", "commit"),  # submodule ref — skipped
]
