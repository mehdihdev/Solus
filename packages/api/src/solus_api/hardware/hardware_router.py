"""docs/api/hardware.md §2-3 — the robot's config document, authored parts and lifecycle
promotion, and the link-suggestion inbox. All scoped through `ProjectCtx` (§7: non-member →
404); writes need the member role; every mutation emits a data event.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, require_role
from solus_api.graph.live import graph_changed_frame
from solus_api.hardware.config import HardwareConfig, LifecycleState, Scalar
from solus_api.hardware.detect import (
    ConfirmIn,
    DetectedDeviceOut,
    ProposeIn,
    bind_device,
    bound_repo_config_ids,
    confirm_proposal,
    exclude_bound,
    propose_via_local,
    reconcile_device,
    validated_repo_root,
)
from solus_api.hardware.links import decide_suggestion, list_suggestions, serialize_suggestion
from solus_api.hardware.store import (
    MAX_ATTACH,
    MAX_SPECS,
    attach_existing_parts,
    create_part,
    ensure_config,
    promote,
    put_config,
    robot_root,
    unassigned_parts_stmt,
)
from solus_api.livebench.bench_router import get_bench_local, get_session_manager
from solus_api.models import GraphEntity, HardwareSuggestion, Role, SuggestionStatus, utcnow
from solus_api.schemas import serialize_entity
from solus_api.services.events import emit_event
from solus_api.services.physical_robots import GraphChangeCounts

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/projects/{project_id}/hardware")

#: The seven categories (the store re-checks against `ROBOT_CATEGORIES`, the one source).
Category = Literal[
    "sensors", "actuators", "controllers", "end_effectors", "power", "structure", "wiring"
]


class ConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: HardwareConfig


class PartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512, strict=True)
    ]
    category: Category
    specs: dict[str, Scalar] = Field(default_factory=dict, max_length=MAX_SPECS)
    lifecycle: LifecycleState = LifecycleState.PLANNED


class LifecycleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: LifecycleState


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=512)


def _emit_hardware_event(
    ctx: ProjectCtx, session: SessionDep, event_type: str, payload: dict[str, Any]
) -> None:
    emit_event(
        session,
        user=ctx.user,
        event_type=event_type,
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload=payload,
    )


def _config_view(entry_id: uuid.UUID, config: HardwareConfig) -> dict[str, Any]:
    return {
        "entry_id": entry_id,
        "robot_entity_id": config.robot_entity_id,
        "config": config.model_dump(mode="json"),
    }


@router.get("/robots/{robot_id}/config")
async def get_config(robot_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    robot = await robot_root(session, ctx.project.id, robot_id)
    entry, config = await ensure_config(session, ctx.project.id, robot, created_by=ctx.user.id)
    await session.commit()  # a first read creates the entry; it must persist
    return envelope(_config_view(entry.id, config))


@router.put("/robots/{robot_id}/config")
async def replace_config(
    robot_id: uuid.UUID, body: ConfigIn, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    robot = await robot_root(session, ctx.project.id, robot_id)
    entry = await put_config(session, ctx.project.id, robot, body.config, created_by=ctx.user.id)
    _emit_hardware_event(
        ctx,
        session,
        "hardware.config_updated",
        {"robot_id": str(robot.id), "entry_id": str(entry.id)},
    )
    await session.commit()
    return envelope(_config_view(entry.id, body.config))


@router.post("/robots/{robot_id}/parts", status_code=201)
async def author_part(
    robot_id: uuid.UUID, body: PartIn, request: Request, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    robot = await robot_root(session, ctx.project.id, robot_id)
    part, entry = await create_part(
        session,
        ctx.project.id,
        robot,
        name=body.name,
        category=body.category,
        specs=body.specs,
        lifecycle=body.lifecycle,
        created_by=ctx.user.id,
    )
    _emit_hardware_event(
        ctx,
        session,
        "hardware.part_created",
        {"robot_id": str(robot.id), "part_id": str(part.id), "category": body.category},
    )
    await session.commit()
    await request.app.state.graph_hub.publish(
        ctx.project.id,
        graph_changed_frame(
            project_id=ctx.project.id,
            source_id=None,
            sync_id=None,
            counts=GraphChangeCounts(entities_created=1, relations_created=1),
            at=utcnow().isoformat(),
        ),
    )
    return envelope({"entity": serialize_entity(part), "config_entry_id": entry.id})


@router.post("/robots/{robot_id}/parts/{part_id}/lifecycle")
async def promote_lifecycle(
    robot_id: uuid.UUID,
    part_id: uuid.UUID,
    body: LifecycleIn,
    ctx: ProjectCtx,
    session: SessionDep,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    robot = await robot_root(session, ctx.project.id, robot_id)
    _, before = await ensure_config(session, ctx.project.id, robot, created_by=ctx.user.id)
    previous = before.parts.get(str(part_id))
    promoted, _ = await promote(
        session, ctx.project.id, robot, part_id, body.state, created_by=ctx.user.id
    )
    _emit_hardware_event(
        ctx,
        session,
        "hardware.lifecycle_promoted",
        {
            "part_id": str(part_id),
            "from": previous.lifecycle.value if previous is not None else None,
            "to": body.state.value,
        },
    )
    await session.commit()
    return envelope({"part_id": part_id, "config": promoted.model_dump(mode="json")})


class AttachIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_ATTACH)
    category: Category


@router.get("/unassigned")
async def list_unassigned(
    ctx: ProjectCtx,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
) -> dict[str, Any]:
    """Connector-sourced parts no robot category owns yet (From a file)."""
    stmt = unassigned_parts_stmt(ctx.project.id)
    if cursor:
        stmt = stmt.where(cursor_filter(GraphEntity.created_at, GraphEntity.id, cursor))
    stmt = stmt.order_by(GraphEntity.created_at.desc(), GraphEntity.id.desc()).limit(limit + 1)
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    return envelope([serialize_entity(e) for e in visible], meta=meta)


@router.post("/robots/{robot_id}/parts/attach")
async def attach_parts(
    robot_id: uuid.UUID, body: AttachIn, request: Request, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    robot = await robot_root(session, ctx.project.id, robot_id)
    attached, skipped, entry = await attach_existing_parts(
        session,
        ctx.project.id,
        robot,
        entity_ids=body.entity_ids,
        category=body.category,
        created_by=ctx.user.id,
    )
    _emit_hardware_event(
        ctx,
        session,
        "hardware.parts_attached",
        {"robot_id": str(robot.id), "attached": len(attached), "category": body.category},
    )
    await session.commit()
    if attached:
        await request.app.state.graph_hub.publish(
            ctx.project.id,
            graph_changed_frame(
                project_id=ctx.project.id,
                source_id=None,
                sync_id=None,
                counts=GraphChangeCounts(relations_created=len(attached)),
                at=utcnow().isoformat(),
            ),
        )
    return envelope({"attached": attached, "skipped": skipped, "config_entry_id": entry.id})


def _local_runner(request: Request) -> Any:
    local = get_bench_local(request)
    if local is None:
        raise APIError(503, "source_unavailable", "livebench is not installed on this server")
    return local


@router.get("/detected")
async def list_detected(ctx: ProjectCtx, request: Request) -> dict[str, Any]:
    """Devices on this machine at whichever level is honestly known (opens no port)."""
    local = _local_runner(request)
    raw = await asyncio.to_thread(local.detect_devices)
    devices = [DetectedDeviceOut.model_validate(item) for item in raw]
    return envelope([device.model_dump(mode="json") for device in devices])


@router.post("/detected/{device_ref}/propose")
async def propose_detected(
    device_ref: str,
    ctx: ProjectCtx,
    session: SessionDep,
    request: Request,
    body: ProposeIn | None = None,
) -> dict[str, Any]:
    local = _local_runner(request)
    options = body or ProposeIn()
    proposal = exclude_bound(
        await propose_via_local(
            local,
            device_ref,
            repo_root=validated_repo_root(options.repo_root),
            budget_s=options.budget_s,
        ),
        await bound_repo_config_ids(session, ctx.project.id),
    )
    suggestions = await reconcile_device(session, ctx.project.id, proposal)
    proposal = proposal.model_copy(
        update={"suggestions": [serialize_suggestion(row) for row in suggestions]}
    )
    _emit_hardware_event(
        ctx,
        session,
        "hardware.proposal_built",
        {
            "device_ref": device_ref,
            "rows": len(proposal.rows),
            "disambiguation": proposal.disambiguation is not None,
        },
    )
    await session.commit()
    return envelope(proposal.model_dump(mode="json"))


@router.post("/detected/{device_ref}/confirm", status_code=201)
async def confirm_detected(
    device_ref: str, body: ConfirmIn, ctx: ProjectCtx, session: SessionDep, request: Request
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    local = _local_runner(request)
    proposal = exclude_bound(
        await propose_via_local(
            local, device_ref, repo_root=validated_repo_root(body.repo_root), budget_s=0.5
        ),
        await bound_repo_config_ids(session, ctx.project.id),
    )
    result = await confirm_proposal(
        session, project_id=ctx.project.id, proposal=proposal, body=body, created_by=ctx.user.id
    )
    _emit_hardware_event(
        ctx,
        session,
        "hardware.robot_confirmed",
        {
            "robot_id": str(result.robot.id),
            "device_ref": device_ref,
            "parts": len(result.part_ids),
            "repo_config": body.repo_config_id,
        },
    )
    await session.commit()
    created = len(result.part_ids) + (8 if result.created_robot else 0)
    await request.app.state.graph_hub.publish(
        ctx.project.id,
        graph_changed_frame(
            project_id=ctx.project.id,
            source_id=None,
            sync_id=None,
            counts=GraphChangeCounts(
                entities_created=created,
                relations_created=len(result.part_ids) + (7 if result.created_robot else 0),
            ),
            at=utcnow().isoformat(),
        ),
    )
    session_id, session_error = (
        await _start_robot_session(
            request, local, ctx.project.id, result.robot, result.config, body.window_seconds
        )
        if body.start_session
        else (None, None)
    )
    return envelope(
        {
            "robot": serialize_entity(result.robot),
            "part_ids": result.part_ids,
            "config_entry_id": result.robot.attrs.get("hardware_config_ref"),
            "session_id": session_id,
            "session_error": session_error,
        }
    )


async def _start_robot_session(
    request: Request,
    local: Any,
    project_id: uuid.UUID,
    robot: GraphEntity,
    config: HardwareConfig,
    window_seconds: float,
) -> tuple[uuid.UUID | None, str | None]:
    """Open the robot's session through the driver registry; the robot exists either way,
    so a session that does not start is reported, never raised."""
    identity, protocol = config.identity, config.protocol
    if identity is None or protocol is None:
        return None, "the robot's config has no transport identity or protocol"
    document = config.model_dump(mode="json")

    async def open_robot() -> Any:
        return await local.open_robot(document, project_id=project_id)

    try:
        record = await get_session_manager(request).start(
            project_id,
            mode="real",
            provider="robot",
            label=f"Robot {robot.name} ({identity.device_ref})",
            open_conn=open_robot,
            window_seconds=window_seconds,
            device={
                "device_ref": identity.device_ref,
                "driver_id": protocol.driver_id,
                "serial_number": identity.binding,
                "device_path": identity.last_seen_path,
                "baud": protocol.params.get("baud"),
            },
        )
    except Exception as exc:
        logger.warning("session after binding failed: %s", type(exc).__name__)
        return None, f"{type(exc).__name__}: the session did not start"
    return record.id, None


@router.get("/suggestions")
async def get_suggestions(
    ctx: ProjectCtx,
    session: SessionDep,
    status: Annotated[str, Query(max_length=16)] = "pending",
) -> dict[str, Any]:
    try:
        parsed = SuggestionStatus(status)
    except ValueError:
        raise APIError(422, "validation_error", "Unknown suggestion status") from None
    rows = await list_suggestions(session, ctx.project.id, status=parsed)
    return envelope([serialize_suggestion(row) for row in rows])


async def _decide(
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    suggestion_id: uuid.UUID,
    *,
    accept: bool,
    reason: str | None,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    row = await decide_suggestion(
        session, ctx.project.id, suggestion_id, accept, ctx.user.id, reason=reason
    )
    _emit_hardware_event(
        ctx,
        session,
        "hardware.suggestion_decided",
        {"suggestion_id": str(row.id), "decision": row.status.value},
    )
    binding: dict[str, Any] = {
        "bound": False,
        "robot_id": row.candidate_robot_id,
        "session_id": None,
        "session_error": None,
        "bind_error": None,
    }
    if accept and row.subject_kind == "device":
        binding.update(await _bind_accepted_device(request, ctx, session, row))
    await session.commit()
    return envelope({**serialize_suggestion(row), **binding})


async def _bind_accepted_device(
    request: Request, ctx: ProjectCtx, session: SessionDep, row: HardwareSuggestion
) -> dict[str, Any]:
    """An accepted device suggestion binds the wire to that robot: re-propose (the wire is
    the truth), write identity/protocol/bus map, key the parts, open the session."""
    local = get_bench_local(request)
    if local is None:
        return {"bind_error": "the local runner (livebench) is not installed on this server"}
    try:
        proposal = exclude_bound(
            await propose_via_local(local, row.subject_ref, repo_root=None, budget_s=0.5),
            await bound_repo_config_ids(session, ctx.project.id),
        )
        robot = await robot_root(session, ctx.project.id, row.candidate_robot_id)
        config = await bind_device(session, ctx.project.id, robot, proposal, created_by=ctx.user.id)
    except APIError as exc:
        return {"bind_error": exc.message}
    _emit_hardware_event(
        ctx,
        session,
        "hardware.device_bound",
        {"robot_id": str(robot.id), "device_ref": row.subject_ref, "suggestion_id": str(row.id)},
    )
    session_id, session_error = await _start_robot_session(
        request, local, ctx.project.id, robot, config, 1.0
    )
    return {"bound": True, "session_id": session_id, "session_error": session_error}


@router.post("/suggestions/{suggestion_id}/accept")
async def accept_suggestion(
    suggestion_id: uuid.UUID, request: Request, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    return await _decide(request, ctx, session, suggestion_id, accept=True, reason=None)


@router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: uuid.UUID,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    body: RejectIn | None = None,
) -> dict[str, Any]:
    reason = body.reason if body is not None else None
    return await _decide(request, ctx, session, suggestion_id, accept=False, reason=reason)
