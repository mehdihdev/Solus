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
from solus_api.graph.neighborhood import MAX_DEPTH, load_neighborhood
from solus_api.models import Domain, GraphEdge, GraphEntity
from solus_api.schemas import serialize_entity, serialize_relation

router = APIRouter(prefix="/api/v1/projects/{project_id}")

MAX_LIMIT = 500
MAX_FILTER_VALUES = 32  # a focus filter, not a query language


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
    external_ref_prefix: Annotated[str | None, Query(max_length=255)] = None,
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
    if external_ref_prefix and external_ref_prefix.strip():
        # SOLUS-A7-01. Entities are keyed `{document_id}:{element_id}:{occurrence}`
        # (connectors/mechanical.py), so this prefix is the only join an Onshape
        # panel has: it knows a document and an element and nothing finer, because
        # no face-level key is persisted.
        #
        # ESCAPED, and anchored with no leading `%`. An `external_ref` is
        # connector-derived, so a `%` inside a prefix would otherwise widen the
        # query to the whole project — over-disclosure to a caller that asked
        # about one document.
        literal = (
            external_ref_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        stmt = stmt.where(GraphEntity.external_ref.like(f"{literal}%", escape="\\"))
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


def _csv(value: str | None) -> list[str] | None:
    """`?entity_types=ic,motor` → ["ic", "motor"]. Bounded so a long query string cannot become a
    huge `IN (…)` list."""
    if not value:
        return None
    parts = [item.strip() for item in value.split(",") if item.strip()][:MAX_FILTER_VALUES]
    return parts or None


@router.get("/graph")
async def get_subgraph(
    ctx: ProjectCtx,
    session: SessionDep,
    root: Annotated[uuid.UUID, Query()],
    depth: Annotated[int, Query(ge=0, le=MAX_DEPTH)] = 1,
    entity_types: Annotated[str | None, Query(max_length=512)] = None,
    relation_types: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 200,
) -> dict[str, Any]:
    """Subgraph extraction around a focused entity — the read WS-01's shared-focus engine uses to
    re-scope every mounted widget in one call, and the same traversal SOL reasons over.

    Bounded by construction: `depth` is capped at `MAX_DEPTH` and `limit` at `MAX_LIMIT`, and
    `truncated` says so when the cap bit — a silently capped subgraph reads as the whole picture.
    """
    # 404s for an unknown or out-of-project root, exactly as the sibling reads do — no existence
    # oracle for another team's entity ids.
    await _scoped_entity(session, ctx, root)
    neighborhood = await load_neighborhood(
        session,
        ctx.project.id,
        roots=[root],
        depth=depth,
        entity_types=_csv(entity_types),
        relation_types=_csv(relation_types),
        max_entities=limit,
    )
    return envelope(
        {
            "entities": [serialize_entity(e) for e in neighborhood.entities],
            "edges": [serialize_relation(r) for r in neighborhood.edges],
            "truncated": neighborhood.truncated,
        }
    )


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
