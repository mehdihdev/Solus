"""The GitLab connector (SOLUSDEV-104) — the CON-01 mirror for GitLab.

Implements `OAuthConnector` on the connector runtime with the same code-entity
mapping and W0-08 committed-export surfacing as GitHub (shared in
`code_host.py`). GitLab differences handled here: nested namespaces
(`group/subgroup/project`), URL-encoded project paths in every API route, a
*paginated* recursive tree endpoint, refresh tokens on OAuth exchange, and an
instance `base_url` so self-hosted GitLab works with the same connector.

Security (CLAUDE.md §7): tree content is ingested, untrusted data — parsed
defensively, never interpreted as instructions. `repo`/`branch` are validated
before being placed in URLs (path-injection guard); the token is sent only in
the Authorization header and never logged.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Final
from urllib.parse import quote, urlencode

import httpx

from solus_api.connectors.code_host import (
    REPO_ROOT_KEY,
    file_entity,
    module_entity,
    parent_key,
    solus_config_blob,
    solus_config_entity,
)
from solus_api.connectors.contracts import (
    AccountInfo,
    ConnectorError,
    Credentials,
    Domain,
    EntityOut,
    OAuthConnector,
    RelationOut,
    SyncContext,
    SyncError,
    SyncResult,
)
from solus_api.widgets.solus_config import MAX_PROJECT_TOML_BYTES, SOLUS_CONFIG_PATH

DEFAULT_BASE_URL: Final = "https://gitlab.com"
REQUEST_TIMEOUT: Final = 30.0
TREE_PER_PAGE: Final = 100
# Pagination bound: 200 pages × 100 items = 20k tree objects. Beyond that the
# sync surfaces a truncation SyncError instead of walking forever.
MAX_TREE_PAGES: Final = 200

# Nested namespaces allowed: 2+ segments of [A-Za-z0-9_.-]. Validated before
# the value is URL-encoded into an API path (CLAUDE.md §7 untrusted input).
_REPO_RE: Final = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+$")
_BRANCH_FORBIDDEN: Final = frozenset(" \t\n\r~^:?*[\\")


def _safe_repo(repo: str) -> str:
    # The charclass admits dots, so dot-only segments ("."/"..") must be
    # rejected explicitly — they are path traversal, not project names.
    if not _REPO_RE.match(repo) or any(seg in (".", "..") for seg in repo.split("/")):
        raise ConnectorError(
            "invalid_repo", "repo must be a GitLab project path like 'group/project'"
        )
    return repo


def _safe_branch(branch: str) -> str:
    if (
        not branch
        or ".." in branch
        or branch.startswith("/")
        or branch.endswith("/")
        or any(ch in _BRANCH_FORBIDDEN for ch in branch)
    ):
        raise ConnectorError("invalid_branch", "branch name contains illegal characters")
    return branch


class GitLabConnector(OAuthConnector):
    """Connector for GitLab projects, gitlab.com or self-hosted (CLAUDE.md §2.1)."""

    provider: ClassVar[str] = "gitlab"
    scopes: ClassVar[tuple[str, ...]] = ("read_api", "read_user")
    config_fields: ClassVar[tuple[str, ...]] = ("repo", "branch")
    #: How the app lets a user choose what to track: exactly one repository.
    #: Read generically by the catalog — no provider id appears in the frontend.
    selection: ClassVar[dict[str, str]] = {
        "mode": "single",
        "config_key": "repo",
        "label": "repository",
    }
    # A GitLab PAT works against the same REST API (same Bearer header), so a
    # directly-supplied token is accepted (gated in connect_source).
    supports_token_connect: ClassVar[bool] = True

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._api = f"{self._base_url}/api/v4"

    # ----------------------------------------------------------------- OAuth

    def authorize_url(self, *, state: str, redirect_uri: str, access: str | None = None) -> str:
        if self._client_id is None:
            raise ConnectorError(
                "oauth_not_configured", "GitLab OAuth client_id is not configured."
            )
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(self.scopes),
                "state": state,
            }
        )
        return f"{self._base_url}/oauth/authorize?{query}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> Credentials:
        if self._client_id is None or self._client_secret is None:
            raise ConnectorError(
                "oauth_not_configured",
                "GitLab OAuth client_id/client_secret is not configured.",
            )
        payload = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        async with self._http() as client:
            response = await client.post(f"{self._base_url}/oauth/token", json=payload)
        body = self._json(response)
        token = body.get("access_token")
        if not token:
            message = body.get("error_description") or body.get("error") or "OAuth exchange failed."
            raise ConnectorError("oauth_exchange_failed", str(message))
        refresh = body.get("refresh_token")
        return Credentials(
            token=str(token),
            refresh_token=str(refresh) if refresh else None,
            metadata={"scope": body.get("scope"), "token_type": body.get("token_type")},
        )

    # ----------------------------------------------------- identity & picker

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        async with self._http(creds) as client:
            response = await client.get(f"{self._api}/user")
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise ConnectorError("invalid_credentials", "GitLab rejected the access token.")
        body = self._ok_json(response)
        if not isinstance(body, dict) or "id" not in body or "username" not in body:
            raise ConnectorError("gitlab_error", "Unexpected GitLab user response shape.")
        return AccountInfo(
            external_id=str(body["id"]),
            login=str(body["username"]),
            name=body.get("name"),
        )

    async def list_repositories(self, creds: Credentials) -> list[dict[str, Any]]:
        async with self._http(creds) as client:
            response = await client.get(
                f"{self._api}/projects",
                params={
                    "membership": True,
                    "per_page": 100,
                    "order_by": "last_activity_at",
                    "simple": True,
                },
            )
        body = self._ok_json(response)
        if not isinstance(body, list):
            raise ConnectorError("gitlab_error", "Unexpected response shape for /projects.")
        return [
            {
                "full_name": project.get("path_with_namespace"),
                "default_branch": project.get("default_branch"),
                "private": project.get("visibility") != "public",
            }
            for project in body
            if isinstance(project, dict)
        ]

    async def list_selectable(self, creds: Credentials) -> list[dict[str, Any]]:
        """The generic picker capability: repositories, in the shape every
        connector's selectable items use. `config` is the exact source config
        this choice writes, so the caller never has to know what a repo means."""
        return [
            {
                "id": repo["full_name"],
                "name": repo["full_name"],
                "subtitle": "private" if repo.get("private") else "public",
                "config": {"repo": repo["full_name"], "branch": repo.get("default_branch")},
            }
            for repo in await self.list_repositories(creds)
            if repo.get("full_name")
        ]

    # --------------------------------------------------------------- syncing

    async def sync(self, ctx: SyncContext) -> SyncResult:
        repo = _safe_repo(str(ctx.config["repo"]))
        configured = ctx.config.get("branch")
        async with self._http(ctx.credentials) as client:
            branch = (
                _safe_branch(str(configured))
                if configured
                else await self._default_branch(client, repo)
            )
            sha = await self._head_sha(client, repo, branch)
            tree, truncated = await self._tree(client, repo, sha)
            solus_text, solus_errors = await self._solus_config_text(client, repo, sha, tree)

        entities, relations, errors = self._build_graph(repo, branch, sha, tree, solus_text)
        errors = [*solus_errors, *errors]
        if truncated:
            errors.append(
                SyncError(
                    item=repo,
                    message=(
                        "Repository tree exceeded the pagination bound; "
                        "some files were not indexed."
                    ),
                )
            )
        return SyncResult(
            entities=entities,
            relations=relations,
            cursor={"branch": branch, "sha": sha},
            errors=errors,
        )

    async def detect_changes(self, ctx: SyncContext) -> bool:
        repo = _safe_repo(str(ctx.config["repo"]))
        configured = ctx.config.get("branch")
        async with self._http(ctx.credentials) as client:
            resolved = (
                _safe_branch(str(configured))
                if configured
                else await self._default_branch(client, repo)
            )
            sha = await self._head_sha(client, repo, resolved)

        return sha != ctx.cursor.get("sha")

    # -------------------------------------------------------- graph building

    async def _solus_config_text(
        self, client: httpx.AsyncClient, repo: str, sha: str, tree: list[dict[str, Any]]
    ) -> tuple[str | None, list[SyncError]]:
        """SOLUSDEV-246: the one blob the connector reads — `.solus/project.toml`.
        GitLab's tree carries no size, so the raw read is bounded by bytes
        received; a fault is a SyncError on that path, never a failed sync."""
        if solus_config_blob(tree) is None:
            return None, []
        url = f"{self._project_url(repo)}/repository/files/{quote(SOLUS_CONFIG_PATH, safe='')}/raw"
        try:
            async with client.stream("GET", url, params={"ref": sha}) as response:
                return await self._read_bounded_text(response), []
        except (ConnectorError, ValueError) as exc:
            return None, [SyncError(item=SOLUS_CONFIG_PATH, message=str(exc))]

    @staticmethod
    async def _read_bounded_text(response: httpx.Response) -> str:
        """The raw-file body, bounded AS IT STREAMS (the Onshape `_read_export`
        pattern): the declared length is checked first, then the running total,
        so an oversized committed file is never held in memory (CLAUDE.md §7)."""
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise ConnectorError("gitlab_error", f"GitLab request failed ({response.status_code}).")
        too_large = ConnectorError("too_large", f"{SOLUS_CONFIG_PATH}: exceeds size cap")
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_PROJECT_TOML_BYTES:
            raise too_large
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_PROJECT_TOML_BYTES:
                raise too_large
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8")

    def _build_graph(
        self,
        repo: str,
        branch: str,
        sha: str,
        tree: list[dict[str, Any]],
        solus_text: str | None = None,
    ) -> tuple[list[EntityOut], list[RelationOut], list[SyncError]]:
        errors: list[SyncError] = []
        entities_by_key: dict[str, EntityOut] = {
            REPO_ROOT_KEY: EntityOut(
                source_key=REPO_ROOT_KEY,
                type="code_repo",
                domain=Domain.CODE,
                name=repo,
                properties={"branch": branch, "commit": sha},
            )
        }
        for item in tree:
            self._land_item(item, entities_by_key, errors)
        if solus_text is not None:
            config, problems = solus_config_entity(solus_text)
            errors.extend(SyncError(item=SOLUS_CONFIG_PATH, message=p) for p in problems)
            if config is not None:
                entities_by_key[SOLUS_CONFIG_PATH] = config

        known_dirs = {key for key, ent in entities_by_key.items() if ent.type == "code_module"}
        relations = [
            RelationOut(from_key=parent_key(key, known_dirs), to_key=key, type="contains")
            for key in entities_by_key
            if key != REPO_ROOT_KEY
        ]
        return list(entities_by_key.values()), relations, errors

    def _land_item(
        self,
        item: dict[str, Any],
        entities: dict[str, EntityOut],
        errors: list[SyncError],
    ) -> None:
        """Land one tree item plus any missing ancestor directories. Defensive:
        a malformed item becomes a SyncError, not a crash (CLAUDE.md §7)."""
        try:
            path = str(item["path"])
            item_type = str(item["type"])
            if not path:
                raise KeyError("path")
            self._ensure_ancestors(path, entities)
            if item_type == "tree":
                entities[path] = module_entity(path)
            elif item_type == "blob":
                # GitLab's tree listing has no size; sha lives in "id".
                entities[path] = file_entity(path, {"sha": item.get("id")})
            # Other object types (e.g. "commit" submodule refs) are skipped.
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(SyncError(item=str(item.get("path", "<unknown>")), message=str(exc)))

    @staticmethod
    def _ensure_ancestors(path: str, entities: dict[str, EntityOut]) -> None:
        """Synthesise code_module entities for ancestor dirs GitLab elided."""
        segments = path.split("/")[:-1]
        accumulated = ""
        for segment in segments:
            accumulated = f"{accumulated}/{segment}" if accumulated else segment
            entities.setdefault(accumulated, module_entity(accumulated))

    # ------------------------------------------------------- GitLab requests

    def _project_url(self, repo: str) -> str:
        return f"{self._api}/projects/{quote(repo, safe='')}"

    async def _default_branch(self, client: httpx.AsyncClient, repo: str) -> str:
        response = await client.get(self._project_url(repo))
        body = self._repo_json(response)
        return str(body["default_branch"])

    async def _head_sha(self, client: httpx.AsyncClient, repo: str, branch: str) -> str:
        ref = quote(branch, safe="")
        response = await client.get(f"{self._project_url(repo)}/repository/commits/{ref}")
        body = self._repo_json(response)
        return str(body["id"])

    async def _tree(
        self, client: httpx.AsyncClient, repo: str, sha: str
    ) -> tuple[list[dict[str, Any]], bool]:
        """Walk the paginated recursive tree. Returns (items, truncated).

        Bounded by an iteration counter, not the server-supplied page number —
        a malicious/buggy server repeating the same x-next-page must terminate
        (§7: pagination headers are untrusted input)."""
        items: list[dict[str, Any]] = []
        page = 1
        for _ in range(MAX_TREE_PAGES):
            response = await client.get(
                f"{self._project_url(repo)}/repository/tree",
                params={
                    "recursive": True,
                    "ref": sha,
                    "per_page": TREE_PER_PAGE,
                    "page": page,
                },
            )
            if response.status_code == httpx.codes.NOT_FOUND:
                raise ConnectorError("repo_not_found", "Repository, branch, or ref not found.")
            if response.status_code >= httpx.codes.BAD_REQUEST:
                raise ConnectorError(
                    "gitlab_error", f"GitLab request failed ({response.status_code})."
                )
            body = response.json()
            if not isinstance(body, list):
                raise ConnectorError("gitlab_error", "Unexpected GitLab tree response shape.")
            items.extend(entry for entry in body if isinstance(entry, dict))
            next_page = response.headers.get("x-next-page", "")
            if not next_page.strip().isdigit():
                return items, False
            page = int(next_page)
        return items, True  # iteration bound hit — partial walk

    # ---------------------------------------------------------------- helpers

    def _http(self, creds: Credentials | None = None) -> httpx.AsyncClient:
        headers = {"Accept": "application/json"}
        if creds is not None:
            headers["Authorization"] = f"Bearer {creds.token}"
        return httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=headers)

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ConnectorError("gitlab_error", "GitLab returned a non-JSON body.") from exc
        return data if isinstance(data, dict) else {}

    @classmethod
    def _ok_json(cls, response: httpx.Response) -> Any:
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise ConnectorError("gitlab_error", f"GitLab request failed ({response.status_code}).")
        return response.json()

    @staticmethod
    def _repo_json(response: httpx.Response) -> dict[str, Any]:
        if response.status_code == httpx.codes.NOT_FOUND:
            raise ConnectorError("repo_not_found", "Repository, branch, or commit not found.")
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise ConnectorError("gitlab_error", f"GitLab request failed ({response.status_code}).")
        data = response.json()
        if not isinstance(data, dict):
            raise ConnectorError("gitlab_error", "Unexpected GitLab response shape.")
        return data
