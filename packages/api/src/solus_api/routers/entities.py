"""§2.4 Graph — entity & relation reads.

Connector-owned entities/relations are read-only here (the connector is the
source of truth; edits happen in the tool and arrive via sync). This ships the
read surface the graph view and onboarding "files indexed" count need; manual
entity/relation mutation lands with the graph-core ticket. Reads are scoped to
live (not soft-deleted) rows.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep
from solus_api.models import Domain, GraphEdge, GraphEntity
from solus_api.schemas import serialize_entity, serialize_relation

router = APIRouter(prefix="/api/v1/projects/{project_id}")

MAX_LIMIT = 500


async def _scoped_entity(session: SessionDep, ctx: ProjectCtx, entity_id: uuid.UUID) -> GraphEntity:
    entity = await session.get(GraphEntity, entity_id)
    if entity is None or entity.project_id != ctx.project.id or entity.deleted_at is not None:
        raise APIError(404, "not_found", "Entity not found")
    return entity


def _domain(value: str) -> Domain:
    try:
        return Domain(value)
    except ValueError as exc:
        raise APIError(422, "validation_error", f"Unknown domain '{value}'") from exc


@router.get("/entities")
async def list_entities(
    ctx: ProjectCtx,
    session: SessionDep,
    type: Annotated[str | None, Query(max_length=64)] = None,
    source_id: Annotated[uuid.UUID | None, Query()] = None,
    domain: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=255)] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 200,
) -> dict[str, Any]:
    stmt = select(GraphEntity).where(
        GraphEntity.project_id == ctx.project.id, GraphEntity.deleted_at.is_(None)
    )
    if type is not None:
        stmt = stmt.where(GraphEntity.kind == type)
    if source_id is not None:
        stmt = stmt.where(GraphEntity.source_id == source_id)
    if domain is not None:
        stmt = stmt.where(GraphEntity.domain == _domain(domain))
    if q:
        stmt = stmt.where(GraphEntity.name.ilike(f"%{q}%"))
    if cursor:
        stmt = stmt.where(cursor_filter(GraphEntity.created_at, GraphEntity.id, cursor))
    stmt = stmt.order_by(GraphEntity.created_at.desc(), GraphEntity.id.desc()).limit(limit + 1)
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    return envelope([serialize_entity(e) for e in visible], meta=meta)


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    entity = await _scoped_entity(session, ctx, entity_id)
    return envelope(serialize_entity(entity))


@router.get("/entities/{entity_id}/relations")
async def get_entity_relations(
    entity_id: uuid.UUID,
    ctx: ProjectCtx,
    session: SessionDep,
    direction: Annotated[str, Query(pattern="^(in|out|both)$")] = "both",
    type: Annotated[str | None, Query(max_length=64)] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 200,
) -> dict[str, Any]:
    await _scoped_entity(session, ctx, entity_id)
    stmt = select(GraphEdge).where(
        GraphEdge.project_id == ctx.project.id, GraphEdge.deleted_at.is_(None)
    )
    if direction == "in":
        stmt = stmt.where(GraphEdge.dst_id == entity_id)
    elif direction == "out":
        stmt = stmt.where(GraphEdge.src_id == entity_id)
    else:
        stmt = stmt.where(or_(GraphEdge.src_id == entity_id, GraphEdge.dst_id == entity_id))
    if type is not None:
        stmt = stmt.where(GraphEdge.relation_type == type)
    if cursor:
        stmt = stmt.where(cursor_filter(GraphEdge.created_at, GraphEdge.id, cursor))
    stmt = stmt.order_by(GraphEdge.created_at.desc(), GraphEdge.id.desc()).limit(limit + 1)
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    return envelope([serialize_relation(r) for r in visible], meta=meta)


@router.get("/relations")
async def list_relations(
    ctx: ProjectCtx,
    session: SessionDep,
    type: Annotated[str | None, Query(max_length=64)] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 200,
) -> dict[str, Any]:
    stmt = select(GraphEdge).where(
        GraphEdge.project_id == ctx.project.id, GraphEdge.deleted_at.is_(None)
    )
    if type is not None:
        stmt = stmt.where(GraphEdge.relation_type == type)
    if cursor:
        stmt = stmt.where(cursor_filter(GraphEdge.created_at, GraphEdge.id, cursor))
    stmt = stmt.order_by(GraphEdge.created_at.desc(), GraphEdge.id.desc()).limit(limit + 1)
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    return envelope([serialize_relation(r) for r in visible], meta=meta)
