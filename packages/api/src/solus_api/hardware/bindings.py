"""Derived manual endpoint bindings: source identities remain untouched."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence

from sqlalchemy import Select, event, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, aliased

from solus_api.core.errors import APIError
from solus_api.graph.edges import write_edge
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


def _desired_bindings(config: EntityHardwareConfig) -> list[tuple[uuid.UUID, str, str, str]]:
    """(target, device ref, address, protocol): each bound brain's bare endpoint (a board may
    emit at its own device key) and each mapped row on the brain it sits behind."""
    desired = [
        (config.entity_id, ref, "", brain.protocol.driver_id if brain.protocol else "")
        for brain in config.identity
        if (ref := brain.device_ref) is not None
    ]
    for row in config.bus_map:
        brain_ref = config.brain_of(row)
        if row.part_entity_id is not None and brain_ref is not None:
            desired.append(
                (row.part_entity_id, part_ref(brain_ref, row.address), row.address, row.protocol)
            )
    return desired


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
    owner = entry.entity_id
    desired = _desired_bindings(config)
    if desired:
        if owner is None:
            raise APIError(409, "binding_conflict", "Hardware config has no graph identity")
        refs = {ref for _, ref, _, _ in desired}
        if await bound_elsewhere(session, project_id, config.entity_id, refs):
            raise APIError(
                409,
                "binding_conflict",
                "A device endpoint is already configured; review its existing binding",
            )
        for target, ref, address, protocol in desired:
            # One identity per (config node, target, device ref, protocol): a re-sync
            # resurrects the same row instead of minting a new one per config version.
            await write_edge(
                session,
                project_id=project_id,
                src_id=owner,
                dst_id=target,
                relation_type=BINDING_RELATION,
                origin="manual",
                confidence=1.0,
                evidence=[],
                created_by=None,
                attrs={
                    "device_ref": ref,
                    "address": address,
                    "protocol": protocol,
                    "config_version": entry.config_version,
                    "enabled": True,
                },
                edge_id=uuid.uuid5(owner, f"{BINDING_RELATION}:{target}:{ref}:{protocol}"),
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


def _current_bindings(
    project_id: uuid.UUID, refs: Collection[str]
) -> Select[tuple[GraphEdge, GraphEntity]]:
    """Live configs' current bindings of `refs`, each with the subject whose config holds it.
    Historical or stale derived rows cannot reserve a current endpoint."""
    subject, target, config_node = aliased(GraphEntity), aliased(GraphEntity), aliased(GraphEntity)
    return (
        select(GraphEdge, subject)
        .join(SolusEntry, SolusEntry.entity_id == GraphEdge.src_id)
        .join(subject, subject.id == SolusEntry.configured_entity_id)
        .join(target, target.id == GraphEdge.dst_id)
        .join(config_node, config_node.id == SolusEntry.entity_id)
        .where(
            GraphEdge.project_id == project_id,
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


async def bound_elsewhere(
    session: AsyncSession, project_id: uuid.UUID, subject_id: uuid.UUID, refs: set[str]
) -> list[GraphEdge]:
    """Current bindings of `refs` held by another subject's live config: one config per device
    project-wide."""
    rows = await session.execute(
        _current_bindings(project_id, refs).where(SolusEntry.configured_entity_id != subject_id)
    )
    return [edge for edge, _ in rows.tuples()]


async def binding_subjects(
    session: AsyncSession, project_id: uuid.UUID, refs: Collection[str]
) -> dict[str, GraphEntity]:
    """The robot or part whose live config binds each of `refs` (SOLUSDEV-326): a brain's
    bare endpoint, so a board bound by its connection alone counts."""
    rows = await session.execute(_current_bindings(project_id, refs))
    return {str(edge.attrs["device_ref"]): subject for edge, subject in rows.tuples()}
