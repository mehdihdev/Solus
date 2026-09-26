"""docs/api/hardware.md §5 — the parts/platform library: search and preview Solus-curated
definitions, import a platform as a new robot (parts under their categories, a LIBRARY config
layer, a reconciliation pass so a detected machine and its library twin stay ONE robot), and
import one part into a robot. `ProjectCtx`-scoped (§7: non-member → 404); MEMBER on writes; an
event on every mutation. Vendor names never appear here — they are data in the definitions.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Path, Query, Request
from pydantic import BaseModel, ConfigDict

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, require_role
from solus_api.graph.live import graph_changed_frame
from solus_api.hardware.config import ConfigLayer, FieldProvenance, HardwareConfig, merge_layers
from solus_api.hardware.detect import DetectedDeviceOut
from solus_api.hardware.library import ID_PATTERN, DefinitionKind, PartDefinition, load_library
from solus_api.hardware.library_import import import_standalone_part
from solus_api.hardware.links import (
    PartObservation,
    RobotCandidate,
    persist_suggestions,
    suggest_links,
)
from solus_api.hardware.store import attach_part, ensure_config, put_config, robot_root
from solus_api.livebench.bench_router import get_bench_local
from solus_api.models import GraphEntity, HardwareSuggestion, Role, utcnow
from solus_api.schemas import serialize_entity
from solus_api.services.events import emit_event
from solus_api.services.physical_robots import (
    ROBOT_CATEGORIES,
    GraphChangeCounts,
    PhysicalRobotService,
    RobotName,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/projects/{project_id}/hardware/library")

Category = Literal[
    "sensors", "actuators", "controllers", "end_effectors", "power", "structure", "wiring"
]
DefinitionId = Annotated[str, Path(pattern=ID_PATTERN)]
#: `PhysicalRobotService.create` lands the root plus its category nodes and `contains` edges.
_ROBOT_ENTITIES = 1 + len(ROBOT_CATEGORIES)
_ROBOT_RELATIONS = len(ROBOT_CATEGORIES)


class PlatformImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: RobotName | None = None


class PartImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: uuid.UUID | None = None
    name: RobotName | None = None
    category: Category | None = None  # defaults to the definition's


def _emit_library_event(
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


async def _publish(
    request: Request, project_id: uuid.UUID, *, entities: int, relations: int
) -> None:
    await request.app.state.graph_hub.publish(
        project_id,
        graph_changed_frame(
            project_id=project_id,
            source_id=None,
            sync_id=None,
            counts=GraphChangeCounts(entities_created=entities, relations_created=relations),
            at=utcnow().isoformat(),
        ),
    )


async def _attach_definition(
    session: SessionDep,
    project_id: uuid.UUID,
    robot: GraphEntity,
    part: PartDefinition,
    *,
    name: str,
    category: str,
    extra: dict[str, Any],
) -> GraphEntity:
    """A library part as a manual `part` entity. No `external_ref`: the wire assigns identity
    later, through detection and the suggestion inbox."""
    return await attach_part(
        session,
        project_id,
        robot,
        name=name,
        category=category,
        attrs={
            "model": part.name,
            "manufacturer": part.manufacturer,
            "definition_id": part.id,
            "specs": dict(part.specs),
            **extra,
        },
        provenance=FieldProvenance.LIBRARY,
    )


async def _reconcile(
    request: Request,
    session: SessionDep,
    project_id: uuid.UUID,
    robot: GraphEntity,
    config: HardwareConfig,
) -> list[HardwareSuggestion]:
    """Devices on this machine against the new library robot, through the link-suggestion
    engine. No runner, an unreadable runner, or no bus evidence is honestly no suggestion —
    the import never fails because detection did, and nothing auto-links (ADR-012)."""
    local = get_bench_local(request)
    if local is None:
        return []
    try:
        raw = await asyncio.to_thread(local.detect_devices)
        devices = [DetectedDeviceOut.model_validate(item) for item in raw]
    except Exception as exc:  # detection is best-effort here; the robot exists either way
        logger.warning("library import skipped reconciliation: %s", type(exc).__name__)
        return []
    candidate = RobotCandidate(robot_entity_id=robot.id, name=robot.name, config=config)
    suggestions = []
    for device in devices:
        if device.device_ref is None:
            continue
        observation = PartObservation(
            subject_ref=device.device_ref,
            subject_kind="device",
            device_ref=device.device_ref,
            evidence=list(device.evidence),
        )
        suggestions.extend(suggest_links(observation, [candidate]))
    return await persist_suggestions(session, project_id, suggestions)


@router.get("")
async def list_definitions(
    ctx: ProjectCtx,
    q: Annotated[str, Query(max_length=256)] = "",
    kind: DefinitionKind | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    hits = load_library().search(q, kind=kind, limit=limit)
    return envelope([hit.model_dump(mode="json") for hit in hits])


@router.get("/{kind}/{definition_id}")
async def get_definition(
    kind: DefinitionKind, definition_id: DefinitionId, ctx: ProjectCtx
) -> dict[str, Any]:
    definition = load_library().get(kind, definition_id)
    if definition is None:
        raise APIError(404, "not_found", f"{kind} definition not found")
    return envelope({"kind": kind, **definition.model_dump(mode="json")})


@router.post("/platforms/{definition_id}/import", status_code=201)
async def import_platform(
    definition_id: DefinitionId,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    body: PlatformImportIn | None = None,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    library = load_library()
    platform = library.platforms.get(definition_id)
    if platform is None:
        raise APIError(404, "not_found", "platform definition not found")
    name = body.name if body is not None and body.name is not None else platform.name
    robot = await PhysicalRobotService(session).create(ctx.project.id, name)
    entity_ids: dict[str, uuid.UUID] = {}
    for slot in platform.parts:
        part = library.parts[slot.part]
        entity = await _attach_definition(
            session,
            ctx.project.id,
            robot,
            part,
            name=slot.role,
            category=slot.category or part.category,
            extra={"role": slot.role, "gear_ratio": slot.gear_ratio},
        )
        entity_ids[slot.address] = entity.id
    layer = ConfigLayer(
        by=FieldProvenance.LIBRARY,
        source=f"platform:{platform.id}",
        document=library.platform_config_layer(platform, entity_ids),
    )
    config = merge_layers(robot.id, [layer])
    entry = await put_config(session, ctx.project.id, robot, config, created_by=ctx.user.id)
    suggestions = await _reconcile(request, session, ctx.project.id, robot, config)
    _emit_library_event(
        ctx,
        session,
        "hardware.library_imported",
        {"definition_id": platform.id, "robot_id": str(robot.id), "parts": len(entity_ids)},
    )
    for row in suggestions:
        _emit_library_event(
            ctx,
            session,
            "hardware.suggestion_created",
            {"suggestion_id": str(row.id), "tier": row.tier},
        )
    await session.commit()
    await _publish(
        request,
        ctx.project.id,
        entities=_ROBOT_ENTITIES + len(entity_ids),
        relations=_ROBOT_RELATIONS + len(entity_ids),
    )
    return envelope(
        {
            "robot": serialize_entity(robot),
            "part_ids": list(entity_ids.values()),
            "config_entry_id": entry.id,
            "suggestion_ids": [row.id for row in suggestions],
        }
    )


@router.post("/parts/{definition_id}/import", status_code=201)
async def import_part(
    definition_id: DefinitionId,
    body: PartImportIn,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    idempotency_key: Annotated[uuid.UUID | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    library = load_library()
    part = library.parts.get(definition_id)
    if part is None:
        raise APIError(404, "not_found", "part definition not found")
    if body.robot_id is None:
        if body.name is None or idempotency_key is None:
            raise APIError(
                422, "validation_error", "Standalone imports require a name and operation key"
            )
        result, replayed = await import_standalone_part(
            session,
            ctx.project.id,
            ctx.user.id,
            idempotency_key,
            part,
            name=body.name,
            category=body.category or part.category,
        )
        if not replayed:
            _emit_library_event(
                ctx,
                session,
                "hardware.library_imported",
                {
                    "definition_id": part.id,
                    "entity_id": result["entity"]["id"],
                    "parts": 1,
                },
            )
        await session.commit()
        if not replayed:
            await _publish(request, ctx.project.id, entities=1, relations=0)
        return envelope(result)
    robot = await robot_root(session, ctx.project.id, body.robot_id)
    entity = await _attach_definition(
        session,
        ctx.project.id,
        robot,
        part,
        name=body.name or part.name,
        category=body.category or part.category,
        extra={},
    )
    _, config = await ensure_config(session, ctx.project.id, robot, created_by=ctx.user.id)
    source = f"part:{part.id}"
    document = config.model_dump(mode="json")
    document["parts"][str(entity.id)] = library.part_config(part, part.id, source=source)
    document["provenance"][f"parts.{entity.id}"] = {
        "by": FieldProvenance.LIBRARY.value,
        "source": source,
    }
    entry = await put_config(
        session,
        ctx.project.id,
        robot,
        HardwareConfig.model_validate(document),
        created_by=ctx.user.id,
    )
    _emit_library_event(
        ctx,
        session,
        "hardware.library_imported",
        {"definition_id": part.id, "robot_id": str(robot.id), "parts": 1},
    )
    await session.commit()
    await _publish(request, ctx.project.id, entities=1, relations=1)
    return envelope({"entity": serialize_entity(entity), "config_entry_id": entry.id})
