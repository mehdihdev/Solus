"""Review status and the verified badge (SOLUSDEV-235 / ADR-035, EXT-08).

docs/api/extensions.md §5.2 — `GET …/versions/{version}/review`: publisher only,
everyone else `404` (a review you did not publish does not exist for you).
§5.4 — `PATCH /extensions/{slug}`: `RequireStaff` + `RequireVerified`, body
exactly `{verified: bool}`, returns the §4.2 detail shape, emits
`extension.verified_changed`. Auth is the centralized dependencies only.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from solus_contracts.extension_manifest import EXTENSION_ID_PATTERN, RESERVED_EXTENSION_IDS
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, RequireStaff, RequireVerified, SessionDep
from solus_api.extensions.schemas import (
    ExtensionDetail,
    serialize_extension_detail,
    serialize_review_status,
)
from solus_api.models import (
    Extension,
    ExtensionPublisher,
    ExtensionVersion,
    ExtensionVersionAsset,
    User,
)
from solus_api.services.events import emit_event

router = APIRouter(prefix="/api/v1/extensions")

VERIFIED_CHANGED_EVENT = "extension.verified_changed"
_SLUG_RE = re.compile(EXTENSION_ID_PATTERN)


class VerifiedPatch(BaseModel):
    """§5.4 body — one field, nothing else (`name`/`summary` come from the manifest)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    verified: bool


def _not_found() -> APIError:
    return APIError(404, "not_found", "Not found")


def _normalize_slug(slug: str) -> str:
    """§3: matched case-insensitively; anything outside the contract shape is a
    `422` before any lookup (no database round-trip on garbage)."""
    lowered = slug.lower()
    if not _SLUG_RE.match(lowered) or lowered in RESERVED_EXTENSION_IDS:
        raise APIError(422, "validation_error", "Invalid extension slug")
    return lowered


async def _live_extension(session: AsyncSession, slug: str) -> Extension:
    extension = await session.scalar(
        select(Extension).where(
            func.lower(Extension.slug) == _normalize_slug(slug), Extension.deleted_at.is_(None)
        )
    )
    if extension is None:
        raise _not_found()
    return extension


async def _publisher_of(session: AsyncSession, extension: Extension) -> ExtensionPublisher:
    publisher = await session.get(ExtensionPublisher, extension.publisher_id)
    if publisher is None:  # RESTRICT FK — unreachable unless the row was tampered with
        raise APIError(500, "internal_error", "Extension has no publisher")
    return publisher


async def _owned_extension(session: AsyncSession, slug: str, user: User) -> Extension:
    """The extension only if `user` is its publisher; otherwise `404`, never `403`."""
    extension = await _live_extension(session, slug)
    publisher = await _publisher_of(session, extension)
    if publisher.user_id != user.id:
        raise _not_found()
    return extension


async def _detail(session: AsyncSession, extension: Extension) -> ExtensionDetail:
    publisher = await _publisher_of(session, extension)
    latest: ExtensionVersion | None = None
    paths: Sequence[str] = ()
    if extension.latest_approved_version_id is not None:
        latest = await session.get(ExtensionVersion, extension.latest_approved_version_id)
    if latest is not None:
        paths = (
            await session.scalars(
                select(ExtensionVersionAsset.path).where(
                    ExtensionVersionAsset.version_id == latest.id
                )
            )
        ).all()
    return serialize_extension_detail(extension, publisher, latest, paths)


# ---------------------------------------------------------------- routes
@router.get("/{slug}/versions/{version}/review")
async def get_review_status(
    slug: str, version: str, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    extension = await _owned_extension(session, slug, user)
    row = await session.scalar(
        select(ExtensionVersion).where(
            ExtensionVersion.extension_id == extension.id,
            ExtensionVersion.version == version,
            ExtensionVersion.deleted_at.is_(None),
        )
    )
    if row is None:
        raise _not_found()
    return envelope(serialize_review_status(extension, row).payload())


@router.patch("/{slug}")
async def set_verified(
    slug: str,
    body: VerifiedPatch,
    user: CurrentUser,
    session: SessionDep,
    _verified: RequireVerified,
    _staff: RequireStaff,
) -> dict[str, Any]:
    extension = await _live_extension(session, slug)
    extension.verified = body.verified
    emit_event(
        session,
        user=user,
        event_type=VERIFIED_CHANGED_EVENT,
        payload={"slug": extension.slug, "verified": body.verified},
    )
    await session.flush()
    detail = await _detail(session, extension)
    await session.commit()
    return envelope(detail.payload())
