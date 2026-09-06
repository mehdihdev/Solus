"""Publishing business logic (SOLUSDEV-235 / ADR-035, EXT-07;
docs/api/extensions.md §3, §4.4, §4.5, §5.1, §5.3).

Pure functions over the session: path-segment validation, the slug claim, the
version create (bytes first, row after — the `create_artifact` posture), the
§5.3 `latest_approved_version_id` recompute, the §4.4 visibility rule shared by
the bundle/asset/review/unpublish routes, and the per-process `Idempotency-Key`
store. No FastAPI objects; errors are `APIError`s carrying the §13 codes.
"""

from __future__ import annotations

import re
import time
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

from solus_contracts.extension_manifest import SEMVER_PATTERN, ExtensionManifest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from solus_api.core.errors import APIError
from solus_api.models import (
    Extension,
    ExtensionPublisher,
    ExtensionReviewStatus,
    ExtensionVersion,
)
from solus_api.storage.extension_bundle_store import ExtensionBundleStore

_SEMVER_RE = re.compile(SEMVER_PATTERN)
_MAX_IDEMPOTENCY_KEY_LEN = 255

#: Phase 4 M4 — display names a FIRST publish may not seed a publisher row with.
#: Compared after :func:`normalize_publisher_name`, so case, spacing,
#: punctuation and the usual lookalike glyphs make no difference.
RESERVED_PUBLISHER_NAMES: frozenset[str] = frozenset(
    {"solus", "solusforge", "solusrobotics", "solusteam", "solusstaff"}
)
#: Lookalikes folded into the ASCII letter they impersonate. Digits/symbols
#: first, then the Cyrillic and Greek glyphs that render identically to Latin.
_HOMOGLYPHS: dict[str, str] = {
    "0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g",
    "|": "l", "!": "i", "$": "s", "@": "a",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i",
    "ѕ": "s", "ԁ": "d", "ɡ": "g", "ı": "i", "α": "a", "ο": "o", "ν": "v", "τ": "t", "ε": "e",
}  # fmt: skip


# ------------------------------------------------------------ path segments
def normalize_publisher_name(display_name: str) -> str:
    """Lower-case, NFKC-fold, map lookalike glyphs, keep `[a-z0-9]` only."""
    folded = unicodedata.normalize("NFKC", display_name).lower()
    mapped = "".join(_HOMOGLYPHS.get(ch, ch) for ch in folded)
    return "".join(ch for ch in mapped if ch.isascii() and ch.isalnum())


def is_reserved_publisher_name(display_name: str) -> bool:
    return normalize_publisher_name(display_name) in RESERVED_PUBLISHER_NAMES


def validate_semver(version: str) -> str:
    """§3: `{version}` is a semver string exactly as stored; garbage is 422."""
    if not _SEMVER_RE.match(version):
        raise APIError(422, "validation_error", "version must be a semver string")
    return version


def validate_idempotency_key(value: str | None) -> str:
    """§5.1: the header is REQUIRED (orchestrator decision: `400
    idempotency_key_required`, not the route plan's 422 — see the EXT-07 report)."""
    if value is None or not value.strip():
        raise APIError(400, "idempotency_key_required", "Idempotency-Key header is required")
    if len(value) > _MAX_IDEMPOTENCY_KEY_LEN:
        raise APIError(422, "validation_error", "Idempotency-Key is too long")
    return value


def semver_key(version: str) -> tuple[int, int, int, int, str]:
    """Sort key with semver precedence: numeric core, then a release outranks any
    pre-release of the same core (`1.0.0-rc.1 < 1.0.0`)."""
    core, _, prerelease = version.partition("-")
    major, minor, patch = (int(part) for part in core.split("."))
    return major, minor, patch, 0 if prerelease else 1, prerelease


# ------------------------------------------------------------- idempotency
@dataclass(frozen=True)
class IdempotencyRecord:
    """What a replay returns: the original 202 body, bound to the bytes' sha256."""

    content_hash: str
    body: dict[str, Any]


class IdempotencyStore:
    """Per-user `Idempotency-Key` → original 202 (§5.1).

    Deliberately **per-process, in-memory**, like every `FixedWindowLimiter` on
    `app.state`: a multi-instance deployment sees a replay on another instance as
    a fresh publish, which the `(extension, version)` uniqueness then turns into
    `409 version_exists` — safe (never a duplicate row), just not the replayed
    202. A shared Redis record is the named follow-up when the API goes
    multi-instance. Entries expire after `ttl_seconds` and are evicted lazily on
    write so memory stays bounded by recent, distinct keys."""

    def __init__(self, ttl_seconds: int = 86_400, max_entries: int = 10_000) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._entries: dict[tuple[str, str], tuple[float, IdempotencyRecord]] = {}

    def get(self, user_id: uuid.UUID, key: str) -> IdempotencyRecord | None:
        entry = self._entries.get((str(user_id), key))
        if entry is None or entry[0] <= time.time():
            return None
        return entry[1]

    def put(self, user_id: uuid.UUID, key: str, record: IdempotencyRecord) -> None:
        self._evict(time.time())
        self._entries[(str(user_id), key)] = (time.time() + self._ttl, record)

    def _evict(self, now: float) -> None:
        stale = [k for k, (expires, _r) in self._entries.items() if expires <= now]
        for k in stale:
            del self._entries[k]
        while len(self._entries) >= self._max:
            del self._entries[next(iter(self._entries))]


# ------------------------------------------------------------- slug claim
async def find_extension_by_slug(session: AsyncSession, slug: str) -> Extension | None:
    """Case-insensitive, over ALL rows — a slug is never re-claimable (§4.2 schema)."""
    extension: Extension | None = await session.scalar(
        select(Extension).where(func.lower(Extension.slug) == slug.lower())
    )
    return extension


async def get_or_create_publisher(
    session: AsyncSession, *, user_id: uuid.UUID, display_name: str, is_staff: bool = False
) -> ExtensionPublisher:
    """§5.1 step 3: the row is created on the user's first publish; `display_name`
    is seeded from the manifest then and not rewritten by later publishes. A
    reserved (vendor-impersonating) name is refused at that seeding moment only
    — `409 publisher_name_reserved` — so existing publishers are unaffected.
    Solus staff (SOLUSDEV-246) may seed a reserved name: a first-party bundle
    really is published by Solus, and the check exists to stop impersonation."""
    publisher = await session.scalar(
        select(ExtensionPublisher).where(
            ExtensionPublisher.user_id == user_id, ExtensionPublisher.deleted_at.is_(None)
        )
    )
    reserved = APIError(409, "publisher_name_reserved", "This publisher name is reserved for Solus")
    if publisher is None:
        if is_reserved_publisher_name(display_name) and not is_staff:
            raise reserved
        publisher = ExtensionPublisher(user_id=user_id, display_name=display_name)
        session.add(publisher)
        await session.flush()
    elif is_reserved_publisher_name(publisher.display_name) and not is_staff:
        # A publisher seeded under a reserved name while on staff stops
        # publishing as "Solus" the moment the account leaves the staff list.
        raise reserved
    return publisher


async def claim_extension(
    session: AsyncSession, *, publisher: ExtensionPublisher, manifest: ExtensionManifest
) -> Extension:
    """§5.1 step 3: a new slug becomes this publisher's; someone else's → 409 slug_taken."""
    meta = manifest.extension
    extension = await find_extension_by_slug(session, meta.id)
    if extension is None:
        extension = Extension(
            slug=meta.id, publisher_id=publisher.id, name=meta.name, summary=meta.summary
        )
        session.add(extension)
        await session.flush()
        return extension
    if extension.publisher_id != publisher.id:
        raise APIError(409, "slug_taken", "This extension id is owned by another publisher")
    return extension


async def ensure_version_unused(
    session: AsyncSession, *, extension_id: uuid.UUID, version: str
) -> None:
    """§5.1 step 3: `(extension, version)` is unique over ALL rows, soft-deleted included."""
    existing = await session.scalar(
        select(ExtensionVersion.id).where(
            ExtensionVersion.extension_id == extension_id, ExtensionVersion.version == version
        )
    )
    if existing is not None:
        raise APIError(409, "version_exists", "This version has already been published")


async def create_version(
    session: AsyncSession,
    store: ExtensionBundleStore,
    *,
    extension: Extension,
    manifest: ExtensionManifest,
    data: bytes,
    content_hash: str,
) -> ExtensionVersion:
    """§5.1 steps 4–5: bytes into the store FIRST under key = the new row id; the
    `pending` row is added only once the write succeeds (a leftover blob with no
    row is inert — its key never reaches a client)."""
    version_id = uuid7()
    await store.put_bundle(version_id, data)
    version = ExtensionVersion(
        id=version_id,
        extension_id=extension.id,
        version=manifest.extension.version,
        manifest=manifest.model_dump(mode="json", exclude_none=True),
        bundle_storage=store.backend,
        content_hash=content_hash,
        bundle_size_bytes=len(data),
        review_status=ExtensionReviewStatus.PENDING,
    )
    session.add(version)
    await session.flush()
    return version


# --------------------------------------------------------------- visibility
@dataclass(frozen=True)
class ResolvedVersion:
    extension: Extension
    publisher: ExtensionPublisher
    version: ExtensionVersion

    def is_owned_by(self, user_id: uuid.UUID) -> bool:
        return self.publisher.user_id == user_id

    def is_visible_to(self, user_id: uuid.UUID) -> bool:
        """§4.4: approved → everyone signed in; anything else → the publisher only."""
        approved = self.version.review_status == ExtensionReviewStatus.APPROVED
        return approved or self.is_owned_by(user_id)


async def resolve_version(session: AsyncSession, slug: str, version: str) -> ResolvedVersion | None:
    """The live (not soft-deleted) version row behind `{slug}/{version}`, with its
    extension and publisher — or None, which every caller collapses to 404."""
    extension = await find_extension_by_slug(session, slug)
    if extension is None or extension.deleted_at is not None:
        return None
    row = await session.scalar(
        select(ExtensionVersion).where(
            ExtensionVersion.extension_id == extension.id,
            ExtensionVersion.version == version,
            ExtensionVersion.deleted_at.is_(None),
        )
    )
    publisher = await session.get(ExtensionPublisher, extension.publisher_id)
    if row is None or publisher is None:
        return None
    return ResolvedVersion(extension=extension, publisher=publisher, version=row)


def not_found() -> APIError:
    """§3: unknown, foreign, unapproved-to-a-non-publisher and deleted all collapse
    to the SAME 404 — never a 403, so nothing is an existence oracle."""
    return APIError(404, "not_found", "Extension version not found")


async def resolve_visible_version(
    session: AsyncSession, slug: str, version: str, *, user_id: uuid.UUID
) -> ResolvedVersion:
    resolved = await resolve_version(session, slug, version)
    if resolved is None or not resolved.is_visible_to(user_id):
        raise not_found()
    return resolved


# ---------------------------------------------------------------- unpublish
async def recompute_latest_approved(session: AsyncSession, extension: Extension) -> None:
    """§5.3: the highest remaining live approved semver, or null (which removes the
    extension from the catalog entirely)."""
    approved = (
        await session.scalars(
            select(ExtensionVersion).where(
                ExtensionVersion.extension_id == extension.id,
                ExtensionVersion.deleted_at.is_(None),
                ExtensionVersion.review_status == ExtensionReviewStatus.APPROVED,
            )
        )
    ).all()
    latest = max(approved, key=lambda row: semver_key(row.version), default=None)
    extension.latest_approved_version_id = latest.id if latest else None
