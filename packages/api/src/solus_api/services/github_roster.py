"""The linked GitHub organization's member roster (SOLUSDEV-216, ADR-039 section 6).

Listed with the installation token (`members:read`), walked to a bound by the App client, and
cached per GitHub installation id (`roster_cache_key`) so a team that re-links reads nothing from
the previous owner. Only numeric ids are trusted: logins and avatars are display text.

The cache holds the raw roster only. Solus status (member / invited / not_on_solus) is derived
per request from our own tables, so it is never stale.
"""

from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass
from typing import Any, Final

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.github_app import GitHubAppClient, mint_installation_token
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.core.errors import APIError
from solus_api.models import TeamInstallation
from solus_api.services.github_identity import GITHUB_LOGIN_PATTERN
from solus_api.services.team_installations import roster_cache_key

logger = logging.getLogger("solus.services.github_roster")

ROSTER_TTL_SECONDS: Final = 300
ORGANIZATION: Final = "Organization"
_MAX_AVATAR_CHARS: Final = 512
_MAX_ID: Final = 2**63 - 1


@dataclass(frozen=True)
class RosterMember:
    github_id: int
    github_login: str
    avatar_url: str

    def to_cache(self) -> dict[str, Any]:
        return {"id": self.github_id, "login": self.github_login, "avatar_url": self.avatar_url}


def _parse_member(raw: Any) -> RosterMember | None:
    """One roster entry, or None when it is malformed (never trusted, never raised on)."""
    if not isinstance(raw, dict):
        return None
    gid, login, avatar = raw.get("id"), raw.get("login"), raw.get("avatar_url")
    if isinstance(gid, bool) or not isinstance(gid, int) or not 0 < gid <= _MAX_ID:
        return None
    if not isinstance(login, str) or GITHUB_LOGIN_PATTERN.fullmatch(login) is None:
        return None
    if not isinstance(avatar, str) or len(avatar) > _MAX_AVATAR_CHARS:
        avatar = ""
    return RosterMember(gid, login, avatar)


def _parse_roster(raw: Any) -> list[RosterMember]:
    """Valid entries, de-duplicated by id and ordered by id (the pagination order)."""
    if not isinstance(raw, list):
        return []
    unique = {m.github_id: m for m in map(_parse_member, raw) if m is not None}
    return [unique[gid] for gid in sorted(unique)]


def api_error_for(exc: ConnectorError) -> APIError:
    """Map a connector failure to the public envelope. Messages are fixed text."""
    if exc.code == "rate_limited":
        return APIError(429, "rate_limited", "GitHub is rate limiting requests; try again shortly")
    if exc.code == "installation_unavailable":
        return APIError(409, "installation_revoked", "The GitHub App installation was revoked.")
    return APIError(502, "github_error", "GitHub could not list the organization members")


async def _fetch(inst: TeamInstallation) -> list[RosterMember]:
    minted = await mint_installation_token(
        inst.external_installation_id, api_base_url=inst.api_base_url
    )
    client = GitHubAppClient(inst.api_base_url, inst.web_base_url)
    return _parse_roster(await client.list_org_members(minted.token, inst.account_login))


async def get_roster(
    cache: IntegrationCache, inst: TeamInstallation, *, refresh: bool = False
) -> tuple[list[RosterMember], bool]:
    """`(roster, served_from_cache)`. `refresh` skips the cache read and rewrites it."""
    key = roster_cache_key(inst.external_installation_id)
    if not refresh:
        cached = await cache.get(key)
        if cached is not None:
            return _parse_roster(cached), True
    try:
        roster = await _fetch(inst)
    except ConnectorError as exc:
        logger.warning("roster fetch failed team_installation=%s code=%s", inst.id, exc.code)
        raise api_error_for(exc) from exc
    await cache.put(key, [m.to_cache() for m in roster], ROSTER_TTL_SECONDS)
    return roster, False


async def require_org_member(
    cache: IntegrationCache, inst: TeamInstallation, github_id: int
) -> RosterMember:
    """The roster entry for `github_id`, or 400 `not_an_org_member`.

    A miss on a CACHED roster refreshes once (someone may have just joined the org); a miss on
    a roster fetched this very call is final."""
    roster, from_cache = await get_roster(cache, inst)
    found = _find(roster, github_id)
    if found is None and from_cache:
        roster, _ = await get_roster(cache, inst, refresh=True)
        found = _find(roster, github_id)
    if found is None:
        raise APIError(
            400, "not_an_org_member", "That GitHub user is not a member of the linked organization"
        )
    return found


def _find(roster: list[RosterMember], github_id: int) -> RosterMember | None:
    return next((m for m in roster if m.github_id == github_id), None)


# ------------------------------------------------------------------ pagination


def encode_cursor(last_id: int) -> str:
    return base64.urlsafe_b64encode(str(last_id).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("ascii")
        if raw.isdigit():
            return int(raw)
    except (binascii.Error, UnicodeDecodeError):
        pass
    raise APIError(400, "invalid_cursor", "Malformed pagination cursor")


def page_of(
    roster: list[RosterMember], cursor: str | None, limit: int
) -> tuple[list[RosterMember], dict[str, Any]]:
    """The `limit` entries after `cursor` (ids ascend) plus the standard `meta` block."""
    after = decode_cursor(cursor) if cursor else 0
    remaining = [m for m in roster if m.github_id > after]
    visible = remaining[:limit]
    has_next = len(remaining) > limit
    meta = {
        "limit": limit,
        "has_next": has_next,
        "next_cursor": encode_cursor(visible[-1].github_id) if has_next and visible else None,
        "total": len(roster),
    }
    return visible, meta
