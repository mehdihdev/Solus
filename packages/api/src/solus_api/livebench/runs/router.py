"""Member-only recording routes. Capture never starts a device or commands motion."""

import asyncio
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, ValidationError
from sqlalchemy import select, tuple_

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, require_role, require_verified
from solus_api.livebench.runs import analysis, narration, store
from solus_api.livebench.runs.capture import Capture, RunCaptureManager
from solus_api.livebench.runs.models import (
    MAX_BYTES,
    RunSummary,
    StrictModel,
    encode_manifest,
    parse_manifest,
)
from solus_api.livebench.runs.snapshot import portable_manifest, snapshot, validate_references
from solus_api.livebench.sessions import SessionNotFoundError
from solus_api.models import GraphEntity, Role, utcnow
from solus_api.services.artifacts import fetch_artifact_bytes, get_artifact_metadata
from solus_api.services.solus_graph import lock_project

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/bench/runs", dependencies=[Depends(require_verified)]
)
Name = Annotated[str, Field(min_length=1, max_length=120)]


class StartIn(StrictModel):
    robot_id: uuid.UUID
    session_id: uuid.UUID
    name: Name


class ImportIn(StrictModel):
    robot_id: uuid.UUID
    artifact_id: uuid.UUID
    name: Name
    origin: Literal["recorded", "synthetic"]


class CompareIn(StrictModel):
    baseline_id: uuid.UUID
    candidate_id: uuid.UUID


def manager(request: Request) -> RunCaptureManager:
    existing: RunCaptureManager | None = getattr(request.app.state, "bench_runs", None)
    if existing is None:
        existing = RunCaptureManager(
            request.app.state.sessionmaker,
            request.app.state.artifact_store,
            request.app.state.bench_sessions,
        )
        request.app.state.bench_runs = existing
        request.app.state.telemetry_plumbing.capture_sink = existing.ingest
    return existing


@router.post("", status_code=201)
async def start_run(
    ctx: ProjectCtx, session: SessionDep, body: StartIn, request: Request
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    captures = manager(request)
    await lock_project(session, ctx.project.id)
    active = list(
        await session.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == ctx.project.id,
                GraphEntity.kind == store.RUN_KIND,
                GraphEntity.deleted_at.is_(None),
                GraphEntity.attrs["summary"]["status"].astext == "running",
            )
        )
    )
    actual = [row for row in active if captures.contains(row.id)]
    if len(actual) >= 4 or len(captures.active) >= 64:
        raise APIError(409, "run_limit", "Stop an active run before starting another")
    try:
        bench = request.app.state.bench_sessions.get(ctx.project.id, body.session_id)
    except SessionNotFoundError:
        raise APIError(404, "not_found", "Session not found") from None
    if bench.status != "active":
        raise APIError(409, "session_inactive", "Run capture requires an active session")
    manifest = await snapshot(session, ctx.project.id, body.robot_id, bench)
    data = await asyncio.to_thread(encode_manifest, manifest)
    info = RunSummary(
        id=uuid.uuid4(),
        robot_id=body.robot_id,
        session_id=body.session_id,
        name=body.name,
        origin="live",
        status="running",
        started_at=manifest.started_at,
    )
    entity = store.new_record(ctx.project.id, info, ctx.user.id)
    session.add(entity)
    await session.flush()
    await store.save(
        session, request.app.state.artifact_store, entity, info, manifest, ctx.user.id, final=False
    )
    captures.add(Capture(ctx.project.id, ctx.user.id, info, manifest, len(data)))
    return envelope(info.model_dump(mode="json"))


@router.post("/import", status_code=201)
async def import_run(
    ctx: ProjectCtx, session: SessionDep, body: ImportIn, request: Request
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    settings = request.app.state.settings
    _, data = await fetch_artifact_bytes(
        session,
        request.app.state.artifact_store,
        project_id=ctx.project.id,
        artifact_id=body.artifact_id,
        requester_id=ctx.user.id,
        ttl_seconds=settings.artifact_ttl_seconds,
        max_bytes=MAX_BYTES,
    )
    try:
        manifest = await asyncio.to_thread(parse_manifest, data)
        manifest = await asyncio.to_thread(portable_manifest, manifest)
    except (ValueError, ValidationError):
        raise APIError(
            422, "invalid_run", "Run manifest is invalid or exceeds its bounds"
        ) from None
    if manifest.robot_id != body.robot_id:
        raise APIError(404, "not_found", "Recording does not match this robot")
    await validate_references(session, ctx.project.id, manifest)
    for sensor in manifest.sensors:
        await get_artifact_metadata(
            session,
            project_id=ctx.project.id,
            artifact_id=sensor.artifact_id,
            requester_id=ctx.user.id,
            requester_has_project_access=True,
            ttl_seconds=settings.artifact_ttl_seconds,
        )
    info = RunSummary(
        id=uuid.uuid4(),
        robot_id=body.robot_id,
        name=body.name,
        origin=body.origin,
        status="completed",
        started_at=manifest.started_at,
        ended_at=utcnow(),
        packet_count=len(manifest.packets),
    )
    entity = store.new_record(ctx.project.id, info, ctx.user.id)
    session.add(entity)
    await session.flush()
    await store.save(
        session, request.app.state.artifact_store, entity, info, manifest, ctx.user.id, final=True
    )
    return envelope(info.model_dump(mode="json"))


@router.get("")
async def list_runs(
    ctx: ProjectCtx,
    session: SessionDep,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: uuid.UUID | None = None,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    query = select(GraphEntity).where(
        GraphEntity.project_id == ctx.project.id,
        GraphEntity.kind == store.RUN_KIND,
        GraphEntity.origin == "system",
        GraphEntity.deleted_at.is_(None),
    )
    if cursor is not None:
        previous = await store.record(session, ctx.project.id, cursor)
        query = query.where(
            tuple_(GraphEntity.created_at, GraphEntity.id) < (previous.created_at, previous.id)
        )
    rows = list(
        await session.scalars(
            query.order_by(GraphEntity.created_at.desc(), GraphEntity.id.desc()).limit(limit + 1)
        )
    )
    captures = manager(request)
    summaries = []
    for row in rows[:limit]:
        info = store.summary(row)
        if info.status == "running" and not captures.contains(info.id):
            info.status = "interrupted"
        summaries.append(info.model_dump(mode="json"))
    return envelope(
        {"runs": summaries, "next_cursor": str(rows[limit - 1].id) if len(rows) > limit else None}
    )


@router.post("/compare")
async def compare_runs(
    ctx: ProjectCtx, session: SessionDep, request: Request, body: CompareIn
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    manifests = []
    for identity in (body.baseline_id, body.candidate_id):
        entity = await store.record(session, ctx.project.id, identity)
        if store.summary(entity).status == "running" and manager(request).contains(entity.id):
            raise APIError(409, "run_active", "Stop both runs before comparing")
        manifests.append(
            await store.load(
                session,
                request.app.state.artifact_store,
                entity,
                ctx.user.id,
                request.app.state.settings.artifact_ttl_seconds,
            )
        )
    try:
        result = await asyncio.to_thread(analysis.compare, *manifests)
    except ValueError:
        raise APIError(422, "robot_mismatch", "Compare runs of the same robot") from None
    return envelope(result)


@router.get("/{run_id}")
async def get_run(
    ctx: ProjectCtx, session: SessionDep, request: Request, run_id: uuid.UUID
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    entity = await store.record(session, ctx.project.id, run_id)
    info = store.summary(entity)
    if info.status == "running" and not manager(request).contains(run_id):
        info.status = "interrupted"
    manifest = await store.load(
        session,
        request.app.state.artifact_store,
        entity,
        ctx.user.id,
        request.app.state.settings.artifact_ttl_seconds,
    )
    return envelope(store.detail(info, manifest))


@router.post("/{run_id}/stop")
async def stop_run(
    ctx: ProjectCtx, session: SessionDep, request: Request, run_id: uuid.UUID
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    entity = await store.record(session, ctx.project.id, run_id)
    info = await manager(request).stop(run_id)
    if info is None:
        info = store.summary(entity)
        if info.status == "running":
            entity = await store.record(session, ctx.project.id, run_id, lock=True)
            info = store.summary(entity)
            if info.status == "running":
                info.status = "interrupted"
                info.ended_at = utcnow()
                manifest = await store.load(
                    session,
                    request.app.state.artifact_store,
                    entity,
                    ctx.user.id,
                    request.app.state.settings.artifact_ttl_seconds,
                )
                await store.save(
                    session,
                    request.app.state.artifact_store,
                    entity,
                    info,
                    manifest,
                    ctx.user.id,
                    final=True,
                )
    return envelope(info.model_dump(mode="json"))


@router.get("/{run_id}/findings")
async def get_findings(
    ctx: ProjectCtx, session: SessionDep, request: Request, run_id: uuid.UUID
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    entity = await store.record(session, ctx.project.id, run_id)
    manifest = await store.load(
        session,
        request.app.state.artifact_store,
        entity,
        ctx.user.id,
        request.app.state.settings.artifact_ttl_seconds,
    )
    result = await asyncio.to_thread(analysis.findings, manifest)
    result["evidence_origin"] = store.summary(entity).origin
    return envelope(result)


@router.post("/{run_id}/narrate")
async def narrate_run(
    ctx: ProjectCtx, session: SessionDep, request: Request, run_id: uuid.UUID
) -> dict[str, Any]:
    """Optional cheap-tier prose uses the authenticated user's metered gateway."""
    require_role(ctx, Role.MEMBER)
    entity = await store.record(session, ctx.project.id, run_id)
    manifest = await store.load(
        session,
        request.app.state.artifact_store,
        entity,
        ctx.user.id,
        request.app.state.settings.artifact_ttl_seconds,
    )
    result = await asyncio.to_thread(analysis.findings, manifest)
    evidence_origin = store.summary(entity).origin
    response = await narration.narrate(
        result,
        secret_store=request.app.state.secret_store,
        user_id=ctx.user.id,
        session=session,
        redis=getattr(request.app.state, "redis", None),
        enqueue=getattr(request.app.state, "enqueue", None),
        mode=ctx.user.sol_mode,
    )
    response["evidence_origin"] = evidence_origin
    return envelope(response)
