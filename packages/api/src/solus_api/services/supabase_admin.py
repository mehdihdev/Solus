"""Supabase Admin API client (service-role) — account-lifecycle actions
(SOLUSDEV-82 / SOLUS-FND-02).

Used only server-side. The service-role key grants full auth-admin power, so it
is sourced from the environment / Secrets Manager (CLAUDE.md §7), never logged
and never returned by any API response. When unconfigured the client no-ops so
local dev and the test suite run without a live Supabase project.
"""

import logging
import re
from typing import Any

import httpx

from solus_api.core.config import Settings

logger = logging.getLogger("solus.auth.admin")

_TIMEOUT_SECONDS = 10.0
#: A Supabase auth user id is a UUID; anything path-shaped is refused before it can reach a URL.
_SAFE_USER_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


class SupabaseAdmin:
    """Thin wrapper over the Supabase auth-admin endpoints we need."""

    def __init__(self, base_url: str | None, service_role_key: str | None) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._service_role_key = service_role_key

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._service_role_key)

    async def delete_user(self, supabase_user_id: str) -> bool:
        """Delete the Supabase auth user, which also revokes their refresh
        tokens / sessions. Best-effort: returns True when the remote delete was
        made (or the user was already gone), False when unconfigured or the call
        failed — the caller has already removed local data and tombstoned the
        identity, so a failure here never blocks account deletion.
        """
        if not self.configured:
            logger.warning(
                "Supabase admin not configured; skipping remote deletion of auth "
                "user (local data removed, remote session NOT revoked)."
            )
            return False
        url = f"{self._base_url}/auth/v1/admin/users/{supabase_user_id}"
        headers = {
            "apikey": self._service_role_key or "",
            "Authorization": f"Bearer {self._service_role_key or ''}",
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.delete(url, headers=headers)
        except httpx.HTTPError:
            logger.exception("Supabase admin delete_user request failed")
            return False
        # 404 → already deleted; treat as success. Other 4xx/5xx: log the status
        # (never the body/key) and report failure without raising.
        if resp.status_code >= 400 and resp.status_code != 404:
            logger.error("Supabase admin delete_user returned %s", resp.status_code)
            return False
        return True

    async def github_identity(self, user_supabase_id: str) -> int | None:
        """The numeric GitHub user id linked to this Supabase auth user, read through the
        admin API (`identities[provider == "github"].id`), or None.

        Server-side proof only: never read from a JWT. Returns None when unconfigured, the id
        is not a plain auth-user id, or anything goes wrong; it never raises to the caller."""
        if not self.configured or _SAFE_USER_ID.fullmatch(user_supabase_id) is None:
            return None
        url = f"{self._base_url}/auth/v1/admin/users/{user_supabase_id}"
        headers = {
            "apikey": self._service_role_key or "",
            "Authorization": f"Bearer {self._service_role_key or ''}",
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code != httpx.codes.OK:
                logger.warning("Supabase admin github_identity returned %s", resp.status_code)
                return None
            return _github_id_from(resp.json())
        except (httpx.HTTPError, ValueError):
            logger.warning("Supabase admin github_identity request failed")
            return None


def _github_id_from(body: Any) -> int | None:
    identities = body.get("identities") if isinstance(body, dict) else None
    if not isinstance(identities, list):
        return None
    for identity in identities:
        if not isinstance(identity, dict) or identity.get("provider") != "github":
            continue
        raw = identity.get("id")
        if isinstance(raw, str) and raw.isascii() and raw.isdigit() and int(raw) > 0:
            return int(raw)
    return None


def build_supabase_admin(settings: Settings) -> SupabaseAdmin:
    admin = SupabaseAdmin(settings.supabase_url, settings.supabase_service_role_key)
    if not admin.configured:
        logger.warning(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY unset — account deletion will "
            "not revoke Supabase sessions. Set both in any shared/prod environment."
        )
    return admin
