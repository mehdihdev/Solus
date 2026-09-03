"""§4.4 bundle download + §4.5 store-facing assets (SOLUSDEV-235 / ADR-035,
EXT-07; docs/api/extensions.md). Both serve stored bytes ONLY: no unzip, no
transform, no filesystem or zip lookup in the request. Visibility is the §4.4
rule — approved for anyone signed in, the publisher's own otherwise, 404 else.

Exports `router`; the aggregator (`routers/extensions/__init__.py`) mounts it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from solus_api.core.errors import error_response
from solus_api.deps import CurrentUser, SessionDep, SettingsDep
from solus_api.extensions.publishing import (
    not_found,
    resolve_visible_version,
    validate_semver,
    validate_slug,
)
from solus_api.models import ExtensionVersionAsset
from solus_api.services.artifacts import FixedWindowLimiter
from solus_api.services.events import emit_event
from solus_api.storage import ArtifactNotFoundError
from solus_api.storage.extension_bundle_store import ExtensionBundleStore

router = APIRouter(prefix="/api/v1/extensions")

_DOWNLOAD_WINDOW_SECONDS = 60
#: §4.5: a version's assets never change once approved.
_ASSET_CACHE_CONTROL = "private, max-age=86400, immutable"
#: Belt and braces over the review-time SVG reduction: even if an inline
#: script survived sanitization, the browser may not run it from this origin.
_SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'"


def _download_limiter(request: Request) -> FixedWindowLimiter:
    """Per-user per-minute window (§12). Lazily created on `app.state` (main.py
    is outside this task's ownership); per-process like its siblings."""
    limiter: FixedWindowLimiter | None = getattr(
        request.app.state, "extension_download_limiter", None
    )
    if limiter is None:
        limiter = FixedWindowLimiter(window_seconds=_DOWNLOAD_WINDOW_SECONDS)
        request.app.state.extension_download_limiter = limiter
    return limiter


def _bundle_store(request: Request) -> ExtensionBundleStore:
    return ExtensionBundleStore(request.app.state.artifact_store)


def _rate_limited(message: str, retry_after_seconds: int) -> Response:
    resp = error_response(429, "rate_limited", message)
    resp.headers["Retry-After"] = str(retry_after_seconds)
    return resp


@router.get("/{slug}/versions/{version}/bundle", response_class=Response)
async def download_bundle(
    slug: str,
    version: str,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    slug, version = validate_slug(slug), validate_semver(version)
    limit = settings.extension_bundle_downloads_per_minute_per_user
    if _download_limiter(request).bump(str(user.id)) > limit:
        emit_event(
            session, user=user, event_type="extension.rate_limited", payload={"route": "bundle"}
        )
        await session.commit()
        return _rate_limited("Too many bundle downloads; slow down", _DOWNLOAD_WINDOW_SECONDS)

    resolved = await resolve_visible_version(session, slug, version, user_id=user.id)
    data = await _stored_bytes(_bundle_store(request), resolved.version.id, asset=False)
    headers = {
        "X-Solus-Content-Hash": resolved.version.content_hash,
        "Content-Length": str(len(data)),
    }
    return Response(content=data, media_type="application/zip", headers=headers)


@router.get("/{slug}/versions/{version}/assets/{path:path}", response_class=Response)
async def get_asset(
    slug: str,
    version: str,
    path: str,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    """Only a `path` recorded in `extension_version_assets` for this version is
    served, compared as a whole string; the bytes come from the store under the
    asset row's key. Rides the global limiter only (§12)."""
    slug, version = validate_slug(slug), validate_semver(version)
    resolved = await resolve_visible_version(session, slug, version, user_id=user.id)
    asset = await session.scalar(
        select(ExtensionVersionAsset).where(
            ExtensionVersionAsset.version_id == resolved.version.id,
            ExtensionVersionAsset.path == path,
        )
    )
    if asset is None:
        raise not_found()
    data = await _stored_bytes(_bundle_store(request), asset.storage_key, asset=True)
    headers = {
        "Content-Length": str(len(data)),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": _ASSET_CACHE_CONTROL,
    }
    if asset.media_type == "image/svg+xml":
        headers["Content-Security-Policy"] = _SVG_CSP
    return Response(content=data, media_type=asset.media_type, headers=headers)


async def _stored_bytes(store: ExtensionBundleStore, key: uuid.UUID, *, asset: bool) -> bytes:
    """A row whose bytes are gone (swept, or a failed write) is the same 404 as a
    row that never existed — no oracle, and no storage detail in the message."""
    try:
        return await (store.get_asset(key) if asset else store.get_bundle(key))
    except ArtifactNotFoundError:
        raise not_found() from None
