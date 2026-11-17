"""Versioned project ownership, independent from configuration and provider containment.

A part's parent is a live manual Physical Robot root that contains it directly
(`ownership_edge`, SOLUSDEV-326); robot category nodes are retired.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.graph.edges import write_edge
from solus_api.graph.read_scope import GraphReadScope, current_scope, flags_of, visible_to
from solus_api.hardware.bindings import disable_part_bindings
from solus_api.hardware.in_graph import put_on, refuse_onto, stamp
from solus_api.models import GraphEdge, GraphEntity, utcnow
from solus_api.services.physical_robots import ownership_edge
from solus_api.services.solus_graph import lock_project


async def current_parent(
    session: AsyncSession, project_id: uuid.UUID, part_id: uuid.UUID
) -> uuid.UUID | None:
    rows = list(
        await session.scalars(
            select(GraphEdge.src_id)
            .where(ownership_edge(project_id), GraphEdge.dst_id == part_id)
            .limit(2)
        )
    )
    if len(rows) > 1:
        raise APIError(409, "ownership_conflict", "Multiple owners require review")
    return rows[0] if rows else None


async def list_parts(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    ownership: Literal["unassigned", "all"],
    limit: int,
    cursor: str | None,
) -> tuple[list[tuple[GraphEntity, uuid.UUID | None]], dict[str, Any]]:
    """A page of the part-like entities `user_id` may see, newest first, each with the robot that
    owns it — none when that robot is one they cannot see (another member's hidden robot holding
    a connector's part, which never carries its keys, SOLUSDEV-326); and the page's meta.
    `unassigned` is the parts no robot owns."""
    from solus_api.hardware.store import PART_KINDS, unassigned_parts_stmt

    stmt = (
        unassigned_parts_stmt(project_id)
        if ownership == "unassigned"
        else select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind.in_(PART_KINDS),
            GraphEntity.deleted_at.is_(None),
        )
    ).where(visible_to(user_id))
    if cursor:
        stmt = stmt.where(cursor_filter(GraphEntity.created_at, GraphEntity.id, cursor))
    rows = list(
        await session.scalars(
            stmt.order_by(GraphEntity.created_at.desc(), GraphEntity.id.desc()).limit(limit + 1)
        )
    )
    visible, meta = page_meta(rows, limit)
    hidden = await GraphReadScope(project_id, viewer_id=user_id).hidden_ids(session)
    parents = [await current_parent(session, project_id, part.id) for part in visible]
    return [
        (part, None if parent in hidden else parent)
        for part, parent in zip(visible, parents, strict=True)
    ], meta


async def _known_parent(
    session: AsyncSession, project_id: uuid.UUID, part_id: uuid.UUID
) -> uuid.UUID | None:
    """The part's parent for the bound reader. A part another member's hidden robot contains (a
    connector's part, which never carries the keys) is unknown to them (SOLUSDEV-326): 404,
    before a 409 could name that robot."""
    current = await current_parent(session, project_id, part_id)
    owner = await session.get(GraphEntity, current) if current is not None else None
    if owner is not None and current_scope(project_id).hides(owner.attrs):
        raise APIError(404, "not_found", "Part not found")
    return current


async def assign_parent(
    session: AsyncSession,
    project_id: uuid.UUID,
    part_id: uuid.UUID,
    *,
    parent_id: uuid.UUID | None,
    expected_parent_id: uuid.UUID | None,
    version: int,
    actor_id: uuid.UUID | None = None,
    new: bool = False,
) -> tuple[GraphEntity, uuid.UUID | None]:
    """`new`: a part created in this call takes its robot's keys outright; an existing one keeps
    its own onboarder on a robot in the graph (`put_on`)."""
    from solus_api.hardware.store import PART_KINDS, hardware_entity, robot_root

    await lock_project(session, project_id)
    part = await hardware_entity(session, project_id, part_id)
    if part.kind not in PART_KINDS:
        raise APIError(404, "not_found", "Part not found")
    current = await _known_parent(session, project_id, part_id)
    if part.version != version or current != expected_parent_id:
        raise APIError(
            409,
            "ownership_conflict",
            "Ownership changed; review the current parent",
            details=[
                {"parent_id": str(current) if current else None, "ownership_version": part.version}
            ],
        )
    # Only a robot root is a parent: a retired category's id, or anything else, is a 404.
    wanted = await robot_root(session, project_id, parent_id) if parent_id else None
    desired_id = wanted.id if wanted else None
    if current == desired_id:
        return part, current
    await _move(session, project_id, part, current, wanted, actor_id, new=new)
    part.version += 1
    await disable_part_bindings(session, project_id, [part.id])
    await session.flush()
    return part, desired_id


async def _move(
    session: AsyncSession,
    project_id: uuid.UUID,
    part: GraphEntity,
    current: uuid.UUID | None,
    wanted: GraphEntity | None,
    actor_id: uuid.UUID | None,
    *,
    new: bool,
) -> None:
    """The part's contains edge moves from `current` to `wanted`. Attributes from providers are
    facts; a manual part records its robot and is seen by whoever sees it (SOLUSDEV-326, after
    `refuse_onto`), and a part taken off keeps what it had."""
    manual = part.origin == "manual" and part.source_id is None
    if wanted is not None and manual:
        await refuse_onto(session, project_id, wanted, [part])
    if current is not None:
        rows = await session.scalars(
            select(GraphEdge).where(
                ownership_edge(project_id),
                GraphEdge.src_id == current,
                GraphEdge.dst_id == part.id,
            )
        )
        for edge in rows:
            edge.deleted_at = utcnow()
    if wanted is not None:
        await write_edge(
            session,
            project_id=project_id,
            src_id=wanted.id,
            dst_id=part.id,
            relation_type="contains",
            origin="manual",
            confidence=1.0,
            evidence=[],
            created_by=None,
        )
    if manual:
        attrs = {key: value for key, value in part.attrs.items() if key != "robot_id"}
        if wanted is not None:
            attrs["robot_id"] = str(wanted.id)
        part.attrs = attrs
        if wanted is not None and new:
            await stamp(session, project_id, [part], flags_of(wanted.attrs))
        elif wanted is not None:
            await put_on(session, project_id, wanted, part, actor_id)
