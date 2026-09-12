"""§2.4 Graph reads and the bounded Physical Robot manual mutation subtype."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request
from sqlalchemy import and_, or_, select

from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, require_role
from solus_api.graph.live import graph_changed_frame
from solus_api.graph.neighborhood import MAX_DEPTH, load_neighborhood
from solus_api.graph.read_scope import current_scope
from solus_api.models import Domain, GraphEdge, GraphEntity, Role, Source, utcnow
from solus_api.schemas import serialize_entity, serialize_relation
from solus_api.services.events import emit_event
from solus_api.services.physical_robots import (
    GraphChangeCounts,
    PhysicalRobotCreate,
    PhysicalRobotRename,
    PhysicalRobotService,
    orphaned_robot_part_filter,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}")

MAX_LIMIT = 500
MAX_FILTER_VALUES = 32  # a focus filter, not a query language
IfMatch = Annotated[str, Header(pattern=r"^[0-9]+$", max_length=10)]


async def _scoped_entity(session: SessionDep, ctx: ProjectCtx, entity_id: uuid.UUID) -> GraphEntity:
    entity = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.id == entity_id, current_scope(ctx.project.id).entity_predicate()
        )
    )
    if entity is None or entity.project_id != ctx.project.id or entity.deleted_at is not None:
        raise APIError(404, "not_found", "Entity not found")
    return entity


async def _refuse_snapshot_mutation(
    session: SessionDep, ctx: ProjectCtx, entity_id: uuid.UUID
) -> None:
    entity = await _scoped_entity(session, ctx, entity_id)
    if entity.source_id is not None:
        source = await session.get(Source, entity.source_id)
        if source is not None and source.revision_base_source_id is not None:
            raise APIError(409, "immutable_revision", "Revision snapshots cannot be edited")


def _domain(value: str) -> Domain:
    try:
        return Domain(value)
    except ValueError as exc:
        raise APIError(422, "validation_error", f"Unknown domain '{value}'") from exc


def _like_literal(value: str) -> str:
    """Neutralise LIKE's wildcards so a caller's text matches itself and nothing
    else. Backslash FIRST, or it would re-escape the escapes we just added.

    Both LIKE filters below take user-influenced text, and an unescaped `%`
    turns either into "everything in this project" — a filter that silently
    stops filtering. Match with `escape="\\"` wherever this is used.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/entities")
async def list_entities(
    ctx: ProjectCtx,
    session: SessionDep,
    type: Annotated[str | None, Query(max_length=64)] = None,
    source_id: Annotated[uuid.UUID | None, Query()] = None,
    domain: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=255)] = None,
    external_ref_prefix: Annotated[str | None, Query(max_length=255)] = None,
    orphaned_from_robot: Annotated[bool, Query()] = False,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 200,
) -> dict[str, Any]:
    stmt = select(GraphEntity).where(
        GraphEntity.project_id == ctx.project.id,
        GraphEntity.deleted_at.is_(None),
        current_scope(ctx.project.id).entity_predicate(),
    )
    if type is not None:
        stmt = stmt.where(GraphEntity.kind == type)
    if source_id is not None:
        stmt = stmt.where(GraphEntity.source_id == source_id)
    if orphaned_from_robot:
        stmt = stmt.where(orphaned_robot_part_filter(ctx.project.id))
    if domain is not None:
        stmt = stmt.where(GraphEntity.domain == _domain(domain))
    if q:
        # Escaped for the same reason the prefix below is: this is the SOL
        # composer's `@`-mention typeahead, so `q` is text a person is typing,
        # and a bare `%` would match every entity in the project — a search box
        # that silently stops filtering.
        pattern = f"%{_like_literal(q)}%"
        stmt = stmt.where(
            or_(
                GraphEntity.name.ilike(pattern, escape="\\"),
                and_(
                    GraphEntity.kind.in_(("code_file", "code_module")),
                    or_(
                        GraphEntity.external_ref.ilike(pattern, escape="\\"),
                        GraphEntity.attrs["path"].astext.ilike(pattern, escape="\\"),
                    ),
                ),
            )
        )
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
        literal = _like_literal(external_ref_prefix)
        stmt = stmt.where(GraphEntity.external_ref.like(f"{literal}%", escape="\\"))
    if cursor:
        stmt = stmt.where(cursor_filter(GraphEntity.created_at, GraphEntity.id, cursor))
    stmt = stmt.order_by(GraphEntity.created_at.desc(), GraphEntity.id.desc()).limit(limit + 1)
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    return envelope([serialize_entity(e) for e in visible], meta=meta)


async def _commit_robot_change(
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    root: GraphEntity,
    action: str,
    counts: GraphChangeCounts,
) -> None:
    emit_event(
        session,
        user=ctx.user,
        event_type=f"workspace.robot_{action}",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"entity_id": str(root.id), "version": root.version},
    )
    await session.commit()
    await request.app.state.graph_hub.publish(
        ctx.project.id,
        graph_changed_frame(
            project_id=ctx.project.id,
            source_id=None,
            sync_id=None,
            counts=counts,
            at=utcnow().isoformat(),
        ),
    )


@router.post("/entities", status_code=201)
async def create_entity(
    body: PhysicalRobotCreate, request: Request, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    root = await PhysicalRobotService(session).create(ctx.project.id, body.name)
    await _commit_robot_change(
        request,
        ctx,
        session,
        root,
        "created",
        GraphChangeCounts(entities_created=8, relations_created=7),
    )
    return envelope(serialize_entity(root))


@router.patch("/entities/{entity_id}")
async def rename_entity(
    entity_id: uuid.UUID,
    body: PhysicalRobotRename,
    if_match: IfMatch,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    await _refuse_snapshot_mutation(session, ctx, entity_id)
    root = await PhysicalRobotService(session).rename(
        ctx.project.id, entity_id, int(if_match), body.name
    )
    await _commit_robot_change(
        request, ctx, session, root, "renamed", GraphChangeCounts(entities_updated=1)
    )
    return envelope(serialize_entity(root))


@router.delete("/entities/{entity_id}")
async def delete_entity(
    entity_id: uuid.UUID, if_match: IfMatch, request: Request, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    await _refuse_snapshot_mutation(session, ctx, entity_id)
    root = await _scoped_entity(session, ctx, entity_id)
    if root.version != int(if_match):
        raise APIError(409, "conflict", "Entity version changed; reload before deleting")
    request.app.state.hardware_connections.assert_deletable(root.attrs.get("connection"))
    await request.app.state.hardware_connections.cancel_robot(ctx.project.id, entity_id)
    removal = await PhysicalRobotService(session).delete(ctx.project.id, entity_id, int(if_match))
    # The service holds the project lock and refreshed attrs; a concurrent attempt
    # cannot be accepted between this check and the deletion commit.
    request.app.state.hardware_connections.assert_deletable(removal.root.attrs.get("connection"))
    await _commit_robot_change(request, ctx, session, removal.root, "removed", removal.counts)
    return envelope(
        {"deleted_entity_id": entity_id, "retained_part_ids": removal.retained_part_ids}
    )


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
        GraphEdge.project_id == ctx.project.id,
        GraphEdge.deleted_at.is_(None),
        current_scope(ctx.project.id).edge_predicate(),
    )
    if direction == "in":
        stmt = stmt.where(GraphEdge.dst_id.in_(current_scope(ctx.project.id).aliases([entity_id])))
    elif direction == "out":
        stmt = stmt.where(GraphEdge.src_id.in_(current_scope(ctx.project.id).aliases([entity_id])))
    else:
        stmt = stmt.where(
            or_(
                GraphEdge.src_id.in_(current_scope(ctx.project.id).aliases([entity_id])),
                GraphEdge.dst_id.in_(current_scope(ctx.project.id).aliases([entity_id])),
            )
        )
    if type is not None:
        stmt = stmt.where(GraphEdge.relation_type == type)
    if cursor:
        stmt = stmt.where(cursor_filter(GraphEdge.created_at, GraphEdge.id, cursor))
    stmt = stmt.order_by(GraphEdge.created_at.desc(), GraphEdge.id.desc()).limit(limit + 1)
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    return envelope(
        [serialize_relation(current_scope(ctx.project.id).project_edge(r)) for r in visible],
        meta=meta,
    )


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
        GraphEdge.project_id == ctx.project.id,
        GraphEdge.deleted_at.is_(None),
        current_scope(ctx.project.id).edge_predicate(),
    )
    if type is not None:
        stmt = stmt.where(GraphEdge.relation_type == type)
    if cursor:
        stmt = stmt.where(cursor_filter(GraphEdge.created_at, GraphEdge.id, cursor))
    stmt = stmt.order_by(GraphEdge.created_at.desc(), GraphEdge.id.desc()).limit(limit + 1)
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    return envelope(
        [serialize_relation(current_scope(ctx.project.id).project_edge(r)) for r in visible],
        meta=meta,
    )
