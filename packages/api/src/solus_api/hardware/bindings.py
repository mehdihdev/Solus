"""Derived manual endpoint bindings: source identities remain untouched."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import event, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, aliased

from solus_api.core.errors import APIError
from solus_api.hardware.config import EntityHardwareConfig, part_ref
from solus_api.models import GraphEdge, GraphEntity, SolusEntry, SolusEntryKind, utcnow

BINDING_RELATION = "binds"
_EPOCHS: dict[uuid.UUID, int] = {}


def binding_epoch(project_id: uuid.UUID) -> int:
    return _EPOCHS.get(project_id, 0)


def invalidate_after_commit(session: AsyncSession, project_id: uuid.UUID) -> None:
    session.info.setdefault("hardware_binding_changes", set()).add(project_id)


@event.listens_for(Session, "after_commit")
def _committed(session: Session) -> None:
    for project_id in session.info.pop("hardware_binding_changes", set()):
        _EPOCHS[project_id] = _EPOCHS.get(project_id, 0) + 1


@event.listens_for(Session, "after_rollback")
def _rolled_back(session: Session) -> None:
    session.info.pop("hardware_binding_changes", None)


async def synchronize_bindings(
    session: AsyncSession, project_id: uuid.UUID, entry: SolusEntry, config: EntityHardwareConfig
) -> None:
    """A reviewed config replaces only its own derived mapping edges, under project lock."""
    old = list(
        await session.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == project_id,
                GraphEdge.src_id == entry.entity_id,
                GraphEdge.relation_type == BINDING_RELATION,
                GraphEdge.origin == "manual",
                GraphEdge.source_id.is_(None),
                GraphEdge.deleted_at.is_(None),
            )
        )
    )
    for edge in old:
        edge.deleted_at = utcnow()
    if config.identity is not None:
        desired = [
            (item.part_entity_id, item.address, item.protocol)
            for item in config.bus_map
            if item.part_entity_id is not None
        ]
        # A bare sensor/controller may emit at the device key itself.
        desired.append((config.entity_id, "", config.protocol.driver_id if config.protocol else ""))
        refs = {
            part_ref(config.identity.device_ref, address) if address else config.identity.device_ref
            for _, address, _ in desired
        }
        others = await _conflicting_bindings(session, project_id, entry, refs)
        if others:
            raise APIError(
                409,
                "binding_conflict",
                "A device endpoint is already configured; review its existing binding",
            )
        for target, address, protocol in desired:
            ref = (
                part_ref(config.identity.device_ref, address)
                if address
                else config.identity.device_ref
            )
            session.add(
                GraphEdge(
                    project_id=project_id,
                    src_id=entry.entity_id,
                    dst_id=target,
                    relation_type=BINDING_RELATION,
                    domain_pair="project<->project",
                    origin="manual",
                    attrs={
                        "device_ref": ref,
                        "address": address,
                        "protocol": protocol,
                        "config_version": entry.config_version,
                        "enabled": True,
                    },
                )
            )
    invalidate_after_commit(session, project_id)
    await session.flush()


async def disable_part_bindings(
    session: AsyncSession,
    project_id: uuid.UUID,
    part_ids: Sequence[uuid.UUID],
    *,
    retired_owner_ids: Sequence[uuid.UUID] = (),
) -> None:
    """Disable former-owner mappings; a retired owner also releases its bare endpoint."""
    if not part_ids and not retired_owner_ids:
        return
    rows = await session.scalars(
        select(GraphEdge)
        .join(SolusEntry, SolusEntry.entity_id == GraphEdge.src_id)
        .where(
            GraphEdge.project_id == project_id,
            SolusEntry.project_id == project_id,
            or_(
                (GraphEdge.dst_id.in_(part_ids))
                & (SolusEntry.configured_entity_id != GraphEdge.dst_id),
                SolusEntry.configured_entity_id.in_(retired_owner_ids),
            ),
            GraphEdge.relation_type == BINDING_RELATION,
            GraphEdge.origin == "manual",
            GraphEdge.source_id.is_(None),
            GraphEdge.deleted_at.is_(None),
        )
    )
    for edge in rows:
        edge.attrs = {**edge.attrs, "enabled": False, "disabled_reason": "ownership_changed"}
    from solus_api.hardware.topology import HOST_MARKER, MARKER, MEMBERSHIP, RELATION
    from solus_api.models import utcnow

    topology = await session.scalars(
        select(GraphEdge).where(
            GraphEdge.project_id == project_id,
            GraphEdge.relation_type.in_((RELATION, MEMBERSHIP)),
            GraphEdge.attrs["managed_by"].astext.in_((MARKER, HOST_MARKER)),
            GraphEdge.origin == "manual",
            GraphEdge.source_id.is_(None),
            GraphEdge.deleted_at.is_(None),
            or_(
                GraphEdge.dst_id.in_(part_ids),
                GraphEdge.attrs["robot_id"].astext.in_([str(i) for i in retired_owner_ids]),
            ),
        )
    )
    for edge in topology:
        edge.deleted_at = utcnow()
    invalidate_after_commit(session, project_id)


async def _conflicting_bindings(
    session: AsyncSession, project_id: uuid.UUID, entry: SolusEntry, refs: set[str]
) -> list[GraphEdge]:
    """Historical or stale derived rows cannot reserve a current endpoint."""
    subject, target, config_node = aliased(GraphEntity), aliased(GraphEntity), aliased(GraphEntity)
    return list(
        await session.scalars(
            select(GraphEdge)
            .join(SolusEntry, SolusEntry.entity_id == GraphEdge.src_id)
            .join(subject, subject.id == SolusEntry.configured_entity_id)
            .join(target, target.id == GraphEdge.dst_id)
            .join(config_node, config_node.id == SolusEntry.entity_id)
            .where(
                GraphEdge.project_id == project_id,
                GraphEdge.src_id != entry.entity_id,
                GraphEdge.relation_type == BINDING_RELATION,
                GraphEdge.origin == "manual",
                GraphEdge.source_id.is_(None),
                GraphEdge.deleted_at.is_(None),
                GraphEdge.attrs["enabled"].as_boolean().is_(True),
                GraphEdge.attrs["device_ref"].astext.in_(refs),
                GraphEdge.attrs["config_version"].as_integer() == SolusEntry.config_version,
                SolusEntry.project_id == project_id,
                SolusEntry.kind == SolusEntryKind.CONFIG,
                SolusEntry.deleted_at.is_(None),
                subject.project_id == project_id,
                subject.deleted_at.is_(None),
                target.project_id == project_id,
                target.deleted_at.is_(None),
                config_node.project_id == project_id,
                config_node.deleted_at.is_(None),
            )
        )
    )
