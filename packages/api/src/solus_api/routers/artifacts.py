"""§4/docs/api/artifacts.md — project artifact upload/fetch. Multipart upload
(member+), metadata, and content routes, all scoped through `ProjectCtx` (§7
tenant isolation; non-member → 404, no existence leak).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request, Response
from starlette.datastructures import UploadFile

from solus_api.core.errors import APIError, error_response
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, SettingsDep, require_role
from solus_api.models import Role
from solus_api.schemas import serialize_artifact, serialize_artifact_ref
from solus_api.services.artifacts import (
    FixedWindowLimiter,
    create_artifact,
    get_artifact_metadata,
    read_artifact_content,
    read_bounded,
    validate_call_id,
    validate_media_type,
    validate_source_tool,
)
from solus_api.services.events import emit_event
from solus_api.storage import ArtifactStore

router = APIRouter(prefix="/api/v1/projects/{project_id}/artifacts")

_ALLOWED_FIELDS = frozenset({"file", "media_type", "source_tool", "call_id"})
# Slack over the byte cap so the multipart boilerplate (boundaries, the other
# form fields) never trips the Content-Length pre-check on a right-sized file.
_MULTIPART_OVERHEAD_BYTES = 8_192


def _get_artifact_store(request: Request) -> ArtifactStore:
    store: ArtifactStore = request.app.state.artifact_store
    return store


def _form_str(value: str | UploadFile | None) -> str | None:
    return value if isinstance(value, str) else None


def _reject_if_content_length_exceeds_cap(request: Request, max_bytes: int) -> None:
    """§4.4 half one: reject a declared-oversized (or absent/malformed) body
    before reading it.

    Phase 4 M1 fix: a request with NO `Content-Length` (a chunked-encoded
    body) used to sail straight through this check to `request.form()`,
    which spools the ENTIRE multipart body to disk/memory with no cap of its
    own — a chunked upload could exhaust the server before `read_bounded`'s
    streamed cap ever got a chance to run. Requiring a valid, in-cap
    `Content-Length` up front (`411 length_required` when absent/malformed,
    documented in docs/api/artifacts.md §5) closes that hole; a client that
    lies about a SMALL Content-Length still can't overshoot the cap, because
    `read_bounded` enforces it again while streaming."""
    declared = request.headers.get("content-length")
    if declared is None:
        raise APIError(411, "length_required", "Content-Length header is required for uploads")
    try:
        declared_bytes = int(declared)
    except ValueError:
        raise APIError(411, "length_required", "Content-Length header is invalid") from None
    if declared_bytes > max_bytes + _MULTIPART_OVERHEAD_BYTES:
        raise APIError(413, "payload_too_large", "Upload exceeds the size limit")


def _rate_limited(message: str, retry_after_seconds: int) -> Response:
    """§4.5: exceeded → 429 rate_limited + Retry-After."""
    resp = error_response(429, "rate_limited", message)
    resp.headers["Retry-After"] = str(retry_after_seconds)
    return resp


def _upload_request_limit_exceeded(request: Request, user_id: uuid.UUID, limit: int) -> bool:
    limiter: FixedWindowLimiter = request.app.state.artifact_upload_request_limiter
    return limiter.bump(str(user_id)) > limit


def _upload_byte_budget_exceeded(
    request: Request, team_id: uuid.UUID, accepted_bytes: int, limit: int
) -> bool:
    limiter: FixedWindowLimiter = request.app.state.artifact_upload_byte_limiter
    return limiter.bump(str(team_id), accepted_bytes) > limit


@router.post("", status_code=201, response_model=None)
async def upload_artifact(
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any] | Response:
    require_role(ctx, Role.MEMBER)
    store = _get_artifact_store(request)

    _reject_if_content_length_exceeds_cap(request, settings.artifact_max_bytes)
    if _upload_request_limit_exceeded(
        request, ctx.user.id, settings.artifact_uploads_per_minute_per_user
    ):
        return _rate_limited("Too many artifact uploads; slow down", retry_after_seconds=60)

    form = await request.form()
    unknown = set(form.keys()) - _ALLOWED_FIELDS
    if unknown:
        raise APIError(422, "validation_error", f"Unknown field(s): {', '.join(sorted(unknown))}")

    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise APIError(422, "validation_error", "file is required")

    media_type = validate_media_type(_form_str(form.get("media_type")))
    source_tool = validate_source_tool(_form_str(form.get("source_tool")))
    tool_call_id = validate_call_id(_form_str(form.get("call_id")))

    data = await read_bounded(upload, settings.artifact_max_bytes)
    if _upload_byte_budget_exceeded(
        request, ctx.team.id, len(data), settings.artifact_upload_bytes_per_hour_per_team
    ):
        return _rate_limited("Team upload byte budget exceeded", retry_after_seconds=3600)

    artifact = await create_artifact(
        session,
        store,
        project_id=ctx.project.id,
        created_by=ctx.user.id,
        data=data,
        media_type=media_type,
        source_tool=source_tool,
        tool_call_id=tool_call_id,
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="artifact.uploaded",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"artifact_id": str(artifact.id), "size_bytes": artifact.size_bytes},
    )
    await session.commit()
    return envelope(serialize_artifact_ref(artifact))


@router.get("/{artifact_id}")
async def get_artifact(
    artifact_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    artifact = await get_artifact_metadata(
        session,
        project_id=ctx.project.id,
        artifact_id=artifact_id,
        requester_id=ctx.user.id,
        requester_has_project_access=True,
        ttl_seconds=settings.artifact_ttl_seconds,
    )
    return envelope(serialize_artifact(artifact))


@router.get("/{artifact_id}/content")
async def get_artifact_content(
    artifact_id: uuid.UUID,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    # Phase 4 H1/M3 fix: this route used to fetch-AND-DESTROY on every GET
    # with no role check — a viewer or share-only user (ctx.membership is
    # None) could silently destroy a design export just by reading it once.
    # It is now (a) role-gated to `member`+ (viewer/share-only -> 403) and
    # (b) non-destructive: one-shot consumption is exclusive to
    # `services.artifacts.consume_tool_artifact`, never reachable from here.
    require_role(ctx, Role.MEMBER)
    store = _get_artifact_store(request)
    data, media_type = await read_artifact_content(
        session,
        store,
        project_id=ctx.project.id,
        artifact_id=artifact_id,
        requester_id=ctx.user.id,
        requester_has_project_access=True,
        ttl_seconds=settings.artifact_ttl_seconds,
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="artifact.viewed",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"artifact_id": str(artifact_id)},
    )
    await session.commit()
    return Response(content=data, media_type=media_type)
