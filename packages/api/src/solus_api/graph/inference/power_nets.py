"""`wires` and `powers` from an EDA netlist's `connected_to` edges (relations.md §1)."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from solus_contracts.relations import EdgeEvidence, EvidenceKind, RelationType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.graph import kinds
from solus_api.graph.inference.common import EdgeWriter, InferenceReport, behaviour_class_of
from solus_api.models import GraphEdge, GraphEntity

MODULE: Final = "power_nets"
POWER_NET: Final = re.compile(r"^(VCC|VDD|VBAT|VIN|V\+|\+?\d+(\.\d+)?V\d*)$")
GROUND_NET: Final = re.compile(r"^(A|D|P)?GND\d*$|^VSS|ground", re.IGNORECASE)
SUPPLY_HINT: Final = re.compile(r"regulator|ldo|batt|vreg|buck|boost|psu|supply", re.IGNORECASE)
SUPPLY_CLASSES: Final = frozenset({"power", "switcher"})
#: ponytail: pairwise `wires` on a net is O(members²); a net wider than this is a rail or bus
#: (every VCC/GND pin of a big board) and gets `powers` only — the net node already joins them.
MAX_WIRED_NET_MEMBERS: Final = 32
#: `powers` fans out supply × sink per rail; past this many pairs on one net the "supplies" are
#: hint false positives on a bus — the rail is skipped and logged, never flooded into the graph.
MAX_POWERED_NET_PAIRS: Final = 512

logger = logging.getLogger(__name__)

Pair = tuple[UUID, UUID]


def is_supply(component: GraphEntity) -> bool:
    if behaviour_class_of(component) in SUPPLY_CLASSES:
        return True
    hints = (component.attrs.get("value"), component.attrs.get("libsource"))
    return any(isinstance(h, str) and SUPPLY_HINT.search(h) for h in hints)


def is_power_rail_name(name: str) -> bool:
    return bool(POWER_NET.match(name)) and not GROUND_NET.search(name)


@dataclass
class _Nets:
    """net entity → {component → pins}, grouped by ENTITY so two boards' "GND" never meet."""

    components: dict[UUID, GraphEntity] = field(default_factory=dict)
    names: dict[UUID, str] = field(default_factory=dict)
    members: dict[UUID, dict[UUID, list[str]]] = field(default_factory=lambda: defaultdict(dict))

    def pins_on(self, component_id: UUID, net_names: list[str]) -> list[str]:
        pins: set[str] = set()
        for net_id, by_component in self.members.items():
            if self.names[net_id] in net_names and component_id in by_component:
                pins.update(by_component[component_id])
        return sorted(pins)


async def _load(session: AsyncSession, project_id: UUID) -> _Nets:
    rows = (
        await session.execute(
            select(GraphEdge, GraphEntity)
            .join(GraphEntity, GraphEntity.id == GraphEdge.src_id)
            .where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type == RelationType.CONNECTED_TO.value,
                GraphEdge.deleted_at.is_(None),
                GraphEntity.kind == kinds.COMPONENT,
                GraphEntity.deleted_at.is_(None),
            )
        )
    ).all()
    nets = _Nets()
    net_ids = {edge.dst_id for edge, _ in rows}
    if net_ids:
        nets.names = {
            net.id: net.name
            for net in await session.scalars(
                select(GraphEntity).where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.id.in_(net_ids),
                    GraphEntity.kind == kinds.NET,
                    GraphEntity.deleted_at.is_(None),
                )
            )
        }
    for edge, component in rows:
        if edge.dst_id in nets.names:
            nets.components[component.id] = component
            pins = [str(p) for p in edge.attrs.get("pins", [])]
            nets.members[edge.dst_id].setdefault(component.id, []).extend(pins)
    return nets


def _pairs(nets: _Nets) -> tuple[dict[Pair, list[str]], dict[Pair, list[str]]]:
    """`(wires, powers)`: unordered component pairs (src < dst by id) → shared net names."""
    wires: dict[Pair, list[str]] = defaultdict(list)
    powers: dict[Pair, list[str]] = defaultdict(list)
    for net_id, by_component in nets.members.items():
        name = nets.names[net_id]
        ids = sorted(by_component)
        if len(ids) <= MAX_WIRED_NET_MEMBERS:
            for i, a in enumerate(ids):
                for b in ids[i + 1 :]:
                    wires[(a, b)].append(name)
        if not is_power_rail_name(name):
            continue
        supplies = {cid for cid in ids if is_supply(nets.components[cid])}
        sinks = [cid for cid in ids if cid not in supplies]
        if len(supplies) * len(sinks) > MAX_POWERED_NET_PAIRS:
            logger.warning(
                "power_nets: net %r has %d supplies x %d sinks; powers skipped",
                name,
                len(supplies),
                len(sinks),
            )
            continue
        for supply in sorted(supplies):
            for sink in sinks:
                powers[(supply, sink)].append(name)
    return wires, powers


async def infer(session: AsyncSession, project_id: UUID) -> InferenceReport:
    nets = await _load(session, project_id)
    wires, powers = _pairs(nets)
    writer = await EdgeWriter.open(
        session, project_id, MODULE, (RelationType.WIRES.value, RelationType.POWERS.value)
    )
    for (a, b), shared in wires.items():
        shared = sorted(shared)
        await writer.write(
            nets.components[a],
            nets.components[b],
            RelationType.WIRES.value,
            confidence=1.0,
            evidence=[EdgeEvidence(kind=EvidenceKind.NETLIST, ref=net) for net in shared],
            attrs={
                "nets": shared,
                "pins": {str(a): nets.pins_on(a, shared), str(b): nets.pins_on(b, shared)},
            },
        )
    for (supply, sink), shared in powers.items():
        shared = sorted(shared)
        await writer.write(
            nets.components[supply],
            nets.components[sink],
            RelationType.POWERS.value,
            confidence=0.9,
            evidence=[EdgeEvidence(kind=EvidenceKind.NETLIST, ref=net) for net in shared],
            attrs={"nets": shared},
        )
    return writer.report
