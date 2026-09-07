"""Sourcing routes (SOLUSDEV-246 ST5, docs/api/sourcing.md) — one engine for two doors.

`/api/v1/projects/{project_id}/sourcing/…` under `ProjectCtx`: reads are open
to every member; writes (rules, a request, a selection) take the `member`
floor and a per-user request budget. A request runs as a `JobKind.SOURCING`
job (ARQ when Redis is configured, inline otherwise) whose model call is
metered to the requesting user through the orchestration gateway.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectContext, ProjectCtx, SessionDep, SettingsDep, require_role
from solus_api.extensions.ratelimit import get_or_create_limiter, rate_limited_response
from solus_api.models import Job, JobKind, JobStatus, Role, SourcingRequest, utcnow
from solus_api.schemas import serialize_entity
from solus_api.services.events import emit_event
from solus_api.sourcing import service
from solus_api.sourcing.candidates import RequirementSpec
from solus_api.sourcing.engine import run_request
from solus_api.sourcing.rules import SourcingRules
from solus_api.sourcing.tools import derive_for_assembly
from solus_api.sourcing.torque import (
    DEFAULT_SAFETY_FACTOR,
    MAX_SAFETY_FACTOR,
    MIN_SAFETY_FACTOR,
    torque_from_spec,
)
from solus_api.sourcing.worker import SOURCING_JOB

router = APIRouter(prefix="/api/v1/projects/{project_id}/sourcing")

logger = logging.getLogger(__name__)

REQUESTS_PER_MINUTE_PER_USER = 10
_LIMITER = "sourcing_request_limiter"
_WINDOW = 60
Pivot = Annotated[list[float], Field(min_length=3, max_length=3)]
Safety = Annotated[float, Field(ge=MIN_SAFETY_FACTOR, le=MAX_SAFETY_FACTOR)]
Masses = Annotated[
    dict[uuid.UUID, Annotated[float, Field(ge=0, le=1_000_000)]], Field(max_length=500)
]


class TorqueBody(BaseModel):
    """Either an assembly (geometry + masses) or a plain spec (load at arm)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    assembly_entity_id: uuid.UUID | None = None
    pivot_mm: Pivot | None = None
    masses: Masses | None = None
    load_kg: Annotated[float, Field(ge=0, le=100_000)] | None = None
    arm_m: Annotated[float, Field(ge=0, le=1000)] | None = None
    safety_factor: Safety = DEFAULT_SAFETY_FACTOR


PreferenceText = Annotated[str, StringConstraints(max_length=2400)] | None


class PreferencesBody(BaseModel):
    """The `~/.solus/preferences.json` sections the engine reads (engine.PREFERENCE_KEYS) —
    ranking context only. Other sections of the user's file are dropped at the boundary, never
    stored (security review M3)."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    mechanical: PreferenceText = None
    electrical: PreferenceText = None
    unitsStandards: PreferenceText = None  # noqa: N815 — the file's own key
    freeText: PreferenceText = None  # noqa: N815


class RequestBody(TorqueBody):
    spec: RequirementSpec = RequirementSpec()
    door: Literal["workspace", "bom"] = "bom"
    #: The user's `~/.solus/preferences.json` sections, ranking context only (SOLUSDEV-244).
    preferences: PreferencesBody | None = None


class SelectBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]
    category_entity_id: uuid.UUID | None = None
    quantity: Annotated[int, Field(ge=1, le=100_000)] = 1


def _budget(request: Request, ctx: ProjectContext) -> Response | None:
    limiter = get_or_create_limiter(request.app.state, _LIMITER, _WINDOW)
    if limiter.bump(str(ctx.user.id)) <= REQUESTS_PER_MINUTE_PER_USER:
        return None
    return rate_limited_response("Too many sourcing requests; slow down", _WINDOW)


def _emit(ctx: ProjectContext, session: Any, event_type: str, payload: dict[str, Any]) -> None:
    emit_event(
        session,
        user=ctx.user,
        event_type=event_type,
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload=payload,
    )


def serialize_request(row: SourcingRequest) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "status": row.status.value,
        "door": row.door,
        "spec": {k: v for k, v in row.spec.items() if k != "preferences"},
        "torque": row.torque,
        "assembly_entity_id": str(row.assembly_entity_id) if row.assembly_entity_id else None,
        "candidates": row.candidates,
        "excluded": row.excluded,
        "rules": row.rules,
        "model": row.model,
        "error": row.error,
        "job_id": str(row.job_id) if row.job_id else None,
        "selected_candidate_id": row.selected_candidate_id,
        "selected_entity_id": str(row.selected_entity_id) if row.selected_entity_id else None,
        "created_at": row.created_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


# --------------------------------------------------------------------- rules


@router.get("/rules")
async def get_rules(ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    return envelope((await service.load_rules(session, ctx.project.id)).payload())


@router.put("/rules")
async def put_rules(body: SourcingRules, ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    await service.save_rules(session, ctx.project.id, body)
    _emit(
        ctx,
        session,
        "sourcing.rules_updated",
        {
            "excluded_suppliers": len(body.excluded_suppliers),
            "required_certifications": len(body.required_certifications),
            "max_voltage_v": body.max_voltage_v,
            "allowed_protocols": len(body.allowed_protocols),
        },
    )
    await session.commit()
    return envelope((await service.load_rules(session, ctx.project.id)).payload())


# -------------------------------------------------------------------- torque


async def _torque_payload(
    session: Any, ctx: ProjectContext, body: TorqueBody
) -> dict[str, Any] | None:
    """Assembly-derived when an assembly is named, spec-derived when a load and
    arm are given, None when neither (a request may still run without torque)."""
    if body.assembly_entity_id is not None:
        pivot = tuple(body.pivot_mm) if body.pivot_mm else None
        return await derive_for_assembly(
            session,
            ctx.project.id,
            body.assembly_entity_id,
            pivot_mm=pivot,  # type: ignore[arg-type]
            masses=body.masses,
            safety_factor=body.safety_factor,
        )
    if body.load_kg is not None and body.arm_m is not None:
        try:
            return torque_from_spec(
                load_kg=body.load_kg, arm_m=body.arm_m, safety_factor=body.safety_factor
            ).payload()
        except ValueError as exc:
            raise APIError(422, "validation_error", str(exc)) from exc
    return None


@router.post("/torque", response_model=None)
async def derive_torque_route(
    body: TorqueBody, request: Request, ctx: ProjectCtx, session: SessionDep
) -> Any:
    if (limited := _budget(request, ctx)) is not None:
        return limited
    payload = await _torque_payload(session, ctx, body)
    if payload is None:
        raise APIError(422, "validation_error", "Name an assembly, or give load_kg and arm_m")
    return envelope(payload)


# ------------------------------------------------------------------ requests


async def _dispatch(
    request: Request, background: BackgroundTasks, settings: Any, request_id: uuid.UUID
) -> None:
    app = request.app
    if settings.redis_url and not getattr(settings, "sync_inline", False):
        from solus_api.routers.sources import _arq_pool  # the one ARQ pool per process

        pool = await _arq_pool(app)
        await pool.enqueue_job(SOURCING_JOB, str(request_id))
        return
    background.add_task(
        run_request,
        app.state.sessionmaker,
        request_id,
        secret_store=app.state.secret_store,
        adapters=getattr(app.state, "orchestration_adapters", None),
        config=getattr(app.state, "orchestration_config", None),
        redis=getattr(app.state, "redis", None),
        enqueue=getattr(app.state, "enqueue", None),
    )


@router.post("/requests", status_code=202, response_model=None)
async def create_request(
    body: RequestBody,
    request: Request,
    background: BackgroundTasks,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
) -> Any:
    require_role(ctx, Role.MEMBER)
    if (limited := _budget(request, ctx)) is not None:
        return limited
    torque = await _torque_payload(session, ctx, body)
    if torque is None and not body.spec.text.strip():
        # A metered call needs an ask (the client refuses the same; the boundary must too).
        raise APIError(
            422,
            "validation_error",
            "Describe the requirement, give load_kg and arm_m, or name an assembly",
        )
    spec = body.spec.model_dump(mode="json")
    if torque is not None and "assembly" in torque:
        spec["assembly_name"] = torque["assembly"]
    if body.preferences:
        sections = body.preferences.model_dump(exclude_none=True)
        if sections:
            spec["preferences"] = sections
    job = Job(
        project_id=ctx.project.id,
        team_id=ctx.team.id,
        kind=JobKind.SOURCING,
        status=JobStatus.QUEUED,
        created_by=ctx.user.id,
    )
    session.add(job)
    await session.flush()
    row = SourcingRequest(
        project_id=ctx.project.id,
        created_by=ctx.user.id,
        door=body.door,
        spec=spec,
        torque=torque,
        assembly_entity_id=body.assembly_entity_id,
        job_id=job.id,
    )
    session.add(row)
    await session.flush()
    _emit(
        ctx,
        session,
        "sourcing.requested",
        {
            "request_id": str(row.id),
            "door": body.door,
            "has_assembly": body.assembly_entity_id is not None,
            "has_torque": torque is not None,
        },
    )
    await session.commit()
    try:
        await _dispatch(request, background, settings, row.id)
    except Exception:  # noqa: BLE001 — the row is committed; never strand it QUEUED
        logger.exception("sourcing: could not dispatch request %s", row.id)
        row.status = JobStatus.FAILED
        row.error = {"code": "dispatch_failed", "message": "Solus could not start sourcing."}
        row.finished_at = utcnow()
        job.status = JobStatus.FAILED
        job.error = row.error
        job.finished_at = utcnow()
        await session.commit()
    return JSONResponse(
        status_code=202,
        content=envelope({"request": serialize_request(row), "job_id": str(job.id)}),
    )


@router.get("/requests")
async def list_requests(
    ctx: ProjectCtx,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    rows = await service.list_requests(session, ctx.project.id, limit=limit)
    return envelope([serialize_request(r) for r in rows])


@router.get("/requests/{request_id}")
async def get_request(
    request_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    return envelope(
        serialize_request(await service.get_request(session, ctx.project.id, request_id))
    )


@router.post("/requests/{request_id}/select", status_code=201)
async def select_candidate(
    request_id: uuid.UUID, body: SelectBody, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    row = await service.get_request(session, ctx.project.id, request_id)
    candidate = service.candidate_of(row, body.candidate_id)
    if candidate is None:
        raise APIError(404, "not_found", "No such candidate on this request")
    part = await service.select_candidate(
        session,
        request=row,
        candidate=candidate,
        user_id=ctx.user.id,
        category_id=body.category_entity_id,
        quantity=body.quantity,
    )
    _emit(
        ctx,
        session,
        "sourcing.selected",
        {
            "request_id": str(row.id),
            "candidate_id": candidate.id,
            "entity_id": str(part.id),
            "grounding": candidate.grounding,
            "door": row.door,
        },
    )
    await session.commit()
    await session.refresh(part)
    return envelope({"entity": serialize_entity(part), "request": serialize_request(row)})


__all__ = ["router"]
