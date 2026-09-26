"""Persist accepted physical connectivity separately from robot ownership.

Category/CONFIG records remain the compatibility authority. These additive graph facts
never grant transport permissions and reads never infer missing hardware or software.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.models import Domain, GraphEdge, GraphEntity, utcnow

MARKER = "hardware_topology_v1"
HOST_MARKER = "hardware_host_topology_v1"
EVIDENCE_MARKER = "hardware_extraction_evidence_v1"
EVIDENCE_RELATION = "hardware_evidence_for"
RELATION = "hardware_connected_to"
MEMBERSHIP = "hardware_topology_member"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: str = Field(max_length=32)
    source: str | None = Field(default=None, max_length=512)


class TopologyNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    name: str
    role: Literal["brain", "bus", "device", "part"]
    brain_kind: Literal["host", "mcu", "onboard"] | None = None
    category: str | None = None
    channel: str | None = None
    software: str | None = None
    presence: str | None = None
    evidence: list[Evidence] = Field(default_factory=list, max_length=32)


class TopologyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    source: uuid.UUID
    target: uuid.UUID
    protocol: str | None = None
    address: str | None = None


class RobotTopology(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: uuid.UUID
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
    roots: list[uuid.UUID]


class RobotTopologyEnvelope(BaseModel):
    data: RobotTopology


async def sync_topology(session: AsyncSession, project_id: uuid.UUID, robot_id: uuid.UUID) -> None:
    """Refresh derived edges in the caller's reviewed, project-locked transaction."""
    from solus_api.hardware.store import robot_root
    from solus_api.services.solus_graph import lock_project

    await lock_project(session, project_id)
    await robot_root(session, project_id, robot_id)
    config = await resolve_runtime_config(session, project_id, robot_id)
    targets = [item.part_entity_id for item in config.bus_map if item.part_entity_id is not None]
    if len(targets) != len(set(targets)):
        raise APIError(409, "topology_conflict", "Ambiguous topology part addresses require review")
    existing = list(
        await session.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type.in_((RELATION, MEMBERSHIP)),
                GraphEdge.attrs["robot_id"].astext == str(robot_id),
                GraphEdge.origin == "manual",
                GraphEdge.source_id.is_(None),
            )
        )
    )
    desired: set[uuid.UUID] = set()
    endpoint_id: uuid.UUID | None = None
    if config.identity is not None:
        endpoint_id = uuid.uuid5(project_id, f"{MARKER}:endpoint:{config.identity.device_ref}")
        await _node(
            session,
            project_id,
            endpoint_id,
            "hardware_brain",
            config.identity.device_ref,
            {"channel": config.identity.kind.value},
            owner_id=robot_id,
        )
        # A membership edge selects the robot projection; it is not physical wiring.
        await _edge(session, project_id, robot_id, robot_id, endpoint_id, None, None, [], desired)
        for index, item in enumerate(config.bus_map):
            bus_id = uuid.uuid5(endpoint_id, f"bus:{item.protocol}")
            await _node(session, project_id, bus_id, "hardware_bus", item.protocol, {})
            record = config.provenance_of(f"bus_map.{index}.protocol")
            evidence = [Evidence(by=record.by.value, source=record.source).model_dump()]
            await _edge(
                session,
                project_id,
                robot_id,
                endpoint_id,
                bus_id,
                item.protocol,
                None,
                evidence,
                desired,
            )
            if item.part_entity_id is None:
                continue
            part = await session.scalar(
                select(GraphEntity).where(
                    GraphEntity.id == item.part_entity_id,
                    GraphEntity.project_id == project_id,
                    GraphEntity.deleted_at.is_(None),
                )
            )
            if part is None:
                raise APIError(
                    409, "topology_conflict", "A configured part is absent from this project"
                )
            await _edge(
                session,
                project_id,
                robot_id,
                bus_id,
                part.id,
                item.protocol,
                item.address,
                evidence,
                desired,
            )
    for edge in existing:
        if edge.attrs.get("managed_by") == HOST_MARKER and edge.attrs.get("endpoint_id") == str(
            endpoint_id
        ):
            continue
        if edge.id not in desired:
            edge.deleted_at = utcnow()
    await session.flush()


async def _node(
    session: AsyncSession,
    project_id: uuid.UUID,
    node_id: uuid.UUID,
    kind: str,
    name: str,
    facts: dict[str, str],
    *,
    owner_id: uuid.UUID | None = None,
) -> None:
    node = await session.get(GraphEntity, node_id)
    if node is None:
        node = GraphEntity(
            id=node_id,
            project_id=project_id,
            kind=kind,
            domain=Domain.ELECTRICAL,
            origin="manual",
            name=name,
            attrs={"managed_by": MARKER, **facts},
        )
        session.add(node)
    elif node.project_id != project_id or node.attrs.get("managed_by") != MARKER:
        raise APIError(409, "topology_conflict", "Hardware topology identity conflicts")
    elif facts.get("channel") is not None and facts["channel"] != node.attrs.get("channel"):
        other = await session.scalar(
            select(GraphEdge.id)
            .join(GraphEntity, GraphEntity.id == GraphEdge.src_id)
            .where(
                GraphEdge.project_id == project_id,
                GraphEdge.dst_id == node_id,
                GraphEdge.src_id != owner_id,
                GraphEdge.relation_type == MEMBERSHIP,
                GraphEdge.origin == "manual",
                GraphEdge.source_id.is_(None),
                GraphEdge.deleted_at.is_(None),
                GraphEntity.project_id == project_id,
                GraphEntity.deleted_at.is_(None),
            )
            .limit(1)
        )
        if other is not None:
            raise APIError(
                409, "topology_conflict", "Shared hardware channel requires joint review"
            )
    node.attrs = {**node.attrs, **facts}
    node.deleted_at = None
    await session.flush()


async def _edge(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot_id: uuid.UUID,
    src: uuid.UUID,
    dst: uuid.UUID,
    protocol: str | None,
    address: str | None,
    evidence: list[dict[str, str | None]],
    desired: set[uuid.UUID],
) -> None:
    edge_id = uuid.uuid5(robot_id, f"{MARKER}:{src}:{dst}:{protocol}:{address}")
    desired.add(edge_id)
    edge = await session.get(GraphEdge, edge_id)
    attrs = {
        "managed_by": MARKER,
        "robot_id": str(robot_id),
        "protocol": protocol,
        "address": address,
        "evidence": evidence,
    }
    if edge is None:
        edge = GraphEdge(
            id=edge_id,
            project_id=project_id,
            src_id=src,
            dst_id=dst,
            relation_type=MEMBERSHIP if src == robot_id else RELATION,
            domain_pair="electrical<->electrical",
            origin="manual",
            attrs=attrs,
        )
        session.add(edge)
    elif edge.project_id != project_id or edge.attrs.get("managed_by") != MARKER:
        raise APIError(409, "topology_conflict", "Hardware relation identity conflicts")
    else:
        edge.attrs = attrs
        edge.deleted_at = None


async def read_topology(
    session: AsyncSession, project_id: uuid.UUID, robot_id: uuid.UUID
) -> RobotTopology:
    from solus_api.hardware.store import robot_root

    await robot_root(session, project_id, robot_id)
    edges = list(
        await session.scalars(
            select(GraphEdge)
            .where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type.in_((RELATION, MEMBERSHIP, EVIDENCE_RELATION)),
                GraphEdge.attrs["robot_id"].astext == str(robot_id),
                GraphEdge.deleted_at.is_(None),
                GraphEdge.origin == "manual",
                GraphEdge.source_id.is_(None),
            )
            .order_by(GraphEdge.id)
        )
    )
    ids = {e.src_id for e in edges} | {e.dst_id for e in edges}
    ids.discard(robot_id)
    category_rows = (
        await session.execute(
            select(GraphEdge.dst_id, GraphEntity.attrs["category"].astext)
            .join(GraphEntity, GraphEntity.id == GraphEdge.src_id)
            .where(
                GraphEntity.project_id == project_id,
                GraphEntity.kind == "robot_category",
                GraphEntity.origin == "manual",
                GraphEntity.source_id.is_(None),
                GraphEntity.deleted_at.is_(None),
                GraphEntity.attrs["robot_id"].astext == str(robot_id),
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type == "contains",
                GraphEdge.origin == "manual",
                GraphEdge.source_id.is_(None),
                GraphEdge.deleted_at.is_(None),
            )
        )
    ).all()
    categories = {row[0]: row[1] for row in category_rows}
    ids.update(categories)
    entities = (
        list(
            await session.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.id.in_(ids),
                    GraphEntity.deleted_at.is_(None),
                    GraphEntity.kind != "robot_category",
                )
                .order_by(GraphEntity.id)
            )
        )
        if ids
        else []
    )
    nodes = []
    evidence_ids = {
        entity.id
        for entity in entities
        if entity.kind == "hardware_evidence" and entity.attrs.get("managed_by") == EVIDENCE_MARKER
    }
    annotations = [
        edge
        for edge in edges
        if edge.relation_type == EVIDENCE_RELATION
        and edge.attrs.get("managed_by") == EVIDENCE_MARKER
    ]
    # Reviewed annotations enrich existing identities; only newly created evidence
    # nodes gain a display parent. No annotation changes operational connectivity.
    edges = [
        edge
        for edge in edges
        if edge.relation_type != EVIDENCE_RELATION
        or (
            edge in annotations
            and edge.attrs.get("is_placement") is True
            and edge.dst_id in evidence_ids
        )
    ]
    for entity in entities:
        role: Literal["brain", "bus", "device", "part"] = (
            "brain"
            if entity.kind == "hardware_brain"
            else "bus"
            if entity.kind == "hardware_bus"
            else "part"
        )
        facts = entity.attrs if entity.attrs.get("managed_by") in (MARKER, HOST_MARKER) else {}
        overlay = next(
            (
                e.attrs
                for e in edges
                if e.dst_id == entity.id and e.attrs.get("managed_by") == HOST_MARKER
            ),
            {},
        )
        evidence: list[Evidence] = [
            Evidence.model_validate(item)
            for item in next(
                (e.attrs.get("evidence", []) for e in edges if e.dst_id == entity.id), []
            )
        ]
        for annotation in annotations:
            if annotation.dst_id == entity.id and len(evidence) < 32:
                row = annotation.attrs.get("row", {})
                source = row.get("source_ref") if isinstance(row, dict) else None
                if source is None or (isinstance(source, str) and len(source) <= 512):
                    evidence.append(Evidence(by="user", source=source))
        nodes.append(
            TopologyNode(
                id=entity.id,
                name=entity.name,
                role=role,
                channel=facts.get("channel"),
                brain_kind=overlay.get("brain_kind") or facts.get("brain_kind"),
                software=overlay.get("software", facts.get("software")),
                presence="reviewed evidence; not configured"
                if entity.id in evidence_ids
                else facts.get("presence"),
                category=categories.get(entity.id),
                evidence=evidence,
            )
        )
    live = {n.id for n in nodes}
    links = [
        TopologyEdge(
            id=e.id,
            source=e.src_id,
            target=e.dst_id,
            protocol=e.attrs.get("protocol"),
            address=e.attrs.get("address"),
        )
        for e in edges
        if e.src_id in live and e.dst_id in live
    ]
    roots = sorted(live - {e.target for e in links}, key=str)
    _validate_tree(live, links, roots)
    return RobotTopology(robot_id=robot_id, nodes=nodes, edges=links, roots=roots)


def _validate_tree(live: set[uuid.UUID], links: list[TopologyEdge], roots: list[uuid.UUID]) -> None:
    incoming = {node: 0 for node in live}
    for link in links:
        incoming[link.target] += 1
    if any(count > 1 for count in incoming.values()):
        raise APIError(409, "topology_conflict", "Stored hardware topology has ambiguous parents")
    pending = list(roots)
    visited = 0
    while pending:
        node = pending.pop()
        visited += 1
        for link in links:
            if link.source == node:
                incoming[link.target] -= 1
                if incoming[link.target] == 0:
                    pending.append(link.target)
    if visited != len(live):
        raise APIError(409, "topology_conflict", "Stored hardware topology contains a cycle")
