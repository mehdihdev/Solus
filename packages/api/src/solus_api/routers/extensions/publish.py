"""§5.1 publish + §5.3 unpublish (SOLUSDEV-235 / ADR-035, EXT-07;
docs/api/extensions.md). Multipart upload hygiene mirrors `routers/artifacts.py`
(411/413 pre-check + streamed cap, unknown fields 422, per-user fixed window);
the bundle is inspected in the request path by the pure, bounded
`inspect_bundle` and then stored VERBATIM — never unzipped to disk, never run.

Exports `router`; the aggregator (`routers/extensions/__init__.py`) mounts it.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from solus_contracts.extension_manifest import LIMITS
from starlette.datastructures import UploadFile

from solus_api.core.errors import APIError, error_response
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, RequireVerified, SessionDep, SettingsDep
from solus_api.extensions.bundle import inspect_bundle
from solus_api.extensions.publishing import (
    IdempotencyRecord,
    IdempotencyStore,
    claim_extension,
    create_version,
    ensure_version_unused,
    get_or_create_publisher,
    not_found,
    recompute_latest_approved,
    resolve_version,
    validate_idempotency_key,
    validate_semver,
    validate_slug,
)
from solus_api.extensions.schemas import serialize_published_version
from solus_api.models import utcnow
from solus_api.services.artifacts import FixedWindowLimiter, read_bounded
from solus_api.services.events import emit_event
from solus_api.storage.extension_bundle_store import ExtensionBundleStore

logger = logging.getLogger("solus.extensions.publish")

router = APIRouter(prefix="/api/v1/extensions")

_ALLOWED_FIELDS = frozenset({"bundle"})
# Slack over the byte cap so multipart boilerplate never trips the pre-check
# on a right-sized bundle (same constant as the artifact upload route).
_MULTIPART_OVERHEAD_BYTES = 8_192
_PUBLISH_WINDOW_SECONDS = 3_600
#: ARQ function registered by `connectors/worker.py` (another EXT task).
REVIEW_JOB = "extension_review"


# ------------------------------------------------------------- app.state
def _publish_limiter(request: Request) -> FixedWindowLimiter:
    """Per-user hourly window (§12). Created lazily on `app.state` because
    `main.py` is outside this task's ownership; per-process like every other
    `FixedWindowLimiter` (artifacts.md §4.5 caveats apply)."""
    limiter: FixedWindowLimiter | None = getattr(
        request.app.state, "extension_publish_limiter", None
    )
    if limiter is None:
        limiter = FixedWindowLimiter(window_seconds=_PUBLISH_WINDOW_SECONDS)
        request.app.state.extension_publish_limiter = limiter
    return limiter


def _idempotency_store(request: Request) -> IdempotencyStore:
    store: IdempotencyStore | None = getattr(
        request.app.state, "extension_publish_idempotency", None
    )
    if store is None:
        store = IdempotencyStore()
        request.app.state.extension_publish_idempotency = store
    return store


def _bundle_store(request: Request) -> ExtensionBundleStore:
    return ExtensionBundleStore(request.app.state.artifact_store)


# ---------------------------------------------------------------- hygiene
def _require_content_length_within_cap(request: Request, max_bytes: int) -> None:
    """§5.1 step 1 (artifacts.md §4.4 M1): a chunked body would be spooled whole
    by `request.form()`, so an in-cap `Content-Length` is required up front."""
    declared = request.headers.get("content-length")
    if declared is None:
        raise APIError(411, "length_required", "Content-Length header is required for uploads")
    try:
        declared_bytes = int(declared)
    except ValueError:
        raise APIError(411, "length_required", "Content-Length header is invalid") from None
    if declared_bytes > max_bytes + _MULTIPART_OVERHEAD_BYTES:
        raise APIError(413, "payload_too_large", "Bundle exceeds the 25 MiB limit")


def _rate_limited(message: str, retry_after_seconds: int) -> Response:
    resp = error_response(429, "rate_limited", message)
    resp.headers["Retry-After"] = str(retry_after_seconds)
    return resp


async def _bundle_part(request: Request) -> UploadFile:
    form = await request.form()
    unknown = set(form.keys()) - _ALLOWED_FIELDS
    if unknown:
        raise APIError(422, "validation_error", f"Unknown field(s): {', '.join(sorted(unknown))}")
    upload = form.get("bundle")
    if not isinstance(upload, UploadFile):
        raise APIError(422, "validation_error", "bundle is required")
    return upload


def _replay_or_conflict(record: IdempotencyRecord, content_hash: str) -> dict[str, Any]:
    if record.content_hash != content_hash:
        raise APIError(
            409, "idempotency_conflict", "Idempotency-Key was already used with different bytes"
        )
    return record.body


async def _enqueue_review(app: FastAPI, version_id: uuid.UUID) -> None:
    """Hand the version to the ARQ review job. Without Redis (tests, bare dev)
    the enqueue is skipped — the version stays `pending` — mirroring how
    `routers/sources.py` gates its own enqueue on `settings.redis_url`."""
    if not app.state.settings.redis_url:
        logger.info("extension_review enqueue skipped (no redis) version=%s", version_id)
        return
    pool = await _arq_pool(app)
    await pool.enqueue_job(REVIEW_JOB, str(version_id))


async def _arq_pool(app: FastAPI) -> Any:
    pool = getattr(app.state, "arq_pool", None)
    if pool is None:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(app.state.settings.redis_url))
        app.state.arq_pool = pool
    return pool


# ------------------------------------------------------------------ routes
@router.post("/publish", status_code=202, response_model=None)
async def publish_extension(
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    _verified: RequireVerified,
) -> dict[str, Any] | Response:
    _require_content_length_within_cap(request, LIMITS.bundle_bytes)
    idempotency_key = validate_idempotency_key(request.headers.get("idempotency-key"))
    if (
        _publish_limiter(request).bump(str(user.id))
        > settings.extension_publishes_per_hour_per_user
    ):
        emit_event(
            session, user=user, event_type="extension.rate_limited", payload={"route": "publish"}
        )
        await session.commit()
        return _rate_limited("Too many publishes; slow down", _PUBLISH_WINDOW_SECONDS)

    upload = await _bundle_part(request)
    data = await read_bounded(upload, LIMITS.bundle_bytes)
    content_hash = hashlib.sha256(data).hexdigest()

    idempotency = _idempotency_store(request)
    if (record := idempotency.get(user.id, idempotency_key)) is not None:
        return _replay_or_conflict(record, content_hash)

    report = inspect_bundle(data)
    if not report.ok or report.manifest is None:
        raise APIError(422, "bundle_invalid", "Bundle failed validation", details=report.problems)
    manifest = report.manifest

    publisher = await get_or_create_publisher(
        session, user_id=user.id, display_name=manifest.extension.publisher
    )
    extension = await claim_extension(session, publisher=publisher, manifest=manifest)
    await ensure_version_unused(
        session, extension_id=extension.id, version=manifest.extension.version
    )
    version = await create_version(
        session,
        _bundle_store(request),
        extension=extension,
        manifest=manifest,
        data=data,
        content_hash=content_hash,
    )
    emit_event(
        session,
        user=user,
        event_type="extension.publish",
        payload={
            "slug": extension.slug,
            "version": version.version,
            "bundle_size_bytes": version.bundle_size_bytes,
            "content_hash": version.content_hash,
        },
    )
    await session.commit()
    await _enqueue_review(request.app, version.id)

    body = envelope(
        {
            "version": serialize_published_version(extension, version).payload(),
            "review": {"status": version.review_status.value, "problems": []},
        }
    )
    idempotency.put(user.id, idempotency_key, IdempotencyRecord(content_hash, body))
    return body


@router.delete("/{slug}/versions/{version}", status_code=204, response_class=Response)
async def unpublish_version(
    slug: str, version: str, user: CurrentUser, session: SessionDep, _verified: RequireVerified
) -> Response:
    """§5.3: publisher only (others 404); soft delete; the version string is
    burned; `latest_approved_version_id` falls back to the highest remaining
    approved semver or null. Stored bytes are kept — pinned installs still
    resolve the row and the desktop's ADR-034 cache stays valid."""
    resolved = await resolve_version(session, validate_slug(slug), validate_semver(version))
    if resolved is None or not resolved.is_owned_by(user.id):
        raise not_found()
    resolved.version.deleted_at = utcnow()
    await recompute_latest_approved(session, resolved.extension)
    emit_event(
        session,
        user=user,
        event_type="extension.unpublish",
        payload={"slug": resolved.extension.slug, "version": resolved.version.version},
    )
    await session.commit()
    return Response(status_code=204)
