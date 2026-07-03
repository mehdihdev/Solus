"""§2.4 Graph — entity & relation reads.

Connector-owned entities/relations are read-only here (the connector is the
source of truth; edits happen in the tool and arrive via sync). This ships the
read surface the graph view and onboarding "files indexed" count need; manual
entity/relation mutation lands with the graph-core ticket.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep
from solus_api.models import Entity, Relation
from solus_api.schemas import serialize_entity, serialize_relation

router = APIRouter(prefix="/api/v1/projects/{project_id}")

MAX_LIMIT = 500


async def _scoped_entity(session: SessionDep, ctx: ProjectCtx, entity_id: uuid.UUID) -> Entity:
    entity = await session.get(Entity, entity_id)
    if entity is None or entity.project_id != ctx.project.id:
        raise APIError(404, "not_found", "Entity not found")
    return entity


@router.get("/entities")
async def list_entities(
    ctx: ProjectCtx,
    session: SessionDep,
    type: Annotated[str | None, Query()] = None,
    source_id: Annotated[uuid.UUID | None, Query()] = None,
    domain: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 200,
) -> dict[str, Any]:
    stmt = select(Entity).where(Entity.project_id == ctx.project.id)
    if type is not None:
        stmt = stmt.where(Entity.type == type)
    if source_id is not None:
        stmt = stmt.where(Entity.source_id == source_id)
    if domain is not None:
        stmt = stmt.where(Entity.domain == domain)
    if q:
        stmt = stmt.where(Entity.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(Entity.created_at.desc(), Entity.id.desc()).limit(limit)
    rows = await session.scalars(stmt)
    return envelope([serialize_entity(e) for e in rows.all()])


@router.get("/entities/{entity_id}")
async def get_entity(
    entity_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    entity = await _scoped_entity(session, ctx, entity_id)
    return envelope(serialize_entity(entity))


@router.get("/entities/{entity_id}/relations")
async def get_entity_relations(
    entity_id: uuid.UUID,
    ctx: ProjectCtx,
    session: SessionDep,
    direction: Annotated[str, Query(pattern="^(in|out|both)$")] = "both",
    type: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    await _scoped_entity(session, ctx, entity_id)
    stmt = select(Relation).where(Relation.project_id == ctx.project.id)
    if direction == "in":
        stmt = stmt.where(Relation.to_entity_id == entity_id)
    elif direction == "out":
        stmt = stmt.where(Relation.from_entity_id == entity_id)
    else:
        stmt = stmt.where(
            or_(Relation.from_entity_id == entity_id, Relation.to_entity_id == entity_id)
        )
    if type is not None:
        stmt = stmt.where(Relation.type == type)
    rows = await session.scalars(stmt)
    return envelope([serialize_relation(r) for r in rows.all()])


@router.get("/relations")
async def list_relations(
    ctx: ProjectCtx,
    session: SessionDep,
    type: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 200,
) -> dict[str, Any]:
    stmt = select(Relation).where(Relation.project_id == ctx.project.id)
    if type is not None:
        stmt = stmt.where(Relation.type == type)
    stmt = stmt.order_by(Relation.created_at.desc(), Relation.id.desc()).limit(limit)
    rows = await session.scalars(stmt)
    return envelope([serialize_relation(r) for r in rows.all()])
