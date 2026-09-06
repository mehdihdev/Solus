"""Artifact upload/fetch business logic (SOLUSDEV-100 T4c,
docs/api/artifacts.md). Field validation, the bytes-first/row-after create
path, the §4.1 scope check, §4.2 TTL + one-shot consumption, and a small
per-key fixed-window limiter for the §4.5 upload budgets.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile
from uuid6 import uuid7

from solus_api.core.errors import APIError
from solus_api.models import (
    Artifact,
    ArtifactScope,
    Project,
    artifact_is_accessible,
    ensure_utc,
    utcnow,
)

if TYPE_CHECKING:
    from solus_api.storage import ArtifactStore

MAX_MEDIA_TYPE_LEN = 255
MAX_SOURCE_TOOL_LEN = 64
MAX_CALL_ID_LEN = 64  # matches artifacts.tool_call_id (String(64))
_READ_CHUNK_BYTES = 65_536
_MEDIA_TYPE_RE = re.compile(r"^[A-Za-z0-9][\w.+-]*/[A-Za-z0-9][\w.+-]*$")


def _validation_error(message: str) -> APIError:
    return APIError(422, "validation_error", message)


def validate_media_type(value: str | None) -> str:
    if not value or len(value) > MAX_MEDIA_TYPE_LEN or not _MEDIA_TYPE_RE.match(value):
        raise _validation_error("media_type must be a syntactically valid MIME type")
    return value


def validate_source_tool(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) > MAX_SOURCE_TOOL_LEN:
        raise _validation_error(f"source_tool must be at most {MAX_SOURCE_TOOL_LEN} characters")
    return value


def validate_call_id(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) > MAX_CALL_ID_LEN:
        raise _validation_error(f"call_id must be at most {MAX_CALL_ID_LEN} characters")
    return value


async def read_bounded(upload: UploadFile, max_bytes: int) -> bytes:
    """Read `upload` in chunks, aborting the instant the running total exceeds
    `max_bytes` — the streamed half of §4.4's "Content-Length + streaming"
    enforcement, so a lying Content-Length header can never overshoot the cap."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise APIError(413, "payload_too_large", "Upload exceeds the size limit")
        chunks.append(chunk)
    return b"".join(chunks)


async def create_artifact(
    session: AsyncSession,
    store: ArtifactStore,
    *,
    project_id: uuid.UUID,
    created_by: uuid.UUID,
    data: bytes,
    media_type: str,
    source_tool: str | None,
    tool_call_id: str | None,
) -> Artifact:
    """Bytes are written to the store FIRST; the row is only added/flushed once
    the write succeeds — a mid-write failure never leaves a DB row pointing at
    bytes that don't exist (a leftover blob with no row is harmless and inert;
    it never leaks, since no artifact_id reaches a client on that path)."""
    artifact_id = uuid7()
    await store.put(str(artifact_id), data)
    artifact = Artifact(
        id=artifact_id,
        project_id=project_id,
        scope=ArtifactScope.PROJECT,
        uri=f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/content",
        media_type=media_type,
        size_bytes=len(data),
        storage_location=store.backend,
        created_by=created_by,
        source_tool=source_tool,
        tool_call_id=tool_call_id,
    )
    session.add(artifact)
    await session.flush()
    return artifact


def _is_expired(artifact: Artifact, ttl_seconds: int, *, now: datetime | None = None) -> bool:
    if artifact.retained:  # a `.solus` document is kept, not a hand-off buffer (SOLUSDEV-240)
        return False
    return ensure_utc(artifact.created_at) + timedelta(seconds=ttl_seconds) <= (now or utcnow())


def _ensure_live_and_accessible(
    artifact: Artifact | None,
    *,
    ttl_seconds: int,
    requester_id: uuid.UUID,
    requester_has_project_access: bool,
) -> Artifact:
    """§3/§4 404 semantics: unknown, foreign, soft-deleted (consumed/expired),
    or a PRIVATE artifact you didn't create — all collapse to the SAME 404, so
    there is no existence oracle."""
    if artifact is None or artifact.deleted_at is not None or _is_expired(artifact, ttl_seconds):
        raise APIError(404, "not_found", "Artifact not found")
    if not artifact_is_accessible(
        scope=artifact.scope,
        created_by=artifact.created_by,
        requester_id=requester_id,
        requester_has_project_access=requester_has_project_access,
    ):
        raise APIError(404, "not_found", "Artifact not found")
    return artifact


async def get_artifact_metadata(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    artifact_id: uuid.UUID,
    requester_id: uuid.UUID,
    requester_has_project_access: bool,
    ttl_seconds: int,
) -> Artifact:
    artifact = await session.get(Artifact, artifact_id)
    if artifact is not None and artifact.project_id != project_id:
        artifact = None
    return _ensure_live_and_accessible(
        artifact,
        ttl_seconds=ttl_seconds,
        requester_id=requester_id,
        requester_has_project_access=requester_has_project_access,
    )


async def read_artifact_content(
    session: AsyncSession,
    store: ArtifactStore,
    *,
    project_id: uuid.UUID,
    artifact_id: uuid.UUID,
    requester_id: uuid.UUID,
    requester_has_project_access: bool,
    ttl_seconds: int,
) -> tuple[bytes, str]:
    """Non-destructive read of an artifact's bytes — the generic HTTP content
    route (docs/api/artifacts.md §4). Scope/TTL/accessibility-checked exactly
    like the metadata route (§3); NEVER consumes or deletes anything.

    Phase 4 H1/M3 fix: this route used to fetch-and-destroy on every GET with
    no role check, so ANY project reader (viewer, share-only) could silently
    destroy a design export by reading it once. One-shot consumption is not a
    property of a generic content-serving route at all — it is now exclusive
    to `consume_tool_artifact`, the bridge acquirer's own internal path."""
    artifact = await get_artifact_metadata(
        session,
        project_id=project_id,
        artifact_id=artifact_id,
        requester_id=requester_id,
        requester_has_project_access=requester_has_project_access,
        ttl_seconds=ttl_seconds,
    )

    from solus_api.storage import ArtifactNotFoundError

    try:
        data = await store.get(str(artifact.id))
    except ArtifactNotFoundError:
        raise APIError(404, "not_found", "Artifact not found") from None
    return data, artifact.media_type


async def consume_tool_artifact(
    session: AsyncSession,
    store: ArtifactStore,
    *,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    artifact_id: uuid.UUID,
    requester_id: uuid.UUID,
    source_tool: str,
    tool_call_id: str,
    ttl_seconds: int,
) -> tuple[bytes, str]:
    """THE ONLY artifact consumption path in the codebase (docs/api/artifacts.md
    §4.3, Phase 4 H1/M3 fix). Enforces every one of the six anti-forgery
    conditions before a companion's `tool_result`-referenced `ArtifactRef` is
    ever read, then soft-deletes the row and removes the backing bytes in the
    SAME transaction as the match — one-shot, first consumer wins, mirroring
    the FOR-UPDATE + same-transaction-soft-delete concurrency guarantee this
    replaces (previously `fetch_and_consume_content`, which only enforced
    project scope + accessibility; the three ToolCall-identity checks lived,
    duplicated and incompletely, in `connectors/mcp_acquire.py`).

    Never reachable via HTTP: `connectors/mcp_acquire.py`'s bridge export
    acquirer is this function's only caller, so a companion can never trigger
    consumption of an artifact through any client-facing route.

    All six conditions must hold, or the artifact is left completely
    untouched and a 404 is raised (no existence oracle, same posture as every
    other artifact read):

    1. `artifacts.project_id` == `project_id` (the call's bound project scope),
    2. the project's `team_id` == `team_id` (the call's bound team scope),
    3. `artifacts.created_by` == `requester_id` (the dispatched session user),
    4. `artifacts.source_tool` == `source_tool` (the dispatched `{server}.{tool}`),
    5. `artifacts.tool_call_id` == `tool_call_id` (the dispatched call id),
    6. the artifact is live — not already consumed, not TTL-expired.
    """
    artifact = await session.scalar(
        select(Artifact)
        .where(Artifact.id == artifact_id, Artifact.project_id == project_id)
        .with_for_update()
    )
    if artifact is None or artifact.deleted_at is not None or _is_expired(artifact, ttl_seconds):
        raise APIError(404, "not_found", "Artifact not found")

    project = await session.get(Project, project_id)
    if (
        project is None
        or project.team_id != team_id
        or artifact.created_by != requester_id
        or artifact.source_tool != source_tool
        or artifact.tool_call_id != tool_call_id
    ):
        raise APIError(404, "not_found", "Artifact not found")

    media_type = artifact.media_type
    storage_key = str(artifact.id)
    artifact.deleted_at = utcnow()
    await session.commit()

    from solus_api.storage import ArtifactNotFoundError

    try:
        data = await store.get(storage_key)
    except ArtifactNotFoundError:
        raise APIError(404, "not_found", "Artifact not found") from None
    await store.delete(storage_key)
    return data, media_type


async def sweep_expired_artifacts(
    session: AsyncSession,
    store: ArtifactStore,
    *,
    ttl_seconds: int,
    now: datetime | None = None,
) -> int:
    """ARQ cron target (§4.2): soft-deletes any live artifact past its TTL and
    removes its bytes. Registration is deferred — see the T4c completion
    report (the cron list lives in connectors/worker.py, owned by T4b)."""
    cutoff = (now or utcnow()) - timedelta(seconds=ttl_seconds)
    candidates = (
        await session.scalars(
            select(Artifact).where(
                Artifact.deleted_at.is_(None),
                Artifact.retained.is_(False),
                Artifact.created_at <= cutoff,
            )
        )
    ).all()
    for artifact in candidates:
        await store.delete(str(artifact.id))
        artifact.deleted_at = utcnow()
    if candidates:
        await session.commit()
    return len(candidates)


class FixedWindowLimiter:
    """Reusable per-key fixed-window counter — mirrors `core.ratelimit`'s
    bucket-key mechanics (SOLUSDEV-100 T4c) for named budgets that don't fit
    that ASGI middleware's per-path shape (a per-team accepted-BYTE budget, a
    per-user upload-request budget).

    Two known limits, both intentional for v1 (Phase 4 M2 — documented here,
    not silently left as a surprise): (a) **per-process, in-memory** — a
    multi-instance API deployment gets one independent counter per instance,
    so the real enforced limit is `limit * instance_count`; a shared Redis
    counter is the named follow-up when the API goes multi-instance (mirrors
    `bridge_revocation_poll_seconds`'s own documented single-instance gap).
    (b) counters are pruned lazily on `bump` — see `_evict_stale` — so memory
    stays bounded by the number of DISTINCT keys seen in the CURRENT window,
    never by the lifetime count of every key this process has ever seen."""

    def __init__(self, window_seconds: int = 60) -> None:
        self._window_seconds = window_seconds
        self._counters: dict[str, tuple[int, int]] = {}

    def bump(self, key: str, amount: int = 1) -> int:
        window = int(time.time()) // self._window_seconds
        self._evict_stale(window)
        stored_window, count = self._counters.get(key, (window, 0))
        if stored_window != window:
            count = 0
        count += amount
        self._counters[key] = (window, count)
        return count

    def _evict_stale(self, current_window: int) -> None:
        """Drop every counter from a window before the current one. Without
        this (Phase 4 M2), a key is added on first use and NEVER removed — a
        limiter driven by untrusted, high-cardinality keys (per-user ids,
        per-team ids) grows without bound for the life of the process."""
        stale_keys = [
            key for key, (window, _count) in self._counters.items() if window != current_window
        ]
        for key in stale_keys:
            del self._counters[key]
