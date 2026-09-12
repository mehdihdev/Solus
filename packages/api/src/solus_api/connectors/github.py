"""The GitHub connector (SOLUSDEV-103) — turns a repo's git tree into graph data.

Implements `OAuthConnector` (CLAUDE.md §9 contract): OAuth authorize/exchange,
credential validation, repo listing for the picker, a full `sync` that walks one
branch's tree, and a cheap `detect_changes` probe.

W0-08 — committed design exports: a repo often carries fabrication/CAD outputs
checked in next to firmware (Gerbers, STEP models, netlists, SPICE decks). The
connector recognises these by extension and lands them as cross-domain
`design_export` entities (electrical/mechanical) so the rest of Solus can reason
across the code boundary.

Security (CLAUDE.md §7): every byte of the tree is *ingested, untrusted data*.
It is parsed defensively (a bad item becomes a `SyncError`, never a crash) and
never interpreted as an instruction. The access token is sent only in the
Authorization header and is never logged.
"""

from __future__ import annotations

import base64
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
    solus_config_too_large,
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
from solus_api.widgets.solus_config import SOLUS_CONFIG_PATH

GITHUB_API: Final = "https://api.github.com"
GITHUB_OAUTH: Final = "https://github.com/login/oauth"

#: Cursor key holding the last commit-endpoint ETag (SOLUSDEV-167). GitHub
#: documents that a conditional request answered 304 does NOT count against the
#: rate limit, so this makes the common "nothing changed" probe free. Durable in
#: the cursor rather than a cache; losing it just means the next probe re-earns
#: one.
ETAG_KEY: Final = "commit_etag"
REQUEST_TIMEOUT: Final = 30.0


# `repo` and `branch` are user-controlled and interpolated into GitHub API URL
# paths — validate them at the boundary so a crafted value can't reshape the
# request (path traversal / endpoint injection). CLAUDE.md §7 (untrusted input).
_REPO_RE: Final = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_FORBIDDEN: Final = frozenset(" \t\n\r~^:?*[\\")


def _safe_repo(repo: str) -> str:
    # The charclass admits dots, so dot-only segments ("."/"..") must be
    # rejected explicitly — they are path traversal, not repo names.
    if not _REPO_RE.match(repo) or any(seg in (".", "..") for seg in repo.split("/")):
        raise ConnectorError("invalid_repo", "repo must be in 'owner/name' form")
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


class GitHubConnector(OAuthConnector):
    """Connector for GitHub repositories (CLAUDE.md §2.1)."""

    provider: ClassVar[str] = "github"
    scopes: ClassVar[tuple[str, ...]] = ("repo", "read:user")
    config_fields: ClassVar[tuple[str, ...]] = ("repo", "branch")
    #: How the app lets a user choose what to track: exactly one repository.
    #: Read generically by the catalog — no provider id appears in the frontend.
    selection: ClassVar[dict[str, str]] = {
        "mode": "single",
        "config_key": "repo",
        "label": "repository",
    }
    # A GitHub PAT works against the same REST API, so a directly-supplied token
    # is an accepted alternative to the OAuth flow (gated in connect_source).
    supports_token_connect: ClassVar[bool] = True

    def __init__(self, client_id: str | None = None, client_secret: str | None = None) -> None:
        self._client_id = client_id
        self._client_secret = client_secret

    # ----------------------------------------------------------------- OAuth

    def authorize_url(self, *, state: str, redirect_uri: str, access: str | None = None) -> str:
        if self._client_id is None:
            raise ConnectorError(
                "oauth_not_configured",
                "GitHub OAuth client_id is not configured.",
            )
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(self.scopes),
                "state": state,
            }
        )
        return f"{GITHUB_OAUTH}/authorize?{query}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> Credentials:
        if self._client_id is None or self._client_secret is None:
            raise ConnectorError(
                "oauth_not_configured",
                "GitHub OAuth client_id/client_secret is not configured.",
            )
        payload = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        async with self._http() as client:
            response = await client.post(
                f"{GITHUB_OAUTH}/access_token",
                json=payload,
                headers={"Accept": "application/json"},
            )
        body = self._json(response)
        token = body.get("access_token")
        if not token:
            message = body.get("error_description") or body.get("error") or "OAuth exchange failed."
            raise ConnectorError("oauth_exchange_failed", str(message))
        return Credentials(
            token=str(token),
            metadata={
                "scope": body.get("scope"),
                "token_type": body.get("token_type"),
            },
        )

    # ----------------------------------------------------- identity & picker

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        async with self._http(creds) as client:
            response = await client.get(f"{GITHUB_API}/user")
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise ConnectorError("invalid_credentials", "GitHub rejected the access token.")
        body = self._ok_json(response)
        if not isinstance(body, dict) or "id" not in body or "login" not in body:
            raise ConnectorError("github_error", "Unexpected GitHub user response shape.")
        return AccountInfo(
            external_id=str(body["id"]),
            login=str(body["login"]),
            name=body.get("name"),
        )

    async def list_repositories(self, creds: Credentials) -> list[dict[str, Any]]:
        async with self._http(creds) as client:
            response = await client.get(
                f"{GITHUB_API}/user/repos",
                params={"per_page": 100, "sort": "updated"},
            )
        body = self._ok_json(response)
        if not isinstance(body, list):
            raise ConnectorError("github_error", "Unexpected response shape for /user/repos.")
        return [
            {
                "full_name": repo.get("full_name"),
                "default_branch": repo.get("default_branch"),
                "private": repo.get("private"),
            }
            for repo in body
            if isinstance(repo, dict)
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
            sha, etag = await self._head_sha_and_etag(client, repo, branch)
            tree, truncated = await self._tree(client, repo, sha)
            solus_text, solus_errors = await self._solus_config_text(client, repo, tree)

        entities, relations, errors = self._build_graph(repo, branch, sha, tree, solus_text)
        errors = [*solus_errors, *errors]
        if truncated:
            # GitHub caps the recursive tree (~100k objects) and returns a partial
            # list — surface it so a partial graph isn't mistaken for complete.
            errors.append(
                SyncError(
                    item=repo,
                    message="GitHub truncated the repository tree; some files were not indexed.",
                )
            )
        return SyncResult(
            entities=entities,
            relations=relations,
            # The ETag key is present only when GitHub actually gave us one —
            # a null placeholder would be noise in a cursor other code compares.
            cursor=(
                {"branch": branch, "sha": sha, ETAG_KEY: etag}
                if etag
                else {"branch": branch, "sha": sha}
            ),
            errors=errors,
        )

    async def detect_changes(self, ctx: SyncContext) -> bool:
        """Cheap probe, and against GitHub it can be FREE.

        GitHub documents that a conditional request answered `304 Not Modified`
        does not count against the rate limit. So when a previous probe left us
        an ETag we send `If-None-Match`, and the overwhelmingly common answer —
        nothing changed — costs nothing at all. Zero conditional requests existed
        anywhere in this repo before SOLUSDEV-167; the only headers ever built
        were Accept and Authorization.

        The validator rides `ctx.cursor` beside the sha, so it is durable and
        needs no cache. Losing it is harmless: the next probe is simply a normal
        (counted) request that re-earns one.
        """
        repo = _safe_repo(str(ctx.config["repo"]))
        configured = ctx.config.get("branch")
        async with self._http(ctx.credentials) as client:
            resolved = (
                _safe_branch(str(configured))
                if configured
                else await self._default_branch(client, repo)
            )
            etag = ctx.cursor.get(ETAG_KEY)
            if isinstance(etag, str) and etag and ctx.cursor.get("branch") == resolved:
                unchanged = await self._head_unmodified(client, repo, resolved, etag)
                if unchanged:
                    return False
            sha = await self._head_sha(client, repo, resolved)

        return sha != ctx.cursor.get("sha")

    async def _head_unmodified(
        self, client: httpx.AsyncClient, repo: str, branch: str, etag: str
    ) -> bool:
        """True when GitHub answers 304 — a free "nothing changed"."""
        ref = quote(branch, safe="")
        response = await client.get(
            f"{GITHUB_API}/repos/{repo}/commits/{ref}", headers={"If-None-Match": etag}
        )
        self._raise_for_error(response)
        return response.status_code == 304

    # -------------------------------------------------------- graph building

    async def _solus_config_text(
        self, client: httpx.AsyncClient, repo: str, tree: list[dict[str, Any]]
    ) -> tuple[str | None, list[SyncError]]:
        """SOLUSDEV-246: the one blob the connector reads — `.solus/project.toml`,
        only when the tree lists it and its declared size is within the cap. A
        fetch failure is a SyncError on that path, never a failed sync."""
        item = solus_config_blob(tree)
        if item is None:
            return None, []
        if solus_config_too_large(item):
            return None, [
                SyncError(item=SOLUS_CONFIG_PATH, message=f"{SOLUS_CONFIG_PATH}: exceeds size cap")
            ]
        try:
            blob_sha = quote(str(item["sha"]), safe="")
            response = await client.get(f"{GITHUB_API}/repos/{repo}/git/blobs/{blob_sha}")
            body = self._repo_json(response)
            raw = base64.b64decode(str(body.get("content", "")), validate=False)
            return raw.decode("utf-8"), []
        except (ConnectorError, ValueError, KeyError) as exc:
            return None, [SyncError(item=SOLUS_CONFIG_PATH, message=str(exc))]

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
            RelationOut(
                from_key=parent_key(key, known_dirs),
                to_key=key,
                type="contains",
            )
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
        a malformed item is recorded as a SyncError, not raised (CLAUDE.md §7)."""
        try:
            path = str(item["path"])
            item_type = str(item["type"])
            if not path:
                raise KeyError("path")
            self._ensure_ancestors(path, entities)
            if item_type == "tree":
                entities[path] = module_entity(path)
            elif item_type == "blob":
                entities[path] = file_entity(path, item)
            # Unknown object types (e.g. "commit" submodule refs) are skipped.
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(SyncError(item=str(item.get("path", "<unknown>")), message=str(exc)))

    @staticmethod
    def _ensure_ancestors(path: str, entities: dict[str, EntityOut]) -> None:
        """Synthesise code_module entities for any ancestor dirs GitHub elided."""
        segments = path.split("/")[:-1]
        accumulated = ""
        for segment in segments:
            accumulated = f"{accumulated}/{segment}" if accumulated else segment
            entities.setdefault(accumulated, module_entity(accumulated))

    # ------------------------------------------------------- GitHub requests

    async def _default_branch(self, client: httpx.AsyncClient, repo: str) -> str:
        response = await client.get(f"{GITHUB_API}/repos/{repo}")
        body = self._repo_json(response)
        return str(body["default_branch"])

    async def _head_sha(self, client: httpx.AsyncClient, repo: str, branch: str) -> str:
        sha, _etag = await self._head_sha_and_etag(client, repo, branch)
        return sha

    async def _head_sha_and_etag(
        self, client: httpx.AsyncClient, repo: str, branch: str
    ) -> tuple[str, str | None]:
        ref = quote(branch, safe="")
        response = await client.get(f"{GITHUB_API}/repos/{repo}/commits/{ref}")
        body = self._repo_json(response)
        return str(body["sha"]), response.headers.get("etag")

    async def _tree(
        self, client: httpx.AsyncClient, repo: str, sha: str
    ) -> tuple[list[dict[str, Any]], bool]:
        response = await client.get(
            f"{GITHUB_API}/repos/{repo}/git/trees/{sha}",
            params={"recursive": 1},
        )
        body = self._repo_json(response)
        tree = body.get("tree", [])
        items = list(tree) if isinstance(tree, list) else []
        return items, bool(body.get("truncated", False))

    # -------------------------------------------------------------- helpers

    def _http(self, creds: Credentials | None = None) -> httpx.AsyncClient:
        headers = {"Accept": "application/vnd.github+json"}
        if creds is not None:
            headers["Authorization"] = f"Bearer {creds.token}"
        return httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=headers)

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ConnectorError("github_error", "GitHub returned a non-JSON body.") from exc
        return data if isinstance(data, dict) else {}

    @classmethod
    def _ok_json(cls, response: httpx.Response) -> Any:
        cls._raise_for_error(response)
        return response.json()

    @staticmethod
    def _raise_for_error(response: httpx.Response) -> None:
        if response.status_code == 429 or (
            response.status_code == 403
            and (
                response.headers.get("Retry-After", "").strip()
                or response.headers.get("X-RateLimit-Remaining") == "0"
            )
        ):
            raise ConnectorError(
                "rate_limited", "GitHub is rate limiting requests; try again later."
            )
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise ConnectorError("github_error", f"GitHub request failed ({response.status_code}).")

    @classmethod
    def _repo_json(cls, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == httpx.codes.NOT_FOUND:
            raise ConnectorError("repo_not_found", "Repository, branch, or commit not found.")
        cls._raise_for_error(response)
        data = response.json()
        if not isinstance(data, dict):
            raise ConnectorError("github_error", "Unexpected GitHub response shape.")
        return data
