"""`Neighborhood` (+ `HardwareConfig`) → `Diagram`. Pure; no I/O, no vendor names.

Where a pin can come from — and nowhere else:

* an edge's `attrs.pins` (the EDA connectors record `{"net", "pins"}` on a
  component → net `connected_to` edge, see connectors/eda.py; a `wires` edge records
  `{endpoint id: [pins]}` for each side, see graph/inference/power_nets.py);
* an entity's `attrs.pins` (a connector that recorded the part's pins);
* a `PartConfig.firmware` key that names a pin (`*pin*` → its value).

Anything else lands on the `UNKNOWN_PIN` stub and is said so in a note. A candidate edge (an
inference below the confidence threshold) is a proposal, never drawn; the robot config's bus map
is the fallback for a part no graph edge drew (SOLUSDEV-321 P2-T7).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any, Final
from uuid import UUID

from solus_api.agent.diagram.model import (
    UNKNOWN_PIN,
    Diagram,
    DiagramNode,
    DiagramPin,
    DiagramWire,
)
from solus_api.graph import kinds as graph_kinds
from solus_api.graph.edges import is_candidate
from solus_api.graph.neighborhood import Neighborhood
from solus_api.hardware.config import HardwareConfig

#: Relation types that join two things in the robot: wiring, power, a bus driving a device, code
#: commanding a part. Containment/mating are not wiring.
WIRING_RELATIONS: Final = frozenset(
    {"connected_to", "wires", "drives", "reads_from", "powers", "commands", "bus", "wired_to"}
)
#: Links with no pin at either end: a code site commands a part, it is not wired to one.
PINLESS_RELATIONS: Final = frozenset({"commands"})
#: Nodes with no pin concept: a wire ends ON them, not on a pin of theirs.
LINE_KINDS: Final = frozenset({"net", "bus", graph_kinds.HARDWARE_BUS})
#: Display bounds — the SVG cap (svg.MAX_SVG_BYTES) follows from these.
MAX_NODES: Final = 60
MAX_WIRES: Final = 200
MAX_LABEL: Final = 60
UNKNOWN_NOTE: Final = (
    "Dashed wires end on an unknown pin: the graph does not record which pin they use. "
    "Never invent a pin the graph does not know — check the schematic or the firmware."
)


def _label(text: object) -> str:
    return " ".join(str(text).split())[:MAX_LABEL] or "unnamed"


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_label(v) for v in value if isinstance(v, str | int) and str(v).strip()]


def _firmware_pins(config: HardwareConfig | None, entity_id: UUID) -> list[DiagramPin]:
    part = config.parts.get(str(entity_id)) if config is not None else None
    if part is None:
        return []
    return [
        DiagramPin(name=_label(value), known=True, net=key)
        for key, value in sorted(part.firmware.items())
        if "pin" in key.lower() and value is not None and str(value).strip()
    ]


def _bus_wires(
    config: HardwareConfig, present: Mapping[UUID, Any], drawn: Collection[str]
) -> tuple[list[DiagramNode], list[DiagramWire]]:
    """One `bus` node per protocol; a dashed wire per bus_map entry whose part is in view and
    was drawn by no graph edge — the config is the fallback, never a second drawing.
    The address is a bus address, not a pin — so the part-side pin stays unknown."""
    nodes: dict[str, DiagramNode] = {}
    wires: list[DiagramWire] = []
    root = config.robot_entity_id
    for entry in sorted(config.bus_map, key=lambda e: (e.protocol, e.address)):
        part = entry.part_entity_id
        if part is None or part not in present or str(part) in drawn:
            continue
        bus_id = f"bus:{entry.protocol}"
        if bus_id not in nodes:
            nodes[bus_id] = DiagramNode(
                id=bus_id, label=f"{_label(entry.protocol)} bus", kind="bus"
            )
            if root in present:
                wires.append(
                    DiagramWire(str(root), UNKNOWN_PIN, bus_id, "", _label(entry.protocol), False)
                )
        wires.append(
            DiagramWire(
                str(entry.part_entity_id), UNKNOWN_PIN, bus_id, "", f"addr {entry.address}", False
            )
        )
    return list(nodes.values()), wires


def _end_pin(pins: Mapping[str, Any], node: UUID, line: bool) -> str:
    """One end of a `wires` edge: the pins it records for that endpoint, joined — the netlist
    unions an endpoint's pins over the shared nets and never pairs them, so neither do we."""
    if line:
        return ""
    names = _str_list(pins.get(str(node)))
    return _label(", ".join(names)) if names else UNKNOWN_PIN


def _edge_wires(edge: Any, kinds: Mapping[UUID, str]) -> list[DiagramWire]:
    attrs = edge.attrs or {}
    label = _label(
        attrs.get("net") or ", ".join(_str_list(attrs.get("nets"))) or edge.relation_type
    )
    src, dst = str(edge.src_id), str(edge.dst_id)
    if edge.relation_type in PINLESS_RELATIONS:
        return [DiagramWire(src, "", dst, "", label, True)]
    src_line, dst_line = kinds[edge.src_id] in LINE_KINDS, kinds[edge.dst_id] in LINE_KINDS
    if isinstance(attrs.get("pins"), dict):
        from_pin = _end_pin(attrs["pins"], edge.src_id, src_line)
        to_pin = _end_pin(attrs["pins"], edge.dst_id, dst_line)
        return [
            DiagramWire(src, from_pin, dst, to_pin, label, UNKNOWN_PIN not in (from_pin, to_pin))
        ]
    to_pin = "" if dst_line else UNKNOWN_PIN
    pins = _str_list(attrs.get("pins")) if not src_line else []
    if not pins:
        from_pin = "" if src_line else UNKNOWN_PIN
        known = from_pin != UNKNOWN_PIN and to_pin != UNKNOWN_PIN
        return [DiagramWire(src, from_pin, dst, to_pin, label, known)]
    return [DiagramWire(src, pin, dst, to_pin, label, to_pin != UNKNOWN_PIN) for pin in pins]


def _pins_of(
    node_id: str, entity: Any, wires: Iterable[DiagramWire], extra: list[DiagramPin]
) -> tuple[DiagramPin, ...]:
    recorded = {p: None for p in _str_list((getattr(entity, "attrs", None) or {}).get("pins"))}
    seen: dict[tuple[str, str | None], bool] = {(p, None): True for p in recorded}
    for p in extra:
        seen[(p.name, p.net)] = True
    for w in wires:
        if w.from_node == node_id and w.from_pin:
            seen.setdefault((w.from_pin, w.label), w.from_pin != UNKNOWN_PIN)
        if w.to_node == node_id and w.to_pin:
            seen.setdefault((w.to_pin, w.label), w.to_pin != UNKNOWN_PIN)
    ordered = sorted(
        seen.items(), key=lambda kv: (kv[0][0] == UNKNOWN_PIN, kv[0][0], kv[0][1] or "")
    )
    return tuple(DiagramPin(name=name, known=known, net=net) for (name, net), known in ordered)


def build_wiring_diagram(
    neighborhood: Neighborhood,
    hardware_config: HardwareConfig | None,
    focus_ids: Sequence[UUID],
) -> Diagram:
    """Nodes: focus entities plus every entity touched by a wiring edge or a bus line.
    Deterministic: nodes sort by (label, id), wires by their tuple."""
    entities = {e.id: e for e in neighborhood.entities}
    kinds = {eid: str(e.kind) for eid, e in entities.items()}
    wires: list[DiagramWire] = []
    for edge in neighborhood.edges:
        if (
            edge.relation_type in WIRING_RELATIONS
            and not is_candidate(edge)
            and edge.src_id in kinds
            and edge.dst_id in kinds
        ):
            wires.extend(_edge_wires(edge, kinds))
    bus_nodes: list[DiagramNode] = []
    if hardware_config is not None:
        drawn = {w.from_node for w in wires} | {w.to_node for w in wires}
        bus_nodes, bus_wires = _bus_wires(hardware_config, entities, drawn)
        wires.extend(bus_wires)

    notes: list[str] = []
    wires.sort(key=lambda w: (w.from_node, w.to_node, w.from_pin, w.to_pin, w.label))
    if len(wires) > MAX_WIRES:
        wires, notes = wires[:MAX_WIRES], [f"Diagram truncated to {MAX_WIRES} wires."]
    touched = {w.from_node for w in wires} | {w.to_node for w in wires}
    wanted = [e for eid, e in entities.items() if str(eid) in touched or eid in focus_ids]
    wanted.sort(key=lambda e: (_label(e.name).lower(), str(e.id)))
    if len(wanted) > MAX_NODES:
        wanted = wanted[:MAX_NODES]
        notes.append(f"Diagram truncated to {MAX_NODES} nodes.")
        kept = {str(e.id) for e in wanted} | {b.id for b in bus_nodes}
        wires = [w for w in wires if w.from_node in kept and w.to_node in kept]
    if neighborhood.truncated and not notes:
        notes.append("The graph neighbourhood was truncated; some connections may be missing.")

    nodes = [
        DiagramNode(
            id=str(e.id),
            label=_label(e.name),
            kind=kinds[e.id],
            pins=_pins_of(str(e.id), e, wires, _firmware_pins(hardware_config, e.id)),
        )
        for e in wanted
    ]
    nodes.extend(b for b in bus_nodes if b.id in touched)
    if any(not w.known for w in wires):
        notes.append(UNKNOWN_NOTE)
    return Diagram(nodes=tuple(nodes), wires=tuple(wires), notes=tuple(notes))
