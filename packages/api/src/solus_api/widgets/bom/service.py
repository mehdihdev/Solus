"""BOM reads and writes against the graph (SOLUSDEV-246, STORE ST4).

The one place `ext:bom:item` rows are written — the route and the SOL tool both
come here — and the one loader the view is built from. Every query is
project-scoped; nothing here commits (callers own the transaction).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from solus_contracts.extension_manifest import ExtensionManifest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import Domain, GraphEdge, GraphEntity, utcnow
from solus_api.widgets.bom.rows import (
    CANONICAL_KIND,
    DEFAULT_ITEM_STATE,
    DESIGN_KINDS,
    ITEM_KIND,
    OVERLAY,
    RELATION_SAME_AS,
    BomRow,
    Canonical,
    Item,
    Observation,
    build_rows,
    canonical_from_entity,
    item_from_entity,
    observation_from_entity,
)
from solus_api.widgets.solus_config import effective_bundle_config

ORIGIN = "extension"
#: One project's parts, generously bounded; the payload says when the bound hit.
ENTITY_CAP = 20_000
DEFAULT_CURRENCY = "USD"


@dataclass(frozen=True)
class BomInputs:
    observations: list[Observation]
    canonicals: list[Canonical]
    same_as: list[tuple[uuid.UUID, uuid.UUID]]
    items: list[Item]
    truncated: bool

    def rows(self) -> list[BomRow]:
        return build_rows(self.observations, self.canonicals, self.same_as, self.items)


@dataclass(frozen=True)
class BomConfig:
    preferred_suppliers: list[str]
    cost_target: float | None
    currency: str

    def payload(self) -> dict[str, Any]:
        return {
            "preferred_suppliers": self.preferred_suppliers,
            "cost_target": self.cost_target,
            "currency": self.currency,
        }


async def load_inputs(session: AsyncSession, project_id: uuid.UUID) -> BomInputs:
    kinds = [*DESIGN_KINDS, CANONICAL_KIND, ITEM_KIND]
    entities = list(
        await session.scalars(
            select(GraphEntity)
            .where(
                GraphEntity.project_id == project_id,
                GraphEntity.kind.in_(kinds),
                GraphEntity.deleted_at.is_(None),
            )
            .order_by(GraphEntity.id)
            .limit(ENTITY_CAP + 1)
        )
    )
    truncated = len(entities) > ENTITY_CAP
    entities = entities[:ENTITY_CAP]
    edges = (
        await session.execute(
            select(GraphEdge.src_id, GraphEdge.dst_id).where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type == RELATION_SAME_AS,
                GraphEdge.deleted_at.is_(None),
            )
        )
    ).all()
    observations = [observation_from_entity(e) for e in entities if e.kind in DESIGN_KINDS]
    canonicals = [canonical_from_entity(e) for e in entities if e.kind == CANONICAL_KIND]
    items = [
        item for item in (item_from_entity(e) for e in entities if e.kind == ITEM_KIND) if item
    ]
    return BomInputs(
        observations, canonicals, [(a, b) for a, b in edges], items, truncated=truncated
    )


async def load_config(
    session: AsyncSession, project_id: uuid.UUID, manifest: ExtensionManifest | None
) -> BomConfig:
    """Supplier preferences and the cost target: manifest defaults ← repo
    `[ext.bom]` ← install settings (`effective_bundle_config`)."""
    config = await effective_bundle_config(session, project_id, "bom", manifest) if manifest else {}
    raw_suppliers = config.get("preferred_suppliers")
    suppliers = (
        [s.strip() for s in raw_suppliers.split(",") if s.strip()]
        if isinstance(raw_suppliers, str)
        else []
    )
    target = config.get("cost_target")
    cost_target = (
        float(target) if isinstance(target, int | float) and not isinstance(target, bool) else None
    )
    currency = config.get("currency")
    return BomConfig(
        preferred_suppliers=suppliers[:16],
        cost_target=cost_target if cost_target is None or cost_target >= 0 else None,
        currency=currency if isinstance(currency, str) and currency else DEFAULT_CURRENCY,
    )


def _item_attrs(fields: dict[str, Any], user_id: uuid.UUID | None) -> dict[str, Any]:
    attrs = {k: v for k, v in fields.items() if k != "name" and v is not None}
    attrs["created_by"] = str(user_id) if user_id else None
    return attrs


async def create_item(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID | None,
    name: str,
    category: str,
    fields: dict[str, Any],
) -> GraphEntity:
    """A standalone raw-material / purchase row. `fields` are already validated
    (route body or tool schema); state defaults to `planned`."""
    values = {"category": category, "state": DEFAULT_ITEM_STATE, "quantity": 1, **fields}
    row = GraphEntity(
        project_id=project_id,
        kind=ITEM_KIND,
        domain=Domain.PROJECT,
        name=name[:512],
        origin=ORIGIN,
        attrs=_item_attrs(values, user_id),
    )
    session.add(row)
    await session.flush()
    return row


async def find_item(
    session: AsyncSession, project_id: uuid.UUID, item_id: uuid.UUID
) -> GraphEntity | None:
    row: GraphEntity | None = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.id == item_id,
            GraphEntity.project_id == project_id,
            GraphEntity.kind == ITEM_KIND,
            GraphEntity.deleted_at.is_(None),
        )
    )
    return row


async def find_overlay(
    session: AsyncSession, project_id: uuid.UUID, row_key: str
) -> GraphEntity | None:
    row: GraphEntity | None = await session.scalar(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == ITEM_KIND,
            GraphEntity.deleted_at.is_(None),
            GraphEntity.attrs["category"].astext == OVERLAY,
            GraphEntity.attrs["row_key"].astext == row_key,
        )
        .order_by(GraphEntity.created_at)
        .limit(1)
    )
    return row


def apply_patch(row: GraphEntity, patch: dict[str, Any]) -> None:
    """New attrs dict (no in-place mutation of the JSONB) + name."""
    updates = {k: v for k, v in patch.items() if k != "name"}
    row.attrs = {**row.attrs, **updates}
    if isinstance(patch.get("name"), str):
        row.name = patch["name"][:512]
    row.version = (row.version or 1) + 1


async def upsert_overlay(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID | None,
    row: BomRow,
    patch: dict[str, Any],
) -> GraphEntity:
    existing = await find_overlay(session, project_id, row.key)
    if existing is not None:
        apply_patch(existing, patch)
        await session.flush()
        return existing
    values = {"category": OVERLAY, "row_key": row.key, "state": row.state, "quantity": 1, **patch}
    overlay = GraphEntity(
        project_id=project_id,
        kind=ITEM_KIND,
        domain=Domain.PROJECT,
        name=row.name[:512],
        origin=ORIGIN,
        attrs=_item_attrs(values, user_id),
    )
    session.add(overlay)
    await session.flush()
    return overlay


def soft_delete(row: GraphEntity) -> None:
    row.deleted_at = utcnow()
