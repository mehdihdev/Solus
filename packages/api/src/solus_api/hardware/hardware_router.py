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
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import BridgeSessionsDep, ProjectCtx, RequireVerified, SessionDep, require_role
from solus_api.graph.live import graph_changed_frame
from solus_api.hardware.companion_deployment import (
    PrepareCompanionDeployment,
    get_companion_deployment_service,
)
from solus_api.hardware.config import EntityHardwareConfig, HardwareConfig, LifecycleState, Scalar
from solus_api.hardware.connections import connection_state
from solus_api.hardware.detect import (
    ConfirmIn,
    ProposeIn,
    bind_device,
    bound_repo_config_ids,
    confirm_proposal,
    detected_devices_wire,
    exclude_bound,
    propose_via_local,
    reconcile_device,
    validated_repo_root,
)
from solus_api.hardware.host_topology import (
    HostAttachment,
    HostConfirm,
    HostProposalEnvelope,
    HostTopologyService,
    LocalHostProvider,
    host_provider,
)
from solus_api.hardware.links import decide_suggestion, list_suggestions, serialize_suggestion
from solus_api.hardware.local_runtime import open_local_hardware, prepare_local_hardware
from solus_api.hardware.local_sources import LocalHardwareSources
from solus_api.hardware.operations import HardwareEntityCreate, ReviewedHardwareOperations
from solus_api.hardware.ownership import assign_parent, current_parent
from solus_api.hardware.presence import PreparePresence, PresenceService
from solus_api.hardware.presence_topology import AcceptWiring, WiringRequest, WiringService
from solus_api.hardware.proposal_cache import PROPOSALS
from solus_api.hardware.repo_evidence import read_repo_evidence
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


class EntityConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: EntityHardwareConfig


class ParentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: uuid.UUID | None
    expected_parent_id: uuid.UUID | None
    version: int = Field(ge=0, strict=True)
    category: Category | None = None


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
                counts=GraphChangeCounts(entities_created=8 if body.kind == "robot" else 1),
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
    if subject.kind == "physical_robot":
        from solus_api.hardware.topology import sync_topology

        await sync_topology(session, ctx.project.id, subject.id)
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
        category=body.category,
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
    from sqlalchemy import select

    from solus_api.hardware.store import PART_KINDS

    stmt = (
        unassigned_parts_stmt(ctx.project.id)
        if ownership == "unassigned"
        else select(GraphEntity).where(
            GraphEntity.project_id == ctx.project.id,
            GraphEntity.kind.in_(PART_KINDS),
            GraphEntity.deleted_at.is_(None),
        )
    )
    if cursor:
        stmt = stmt.where(cursor_filter(GraphEntity.created_at, GraphEntity.id, cursor))
    rows = list(
        (
            await session.scalars(
                stmt.order_by(GraphEntity.created_at.desc(), GraphEntity.id.desc()).limit(limit + 1)
            )
        ).all()
    )
    visible, meta = page_meta(rows, limit)
    return envelope(
        [
            {
                **serialize_entity(part),
                "parent_id": await current_parent(session, ctx.project.id, part.id),
                "ownership_version": part.version,
            }
            for part in visible
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
    return envelope(detected_devices_wire(await asyncio.to_thread(local.detect_devices)))


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
    repo_root = validated_repo_root(options.repo_root)
    evidence = await read_repo_evidence(local, ctx.project.id, ctx.user.id, options.source_refs)
    fresh = await propose_via_local(
        local,
        device_ref,
        repo_root=repo_root,
        budget_s=options.budget_s,
        repo_sources=evidence.sources,
    )
    current = await read_repo_evidence(local, ctx.project.id, ctx.user.id, options.source_refs)
    if current.digest != evidence.digest:
        raise APIError(409, "source_changed", "The source changed during review. Propose again.")
    PROPOSALS.put(evidence.key(ctx.project.id, ctx.user.id, device_ref), fresh)
    proposal = exclude_bound(fresh, await bound_repo_config_ids(session, ctx.project.id))
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
    started = perf_counter()
    repo_root = validated_repo_root(body.repo_root)
    evidence = await read_repo_evidence(local, ctx.project.id, ctx.user.id, body.source_refs)
    # Source-backed confirmation must refer to this actor's still-current reviewed snapshot.
    cached = PROPOSALS.take(
        evidence.key(ctx.project.id, ctx.user.id, device_ref), [a.row_id for a in body.accepted]
    )
    if body.source_refs and cached is None:
        raise APIError(409, "proposal_changed", "Source review expired or changed. Propose again.")
    if cached is not None:
        devices = detected_devices_wire(await asyncio.to_thread(local.detect_devices))
        if not any(device["device_ref"] == device_ref for device in devices):
            raise APIError(404, "device_not_found", "The device is no longer connected")
    proposal = exclude_bound(
        cached
        if cached is not None
        else await propose_via_local(local, device_ref, repo_root=repo_root, budget_s=0.5),
        await bound_repo_config_ids(session, ctx.project.id),
    )
    if body.connection_only:
        devices = detected_devices_wire(await asyncio.to_thread(local.detect_devices))
        matching = [device for device in devices if device["device_ref"] == device_ref]
        expected = proposal.identity.model_dump(mode="json") if proposal.identity else None
        if (
            len(matching) != 1
            or matching[0].get("ambiguous")
            or expected is None
            or not isinstance(matching[0].get("identity"), dict)
            or any(
                matching[0]["identity"].get(key) != expected.get(key)
                for key in ("kind", "binding", "vid", "pid")
            )
        ):
            raise APIError(
                409, "device_changed", "Device identity changed; review the connection again"
            )
    start_session = body.start_session and not body.connection_only
    runtime_id = (
        await request.app.state.hardware_connections.ensure_owner() if start_session else None
    )
    proposed_at = perf_counter()
    result = await confirm_proposal(
        session, project_id=ctx.project.id, proposal=proposal, body=body, created_by=ctx.user.id
    )
    attempt_id = uuid.uuid4() if start_session else None
    if attempt_id is not None:
        result.robot.attrs = {
            **result.robot.attrs,
            "connection": connection_state(attempt_id, runtime_id=runtime_id),
        }
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
    written_at = perf_counter()
    if attempt_id is not None:
        request.app.state.hardware_connections.schedule(
            ctx.project.id, ctx.user.id, result.robot.id, attempt_id, body.window_seconds
        )
    session_id, session_error = None, None
    logger.info(
        "hardware.confirm timings",
        extra={
            "project_id": str(ctx.project.id),
            "device_ref": device_ref,
            "proposal_reused": cached is not None,
            "propose_s": round(proposed_at - started, 4),
            "write_s": round(written_at - proposed_at, 4),
            "session_s": round(perf_counter() - written_at, 4),
        },
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
    window_seconds: float,
    *,
    session: AsyncSession,
    account_id: uuid.UUID,
) -> tuple[uuid.UUID | None, str | None]:
    """Open the robot's session through the driver registry; the robot exists either way,
    so a session that does not start is reported, never raised."""
    try:
        config = await resolve_runtime_config(session, project_id, robot.id)
        entry, owner_config = await read_entity_config(session, project_id, robot.id)
        identity, protocol = config.identity, config.protocol
        if entry is None or identity is None or protocol is None:
            return None, "the robot's config has no transport identity or protocol"
        document = await asyncio.to_thread(
            prepare_local_hardware,
            local,
            config,
            project_id,
            account_id,
            entry.id,
            owner_config=owner_config,
        )

        async def open_robot() -> Any:
            return await open_local_hardware(local, document, project_id)

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
                "device_path": getattr(identity, "last_seen_path", None),
                "baud": protocol.params.get("baud"),
            },
        )
    except APIError as exc:
        return None, exc.message
    except Exception as exc:
        logger.warning("session after binding failed: %s", type(exc).__name__)
        return None, f"{type(exc).__name__}: the session did not start"
    return record.id, None


@router.post("/parts/{part_id}/suggestions")
async def propose_part_suggestions(
    part_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep, _verified: RequireVerified
) -> dict[str, Any]:
    from solus_api.hardware.cad_suggestions import propose_cad_suggestions

    require_role(ctx, Role.MEMBER)
    rows = await propose_cad_suggestions(session, ctx.project.id, part_id, ctx.user.id)
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
    from solus_api.hardware.cad_suggestions import filter_visible_cad_suggestions

    rows = await filter_visible_cad_suggestions(session, ctx.project.id, ctx.user.id, rows)
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
    attached_count = 0
    if accept and row.subject_kind == "device":
        binding.update(await _bind_accepted_device(request, ctx, session, row))
    elif accept and row.subject_kind == "part":
        from solus_api.hardware.cad_suggestions import accept_cad_suggestion, is_cad_suggestion

        if is_cad_suggestion(row):
            outcome = await accept_cad_suggestion(session, ctx.project.id, row, ctx.user.id)
            attached_count = outcome.pop("attached_count", 0)
            binding.update(outcome)
    await session.commit()
    if attached_count:
        await request.app.state.graph_hub.publish(
            ctx.project.id,
            graph_changed_frame(
                project_id=ctx.project.id,
                source_id=None,
                sync_id=None,
                counts=GraphChangeCounts(relations_created=attached_count),
                at=utcnow().isoformat(),
            ),
        )
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
        await bind_device(session, ctx.project.id, robot, proposal, created_by=ctx.user.id)
    except APIError as exc:
        return {"bind_error": exc.message}
    _emit_hardware_event(
        ctx,
        session,
        "hardware.device_bound",
        {"robot_id": str(robot.id), "device_ref": row.subject_ref, "suggestion_id": str(row.id)},
    )
    session_id, session_error = await _start_robot_session(
        request, local, ctx.project.id, robot, 1.0, session=session, account_id=ctx.user.id
    )
    return {"bound": True, "session_id": session_id, "session_error": session_error}


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
