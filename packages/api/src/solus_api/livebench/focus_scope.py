"""Authorized, read-only physical focus projection for device telemetry."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.graph.read_scope import current_scope
from solus_api.hardware.topology import HOST_MARKER, MARKER, MEMBERSHIP, RELATION
from solus_api.models import GraphEdge, GraphEntity


async def focus_entity_ids(
    session: AsyncSession, project_id: uuid.UUID, focus_id: uuid.UUID
) -> set[uuid.UUID]:
    scope = current_scope(project_id)
    focus = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.id == focus_id,
            scope.entity_predicate(),
            GraphEntity.deleted_at.is_(None),
        )
    )
    if focus is None:
        raise APIError(404, "not_found", "Focused entity not found")
    # UUID-only UNION (not UNION ALL) deduplicates the recursive frontier, so
    # cycles terminate without path arrays or loading unrelated project edges.
    reachable = (
        select(GraphEntity.id.label("id"))
        .where(
            GraphEntity.id == focus_id, scope.entity_predicate(), GraphEntity.deleted_at.is_(None)
        )
        .cte("focus_reachable", recursive=True)
    )
    step = (
        select(GraphEdge.dst_id.label("id"))
        .join(reachable, GraphEdge.src_id == reachable.c.id)
        .join(GraphEntity, GraphEntity.id == GraphEdge.dst_id)
        .where(
            GraphEdge.project_id == project_id,
            GraphEdge.deleted_at.is_(None),
            GraphEdge.origin == "manual",
            GraphEdge.source_id.is_(None),
            GraphEdge.attrs["managed_by"].astext.in_((MARKER, HOST_MARKER)),
            scope.entity_predicate(),
            GraphEntity.deleted_at.is_(None),
        )
    )
    if focus.kind == "physical_robot":
        step = step.where(
            GraphEdge.relation_type.in_((MEMBERSHIP, RELATION)),
            GraphEdge.attrs["robot_id"].astext == str(focus_id),
        )
    else:
        step = step.where(GraphEdge.relation_type == RELATION)
    reachable = reachable.union(step)
    return set((await session.execute(select(reachable.c.id))).scalars())
