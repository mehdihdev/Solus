"""Which first-party bundles are LIVE in a project (SOLUSDEV-246).

Two consumers, one rule: a bundle counts only while its install row exists, is
enabled, is not team-blocked, and its PINNED manifest declares the capability.
`require_bundle(slug)` is the FastAPI dependency every mounted capability
router runs under (widget-bundles.md §3; a miss is `404 not_found` — the bundle
is simply not there for this project); `load_bundle_capabilities` is what the
SOL registry dependency calls to know which tools to register (§4).
"""

from __future__ import annotations

import functools
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from solus_contracts.extension_manifest import (
    ExtensionManifest,
    declares_first_party,
    parse_extension_manifest,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.deps import ProjectContext, ProjectCtx, SessionDep, SettingsDep, require_role
from solus_api.extensions import installs as svc
from solus_api.extensions.ratelimit import (
    INSTALL_WRITE_MESSAGE,
    WRITE_WINDOW_SECONDS,
    install_write_exceeded,
)
from solus_api.models import (
    Extension,
    ExtensionInstall,
    ExtensionVersion,
    Role,
    TeamExtensionPolicy,
)
from solus_api.services.events import emit_event
from solus_api.widgets.capability import WidgetCapability
from solus_api.widgets.registry import discover_capabilities

logger = logging.getLogger("solus.widgets.guard")

#: (capability, the pinned manifest that declared it) — what the registry needs.
BundleCapabilities = list[tuple[WidgetCapability, ExtensionManifest]]


@dataclass(frozen=True)
class BundleContext:
    """What a capability handler receives: the project context it already
    trusts, plus the install this call runs against."""

    ctx: ProjectContext
    extension: Extension
    install: ExtensionInstall
    manifest: ExtensionManifest


#: Methods that never change state; everything else takes the member floor and
#: the install-write budget (widget-bundles.md §3).
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def pinned_manifest_or_none(pinned: ExtensionVersion | None) -> ExtensionManifest | None:
    """The pinned manifest, or None when the stored object no longer parses (a
    later contract tightening). Callers treat None as "declares nothing" so a
    stale row can never strand an install or 500 a route."""
    if pinned is None:
        return None
    try:
        return parse_extension_manifest(pinned.manifest)
    except ValueError:
        logger.warning("pinned manifest for version %s does not parse", pinned.id)
        return None


async def _resolve(
    session: AsyncSession, ctx: ProjectContext, slug: str
) -> tuple[BundleContext | None, str]:
    extension = await svc.find_live_extension(session, slug)
    if extension is None:
        return None, "not_installed"
    install = await svc.get_install(session, ctx.project.id, extension.id)
    if install is None:
        return None, "not_installed"
    if not install.enabled:
        return None, "disabled"
    if await svc.is_blocked(session, ctx.team.id, extension.id):
        return None, "blocked"
    manifest = pinned_manifest_or_none(await session.get(ExtensionVersion, install.version_id))
    if manifest is None or manifest.backend is None or not manifest.backend.routes:
        return None, "no_routes"
    return BundleContext(ctx, extension, install, manifest), ""


async def _refuse(session: AsyncSession, ctx: ProjectContext, slug: str, reason: str) -> None:
    emit_event(
        session,
        user=ctx.user,
        event_type="widget_bundle.route_refused",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"slug": slug, "reason": reason},
    )
    await session.commit()
    raise APIError(404, "not_found", "No such bundle in this project")


def _enforce_write_floor(request: Request, ctx: ProjectContext, settings: Any) -> None:
    """Every capability write: `member` floor (viewers and share-only users →
    403) and the shared install-write budget (→ 429 + Retry-After) — enforced
    here, once, so no capability handler ever hand-rolls auth (CLAUDE.md §7)."""
    require_role(ctx, Role.MEMBER)
    if install_write_exceeded(
        request.app.state, ctx.user.id, settings.extension_install_writes_per_minute_per_user
    ):
        raise APIError(
            429,
            "rate_limited",
            INSTALL_WRITE_MESSAGE,
            headers={"Retry-After": str(WRITE_WINDOW_SECONDS)},
        )


@functools.cache
def require_bundle(slug: str) -> Callable[..., Awaitable[BundleContext]]:
    """One dependency object per slug (cached, so the router-level dependency
    and a handler's `BundleDep(slug)` resolve ONCE per request)."""

    async def dependency(
        request: Request, ctx: ProjectCtx, session: SessionDep, settings: SettingsDep
    ) -> BundleContext:
        if request.method.upper() not in SAFE_METHODS:
            _enforce_write_floor(request, ctx, settings)
        bundle, reason = await _resolve(session, ctx, slug)
        if bundle is None:
            await _refuse(session, ctx, slug, reason)
            raise AssertionError("unreachable")  # pragma: no cover — _refuse raises
        return bundle

    dependency.__name__ = f"require_bundle_{slug.replace('-', '_')}"
    return dependency


async def load_bundle_capabilities(
    session: AsyncSession, project_id: uuid.UUID, team_id: uuid.UUID
) -> BundleCapabilities:
    """Every enabled, unblocked install in the project whose pinned manifest
    declares a first-party table AND whose slug has an in-repo capability."""
    capabilities = discover_capabilities()
    rows = (
        await session.execute(
            select(Extension.slug, ExtensionVersion, TeamExtensionPolicy.blocked)
            .join(ExtensionInstall, ExtensionInstall.extension_id == Extension.id)
            .join(ExtensionVersion, ExtensionVersion.id == ExtensionInstall.version_id)
            .outerjoin(
                TeamExtensionPolicy,
                (TeamExtensionPolicy.extension_id == Extension.id)
                & (TeamExtensionPolicy.team_id == team_id),
            )
            .where(
                ExtensionInstall.project_id == project_id,
                ExtensionInstall.enabled.is_(True),
                Extension.deleted_at.is_(None),
            )
        )
    ).all()
    live: BundleCapabilities = []
    for slug, pinned, blocked in rows:
        capability = capabilities.get(slug)
        manifest = pinned_manifest_or_none(pinned)
        if blocked or capability is None or manifest is None:
            continue
        if declares_first_party(manifest):
            live.append((capability, manifest))
    return live
