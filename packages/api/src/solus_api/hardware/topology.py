"""Persist accepted physical connectivity separately from robot ownership.

Ownership edges and CONFIG records remain the compatibility authority. These additive graph facts
never grant transport permissions and reads never infer missing hardware or software.

SOLUSDEV-326: the topology is a DAG — a part may sit under two brains and a brain may be reached
two ways; only a cycle is refused. Brains come from the stored config's identity items (`mcu` and
`onboard` items name their kind, `host` items are the host-driven endpoint), `via` wires a brain
to the brain it is reached through, and a brain's measured clock lives on its node.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from solus_contracts.relations import EdgeEvidence, EvidenceKind
from sqlalchemy import ColumnElement, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.graph.edges import write_edge
from solus_api.graph.read_scope import IN_GRAPH, current_scope, flags_of
from solus_api.graph.resolver import REF_ALIASES
from solus_api.hardware.config import (
    BrainIdentity,
    BrainKind,
    EntityHardwareConfig,
    HardwareConfig,
    PortableTransportBinding,
    ProtocolBinding,
    ProvenanceRecord,
    part_ref,
    with_brain,
)
from solus_api.hardware.in_graph import stamp
from solus_api.hardware.runtime import brains_of, resolve_runtime_config
from solus_api.models import Domain, GraphEdge, GraphEntity, utcnow
from solus_api.services.physical_robots import ownership_edge

MARKER = "hardware_topology_v1"
HOST_MARKER = "hardware_host_topology_v1"
EVIDENCE_MARKER = "hardware_extraction_evidence_v1"
EVIDENCE_RELATION = "hardware_evidence_for"
RELATION = "hardware_connected_to"
MEMBERSHIP = "hardware_topology_member"
MAX_NODE_EVIDENCE = 32


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: str = Field(max_length=32)
    source: str | None = Field(default=None, max_length=512)

    def as_edge_evidence(self) -> EdgeEvidence:
        """Stored on the edge as `{kind: config, ref: by, detail: source}`."""
        return EdgeEvidence(kind=EvidenceKind.CONFIG, ref=self.by, detail=self.source)

    @classmethod
    def from_edge_evidence(cls, item: dict[str, Any]) -> Evidence:
        if "by" in item:  # pre-SOLUSDEV-320 shape; migration a32000000001 rewrites it
            return cls.model_validate(item)
        return cls(by=str(item["ref"]), source=item.get("detail"))


class BrainClock(BaseModel):
    """A brain's clock against the host (`brain.attrs.clock`), as measured. Recorded here only:
    applying the offset to ingest timestamps belongs to the Live Bench (telemetry-packet.md §3)."""

    model_config = ConfigDict(extra="forbid")
    offset_ms: float = Field(allow_inf_nan=False)
    jitter_ms: float = Field(ge=0, allow_inf_nan=False)
    measured_at: AwareDatetime
    method: str = Field(min_length=1, max_length=32)


class BrainFacts(BaseModel):
    """What a writer records on a brain node beside its config item (never config itself)."""

    model_config = ConfigDict(extra="forbid")
    clock: BrainClock | None = None
    software: str | None = Field(default=None, min_length=1, max_length=256)


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
    evidence: list[Evidence] = Field(default_factory=list, max_length=MAX_NODE_EVIDENCE)
    clock: BrainClock | None = None


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


def endpoint_id(project_id: uuid.UUID, device_ref: str) -> uuid.UUID:
    """The topology node of the brain bound to `device_ref` (stable across config versions and
    across the brain's kind: one formula for host-driven, MCU and onboard brains)."""
    return uuid.uuid5(project_id, f"{MARKER}:endpoint:{device_ref}")


def host_brain_id(project_id: uuid.UUID, machine_id: str) -> uuid.UUID:
    """The reviewed host brain of one machine, shared by every robot and endpoint it drives."""
    return uuid.uuid5(project_id, f"{HOST_MARKER}:host:{machine_id}")


def host_endpoints(attrs: Mapping[str, Any]) -> set[str]:
    """The endpoints a reviewed host edge serves: `endpoint_ids` (one `endpoint_id` before 326)."""
    ids = attrs.get("endpoint_ids")
    if isinstance(ids, list):
        return {str(item) for item in ids}
    one = attrs.get("endpoint_id")
    return {str(one)} if one else set()


def serving(attrs: Mapping[str, Any], endpoints: Iterable[str]) -> dict[str, Any]:
    """`attrs` of a host edge serving exactly `endpoints` (the pre-326 single key dropped)."""
    kept = {key: value for key, value in attrs.items() if key != "endpoint_id"}
    return {**kept, "endpoint_ids": sorted(endpoints)}


async def sync_topology(session: AsyncSession, project_id: uuid.UUID, robot_id: uuid.UUID) -> None:
    """Refresh derived edges in the caller's reviewed, project-locked transaction: one brain per
    bound identity item with its buses and parts, `via` wires between brains, the reviewed host
    edges of current endpoints, and the extra refs of a part behind several brains."""
    from solus_api.hardware.store import robot_root
    from solus_api.services.solus_graph import lock_project

    await lock_project(session, project_id)
    robot = await robot_root(session, project_id, robot_id)
    config = await resolve_runtime_config(session, project_id, robot_id)
    # A DAG: a part may sit under two brains; twice under ONE brain stays ambiguous. Keyed on
    # each brain's driver document, never a row's raw `brain`: on a one-brain config an implicit
    # row and a row naming that brain are the same brain.
    placed = [
        (index, row.part_entity_id)
        for index, brain in enumerate(brains_of(config))
        for row in brain.bus_map
        if row.part_entity_id
    ]
    if len(placed) != len(set(placed)):
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
    stored = await _stored(session, project_id, robot_id)
    kinds = {item.device_ref: item.kind for item in stored.identity} if stored else {}
    desired: set[uuid.UUID] = set()
    refs: dict[uuid.UUID, set[str]] = {}
    endpoints: set[str] = set()
    for brain in config.per_brain():
        if brain.identity is not None:
            kind = kinds.get(brain.identity.device_ref, "host")
            endpoint = await _sync_brain(session, project_id, robot_id, brain, kind, desired, refs)
            endpoints.add(str(endpoint))
    await _sync_via(session, project_id, robot_id, stored, desired)
    await _sync_ref_aliases(session, project_id, refs, existing)
    _sweep(existing, desired, endpoints)
    # SOLUSDEV-326: the robot's own brains and buses are seen by whoever sees the robot; shared
    # topology, like the host brain and bus, never carries the keys.
    own, shared = await derived_nodes(session, project_id, robot_id)
    await stamp(session, project_id, own, flags_of(robot.attrs))
    await stamp_shared(session, project_id, robot, shared)
    await session.flush()


def _reaching(project_id: uuid.UUID, robot_id: uuid.UUID, *, mine: bool) -> ColumnElement[bool]:
    """A derived node an edge of this robot's derivation reaches (`mine`), or another robot's."""
    owner = GraphEdge.attrs["robot_id"].astext
    ends = (
        select(GraphEdge.src_id, GraphEdge.dst_id)
        .where(
            GraphEdge.project_id == project_id,
            GraphEdge.deleted_at.is_(None),
            owner == str(robot_id) if mine else owner != str(robot_id),
            GraphEdge.attrs["managed_by"].astext.in_((MARKER, EVIDENCE_MARKER)),
        )
        .subquery()
    )
    return or_(GraphEntity.id.in_(select(ends.c.src_id)), GraphEntity.id.in_(select(ends.c.dst_id)))


async def derived_nodes(
    session: AsyncSession, project_id: uuid.UUID, robot_id: uuid.UUID
) -> tuple[list[GraphEntity], list[GraphEntity]]:
    """The topology nodes derived for this robot — its brains and buses (`sync_topology`) and its
    accepted evidence, reached through its own live edges — as (its own, shared): a node another
    robot's derivation also reaches (one device bound to two robots) is shared topology, like the
    reviewed host brain and bus, which are never among them."""
    rows = await session.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.deleted_at.is_(None),
            GraphEntity.attrs["managed_by"].astext.in_((MARKER, EVIDENCE_MARKER)),
            _reaching(project_id, robot_id, mine=True),
        )
        .execution_options(populate_existing=True)
    )
    nodes = list(rows)
    shared = set(
        await session.scalars(
            select(GraphEntity.id).where(
                GraphEntity.id.in_([node.id for node in nodes]),
                _reaching(project_id, robot_id, mine=False),
            )
        )
    )
    return [n for n in nodes if n.id not in shared], [n for n in nodes if n.id in shared]


async def stamp_shared(
    session: AsyncSession, project_id: uuid.UUID, robot: GraphEntity, shared: Iterable[GraphEntity]
) -> int:
    """Shared topology carries no keys while a robot in the graph reaches it, like the host brain
    and bus; reached only by robots out of the graph it keeps `robot`'s, failing closed."""
    nodes = {node.id: node for node in shared}
    if not nodes:
        return 0
    reach = await session.execute(
        select(GraphEdge.src_id, GraphEdge.dst_id, GraphEdge.attrs["robot_id"].astext).where(
            GraphEdge.project_id == project_id,
            GraphEdge.deleted_at.is_(None),
            GraphEdge.attrs["managed_by"].astext.in_((MARKER, EVIDENCE_MARKER)),
            or_(GraphEdge.src_id.in_(nodes), GraphEdge.dst_id.in_(nodes)),
        )
    )
    sharers = [(end, owner) for src, dst, owner in reach for end in (src, dst) if end in nodes]
    public = set(
        await session.scalars(
            select(GraphEntity.id).where(
                GraphEntity.project_id == project_id,
                GraphEntity.id.in_({uuid.UUID(owner) for _, owner in sharers if owner}),
                GraphEntity.deleted_at.is_(None),
                not_(GraphEntity.attrs.contains({IN_GRAPH: False})),
            )
        )
    )
    seen = {end for end, owner in sharers if owner and uuid.UUID(owner) in public}
    changed = 0
    for node_id, node in nodes.items():
        flags = {} if node_id in seen else flags_of(robot.attrs)
        changed += len(await stamp(session, project_id, [node], flags))
    return changed


async def _stored(
    session: AsyncSession, project_id: uuid.UUID, robot_id: uuid.UUID
) -> EntityHardwareConfig | None:
    """The robot's stored v2 config (its identity items); None for none or a legacy v1 one."""
    from solus_api.hardware.store import _find_entry, config_of

    entry = await _find_entry(session, project_id, robot_id)
    stored = config_of(entry) if entry is not None else None
    return stored if isinstance(stored, EntityHardwareConfig) else None


async def _sync_brain(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot_id: uuid.UUID,
    brain: HardwareConfig,
    kind: BrainKind,
    desired: set[uuid.UUID],
    refs: dict[uuid.UUID, set[str]],
) -> uuid.UUID:
    """One bound brain's node, its buses and the parts on them; returns the node. A `host` item
    is the host-driven endpoint (no kind of its own; a reviewed host attach may declare one)."""
    identity = brain.identity
    assert identity is not None  # the caller derives bound brains only
    endpoint = endpoint_id(project_id, identity.device_ref)
    facts = {"channel": identity.kind.value, "brain_kind": None if kind == "host" else kind}
    await _node(
        session,
        project_id,
        endpoint,
        "hardware_brain",
        identity.device_ref,
        facts,
        owner_id=robot_id,
    )
    # A membership edge selects the robot projection; it is not physical wiring.
    await _edge(session, project_id, robot_id, robot_id, endpoint, None, None, [], desired)
    for index, item in enumerate(brain.bus_map):
        bus_id = uuid.uuid5(endpoint, f"bus:{item.protocol}")
        await _node(session, project_id, bus_id, "hardware_bus", item.protocol, {})
        record = brain.provenance_of(f"bus_map.{index}.protocol")
        evidence = [Evidence(by=record.by.value, source=record.source)]
        await _edge(
            session, project_id, robot_id, endpoint, bus_id, item.protocol, None, evidence, desired
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
        refs.setdefault(part.id, set()).add(part_ref(identity.device_ref, item.address))
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
    return endpoint


async def _sync_via(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot_id: uuid.UUID,
    stored: EntityHardwareConfig | None,
    desired: set[uuid.UUID],
) -> None:
    """A brain reached through another: one `hardware_connected_to` edge brain → brain."""
    if stored is None:
        return
    for index, item in enumerate(stored.identity):
        if item.via is None or item.device_ref is None:
            continue
        record = stored.provenance_of(f"identity.{index}.via")
        await _edge(
            session,
            project_id,
            robot_id,
            endpoint_id(project_id, item.via),
            endpoint_id(project_id, item.device_ref),
            None,
            None,
            [Evidence(by=record.by.value, source=record.source)],
            desired,
        )


async def _sync_ref_aliases(
    session: AsyncSession,
    project_id: uuid.UUID,
    refs: Mapping[uuid.UUID, set[str]],
    existing: Iterable[GraphEdge],
) -> None:
    """A part behind several brains answers to each brain's `<device>/<address>` (its
    `attrs.ref_aliases`, read by the resolver beside `external_ref`); a part on one brain, or
    one this robot no longer wires, keeps none and resolves by `external_ref` alone, as before.
    ponytail: a part bound through a brain that later leaves keeps that `external_ref`; re-binding
    it on its remaining brain resolves it again."""
    wired = {
        edge.dst_id
        for edge in existing
        if edge.relation_type == RELATION and edge.attrs.get("managed_by") == MARKER
    }
    ids = set(refs) | wired
    if not ids:
        return
    for part in await session.scalars(
        select(GraphEntity).where(GraphEntity.project_id == project_id, GraphEntity.id.in_(ids))
    ):
        own = refs.get(part.id, set())
        aliases = sorted(own) if len(own) > 1 else []
        if aliases != part.attrs.get(REF_ALIASES, []):
            kept = {key: value for key, value in part.attrs.items() if key != REF_ALIASES}
            part.attrs = {**kept, REF_ALIASES: aliases} if aliases else kept


def _sweep(existing: Iterable[GraphEdge], desired: set[uuid.UUID], endpoints: set[str]) -> None:
    """Retire what this sync did not derive. A reviewed host edge stays while one endpoint it
    serves is still a brain of the robot, pruned to the endpoints that are."""
    for edge in existing:
        served = (
            host_endpoints(edge.attrs) if edge.attrs.get("managed_by") == HOST_MARKER else set()
        )
        if served & endpoints:
            if edge.deleted_at is None and not served <= endpoints:
                edge.attrs = serving(edge.attrs, served & endpoints)
            continue
        if edge.id not in desired:
            edge.deleted_at = utcnow()


async def _node(
    session: AsyncSession,
    project_id: uuid.UUID,
    node_id: uuid.UUID,
    kind: str,
    name: str,
    facts: Mapping[str, str | None],
    *,
    owner_id: uuid.UUID | None = None,
) -> None:
    """Upsert a derived node; `facts` merge over its attrs, so keys other writers own on it (a
    brain's measured `clock`, its `software`) survive every resync."""
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
    evidence: list[Evidence],
    desired: set[uuid.UUID],
) -> None:
    edge_id = uuid.uuid5(robot_id, f"{MARKER}:{src}:{dst}:{protocol}:{address}")
    desired.add(edge_id)
    await write_edge(
        session,
        project_id=project_id,
        src_id=src,
        dst_id=dst,
        relation_type=MEMBERSHIP if src == robot_id else RELATION,
        origin="manual",
        confidence=1.0,
        evidence=[e.as_edge_evidence() for e in evidence],
        created_by=None,
        attrs={
            "managed_by": MARKER,
            "robot_id": str(robot_id),
            "protocol": protocol,
            "address": address,
        },
        edge_id=edge_id,
        managed_by=MARKER,
    )


async def upsert_onboard_brain(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot_id: uuid.UUID,
    binding: PortableTransportBinding,
    *,
    record: ProvenanceRecord,
    protocol: ProtocolBinding | None = None,
    via: str | None = None,
    facts: BrainFacts | None = None,
    created_by: uuid.UUID | None,
) -> uuid.UUID:
    """The writer for a robot computer (P6's survey): its `onboard` identity item enters, or
    replaces the same device's item in, the robot's stored config — whose write runs
    `sync_topology`, which derives the brain node — then `facts` land on that node, where every
    resync keeps them. An unchanged item writes no config version. Returns the node's id.
    `via` names another brain of the config; a config that would not validate is refused with
    its reason (`brain_refusal`) before anything is written."""
    from solus_api.hardware.store import (
        _same,
        brain_refusal,
        put_entity_config,
        read_entity_config,
        robot_root,
    )

    robot = await robot_root(session, project_id, robot_id)
    entry, current = await read_entity_config(session, project_id, robot_id)
    try:
        item = BrainIdentity(kind="onboard", binding=binding, via=via, protocol=protocol)
        config = _with_item(current or EntityHardwareConfig(entity_id=robot_id), item, record)
    except ValueError as error:
        raise brain_refusal(error) from None
    if current is None or not _same(current, config):
        await put_entity_config(
            session,
            project_id,
            robot,
            config,
            expected_version=entry.config_version if entry else 0,
            created_by=created_by,
        )
    node = await session.get(GraphEntity, endpoint_id(project_id, binding.device_ref))
    if node is None or node.deleted_at is not None or node.project_id != project_id:
        raise APIError(409, "topology_conflict", "The onboard brain was not derived")
    if facts is not None:
        node.attrs = {**node.attrs, **facts.model_dump(mode="json", exclude_none=True)}
    await session.flush()
    return node.id


def _with_item(
    config: EntityHardwareConfig, item: BrainIdentity, record: ProvenanceRecord
) -> EntityHardwareConfig:
    """`config` with `item` in place of the same device's brain (its records too), else added
    as another brain (rows the config left implicit then name their brain). Raises what
    `with_brain` and validation raise."""
    ref = str(item.device_ref)
    if ref not in [brain.device_ref for brain in config.identity]:
        # A new brain joins bare, then takes the whole item below: its `via` names a brain of
        # `config`, which a one-item config cannot hold.
        bare = EntityHardwareConfig(
            entity_id=config.entity_id,
            identity=[item.model_copy(update={"via": None})],
            provenance={"identity": record},
        )
        config = with_brain(config, bare, ref)
    index = [brain.device_ref for brain in config.identity].index(ref)
    head = f"identity.{index}"
    document = config.model_dump(mode="json")
    document["identity"][index] = item.model_dump(mode="json")
    document["provenance"] = {
        path: value
        for path, value in document["provenance"].items()
        if path != head and not path.startswith(f"{head}.")
    }
    document["provenance"][head] = record.model_dump(mode="json")
    return EntityHardwareConfig.model_validate(document)


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
    # The parts the robot contains join the node set; the edge keeps a retired category's
    # label (a32600000001), which is only ever read, never written.
    owned = await session.execute(
        select(GraphEdge.dst_id, GraphEdge.attrs["category"].astext).where(
            ownership_edge(project_id), GraphEdge.src_id == robot_id
        )
    )
    labels: dict[uuid.UUID, str | None] = {part_id: label for part_id, label in owned}
    ids.update(labels)
    entities = (
        list(
            await session.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.id.in_(ids),
                    GraphEntity.deleted_at.is_(None),
                    GraphEntity.kind != "robot_category",  # a retired legacy kind
                )
                .order_by(GraphEntity.id)
            )
        )
        if ids
        else []
    )
    # SOLUSDEV-326: a node the reader may not see (another member's hidden part this robot's bus
    # map still names) is left out, and its edges with it.
    scope = current_scope(project_id)
    entities = [entity for entity in entities if not scope.hides(entity.attrs)]
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
    incoming: dict[uuid.UUID, list[GraphEdge]] = {}
    for edge in edges:
        incoming.setdefault(edge.dst_id, []).append(edge)
    nodes = [
        _topology_node(
            entity,
            incoming.get(entity.id, []),
            [a for a in annotations if a.dst_id == entity.id],
            labels.get(entity.id),
            entity.id in evidence_ids,
        )
        for entity in entities
    ]
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
    _reject_cycles(live, links, roots)
    return RobotTopology(robot_id=robot_id, nodes=nodes, edges=links, roots=roots)


def _topology_node(
    entity: GraphEntity,
    incoming: list[GraphEdge],
    annotations: list[GraphEdge],
    label: str | None,
    is_evidence: bool,
) -> TopologyNode:
    """One node, its reviewed host facts and evidence merged across ALL its parents (a DAG).
    A config item's kind outranks a host attach's declaration."""
    facts = entity.attrs if entity.attrs.get("managed_by") in (MARKER, HOST_MARKER) else {}
    overlay = _host_overlay(incoming)
    role: Literal["brain", "bus", "part"] = (
        "brain"
        if entity.kind == "hardware_brain"
        else "bus"
        if entity.kind == "hardware_bus"
        else "part"
    )
    return TopologyNode(
        id=entity.id,
        name=entity.name,
        role=role,
        channel=facts.get("channel"),
        brain_kind=facts.get("brain_kind") or overlay.get("brain_kind"),
        software=overlay.get("software", facts.get("software")),
        presence="reviewed evidence; not configured" if is_evidence else facts.get("presence"),
        category=label or _legacy_category(entity),
        evidence=_merged_evidence(incoming, annotations),
        clock=_clock(facts.get("clock")),
    )


def _host_overlay(incoming: Iterable[GraphEdge]) -> dict[str, Any]:
    """Reviewed host facts on a node's incoming host edges; per key, the first stated value in
    edge-id order wins."""
    overlay: dict[str, Any] = {}
    for edge in incoming:
        if edge.attrs.get("managed_by") == HOST_MARKER:
            for key, value in edge.attrs.items():
                if value is not None:
                    overlay.setdefault(key, value)
    return overlay


def _merged_evidence(
    incoming: Iterable[GraphEdge], annotations: Iterable[GraphEdge]
) -> list[Evidence]:
    """Every parent edge's evidence, then the node's reviewed annotations: deduped, bounded."""
    found = [
        Evidence.from_edge_evidence(item)
        for edge in incoming
        for item in edge.attrs.get("evidence", [])
    ]
    for annotation in annotations:
        row = annotation.attrs.get("row", {})
        source = row.get("source_ref") if isinstance(row, dict) else None
        if source is None or (isinstance(source, str) and len(source) <= 512):
            found.append(Evidence(by="user", source=source))
    return list({(item.by, item.source): item for item in found}.values())[:MAX_NODE_EVIDENCE]


def _clock(value: object) -> BrainClock | None:
    """A brain's recorded clock; a malformed stored one reads as unknown, never a 500."""
    if value is None:
        return None
    try:
        return BrainClock.model_validate(value)
    except ValidationError:
        return None


def _legacy_category(entity: GraphEntity) -> str | None:
    """A manual part's category from before a32600000001; provider attributes never count."""
    value = entity.attrs.get("category")
    manual = entity.origin == "manual" and entity.source_id is None
    return value if manual and isinstance(value, str) else None


def _reject_cycles(live: set[uuid.UUID], links: list[TopologyEdge], roots: list[uuid.UUID]) -> None:
    """A DAG (SOLUSDEV-326): a node may have several parents; only a cycle is refused."""
    incoming = {node: 0 for node in live}
    for link in links:
        incoming[link.target] += 1
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


def clock_source(
    topology: RobotTopology,
    part_id: uuid.UUID,
    *,
    device_stamped: bool,
    endpoint: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """The brain whose clock stamps `part_id`'s data (telemetry-packet.md §3), from topology.

    The endpoint is the brain whose bus carries the part; a part behind several brains needs
    `endpoint`, the one its data came through. A device-timestamped driver stamps on that
    endpoint; a host-stamped one on the host brain above it. Ambiguous or unrecorded: None,
    never a guess."""
    nodes = {node.id: node for node in topology.nodes}
    parents: dict[uuid.UUID, set[uuid.UUID]] = {}
    for edge in topology.edges:
        parents.setdefault(edge.target, set()).add(edge.source)

    def is_brain(node: uuid.UUID) -> bool:
        return nodes[node].role == "brain"

    brains = {node for node in _above(parents, part_id, is_brain) if is_brain(node)}
    candidates = brains if endpoint is None else brains & {endpoint}
    if len(candidates) != 1:
        return None
    (brain,) = candidates
    if device_stamped:
        return brain
    hosts = {n for n in _above(parents, brain, lambda _: False) if nodes[n].brain_kind == "host"}
    return hosts.pop() if len(hosts) == 1 else None


def _above(
    parents: Mapping[uuid.UUID, set[uuid.UUID]],
    start: uuid.UUID,
    stop: Callable[[uuid.UUID], bool],
) -> set[uuid.UUID]:
    """Every node above `start`, never climbing past a node `stop` accepts."""
    seen: set[uuid.UUID] = set()
    pending = list(parents.get(start, ()))
    while pending:
        node = pending.pop()
        if node not in seen:
            seen.add(node)
            if not stop(node):
                pending.extend(parents.get(node, ()))
    return seen
