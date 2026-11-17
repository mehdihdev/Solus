"""docs/api/hardware.md §5 — the parts/platform library: search and preview Solus-curated
definitions, import a platform as a new robot (parts it contains directly, a LIBRARY config
layer, a reconciliation pass so a detected machine and its library twin stay ONE robot), and
import one part into a robot. `ProjectCtx`-scoped (§7: non-member → 404); MEMBER on writes; an
event on every mutation. The imports themselves are `library_import` services SOL's tools share.
Vendor names never appear here — they are data in the definitions.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Path, Query, Request
from pydantic import BaseModel, ConfigDict

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, require_role
from solus_api.graph.live import graph_changed_frame
from solus_api.hardware import library_import
from solus_api.hardware.library import ID_PATTERN, DefinitionKind, load_library
from solus_api.livebench.bench_router import get_bench_local
from solus_api.models import Role, utcnow
from solus_api.schemas import serialize_entity
from solus_api.services.events import emit_event
from solus_api.services.physical_robots import GraphChangeCounts, RobotName

router = APIRouter(prefix="/api/v1/projects/{project_id}/hardware/library")

DefinitionId = Annotated[str, Path(pattern=ID_PATTERN)]


class PlatformImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: RobotName | None = None


class PartImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: uuid.UUID | None = None
    name: RobotName | None = None


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
    imported = await library_import.import_platform(
        session,
        get_bench_local(request),
        library,
        platform,
        project_id=ctx.project.id,
        user_id=ctx.user.id,
        name=body.name if body is not None else None,
    )
    _emit_library_event(
        ctx,
        session,
        "hardware.library_imported",
        {
            "definition_id": platform.id,
            "robot_id": str(imported.robot.id),
            "parts": len(imported.part_ids),
        },
    )
    for row in imported.suggestions:
        _emit_library_event(
            ctx,
            session,
            "hardware.suggestion_created",
            {"suggestion_id": str(row.id), "tier": row.tier},
        )
    await session.commit()
    # The robot root, each part, and each robot -> part `contains` edge.
    parts = len(imported.part_ids)
    await _publish(request, ctx.project.id, entities=1 + parts, relations=parts)
    return envelope(
        {
            "robot": serialize_entity(imported.robot),
            "part_ids": imported.part_ids,
            "config_entry_id": imported.entry.id,
            "suggestion_ids": [row.id for row in imported.suggestions],
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
        result, replayed = await library_import.import_standalone_part(
            session,
            ctx.project.id,
            ctx.user.id,
            idempotency_key,
            part,
            name=body.name,
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
    entity, entry = await library_import.import_part_into_robot(
        session,
        part,
        project_id=ctx.project.id,
        user_id=ctx.user.id,
        robot_id=body.robot_id,
        name=body.name,
    )
    _emit_library_event(
        ctx,
        session,
        "hardware.library_imported",
        {"definition_id": part.id, "robot_id": str(body.robot_id), "parts": 1},
    )
    await session.commit()
    await _publish(request, ctx.project.id, entities=1, relations=1)
    return envelope({"entity": serialize_entity(entity), "config_entry_id": entry.id})
