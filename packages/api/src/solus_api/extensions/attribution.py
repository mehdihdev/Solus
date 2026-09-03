"""Credit attribution for extension-originated SOL turns (SOLUSDEV-235 / EXT-11).

docs/api/extensions.md §9: when the desktop bridge host performs `sol.ask` on
behalf of an extension it sets `X-Solus-Extension: <slug>` on the ordinary SOL
turn request. The header is accepted ONLY when the project has an ENABLED
install of that slug whose `granted_scopes` includes `sol.ask` and the team has
not blocked the extension. Anything else is `403 scope_denied` — a client-
asserted header is refused, never silently downgraded to an unattributed turn,
so an extension cannot launder a turn as the user's own.

On acceptance the turn proceeds exactly as before: the INVOKING user is metered
(ADR-018/019/024 — no pooling, no extension budget); the resolved extension id
only rides along to `credit_ledger.extension_id` (ADR-035 §2).

`extension.bridge_refused` is the desktop host's event (§11); the server logs
the refusal with identifiers only.
"""

import logging
import re
import uuid
from typing import Annotated

from fastapi import Depends, Header
from solus_contracts.extension_manifest import EXTENSION_ID_PATTERN
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.deps import ProjectCtx, SessionDep
from solus_api.models import Extension, ExtensionInstall, Project, TeamExtensionPolicy

logger = logging.getLogger("solus.extensions.attribution")

EXTENSION_HEADER = "X-Solus-Extension"
SOL_ASK_SCOPE = "sol.ask"
_SLUG_RE = re.compile(EXTENSION_ID_PATTERN)


def _denied(project_id: uuid.UUID, reason: str, slug: str | None = None) -> APIError:
    # Identifiers only; the raw header is logged only once it matched the slug regex.
    logger.info(
        "extension attribution refused project_id=%s slug=%s reason=%s", project_id, slug, reason
    )
    return APIError(403, "scope_denied", "This extension may not invoke SOL in this project")


async def resolve_extension_attribution(
    session: AsyncSession, *, project: Project, header_value: str | None
) -> uuid.UUID | None:
    """The extension id to attribute a SOL turn to, or None when no header was
    sent. Every failure — malformed slug, unknown extension, no install in THIS
    project, disabled, `sol.ask` not granted, team-blocked — raises
    `APIError(403, "scope_denied")`."""
    if header_value is None:
        return None
    if _SLUG_RE.fullmatch(header_value) is None:
        raise _denied(project.id, "malformed_slug")
    slug = header_value
    row = (
        await session.execute(
            select(
                ExtensionInstall.extension_id,
                ExtensionInstall.enabled,
                ExtensionInstall.granted_scopes,
                TeamExtensionPolicy.blocked,
            )
            .join(Extension, Extension.id == ExtensionInstall.extension_id)
            .outerjoin(
                TeamExtensionPolicy,
                (TeamExtensionPolicy.extension_id == Extension.id)
                & (TeamExtensionPolicy.team_id == project.team_id),
            )
            .where(ExtensionInstall.project_id == project.id, func.lower(Extension.slug) == slug)
        )
    ).one_or_none()
    if row is None:
        raise _denied(project.id, "not_installed", slug)
    extension_id, enabled, granted_scopes, blocked = row
    if blocked:
        raise _denied(project.id, "blocked", slug)
    if not enabled:
        raise _denied(project.id, "disabled", slug)
    if SOL_ASK_SCOPE not in (granted_scopes or []):
        raise _denied(project.id, "scope_not_granted", slug)
    return uuid.UUID(str(extension_id))


async def extension_attribution(
    ctx: ProjectCtx,
    session: SessionDep,
    header_value: Annotated[str | None, Header(alias=EXTENSION_HEADER)] = None,
) -> uuid.UUID | None:
    """FastAPI dependency: resolves `X-Solus-Extension` against the request's
    project BEFORE the route body runs (so a refusal precedes admission)."""
    return await resolve_extension_attribution(
        session, project=ctx.project, header_value=header_value
    )


ExtensionAttribution = Annotated[uuid.UUID | None, Depends(extension_attribution)]

__all__ = [
    "EXTENSION_HEADER",
    "SOL_ASK_SCOPE",
    "ExtensionAttribution",
    "extension_attribution",
    "resolve_extension_attribution",
]
