"""The automated extension review job (SOLUSDEV-235 / ADR-035 §5, EXT-08).

``run_review`` is the core: it drives one published version through the
docs/schemas/extensions.md §5 state machine — ``pending → checking → approved |
rejected`` — using the pure validator (:func:`inspect_bundle`), extracts the
store-facing assets of §4.4 (the icon stored SANITIZED), recomputes the
extension's highest approved semver, and emits ``extension.review_completed``.
``extension_review`` is the ARQ entrypoint around it and never raises: an
unexpected failure rejects the version with ``"review: internal error"``.

Nothing here executes bundle content; every member read is bounded.
"""

from __future__ import annotations

import itertools
import logging
import re
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from solus_contracts.extension_manifest import LIMITS
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.extensions.bundle import BundleAsset, BundleReport, inspect_bundle, read_member
from solus_api.extensions.svg import sanitize_svg
from solus_api.models import (
    Extension,
    ExtensionPublisher,
    ExtensionReviewStatus,
    ExtensionVersion,
    ExtensionVersionAsset,
    User,
    utcnow,
)
from solus_api.services.events import emit_event
from solus_api.storage import ArtifactStore

logger = logging.getLogger("solus.extensions.review")

MAX_PROBLEMS = 200
MAX_PROBLEM_CHARS = 500
INTERNAL_ERROR_PROBLEM = "review: internal error"
REVIEW_COMPLETED_EVENT = "extension.review_completed"
_SVG_MEDIA_TYPE = "image/svg+xml"
_REVIEWABLE = frozenset({ExtensionReviewStatus.PENDING, ExtensionReviewStatus.CHECKING})
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")

SemverKey = tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]
_UNPARSEABLE: SemverKey = (-1, -1, -1, -1, ())


def semver_key(version: str) -> SemverKey:
    """Sort key implementing semver 2.0 precedence: numeric core, then a release
    outranks any pre-release of the same core, then pre-release identifiers
    (numeric < alphanumeric, shorter prefix < longer). Build metadata is ignored;
    an unparseable string sorts below everything so it can never become latest."""
    match = _SEMVER_RE.match(version)
    if match is None:
        return _UNPARSEABLE
    major, minor, patch, pre = match.groups()
    if pre is None:
        return (int(major), int(minor), int(patch), 1, ())
    idents: tuple[tuple[int, int | str], ...] = tuple(
        (0, int(part)) if part.isdigit() else (1, part) for part in pre.split(".")
    )
    return (int(major), int(minor), int(patch), 0, idents)


def cap_problems(problems: Iterable[str]) -> list[str]:
    """Bound what lands in ``review_problems`` (jsonb): ≤ 200 entries, ≤ 500 chars each."""
    return [p[:MAX_PROBLEM_CHARS] for p in itertools.islice(problems, MAX_PROBLEMS)]


@dataclass(frozen=True)
class _Target:
    """Identity of the version under review, captured before any commit or
    rollback can expire the ORM instance."""

    version_id: uuid.UUID
    extension_id: uuid.UUID
    version: str


@dataclass(frozen=True)
class _Outcome:
    status: ExtensionReviewStatus
    problems: list[str]


# ------------------------------------------------------------------ core
async def run_review(
    session: AsyncSession, store: ArtifactStore, version_id: uuid.UUID
) -> ExtensionReviewStatus:
    """Review one version; returns its final status.

    Idempotent: a version that is already ``approved`` or ``rejected`` is returned
    untouched. A version left ``checking`` by a crashed run is re-reviewed from
    scratch (its partial asset rows are replaced). Raises :class:`LookupError`
    when the version does not exist; every other failure ends in ``rejected``.
    """
    started = time.monotonic()
    version = await session.get(ExtensionVersion, version_id)
    if version is None:
        raise LookupError(f"extension version {version_id} not found")
    if version.review_status not in _REVIEWABLE:
        logger.info(
            "extension review skipped version=%s status=%s", version_id, version.review_status
        )
        return version.review_status
    target = _Target(version.id, version.extension_id, version.version)
    version.review_status = ExtensionReviewStatus.CHECKING
    await session.commit()

    try:
        outcome = await _check(session, store, target)
    except Exception:  # noqa: BLE001 — the job must settle the row, never leave `checking`
        logger.exception("extension review failed version=%s", target.version_id)
        await session.rollback()
        outcome = await _reject(session, target, [INTERNAL_ERROR_PROBLEM])

    duration_ms = int((time.monotonic() - started) * 1000)
    await _emit_completed(session, target, outcome, duration_ms)
    logger.info(
        "extension review completed version=%s status=%s problems=%d duration_ms=%d",
        target.version_id,
        outcome.status,
        len(outcome.problems),
        duration_ms,
    )
    return outcome.status


async def _check(session: AsyncSession, store: ArtifactStore, target: _Target) -> _Outcome:
    data = await store.get(str(target.version_id))
    report = inspect_bundle(data)
    if not report.ok or report.manifest is None:
        return await _reject(session, target, cap_problems(report.problems))
    await _replace_assets(session, store, target.version_id, data, report)
    await _approve(session, target)
    await session.commit()
    return _Outcome(ExtensionReviewStatus.APPROVED, [])


async def _reject(session: AsyncSession, target: _Target, problems: list[str]) -> _Outcome:
    await session.execute(
        update(ExtensionVersion)
        .where(ExtensionVersion.id == target.version_id)
        .values(
            review_status=ExtensionReviewStatus.REJECTED,
            review_problems=problems,
            published_at=None,
        )
    )
    await session.commit()
    return _Outcome(ExtensionReviewStatus.REJECTED, problems)


# ---------------------------------------------------------------- assets
def _asset_bytes(data: bytes, asset: BundleAsset) -> bytes:
    """Bounded read of one accepted store asset; the (only) SVG is the rail icon
    and is stored in its reduced form (docs/api/extensions.md §5.1)."""
    raw = read_member(data, asset.path, max_bytes=asset.size_bytes)
    if asset.media_type == _SVG_MEDIA_TYPE:
        return sanitize_svg(raw, LIMITS.icon_bytes).encode("utf-8")
    return raw


async def _replace_assets(
    session: AsyncSession,
    store: ArtifactStore,
    version_id: uuid.UUID,
    data: bytes,
    report: BundleReport,
) -> None:
    """Rows for a crashed earlier run are dropped first, so a re-review never
    trips the `(version_id, path)` unique constraint or leaves stale sizes."""
    await session.execute(
        delete(ExtensionVersionAsset).where(ExtensionVersionAsset.version_id == version_id)
    )
    seen: set[str] = set()
    for asset in report.assets:
        if asset.path in seen:
            continue
        seen.add(asset.path)
        payload = _asset_bytes(data, asset)
        row = ExtensionVersionAsset(
            version_id=version_id,
            path=asset.path,
            storage=store.backend,
            media_type=asset.media_type,
            size_bytes=len(payload),
        )
        session.add(row)
        await store.put(str(row.id), payload)
    await session.flush()


# -------------------------------------------------------------- approval
async def _approve(session: AsyncSession, target: _Target) -> None:
    version = await session.get(ExtensionVersion, target.version_id)
    if version is None:  # pragma: no cover — deleted mid-review; the outer handler rejects
        raise LookupError(f"extension version {target.version_id} vanished during review")
    version.review_status = ExtensionReviewStatus.APPROVED
    version.review_problems = []
    version.published_at = utcnow()
    await session.flush()
    await recompute_latest_approved(session, target.extension_id)


async def recompute_latest_approved(session: AsyncSession, extension_id: uuid.UUID) -> None:
    """Point `extensions.latest_approved_version_id` at the highest approved, live
    version (or NULL) and sync `name` / `summary` from that version's manifest —
    docs/schemas/extensions.md §4.2, §5. Shared with unpublish, which must repoint
    after a soft delete. Flushes; the caller commits."""
    extension = await session.get(Extension, extension_id)
    if extension is None:
        raise LookupError(f"extension {extension_id} not found")
    approved = await session.scalars(
        select(ExtensionVersion).where(
            ExtensionVersion.extension_id == extension_id,
            ExtensionVersion.review_status == ExtensionReviewStatus.APPROVED,
            ExtensionVersion.deleted_at.is_(None),
        )
    )
    latest = max(approved, key=lambda v: semver_key(v.version), default=None)
    extension.latest_approved_version_id = latest.id if latest else None
    if latest is not None:
        meta: dict[str, Any] = latest.manifest.get("extension", {})
        extension.name = str(meta.get("name") or extension.name)[: LIMITS.name]
        extension.summary = str(meta.get("summary") or extension.summary)[: LIMITS.summary]
    await session.flush()


# ---------------------------------------------------------------- events
async def _emit_completed(
    session: AsyncSession, target: _Target, outcome: _Outcome, duration_ms: int
) -> None:
    """ADR-011 event attributed to the publisher's user; a publisher whose account
    is gone (`user_id` NULL) has nobody to attribute to, so the event is skipped."""
    extension = await session.get(Extension, target.extension_id)
    publisher = await session.get(ExtensionPublisher, extension.publisher_id) if extension else None
    user = (
        await session.get(User, publisher.user_id)
        if publisher is not None and publisher.user_id is not None
        else None
    )
    if extension is None or user is None:
        logger.info(
            "extension review event skipped version=%s reason=no_publisher_user",
            target.version_id,
        )
        return
    emit_event(
        session,
        user=user,
        event_type=REVIEW_COMPLETED_EVENT,
        payload={
            "slug": extension.slug,
            "version": target.version,
            "review_status": outcome.status.value,
            "problem_count": len(outcome.problems),
            "duration_ms": duration_ms,
        },
    )
    await session.commit()


# ------------------------------------------------------------------- ARQ
async def extension_review(ctx: dict[str, Any], version_id: str) -> str:
    """ARQ task (`JobKind.EXTENSION_REVIEW`): review one published version.

    Returns the final status value, `""` when there is nothing to review (unknown
    or malformed id), or `"error"` when even settling the row failed. Never
    raises — mirrors `connectors/worker.py`: a bad bundle or a flaky backend must
    not poison the queue.
    """
    try:
        target_id = uuid.UUID(version_id)
    except ValueError:
        logger.error("extension review: malformed version id %r", version_id)
        return ""
    try:
        async with ctx["sessionmaker"]() as session:
            status = await run_review(session, ctx["artifact_store"], target_id)
    except LookupError:
        logger.warning("extension review: version %s not found", target_id)
        return ""
    except Exception:  # noqa: BLE001 — never raise to ARQ
        logger.exception("extension review: unrecoverable failure version=%s", target_id)
        return "error"
    return status.value
