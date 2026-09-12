"""Versioned project ownership, independent from configuration and provider containment."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.hardware.bindings import disable_part_bindings
from solus_api.models import GraphEdge, GraphEntity, utcnow
from solus_api.services.physical_robots import ROBOT_CATEGORIES
from solus_api.services.solus_graph import lock_project


async def current_parent(
    session: AsyncSession, project_id: uuid.UUID, part_id: uuid.UUID
) -> uuid.UUID | None:
    from solus_api.services.physical_robots import _container_ids

    rows = list(
        await session.scalars(
            select(GraphEdge.src_id)
            .where(
                GraphEdge.project_id == project_id,
                GraphEdge.dst_id == part_id,
                GraphEdge.relation_type == "contains",
                GraphEdge.origin == "manual",
                GraphEdge.source_id.is_(None),
                GraphEdge.deleted_at.is_(None),
                GraphEdge.src_id.in_(_container_ids(project_id, deleted=False)),
            )
            .limit(2)
        )
    )
    if len(rows) > 1:
        raise APIError(409, "ownership_conflict", "Multiple owners require review")
    return rows[0] if rows else None


async def target_category(
    session: AsyncSession, project_id: uuid.UUID, parent_id: uuid.UUID, category: str | None
) -> GraphEntity:
    from solus_api.hardware.store import _category_node, robot_root

    parent = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.id == parent_id,
            GraphEntity.deleted_at.is_(None),
            GraphEntity.origin == "manual",
            GraphEntity.source_id.is_(None),
        )
    )
    if parent is None:
        raise APIError(404, "not_found", "Hardware parent not found")
    if parent.kind == "physical_robot":
        if category is None:
            raise APIError(422, "validation_error", "Choose a category for the robot parent")
        return await _category_node(session, project_id, parent, category)
    if parent.kind != "robot_category":
        raise APIError(404, "not_found", "Hardware parent not found")
    declared = parent.attrs.get("category")
    if declared not in ROBOT_CATEGORIES or (category is not None and category != declared):
        raise APIError(422, "validation_error", "Category does not match the selected parent")
    try:
        robot_id = uuid.UUID(parent.attrs.get("robot_id", ""))
    except (ValueError, TypeError):
        raise APIError(404, "not_found", "Hardware parent not found") from None
    await robot_root(session, project_id, robot_id)
    edge = await session.scalar(
        select(GraphEdge.id).where(
            GraphEdge.project_id == project_id,
            GraphEdge.src_id == robot_id,
            GraphEdge.dst_id == parent.id,
            GraphEdge.relation_type == "contains",
            GraphEdge.origin == "manual",
            GraphEdge.source_id.is_(None),
            GraphEdge.deleted_at.is_(None),
        )
    )
    if edge is None:
        raise APIError(404, "not_found", "Hardware parent not found")
    return parent


async def assign_parent(
    session: AsyncSession,
    project_id: uuid.UUID,
    part_id: uuid.UUID,
    *,
    parent_id: uuid.UUID | None,
    expected_parent_id: uuid.UUID | None,
    version: int,
    category: str | None = None,
) -> tuple[GraphEntity, uuid.UUID | None]:
    from solus_api.hardware.store import PART_KINDS, hardware_entity

    await lock_project(session, project_id)
    part = await hardware_entity(session, project_id, part_id)
    if part.kind not in PART_KINDS:
        raise APIError(404, "not_found", "Part not found")
    current = await current_parent(session, project_id, part_id)
    if part.version != version or current != expected_parent_id:
        raise APIError(
            409,
            "ownership_conflict",
            "Ownership changed; review the current parent",
            details=[
                {"parent_id": str(current) if current else None, "ownership_version": part.version}
            ],
        )
    wanted = await target_category(session, project_id, parent_id, category) if parent_id else None
    desired_id = wanted.id if wanted else None
    if current == desired_id:
        return part, current
    if current is not None:
        rows = await session.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == project_id,
                GraphEdge.src_id == current,
                GraphEdge.dst_id == part.id,
                GraphEdge.relation_type == "contains",
                GraphEdge.origin == "manual",
                GraphEdge.source_id.is_(None),
                GraphEdge.deleted_at.is_(None),
            )
        )
        for edge in rows:
            edge.deleted_at = utcnow()
    if wanted is not None:
        session.add(
            GraphEdge(
                project_id=project_id,
                src_id=wanted.id,
                dst_id=part.id,
                relation_type="contains",
                domain_pair=f"project<->{part.domain.value}",
                origin="manual",
            )
        )
    # Attributes from providers are facts. Manual convenience metadata may track ownership.
    if part.origin == "manual" and part.source_id is None:
        attrs = {key: value for key, value in part.attrs.items() if key != "robot_id"}
        if wanted is not None:
            attrs.update(robot_id=wanted.attrs["robot_id"], category=wanted.attrs["category"])
        part.attrs = attrs
    part.version += 1
    await disable_part_bindings(session, project_id, [part.id])
    await session.flush()
    return part, desired_id
