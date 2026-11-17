"""docs/api/hardware.md §2-3 — the robot's config document, authored parts and lifecycle
promotion, and the link-suggestion inbox. All scoped through `ProjectCtx` (§7: non-member →
404); writes need the member role; every mutation emits a data event.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import BridgeSessionsDep, ProjectCtx, RequireVerified, SessionDep, require_role
from solus_api.graph.live import graph_changed_frame
from solus_api.graph.read_scope import visible_to
from solus_api.hardware import detection_service
from solus_api.hardware.companion_deployment import (
    PrepareCompanionDeployment,
    get_companion_deployment_service,
)
from solus_api.hardware.config import (
    DEVICE_REF_PATTERN,
    EntityHardwareConfig,
    HardwareConfig,
    LifecycleState,
    Scalar,
)
from solus_api.hardware.detect import (
    ConfirmIn,
    ProposeIn,
    detected_devices_wire,
)
from solus_api.hardware.device_memory import (
    annotate,
    clear_dismissals,
    device_context,
    dismiss,
    this_machine,
)
from solus_api.hardware.host_topology import (
    HostAttachment,
    HostConfirm,
    HostProposalEnvelope,
    HostTopologyService,
    LocalHostProvider,
    host_provider,
)
from solus_api.hardware.in_graph import set_in_graph
from solus_api.hardware.links import list_suggestions, serialize_suggestion
from solus_api.hardware.local_sources import LocalHardwareSources
from solus_api.hardware.operations import HardwareEntityCreate, ReviewedHardwareOperations
from solus_api.hardware.ownership import assign_parent, list_parts
from solus_api.hardware.presence import PreparePresence, PresenceService
from solus_api.hardware.presence_topology import AcceptWiring, WiringRequest, WiringService
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.store import (
    MAX_ATTACH,
    MAX_SPECS,
    attach_existing_parts,
    create_part,
    ensure_config,
    hardware_entity,
    promote,
    put_config,
    put_entity_config,
    read_entity_config,
    robot_root,
    unassigned_parts_stmt,
)
from solus_api.hardware.topology import RobotTopologyEnvelope
from solus_api.hardware.topology_acceptance import (
    ExtractionAcceptanceEnvelope,
    ExtractionConfirm,
    TopologyAcceptanceService,
)
from solus_api.hardware.topology_proposals import (
    ExtractionProposalEnvelope,
    ExtractionRequest,
    TopologyProposalService,
    proposal_sources,
)
from solus_api.livebench.bench_router import get_bench_local, get_session_manager
from solus_api.models import GraphEntity, Role, SuggestionStatus, utcnow
from solus_api.schemas import serialize_entity
from solus_api.services.events import emit_event
from solus_api.services.physical_robots import GraphChangeCounts

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/projects/{project_id}/hardware")


class EntityConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: EntityHardwareConfig


class ParentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: uuid.UUID | None
    expected_parent_id: uuid.UUID | None
    version: int = Field(ge=0, strict=True)


ConfigMatch = Annotated[str, Header(alias="If-Match", pattern=r"^(0|[1-9][0-9]{0,9})$")]
OperationKey = Annotated[uuid.UUID, Header(alias="Idempotency-Key")]


@router.post("/entities", status_code=201)
async def create_hardware_entity(
    body: HardwareEntityCreate,
    idempotency_key: OperationKey,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    result, replayed = await ReviewedHardwareOperations(
        session, ctx.project.id, ctx.user.id
    ).create(idempotency_key, body)
    if not replayed:
        _emit_hardware_event(
            ctx,
            session,
            "hardware.entity_created",
            {"entity_id": result["entity"]["id"], "kind": body.kind},
        )
    await session.commit()
    if not replayed:
        await request.app.state.graph_hub.publish(
            ctx.project.id,
            graph_changed_frame(
                project_id=ctx.project.id,
                source_id=None,
                sync_id=None,
                counts=GraphChangeCounts(
                    entities_created=1, relations_created=1 if result["parent_id"] else 0
                ),
                at=utcnow().isoformat(),
            ),
        )
    return envelope(result)


def _entity_config_view(
    entity_id: uuid.UUID, entry: Any, config: EntityHardwareConfig | None
) -> dict[str, Any]:
    return {
        "entry_id": entry.id if entry else None,
        "entity_id": entity_id,
        "version": entry.config_version if entry else 0,
        "config": config.model_dump(mode="json") if config else None,
    }


class InGraphIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    in_graph: StrictBool


@router.put("/entities/{entity_id}/graph")
async def put_in_graph(
    entity_id: uuid.UUID,
    body: InGraphIn,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    """Add a robot (with its own hardware) or a lone part to the workspace graph, or take it
    out (SOLUSDEV-326, docs/api/hardware.md §1a). Only hardware the caller can see."""
    require_role(ctx, Role.MEMBER)
    change = await set_in_graph(
        session,
        ctx.project,
        ctx.user,
        entity_id,
        body.in_graph,
        hub=request.app.state.graph_hub,
    )
    return envelope(
        {
            "entity": serialize_entity(change.entity),
            "in_graph": body.in_graph,
            "updated": change.updated,
        }
    )


@router.get("/entities/{entity_id}/config")
async def get_entity_config(
    entity_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    await hardware_entity(session, ctx.project.id, entity_id)
    entry, config = await read_entity_config(session, ctx.project.id, entity_id)
    return envelope(_entity_config_view(entity_id, entry, config))


@router.put("/entities/{entity_id}/config")
async def replace_entity_config(
    entity_id: uuid.UUID,
    body: EntityConfigIn,
    if_match: ConfigMatch,
    ctx: ProjectCtx,
    session: SessionDep,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    subject = await hardware_entity(session, ctx.project.id, entity_id)
    entry = await put_entity_config(
        session,
        ctx.project.id,
        subject,
        body.config,
        expected_version=int(if_match),
        created_by=ctx.user.id,
    )
    _emit_hardware_event(
        ctx,
        session,
        "hardware.config_updated",
        {"entity_id": str(entity_id), "entry_id": str(entry.id), "version": entry.config_version},
    )
    await session.commit()
    return envelope(_entity_config_view(entity_id, entry, body.config))


@router.patch("/parts/{part_id}/parent")
async def change_parent(
    part_id: uuid.UUID, body: ParentIn, request: Request, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    part, parent_id = await assign_parent(
        session,
        ctx.project.id,
        part_id,
        parent_id=body.parent_id,
        expected_parent_id=body.expected_parent_id,
        version=body.version,
        actor_id=ctx.user.id,
    )
    _emit_hardware_event(
        ctx,
        session,
        "hardware.parent_changed",
        {"part_id": str(part.id), "parent_id": str(parent_id) if parent_id else None},
    )
    await session.commit()
    await request.app.state.graph_hub.publish(
        ctx.project.id,
        graph_changed_frame(
            project_id=ctx.project.id,
            source_id=None,
            sync_id=None,
            counts=GraphChangeCounts(entities_updated=1),
            at=utcnow().isoformat(),
        ),
    )
    return envelope(
        {
            "entity": serialize_entity(part),
            "parent_id": parent_id,
            "ownership_version": part.version,
        }
    )


@router.get("/parts")
async def list_hardware_parts(
    ctx: ProjectCtx,
    session: SessionDep,
    ownership: Literal["unassigned", "all"] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
) -> dict[str, Any]:
    rows, meta = await list_parts(
        session, ctx.project.id, ctx.user.id, ownership=ownership, limit=limit, cursor=cursor
    )
    return envelope(
        [
            {**serialize_entity(part), "parent_id": parent, "ownership_version": part.version}
            for part, parent in rows
        ],
        meta=meta,
    )


class ConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: HardwareConfig


class PartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512, strict=True)
    ]
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


def _config_view(entry_id: uuid.UUID | None, config: HardwareConfig) -> dict[str, Any]:
    return {
        "entry_id": entry_id,
        "robot_entity_id": config.robot_entity_id,
        "config": config.model_dump(mode="json"),
    }


@router.get("/robots/{robot_id}/topology", response_model=RobotTopologyEnvelope)
async def get_topology(robot_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    from solus_api.hardware.topology import read_topology

    return envelope(
        (await read_topology(session, ctx.project.id, robot_id)).model_dump(mode="json")
    )


@router.post(
    "/robots/{robot_id}/topology/extraction/propose", response_model=ExtractionProposalEnvelope
)
async def propose_topology_extraction(
    robot_id: uuid.UUID,
    body: ExtractionRequest,
    ctx: ProjectCtx,
    session: SessionDep,
    _verified: RequireVerified,
    sources: Annotated[LocalHardwareSources, Depends(proposal_sources)],
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    proposal = await TopologyProposalService(session, ctx.project.id, ctx.user.id, sources).propose(
        robot_id, body
    )
    return envelope(proposal.model_dump(mode="json"))


@router.post(
    "/robots/{robot_id}/topology/extraction/confirm", response_model=ExtractionAcceptanceEnvelope
)
async def confirm_topology_extraction(
    robot_id: uuid.UUID,
    body: ExtractionConfirm,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    _verified: RequireVerified,
    sources: Annotated[LocalHardwareSources, Depends(proposal_sources)],
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    result, replayed = await TopologyAcceptanceService(
        session, ctx.project.id, ctx.user.id, sources
    ).confirm(robot_id, body)
    # Proposal freshness expires loaded ORM state; refresh request identities before event use.
    await session.refresh(ctx.project)
    await session.refresh(ctx.team)
    await session.refresh(ctx.user)
    if not replayed:
        _emit_hardware_event(
            ctx,
            session,
            "hardware.extraction_confirmed",
            {
                "robot_id": str(robot_id),
                "brain_id": str(body.brain_id),
                "count": len(result.entity_ids),
            },
        )
    await session.commit()
    if not replayed:
        await request.app.state.graph_hub.publish(
            ctx.project.id,
            graph_changed_frame(
                project_id=ctx.project.id,
                source_id=None,
                sync_id=None,
                counts=GraphChangeCounts(
                    entities_created=result.created, relations_created=len(result.entity_ids)
                ),
                at=utcnow().isoformat(),
            ),
        )
    return envelope(result.model_dump(mode="json"))


@router.post("/robots/{robot_id}/topology/host/propose", response_model=HostProposalEnvelope)
async def propose_host_topology(
    robot_id: uuid.UUID,
    body: HostAttachment,
    ctx: ProjectCtx,
    session: SessionDep,
    sessions: BridgeSessionsDep,
    _verified: RequireVerified,
    provider: Annotated[LocalHostProvider, Depends(host_provider)],
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    proposal = await HostTopologyService(
        session,
        project_id=ctx.project.id,
        team_id=ctx.team.id,
        user_id=ctx.user.id,
        sessions=sessions,
        provider=provider,
    ).propose(robot_id, body)
    return envelope(proposal.model_dump(mode="json"))


@router.post("/robots/{robot_id}/topology/host/confirm", response_model=RobotTopologyEnvelope)
async def confirm_host_topology(
    robot_id: uuid.UUID,
    body: HostConfirm,
    idempotency_key: OperationKey,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    sessions: BridgeSessionsDep,
    _verified: RequireVerified,
    provider: Annotated[LocalHostProvider, Depends(host_provider)],
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    result, replayed = await HostTopologyService(
        session,
        project_id=ctx.project.id,
        team_id=ctx.team.id,
        user_id=ctx.user.id,
        sessions=sessions,
        provider=provider,
    ).confirm(robot_id, body, idempotency_key)
    if not replayed:
        _emit_hardware_event(
            ctx,
            session,
            "hardware.topology_confirmed",
            {
                "robot_id": str(robot_id),
                "endpoint_id": str(body.endpoint_id),
                "local_source_id": str(body.local_source_id),
            },
        )
    await session.commit()
    if not replayed:
        await request.app.state.graph_hub.publish(
            ctx.project.id,
            graph_changed_frame(
                project_id=ctx.project.id,
                source_id=None,
                sync_id=None,
                counts=GraphChangeCounts(entities_updated=1),
                at=utcnow().isoformat(),
            ),
        )
    return envelope(result.model_dump(mode="json"))


@router.get("/robots/{robot_id}/config")
async def get_config(robot_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    await robot_root(session, ctx.project.id, robot_id)
    entry, _ = await read_entity_config(session, ctx.project.id, robot_id)
    config = await resolve_runtime_config(session, ctx.project.id, robot_id)
    return envelope(
        {
            **_config_view(entry.id if entry else None, config),
            "version": entry.config_version if entry else 0,
        }
    )


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
        specs=body.specs,
        lifecycle=body.lifecycle,
        created_by=ctx.user.id,
    )
    _emit_hardware_event(
        ctx,
        session,
        "hardware.part_created",
        {"robot_id": str(robot.id), "part_id": str(part.id)},
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


@router.get("/unassigned")
async def list_unassigned(
    ctx: ProjectCtx,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
) -> dict[str, Any]:
    """Part-like entities no robot owns yet (From a file), less another member's un-added parts."""
    stmt = unassigned_parts_stmt(ctx.project.id).where(visible_to(ctx.user.id))
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
        session, ctx.project.id, robot, entity_ids=body.entity_ids, created_by=ctx.user.id
    )
    _emit_hardware_event(
        ctx,
        session,
        "hardware.parts_attached",
        {"robot_id": str(robot.id), "attached": len(attached)},
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
async def list_detected(ctx: ProjectCtx, session: SessionDep, request: Request) -> dict[str, Any]:
    """Devices on this machine at whichever level is honestly known (opens no port), each with
    what the caller may know of it (§4, SOLUSDEV-326): what binds it, their "Not now", and —
    for the machine's owner — when it was last seen."""
    local = _local_runner(request)
    devices = detected_devices_wire(await asyncio.to_thread(local.detect_devices))
    host = await LocalHostProvider(local).identity()
    machine = await this_machine(session, ctx.project.id, host)
    context = await device_context(session, ctx.project.id, devices, machine)
    return envelope(annotate(devices, context, ctx.user.id))


class DismissalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_ref: str = Field(min_length=1, max_length=160, pattern=DEVICE_REF_PATTERN)


async def _this_host(request: Request) -> str | None:
    """This API's machine (its companion identity); 503 on an API that runs on no one's."""
    return await LocalHostProvider(_local_runner(request)).identity()


@router.post("/devices/dismissals")
async def dismiss_device(
    body: DismissalIn, ctx: ProjectCtx, session: SessionDep, request: Request
) -> dict[str, Any]:
    """The caller's "Not now" to a device on this machine (§4): kept across restarts and
    replugs until they clear it. Their own list comes back."""
    require_role(ctx, Role.MEMBER)
    host = await _this_host(request)
    dismissed = await dismiss(session, ctx.project.id, host, ctx.user.id, body.device_ref)
    _emit_hardware_event(ctx, session, "hardware.device_dismissed", {"device_ref": body.device_ref})
    await session.commit()
    return envelope({"dismissed": dismissed})


@router.delete("/devices/dismissals")
async def clear_device_dismissals(
    ctx: ProjectCtx, session: SessionDep, request: Request
) -> dict[str, Any]:
    """Forget every "Not now" the caller said on this machine ("+ Add hardware")."""
    require_role(ctx, Role.MEMBER)
    host = await _this_host(request)
    cleared = await clear_dismissals(session, ctx.project.id, host, ctx.user.id)
    _emit_hardware_event(ctx, session, "hardware.dismissals_cleared", {"count": cleared})
    await session.commit()
    return envelope({"dismissed": []})


@router.post("/detected/{device_ref}/propose")
async def propose_detected(
    device_ref: str,
    ctx: ProjectCtx,
    session: SessionDep,
    request: Request,
    body: ProposeIn | None = None,
) -> dict[str, Any]:
    proposal = await detection_service.propose_detected(
        session,
        _local_runner(request),
        project_id=ctx.project.id,
        user_id=ctx.user.id,
        device_ref=device_ref,
        options=body or ProposeIn(),
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
    started = perf_counter()
    connections = request.app.state.hardware_connections
    confirmed = await detection_service.confirm_detected(
        session,
        local,
        connections,
        project_id=ctx.project.id,
        user_id=ctx.user.id,
        device_ref=device_ref,
        body=body,
    )
    result = confirmed.result
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
    # Written: the robot root when new, and each part with its robot -> part `contains` edge.
    await request.app.state.graph_hub.publish(
        ctx.project.id,
        graph_changed_frame(
            project_id=ctx.project.id,
            source_id=None,
            sync_id=None,
            counts=GraphChangeCounts(
                entities_created=len(result.part_ids) + int(result.created_robot),
                relations_created=len(result.part_ids),
            ),
            at=utcnow().isoformat(),
        ),
    )
    written_at = perf_counter()
    if confirmed.attempt_id is not None:
        connections.schedule(
            ctx.project.id, ctx.user.id, result.robot.id, confirmed.attempt_id, body.window_seconds
        )
    logger.info(
        "hardware.confirm timings",
        extra={
            "project_id": str(ctx.project.id),
            "device_ref": device_ref,
            "proposal_reused": confirmed.proposal_reused,
            "propose_s": round(confirmed.proposed_at - started, 4),
            "write_s": round(written_at - confirmed.proposed_at, 4),
            "session_s": round(perf_counter() - written_at, 4),
        },
    )
    return envelope(
        {
            "robot": serialize_entity(result.robot),
            "part_ids": result.part_ids,
            "config_entry_id": result.robot.attrs.get("hardware_config_ref"),
            "session_id": None,
            "session_error": None,
        }
    )


@router.post("/parts/{part_id}/suggestions")
async def propose_part_suggestions(
    part_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep, _verified: RequireVerified
) -> dict[str, Any]:
    from solus_api.hardware.cad_suggestions import (
        filter_visible_suggestions,
        propose_cad_suggestions,
    )

    require_role(ctx, Role.MEMBER)
    # SOLUSDEV-326: its counterpart's robot may be one the caller cannot see (§1a).
    rows = await filter_visible_suggestions(
        session,
        ctx.project.id,
        ctx.user.id,
        await propose_cad_suggestions(session, ctx.project.id, part_id, ctx.user.id),
    )
    _emit_hardware_event(
        ctx, session, "hardware.part_links_proposed", {"part_id": str(part_id), "count": len(rows)}
    )
    await session.commit()
    return envelope([serialize_suggestion(row) for row in rows])


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
    from solus_api.hardware.cad_suggestions import filter_visible_suggestions

    rows = await filter_visible_suggestions(session, ctx.project.id, ctx.user.id, rows)
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
    decision = await detection_service.decide_and_link(
        session,
        get_bench_local(request),
        get_session_manager(request),
        project_id=ctx.project.id,
        user_id=ctx.user.id,
        suggestion_id=suggestion_id,
        accept=accept,
        reason=reason,
    )
    row = decision.row
    _emit_hardware_event(
        ctx,
        session,
        "hardware.suggestion_decided",
        {"suggestion_id": str(row.id), "decision": row.status.value},
    )
    if decision.device_bound:
        _emit_hardware_event(
            ctx,
            session,
            "hardware.device_bound",
            {
                "robot_id": str(row.candidate_robot_id),
                "device_ref": row.subject_ref,
                "suggestion_id": str(row.id),
            },
        )
    await session.commit()
    if decision.attached_count:
        await request.app.state.graph_hub.publish(
            ctx.project.id,
            graph_changed_frame(
                project_id=ctx.project.id,
                source_id=None,
                sync_id=None,
                counts=GraphChangeCounts(relations_created=decision.attached_count),
                at=utcnow().isoformat(),
            ),
        )
    return envelope({**serialize_suggestion(row), **decision.binding})


@router.post("/suggestions/{suggestion_id}/accept")
async def accept_suggestion(
    suggestion_id: uuid.UUID,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    _verified: RequireVerified,
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


@router.get("/presence/profiles")
async def presence_profiles(
    request: Request, ctx: ProjectCtx, session: SessionDep, _verified: RequireVerified
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    service = PresenceService(
        session,
        ctx.project.id,
        ctx.user.id,
        request.app.state.artifact_store,
        getattr(request.app.state, "presence_provider", None),
    )
    return envelope(service.profiles())


@router.post("/companion-deployments/prepare", status_code=201)
async def prepare_companion_deployment(
    body: PrepareCompanionDeployment,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    service = get_companion_deployment_service(request, session, ctx.project.id, ctx.user.id)
    result = await service.prepare(body)
    await session.commit()
    return envelope(result)


@router.post("/robots/{robot_id}/brains/{brain_id}/presence/prepare", status_code=201)
async def prepare_presence(
    robot_id: uuid.UUID,
    brain_id: uuid.UUID,
    body: PreparePresence,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    service = PresenceService(
        session,
        ctx.project.id,
        ctx.user.id,
        request.app.state.artifact_store,
        getattr(request.app.state, "presence_provider", None),
    )
    result = await service.prepare(robot_id, brain_id, body)
    await session.refresh(ctx.user)
    await session.refresh(ctx.project)
    await session.refresh(ctx.team)
    _emit_hardware_event(
        ctx,
        session,
        "hardware.presence_prepared",
        {
            "plan_id": result["plan_id"],
            "robot_id": str(robot_id),
            "brain_id": str(brain_id),
            "source_sha256": result["source_sha256"],
            "binary_sha256": result["binary_sha256"],
        },
    )
    await session.commit()
    return envelope(result)


@router.post("/robots/{robot_id}/brains/{brain_id}/presence/wiring/propose", status_code=201)
async def propose_presence_wiring(
    robot_id: uuid.UUID,
    brain_id: uuid.UUID,
    body: WiringRequest,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    service = PresenceService(
        session,
        ctx.project.id,
        ctx.user.id,
        request.app.state.artifact_store,
        getattr(request.app.state, "presence_provider", None),
    )
    result = await WiringService(service).propose(robot_id, brain_id, body)
    _emit_hardware_event(
        ctx,
        session,
        "hardware.wiring_proposed",
        {"proposal_id": result["proposal_id"], "robot_id": str(robot_id)},
    )
    await session.commit()
    return envelope(result)


@router.post("/robots/{robot_id}/brains/{brain_id}/presence/wiring/{proposal_id}/accept")
async def accept_presence_wiring(
    robot_id: uuid.UUID,
    brain_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: AcceptWiring,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    service = PresenceService(
        session,
        ctx.project.id,
        ctx.user.id,
        request.app.state.artifact_store,
        getattr(request.app.state, "presence_provider", None),
    )
    result = await WiringService(service).accept(robot_id, brain_id, proposal_id, body.digest)
    _emit_hardware_event(
        ctx,
        session,
        "hardware.wiring_accepted",
        {"proposal_id": str(proposal_id), "robot_id": str(robot_id)},
    )
    await session.commit()
    return envelope(result)
