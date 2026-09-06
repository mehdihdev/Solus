"""Uninstall leaves no trace (SOLUSDEV-246, widget-bundles.md §5).

Called inside the DELETE install transaction: soft-deletes every live entity of
the bundle's declared kinds in THIS project (and the edges touching them —
ADR-027 soft delete, reversible) and prunes the bundle's ``ext:<slug>`` slot
from every user's canvas layout in the project. Storage rows and the install
row are the route's own job, as before.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from solus_contracts.extension_manifest import ExtensionManifest, graph_kind_name
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import GraphEdge, GraphEntity, WidgetLayout, utcnow


@dataclass(frozen=True)
class BundleSweep:
    entities_soft_deleted: int
    layout_slots_pruned: int


async def _soft_delete_kinds(session: AsyncSession, project_id: uuid.UUID, kinds: list[str]) -> int:
    if not kinds:
        return 0
    now = utcnow()
    live = (
        GraphEntity.project_id == project_id,
        GraphEntity.kind.in_(kinds),
        GraphEntity.deleted_at.is_(None),
    )
    # Edges first (they select on the still-live entities), by subquery — no
    # id list is ever materialised, however many notes a project holds.
    doomed = select(GraphEntity.id).where(*live).scalar_subquery()
    await session.execute(
        update(GraphEdge)
        .where(
            GraphEdge.project_id == project_id,
            or_(GraphEdge.src_id.in_(doomed), GraphEdge.dst_id.in_(doomed)),
            GraphEdge.deleted_at.is_(None),
        )
        .values(deleted_at=now)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(
        update(GraphEntity)
        .where(*live)
        .values(deleted_at=now)
        .execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def _prune_layouts(session: AsyncSession, project_id: uuid.UUID, slug: str) -> int:
    ref = f"ext:{slug}"
    pruned = 0
    for layout in await session.scalars(
        select(WidgetLayout).where(WidgetLayout.project_id == project_id)
    ):
        kept = [slot for slot in layout.layout if slot.get("ref") != ref]
        if len(kept) != len(layout.layout):
            pruned += len(layout.layout) - len(kept)
            layout.layout = kept  # a new list: the JSONB column sees the change
    return pruned


async def remove_bundle_traces(
    session: AsyncSession, project_id: uuid.UUID, slug: str, manifest: ExtensionManifest
) -> BundleSweep:
    kinds = [graph_kind_name(slug, kind.name) for kind in manifest.graph.kinds]
    return BundleSweep(
        entities_soft_deleted=await _soft_delete_kinds(session, project_id, kinds),
        layout_slots_pruned=await _prune_layouts(session, project_id, slug),
    )
