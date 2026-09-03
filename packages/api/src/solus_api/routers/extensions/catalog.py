"""Extension catalog READ routes — `docs/api/extensions.md` §4.1–§4.3 (EXT-06).

Signed-in, tenant-free reads of approved content (route plan §2.1/§3): only
`CurrentUser`, no team or project, and nothing here discloses a tenant. An
unreleased listing or an unapproved version is `404 not_found` to everyone but
its publisher — never a `403`, so no existence oracle. Thin by design: every
visibility decision lives in `extensions.catalog_service`, every shape in
`extensions.schemas`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, SessionDep
from solus_api.extensions import catalog_service as svc
from solus_api.extensions.schemas import (
    serialize_catalog_item,
    serialize_extension_detail,
    serialize_version_summary,
)
from solus_api.models import Extension, ExtensionPublisher

router = APIRouter(prefix="/api/v1/extensions")

Slug = Annotated[str, Path(min_length=1, max_length=64)]
Cursor = Annotated[str | None, Query()]
Limit = Annotated[int, Query(ge=1, le=svc.CATALOG_LIMIT_MAX)]


async def _resolve(
    session: SessionDep, slug: str, user: CurrentUser
) -> tuple[Extension, ExtensionPublisher, bool]:
    """Validate the slug, load the live extension, and decide whether the
    caller is its publisher. Unknown slug → 404 for everyone."""
    found = await svc.get_extension_by_slug(session, svc.validate_slug(slug))
    if found is None:
        raise APIError(404, "not_found", "Extension not found")
    extension, publisher = found
    return extension, publisher, svc.is_publisher(publisher, user.id)


@router.get("")
async def list_extensions(
    user: CurrentUser,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=svc.CATALOG_QUERY_MAX_LENGTH)] = None,
    cursor: Cursor = None,
    limit: Limit = svc.CATALOG_LIMIT_DEFAULT,
) -> dict[str, Any]:
    rows, meta = await svc.list_approved_extensions(session, q=q, cursor=cursor, limit=limit)
    items = [serialize_catalog_item(r.extension, r.publisher, r.latest).payload() for r in rows]
    return envelope(items, meta)


@router.get("/{slug}")
async def get_extension(slug: Slug, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    extension, publisher, as_publisher = await _resolve(session, slug, user)
    latest = await svc.get_latest_approved_version(session, extension)
    if latest is None and not as_publisher:
        raise APIError(404, "not_found", "Extension not found")
    asset_paths = await svc.list_asset_paths(session, latest) if latest else []
    detail = serialize_extension_detail(extension, publisher, latest, asset_paths)
    return envelope(detail.payload())


@router.get("/{slug}/versions")
async def list_extension_versions(
    slug: Slug,
    user: CurrentUser,
    session: SessionDep,
    cursor: Cursor = None,
    limit: Limit = svc.CATALOG_LIMIT_DEFAULT,
) -> dict[str, Any]:
    extension, _publisher, as_publisher = await _resolve(session, slug, user)
    if extension.latest_approved_version_id is None and not as_publisher:
        raise APIError(404, "not_found", "Extension not found")
    versions, meta = await svc.list_versions_for(
        session, extension, as_publisher=as_publisher, cursor=cursor, limit=limit
    )
    items = [serialize_version_summary(v, as_publisher=as_publisher).payload() for v in versions]
    return envelope(items, meta)


__all__ = ["router"]
