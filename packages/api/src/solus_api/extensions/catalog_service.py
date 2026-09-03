"""Catalog READ queries for the extension store (SOLUSDEV-235 / ADR-035, EXT-06).

The query layer behind `docs/api/extensions.md` §4.1–§4.3. Tenant-free by
design (route plan §3: approved extensions are global content), so nothing here
takes a team or project — only the viewer's user id, which decides whether the
publisher-only rows (pending / checking / rejected versions, an unreleased
listing) are visible. Visibility is decided HERE, not in the router, so every
catalog route shares one no-existence-oracle posture.

Ordering (§4.1): `name ASC, id ASC` with an opaque cursor over `(name, id)` —
the `core.pagination` helper is `(created_at, id) DESC` only, so this module
carries its own codec in the same urlsafe-base64 JSON shape. Versions (§4.3)
sort semver-descending, which SQL cannot do on a text column; an extension's
version list is bounded, so it is sorted in Python and paged by version.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from solus_contracts.extension_manifest import EXTENSION_ID_PATTERN, SEMVER_PATTERN
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.models import (
    Extension,
    ExtensionPublisher,
    ExtensionReviewStatus,
    ExtensionVersion,
    ExtensionVersionAsset,
)

#: Route plan §4.1 — `q` cap and page sizes.
CATALOG_QUERY_MAX_LENGTH = 80
CATALOG_LIMIT_DEFAULT = 24
CATALOG_LIMIT_MAX = 100
#: `{slug}` is matched case-insensitively (§3), so the contract regex is applied the same way.
_SLUG_RE = re.compile(EXTENSION_ID_PATTERN, re.IGNORECASE)
_SEMVER_RE = re.compile(SEMVER_PATTERN)
_LIKE_ESCAPE = "\\"

SemverKey = tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]


# ----------------------------------------------------------------- validation
def validate_slug(slug: str) -> str:
    """§3: a path segment failing the id regex is `422` before any lookup."""
    if not _SLUG_RE.match(slug):
        raise APIError(422, "validation_error", "Malformed extension slug")
    return slug


# ------------------------------------------------------------------- cursors
def encode_cursor(parts: Sequence[str]) -> str:
    raw = json.dumps(list(parts)).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, arity: int) -> list[str]:
    """Opaque cursor → its `arity` string parts; anything else is `400 invalid_cursor`."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        parts = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, TypeError) as exc:
        raise APIError(400, "invalid_cursor", "Malformed pagination cursor") from exc
    if (
        not isinstance(parts, list)
        or len(parts) != arity
        or not all(isinstance(p, str) for p in parts)
    ):
        raise APIError(400, "invalid_cursor", "Malformed pagination cursor")
    return parts


def _page(rows: list[Any], limit: int, cursor_of: Any) -> tuple[list[Any], dict[str, Any]]:
    """Trim a limit+1 fetch into the API.md §1.4 `meta` block."""
    has_next = len(rows) > limit
    visible = rows[:limit]
    next_cursor = cursor_of(visible[-1]) if has_next and visible else None
    return visible, {"limit": limit, "has_next": has_next, "next_cursor": next_cursor}


# -------------------------------------------------------------------- semver
def _prerelease_ident(ident: str) -> tuple[int, int | str]:
    # SemVer §11: numeric identifiers sort before alphanumeric ones.
    return (0, int(ident)) if ident.isdigit() else (1, ident)


def semver_key(version: str) -> SemverKey:
    """Sort key implementing SemVer precedence; a release outranks its
    pre-releases. A non-semver string (impossible for contract-validated rows)
    sorts below every valid version rather than raising."""
    match = _SEMVER_RE.match(version)
    if match is None:
        return (-1, -1, -1, -1, ())
    major, minor, patch, prerelease = match.groups()
    idents = tuple(_prerelease_ident(p) for p in prerelease[1:].split(".")) if prerelease else ()
    return (int(major), int(minor), int(patch), 0 if prerelease else 1, idents)


# ------------------------------------------------------------------- queries
@dataclass(frozen=True)
class CatalogRow:
    extension: Extension
    publisher: ExtensionPublisher
    latest: ExtensionVersion


def _catalog_cursor(row: CatalogRow) -> str:
    return encode_cursor([row.extension.name, str(row.extension.id)])


def _search_clause(q: str) -> Any:
    escaped = q.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", r"\%").replace("_", r"\_")
    pattern = f"%{escaped}%"
    return or_(
        Extension.slug.ilike(pattern, escape=_LIKE_ESCAPE),
        Extension.name.ilike(pattern, escape=_LIKE_ESCAPE),
        Extension.summary.ilike(pattern, escape=_LIKE_ESCAPE),
    )


def _after_cursor(cursor: str) -> Any:
    name, raw_id = decode_cursor(cursor, 2)
    try:
        item_id = uuid.UUID(raw_id)
    except ValueError as exc:
        raise APIError(400, "invalid_cursor", "Malformed pagination cursor") from exc
    return or_(Extension.name > name, and_(Extension.name == name, Extension.id > item_id))


async def list_approved_extensions(
    session: AsyncSession, *, q: str | None, cursor: str | None, limit: int
) -> tuple[list[CatalogRow], dict[str, Any]]:
    """§4.1 — live extensions whose `latest_approved_version_id` names a live
    version, `name ASC, id ASC`, optionally narrowed by `q`."""
    stmt = (
        select(Extension, ExtensionPublisher, ExtensionVersion)
        .join(ExtensionPublisher, ExtensionPublisher.id == Extension.publisher_id)
        .join(ExtensionVersion, ExtensionVersion.id == Extension.latest_approved_version_id)
        .where(Extension.deleted_at.is_(None), ExtensionVersion.deleted_at.is_(None))
        .order_by(Extension.name.asc(), Extension.id.asc())
        .limit(limit + 1)
    )
    if q:
        stmt = stmt.where(_search_clause(q))
    if cursor:
        stmt = stmt.where(_after_cursor(cursor))
    rows = [CatalogRow(*row) for row in (await session.execute(stmt)).all()]
    return _page(rows, limit, _catalog_cursor)


async def get_extension_by_slug(
    session: AsyncSession, slug: str
) -> tuple[Extension, ExtensionPublisher] | None:
    """Live extension + its publisher by case-insensitive slug (the
    `lower(slug)` unique index makes this at most one row)."""
    stmt = (
        select(Extension, ExtensionPublisher)
        .join(ExtensionPublisher, ExtensionPublisher.id == Extension.publisher_id)
        .where(func.lower(Extension.slug) == slug.lower(), Extension.deleted_at.is_(None))
    )
    row = (await session.execute(stmt)).first()
    return (row[0], row[1]) if row else None


async def get_latest_approved_version(
    session: AsyncSession, extension: Extension
) -> ExtensionVersion | None:
    if extension.latest_approved_version_id is None:
        return None
    latest: ExtensionVersion | None = await session.scalar(
        select(ExtensionVersion).where(
            ExtensionVersion.id == extension.latest_approved_version_id,
            ExtensionVersion.deleted_at.is_(None),
        )
    )
    return latest


async def list_asset_paths(session: AsyncSession, version: ExtensionVersion) -> list[str]:
    """The `extension_version_assets.path` values recorded for `version` — the
    only paths §4.2 may turn into URLs."""
    stmt = select(ExtensionVersionAsset.path).where(ExtensionVersionAsset.version_id == version.id)
    return list((await session.scalars(stmt)).all())


def is_publisher(publisher: ExtensionPublisher, viewer_user_id: uuid.UUID) -> bool:
    return publisher.user_id is not None and publisher.user_id == viewer_user_id


def _version_cursor(version: ExtensionVersion) -> str:
    return encode_cursor([version.version])


def _after_version(versions: list[ExtensionVersion], cursor: str) -> list[ExtensionVersion]:
    (after,) = decode_cursor(cursor, 1)
    key = semver_key(after)
    return [v for v in versions if semver_key(v.version) < key]


async def list_versions_for(
    session: AsyncSession,
    extension: Extension,
    *,
    as_publisher: bool,
    cursor: str | None,
    limit: int,
) -> tuple[list[ExtensionVersion], dict[str, Any]]:
    """§4.3 — live versions newest first (semver DESC). Everyone sees
    `approved`; the publisher also sees `pending | checking | rejected`."""
    stmt = select(ExtensionVersion).where(
        ExtensionVersion.extension_id == extension.id, ExtensionVersion.deleted_at.is_(None)
    )
    if not as_publisher:
        stmt = stmt.where(ExtensionVersion.review_status == ExtensionReviewStatus.APPROVED)
    versions = sorted(
        (await session.scalars(stmt)).all(), key=lambda v: semver_key(v.version), reverse=True
    )
    if cursor:
        versions = _after_version(versions, cursor)
    return _page(versions[: limit + 1], limit, _version_cursor)
