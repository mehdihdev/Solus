"""GitHub App support for team-owned installations (SOLUSDEV-216, ADR-039).

Three layers, all read-only against GitHub (ADR-039 §9):

* `app_jwt`: the RS256 App JWT, the credential for `/app/...` calls.
* `GitHubAppClient`: the HTTP client for the install-time flow (code exchange, access
  proof, installation details) and the installation-token reads (repos, org roster).
* `mint_installation_token` / `resolve_installation_credentials`: on-demand installation
  tokens for the reserved `secret_ref` `github-app/installation/{id}`.

Security invariants (ADR-039 §3, docs/api/github-orgs.md §3):

* Installation tokens are cached in this process only, never in Redis or the DB, for at
  most 55 minutes. They are never logged, persisted or returned.
* Every resolve re-checks that the `TeamInstallation` row is live and active, so an unlink
  in the API process is honoured by a worker still holding a cached token.
* The API base URL comes only from the installation row (or the github.com default); no
  caller input, webhook payload or `Link` header can redirect a token to another host.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import SplitResult, urlsplit

import httpx
import jwt
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.core.config import Settings
from solus_api.models import InstallationStatus, Team, TeamInstallation

logger = logging.getLogger("solus.connectors.github_app")

DEFAULT_API_BASE: Final = "https://api.github.com"
DEFAULT_WEB_BASE: Final = "https://github.com"
API_VERSION: Final = "2022-11-28"
REQUEST_TIMEOUT: Final = httpx.Timeout(15.0, connect=5.0)

#: GitHub accepts a JWT that expires within ten minutes; `iat` is backdated for clock drift.
JWT_BACKDATE: Final = timedelta(seconds=60)
JWT_LIFETIME: Final = timedelta(minutes=9)

#: Cache until the sooner of "5 minutes before GitHub's expiry" and "55 minutes from mint".
TOKEN_EXPIRY_MARGIN: Final = timedelta(minutes=5)
TOKEN_MAX_CACHE: Final = timedelta(minutes=55)

DEFAULT_PER_PAGE: Final = 100
DEFAULT_MAX_PAGES: Final = 10

#: Every secret_ref under this prefix is reserved: it is never a SecretStore key.
INSTALLATION_REF_PREFIX: Final = "github-app/installation/"
_REF_PATTERN: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_LOGIN_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,38}")
_LINK_PART: Final = re.compile(r"\s*<([^>]*)>(.*)")


class InvalidInstallationRefError(ValueError):
    """A reserved-prefix ref that is not exactly `github-app/installation/{positive int}`."""


# ---------------------------------------------------------------- configuration

_settings: Settings | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def configure_github_app(
    settings: Settings, sessionmaker: async_sessionmaker[AsyncSession] | None = None
) -> None:
    """Store what the App client reads (called at API and worker startup).

    `sessionmaker` is the process's session factory, used for the installation status
    gate. When omitted a short-lived NullPool engine is built from `settings.database_url`
    per gate check, which is correct but slower."""
    global _settings, _sessionmaker
    _settings = settings
    _sessionmaker = sessionmaker


def is_configured() -> bool:
    """True when every GitHub App credential is present."""
    return _settings is not None and _settings.github_app_configured


def _unconfigured() -> ConnectorError:
    return ConnectorError("github_app_unconfigured", "The GitHub App is not configured.")


def _require_settings() -> Settings:
    if _settings is None or not _settings.github_app_configured:
        raise _unconfigured()
    return _settings


def _secret(value: SecretStr | None) -> str:
    return value.get_secret_value() if value is not None else ""


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- reserved refs


def installation_secret_ref(team_installation_id: uuid.UUID) -> str:
    """The `Source.secret_ref` of a source bound to the `team_installations` row.

    The ref names OUR row, never GitHub's installation id: a re-link (even of the same
    GitHub installation, by another team) is a new row, so a stale or copied ref can never
    resolve against another tenant's link (ADR-039 §3-4)."""
    if not isinstance(team_installation_id, uuid.UUID):
        raise InvalidInstallationRefError("installation ref needs the team installation row id")
    return f"{INSTALLATION_REF_PREFIX}{team_installation_id}"


def is_installation_ref(ref: str | None) -> bool:
    """True for anything under the reserved prefix (well-formed or not)."""
    return bool(ref) and str(ref).startswith(INSTALLATION_REF_PREFIX)


def parse_installation_ref(ref: str) -> uuid.UUID:
    """The team installation row id of an exact `github-app/installation/{uuid}` ref.

    Refuses everything else: non-canonical UUIDs (upper case, braces, no hyphens),
    whitespace, traversal, and extra segments such as `/refresh`."""
    if not ref.startswith(INSTALLATION_REF_PREFIX):
        raise InvalidInstallationRefError("not an installation ref")
    tail = ref[len(INSTALLATION_REF_PREFIX) :]
    if _REF_PATTERN.fullmatch(tail) is None:
        raise InvalidInstallationRefError("malformed installation ref")
    return uuid.UUID(tail)


# ---------------------------------------------------------------- the App JWT


def app_jwt(now: datetime | None = None) -> str:
    """The RS256 App JWT: iss = app id, iat = now - 60s, exp = now + 9 min."""
    settings = _require_settings()
    moment = now or _utcnow()
    claims = {
        "iss": str(settings.github_app_id),
        "iat": int((moment - JWT_BACKDATE).timestamp()),
        "exp": int((moment + JWT_LIFETIME).timestamp()),
    }
    pem = settings.github_app_private_key_pem
    if not pem:
        raise _unconfigured()
    try:
        return jwt.encode(claims, pem, algorithm="RS256")
    except (ValueError, TypeError, jwt.PyJWTError) as exc:
        logger.error("GitHub App JWT signing failed: %s", type(exc).__name__)
        raise ConnectorError(
            "github_app_unconfigured", "The GitHub App private key is unusable."
        ) from exc


# ---------------------------------------------------------------- data


@dataclass(frozen=True, slots=True)
class InstallationInfo:
    """`GET /app/installations/{id}`, reduced to what Solus stores. All text is untrusted."""

    installation_id: int
    account_login: str
    account_id: int
    account_type: str
    account_avatar_url: str | None
    repository_selection: str
    suspended_at: datetime | None


@dataclass(frozen=True, slots=True)
class MintedToken:
    """An installation access token. Never repr'd, logged or persisted."""

    token: str = field(repr=False)
    expires_at: datetime


# ---------------------------------------------------------------- pagination guard


def _origin(parts: SplitResult) -> tuple[str, str, int | None]:
    try:
        port = parts.port
    except ValueError:
        port = -1
    default = {"https": 443, "http": 80}.get(parts.scheme)
    return parts.scheme, (parts.hostname or "").lower(), default if port is None else port


def next_page_url(link_header: str | None, api_base: str) -> str | None:
    """The `rel="next"` URL of a Link header, only if it targets the API base's own origin.

    SSRF guard: a token must never be sent anywhere GitHub's response points it to. A
    foreign scheme, host or port, embedded credentials and any malformed value yield None."""
    if not link_header:
        return None
    base = urlsplit(api_base)
    for part in link_header.split(","):
        match = _LINK_PART.match(part)
        if match is None:
            continue
        rels = [
            token
            for param in match.group(2).split(";")
            if param.strip().lower().startswith("rel=")
            for token in param.split("=", 1)[1].strip().strip('"').lower().split()
        ]
        if "next" not in rels:
            continue
        target = match.group(1).strip()
        try:
            parts = urlsplit(target)
        except ValueError:
            return None
        if not parts.hostname or "@" in parts.netloc or _origin(parts) != _origin(base):
            return None
        return target
    return None


# ---------------------------------------------------------------- the client


def _normalise_base(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("GitHub base URLs must be https")
    return url.rstrip("/")


class GitHubAppClient:
    """HTTP client for the GitHub App flows. Stateless; one connection per operation.

    The base URLs are fixed at construction, from the installation row or the defaults;
    nothing a caller passes to a method can change where requests (and tokens) go."""

    def __init__(
        self, api_base_url: str = DEFAULT_API_BASE, web_base_url: str = DEFAULT_WEB_BASE
    ) -> None:
        self._api = _normalise_base(api_base_url)
        self._web = _normalise_base(web_base_url)

    # -- transport ---------------------------------------------------------------
    @staticmethod
    def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        return {**headers, **(extra or {})}

    @staticmethod
    def _http() -> httpx.AsyncClient:
        # No redirects: a 30x must never carry a bearer token to another host.
        return httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=False)

    async def _send(
        self, http: httpx.AsyncClient, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        try:
            return await http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("GitHub request failed: %s %s", method, type(exc).__name__)
            raise ConnectorError("github_unreachable", "GitHub could not be reached.") from exc

    @staticmethod
    def _check(response: httpx.Response) -> None:
        status = response.status_code
        if status == httpx.codes.UNAUTHORIZED:
            raise ConnectorError("invalid_credentials", "GitHub rejected the credentials.")
        limited = response.headers.get("x-ratelimit-remaining") == "0"
        if status == httpx.codes.TOO_MANY_REQUESTS or (status == httpx.codes.FORBIDDEN and limited):
            raise ConnectorError("rate_limited", "GitHub is rate limiting requests.")
        if status >= httpx.codes.BAD_REQUEST:
            raise ConnectorError("github_error", f"GitHub request failed ({status}).")

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise ConnectorError("github_error", "GitHub returned a non-JSON body.") from exc

    # -- install-time flow -------------------------------------------------------
    async def exchange_user_code(self, code: str) -> str:
        """Exchange the install callback `code` for a user-to-server token (kept in memory)."""
        settings = _require_settings()
        refused = ConnectorError("oauth_exchange_failed", "GitHub refused the authorization code.")
        if not code:
            raise refused
        async with self._http() as http:
            response = await self._send(
                http,
                "POST",
                f"{self._web}/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.github_app_client_id or "",
                    "client_secret": _secret(settings.github_app_client_secret),
                    "code": code,
                },
            )
        if response.status_code != httpx.codes.OK:
            raise refused
        try:
            body = response.json()
        except ValueError as exc:
            raise refused from exc
        token = body.get("access_token") if isinstance(body, dict) else None
        if (
            not isinstance(body, dict)
            or "error" in body
            or not isinstance(token, str)
            or not token
            or str(body.get("token_type", "")).lower() != "bearer"
        ):
            raise refused
        return token

    async def user_installation_ids(
        self, user_token: str, max_pages: int = DEFAULT_MAX_PAGES
    ) -> set[int]:
        """Every installation id the user can access (`GET /user/installations`, bounded)."""
        items = await self._walk(
            "/user/installations",
            user_token,
            max_pages=max_pages,
            per_page=DEFAULT_PER_PAGE,
            key="installations",
        )
        return {item["id"] for item in items if isinstance(item.get("id"), int)}

    async def get_installation(self, installation_id: int) -> InstallationInfo:
        """The installation's record, read with the App JWT."""
        async with self._http() as http:
            response = await self._send(
                http,
                "GET",
                f"{self._api}/app/installations/{int(installation_id)}",
                headers=self._headers({"Authorization": f"Bearer {app_jwt()}"}),
            )
        if response.status_code == httpx.codes.NOT_FOUND:
            raise ConnectorError("installation_unavailable", "GitHub installation not found.")
        self._check(response)
        return _parse_installation(self._json(response))

    async def revoke_user_token(self, user_token: str) -> None:
        """Best-effort: stop the user-to-server token living on for 8 hours. Never raises."""
        try:
            settings = _require_settings()
            client_id = settings.github_app_client_id or ""
            async with self._http() as http:
                response = await http.request(
                    "DELETE",
                    f"{self._api}/applications/{client_id}/token",
                    headers=self._headers(),
                    auth=(client_id, _secret(settings.github_app_client_secret)),
                    json={"access_token": user_token},
                )
            if response.status_code not in (204, 404, 422):
                logger.warning("user token revoke answered %s", response.status_code)
        except Exception as exc:  # noqa: BLE001 - best effort; type only, never the detail
            logger.warning("user token revoke failed: %s", type(exc).__name__)

    # -- installation-token reads ------------------------------------------------
    async def list_installation_repos(
        self,
        token: str,
        *,
        page: int = 1,
        per_page: int = DEFAULT_PER_PAGE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> list[dict[str, Any]]:
        """Repositories the installation can see (`GET /installation/repositories`)."""
        return await self._walk(
            "/installation/repositories",
            token,
            page=page,
            per_page=per_page,
            max_pages=max_pages,
            key="repositories",
        )

    async def list_org_members(
        self,
        token: str,
        org_login: str,
        *,
        page: int = 1,
        per_page: int = DEFAULT_PER_PAGE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> list[dict[str, Any]]:
        """The org's members (`GET /orgs/{login}/members`, needs `members:read`)."""
        if _LOGIN_PATTERN.fullmatch(org_login) is None:
            raise ConnectorError("invalid_org", "The organization login is not valid.")
        return await self._walk(
            f"/orgs/{org_login}/members",
            token,
            page=page,
            per_page=per_page,
            max_pages=max_pages,
            key=None,
        )

    async def _walk(
        self,
        path: str,
        token: str,
        *,
        max_pages: int,
        per_page: int,
        key: str | None,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """Collect up to `max_pages` pages, following `rel="next"` on the same origin only."""
        headers = self._headers({"Authorization": f"Bearer {token}"})
        url: str | None = f"{self._api}{path}"
        params: dict[str, int] | None = {
            "per_page": max(1, min(per_page, 100)),
            "page": max(page, 1),
        }
        collected: list[dict[str, Any]] = []
        async with self._http() as http:
            for _ in range(max(max_pages, 0)):
                if url is None:
                    break
                response = await self._send(http, "GET", url, headers=headers, params=params)
                self._check(response)
                body = self._json(response)
                batch = body.get(key) if key and isinstance(body, dict) else body
                if not isinstance(batch, list):
                    raise ConnectorError("github_error", "Unexpected GitHub list response.")
                collected.extend(item for item in batch if isinstance(item, dict))
                url = next_page_url(response.headers.get("link"), self._api)
                params = None  # the next URL already carries its query
        return collected


def _parse_installation(body: Any) -> InstallationInfo:
    bad = ConnectorError("github_error", "Unexpected GitHub installation response.")
    if not isinstance(body, dict) or not isinstance(body.get("account"), dict):
        raise bad
    account = body["account"]
    login, account_id, kind = account.get("login"), account.get("id"), account.get("type")
    selection = body.get("repository_selection")
    if not (
        isinstance(body.get("id"), int)
        and isinstance(login, str)
        and isinstance(account_id, int)
        and isinstance(kind, str)
        and isinstance(selection, str)
    ):
        raise bad
    avatar = account.get("avatar_url")
    return InstallationInfo(
        installation_id=body["id"],
        account_login=login,
        account_id=account_id,
        account_type=kind,
        account_avatar_url=avatar if isinstance(avatar, str) else None,
        repository_selection=selection,
        suspended_at=_parse_time(body.get("suspended_at")),
    )


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ---------------------------------------------------------------- the minter


@dataclass(slots=True)
class _CachedToken:
    minted: MintedToken
    valid_until: datetime


#: Process-local on purpose: a bearer token in Redis could reach disk via RDB/AOF snapshots.
_token_cache: dict[int, _CachedToken] = {}
_mint_locks: dict[int, asyncio.Lock] = {}


def invalidate_installation_token(installation_id: int) -> None:
    """Drop the cached token for an installation (unlink, suspend, revoke)."""
    _token_cache.pop(installation_id, None)


def clear_installation_tokens() -> None:
    """Drop every cached token and lock (tests, shutdown)."""
    _token_cache.clear()
    _mint_locks.clear()


def _cache_deadline(minted: MintedToken, now: datetime) -> datetime:
    return min(minted.expires_at - TOKEN_EXPIRY_MARGIN, now + TOKEN_MAX_CACHE)


@asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    """A short session from the configured factory (or a throwaway NullPool engine)."""
    if _sessionmaker is not None:
        async with _sessionmaker() as session:
            yield session
        return
    settings = _require_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


async def _mark_status(
    installation_id: int, status: InstallationStatus, *, suspended_at: datetime | None = None
) -> None:
    """Record what GitHub told us so every later resolve fails fast at the status gate.

    REVOKED applies to any live row not already revoked; SUSPENDED only to an ACTIVE row,
    so a late suspension answer never downgrades a revoked installation."""
    allowed = (
        (InstallationStatus.ACTIVE,)
        if status is InstallationStatus.SUSPENDED
        else (InstallationStatus.ACTIVE, InstallationStatus.SUSPENDED)
    )
    try:
        async with _session() as session:
            rows = (
                await session.scalars(
                    select(TeamInstallation).where(
                        TeamInstallation.provider == "github",
                        TeamInstallation.external_installation_id == installation_id,
                        TeamInstallation.deleted_at.is_(None),
                        TeamInstallation.status.in_(allowed),
                    )
                )
            ).all()
            for row in rows:
                row.status = status
                if status is InstallationStatus.REVOKED:
                    row.revoked_at = _utcnow()
                else:
                    row.suspended_at = suspended_at or _utcnow()
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - the caller still raises installation_unavailable
        logger.error(
            "could not mark installation %s %s: %s", installation_id, status, type(exc).__name__
        )


async def _record_forbidden(installation_id: int, api_base_url: str) -> None:
    """A mint 403 is ambiguous: GitHub also answers it for a SUSPENDED installation.

    Ask GitHub (App JWT). Suspended -> suspended; gone (404) -> revoked; any other
    outcome, including a failed lookup, leaves the status unchanged."""
    try:
        info = await GitHubAppClient(api_base_url).get_installation(installation_id)
    except ConnectorError as exc:
        if exc.code == "installation_unavailable":
            await _mark_status(installation_id, InstallationStatus.REVOKED)
        return
    if info.suspended_at is not None:
        await _mark_status(
            installation_id, InstallationStatus.SUSPENDED, suspended_at=info.suspended_at
        )


async def _request_token(installation_id: int, api_base_url: str) -> MintedToken:
    client = GitHubAppClient(api_base_url)
    async with client._http() as http:
        response = await client._send(
            http,
            "POST",
            f"{client._api}/app/installations/{installation_id}/access_tokens",
            headers=client._headers({"Authorization": f"Bearer {app_jwt()}"}),
        )
    if response.status_code in (httpx.codes.NOT_FOUND, httpx.codes.FORBIDDEN):
        invalidate_installation_token(installation_id)
        if response.status_code == httpx.codes.NOT_FOUND:
            await _mark_status(installation_id, InstallationStatus.REVOKED)
        else:
            await _record_forbidden(installation_id, api_base_url)
        raise ConnectorError(
            "installation_unavailable", "The GitHub App installation is no longer available."
        )
    client._check(response)
    body = client._json(response)
    token = body.get("token") if isinstance(body, dict) else None
    expires_at = _parse_time(body.get("expires_at")) if isinstance(body, dict) else None
    if not isinstance(token, str) or not token or expires_at is None:
        raise ConnectorError("github_error", "Unexpected installation token response.")
    return MintedToken(token=token, expires_at=expires_at)


async def mint_installation_token(
    installation_id: int, *, api_base_url: str | None = None
) -> MintedToken:
    """A valid installation token: cached, or minted once per installation at a time."""
    _require_settings()
    lock = _mint_locks.setdefault(installation_id, asyncio.Lock())
    async with lock:
        cached = _token_cache.get(installation_id)
        if cached is not None and _utcnow() < cached.valid_until:
            return cached.minted
        minted = await _request_token(installation_id, api_base_url or DEFAULT_API_BASE)
        _token_cache[installation_id] = _CachedToken(minted, _cache_deadline(minted, _utcnow()))
        logger.info("minted installation token installation=%s", installation_id)
        return minted


# ---------------------------------------------------------------- the resolver


def _unavailable() -> ConnectorError:
    return ConnectorError(
        "installation_unavailable", "The GitHub installation is not available to Solus."
    )


async def _live_installation(team_installation_id: uuid.UUID) -> TeamInstallation:
    """The ACTIVE, live row the ref names, whose team is live, or refuse."""
    async with _session() as session:
        row = await session.scalar(
            select(TeamInstallation)
            .join(Team, Team.id == TeamInstallation.team_id)
            .where(
                TeamInstallation.id == team_installation_id,
                TeamInstallation.provider == "github",
                TeamInstallation.deleted_at.is_(None),
                Team.deleted_at.is_(None),
            )
        )
    if row is None or row.status is not InstallationStatus.ACTIVE:
        raise _unavailable()
    return row


async def resolve_installation_credentials(ref: str) -> Credentials:
    """Credentials for a source bound to the reserved installation ref.

    Order matters: the ref is parsed strictly, the App must be configured, and the status
    gate runs on EVERY call before the cache is consulted."""
    try:
        row_id = parse_installation_ref(ref)
    except InvalidInstallationRefError as exc:
        raise ConnectorError(
            "invalid_secret_ref", "The installation reference is invalid."
        ) from exc
    _require_settings()
    row = await _live_installation(row_id)
    installation_id = row.external_installation_id
    minted = await mint_installation_token(installation_id, api_base_url=row.api_base_url)
    return Credentials(
        token=minted.token,
        metadata={
            "kind": "github_app_installation",
            "installation_id": installation_id,
            "team_installation_id": str(row.id),
            "api_base": row.api_base_url,
            "account_login": row.account_login,
        },
    )
