"""SOLUSDEV-321 P2-T7 — `make_diagram` draws the dependency relations a robot's graph records:
`wires` (its ends labelled with the pins the netlist names on each side), `powers`, `drives`
and `commands` (a code site has no pins, so that link claims no unknown pin). A candidate — an
inferred edge below CANDIDATE_THRESHOLD — is a proposal, not a fact, and never draws. The robot
config's bus map is the fallback: a part's bus line is drawn only when no graph edge drew it.
"""

from __future__ import annotations

import uuid

from solus_api.agent.diagram.build import WIRING_RELATIONS, build_wiring_diagram
from solus_api.agent.diagram.model import UNKNOWN_PIN, Diagram
from solus_api.graph import kinds
from solus_api.graph.neighborhood import Neighborhood
from solus_api.hardware.config import (
    BusMapEntry,
    FieldProvenance,
    HardwareConfig,
    ProvenanceRecord,
)
from solus_api.models import GraphEdge, GraphEntity
from solus_contracts.relations import CANDIDATE_THRESHOLD
from test_make_diagram import _diagram_edge, _diagram_entity


def _arm() -> tuple[dict[str, GraphEntity], HardwareConfig]:
    """A controller wired to a servo driver (the netlist names both sides' pins), a supply
    powering it, a bus driving servo 1, code commanding servo 1; servo 2 is only in the bus map."""
    pid = uuid.uuid4()
    entities = {
        "mcu": _diagram_entity(pid, "Controller", "component"),
        "driver": _diagram_entity(pid, "Servo driver", "component"),
        "supply": _diagram_entity(pid, "Buck 5V", "component"),
        "bus": _diagram_entity(pid, "fake bus", kinds.HARDWARE_BUS),
        "servo1": _diagram_entity(pid, "servo 1", kinds.PART),
        "servo2": _diagram_entity(pid, "servo 2", kinds.PART),
        "code": _diagram_entity(pid, "fw/fake_arm.ino", kinds.CODE_FILE),
        "robot": _diagram_entity(pid, "Fake arm", kinds.PHYSICAL_ROBOT),
    }
    config = HardwareConfig(
        robot_entity_id=entities["robot"].id,
        bus_map=[
            BusMapEntry(protocol="lb06", address=str(n), part_entity_id=entities[f"servo{n}"].id)
            for n in (1, 2)
        ],
        provenance={"bus_map": ProvenanceRecord(by=FieldProvenance.USER)},
    )
    return entities, config


def _edges(e: dict[str, GraphEntity]) -> dict[str, GraphEdge]:
    mcu, driver = e["mcu"], e["driver"]
    return {
        "wires": _diagram_edge(
            mcu,
            driver,
            "wires",
            nets=["SCL", "SDA"],
            pins={str(mcu.id): ["PB6", "PB7"], str(driver.id): ["4", "5"]},
        ),
        "powers": _diagram_edge(e["supply"], driver, "powers", nets=["+5V"]),
        "drives": _diagram_edge(e["bus"], e["servo1"], "drives"),
        "commands": _diagram_edge(e["code"], e["servo1"], "commands"),
        "contains1": _diagram_edge(e["robot"], e["servo1"], "contains"),
        "contains2": _diagram_edge(e["robot"], e["servo2"], "contains"),
    }


def _diagram(e: dict[str, GraphEntity], edges: list[GraphEdge], config: HardwareConfig) -> Diagram:
    hood = Neighborhood(entities=list(e.values()), edges=edges, truncated=False)
    return build_wiring_diagram(hood, config, focus_ids=[e["robot"].id])


def _between(diagram: Diagram, a: str, b: str) -> list[tuple[str, str, str, bool]]:
    return [
        (w.from_pin, w.to_pin, w.label, w.known)
        for w in diagram.wires
        if (w.from_node, w.to_node) == (a, b)
    ]


def _as_inferred(edge: GraphEdge, confidence: float) -> GraphEdge:
    edge.origin, edge.confidence = "inferred", confidence
    return edge


def test_draws_wires_powers_drives_commands_then_config() -> None:
    e, config = _arm()
    assert {"wires", "powers", "drives", "commands"} <= WIRING_RELATIONS
    ids = {name: str(entity.id) for name, entity in e.items()}

    diagram = _diagram(e, list(_edges(e).values()), config)

    # `wires`: each end carries that side's pins from attrs.pins; the label is the shared nets.
    assert _between(diagram, ids["mcu"], ids["driver"]) == [("PB6, PB7", "4, 5", "SCL, SDA", True)]
    mcu = next(n for n in diagram.nodes if n.id == ids["mcu"])
    assert [(p.name, p.known) for p in mcu.pins] == [("PB6, PB7", True)]
    # `powers`: the rail is the label; the netlist names no pin, so both ends are stubs.
    assert _between(diagram, ids["supply"], ids["driver"]) == [
        (UNKNOWN_PIN, UNKNOWN_PIN, "+5V", False)
    ]
    # `drives`: a bus is a line (no pin of its own); the servo's pin on it is not recorded.
    assert _between(diagram, ids["bus"], ids["servo1"]) == [("", UNKNOWN_PIN, "drives", False)]
    # `commands`: code has no pins — a link, never an unknown-pin claim.
    assert _between(diagram, ids["code"], ids["servo1"]) == [("", "", "commands", True)]
    assert not any(u.startswith("fw/fake_arm.ino") for u in diagram.unknown_pins)
    assert not any("commands" in u for u in diagram.unknown_pins)

    # The config's bus map draws only the part no graph edge drew.
    bus_line = next(n for n in diagram.nodes if n.kind == "bus")
    assert bus_line.label == "lb06 bus"
    assert [w.label for w in diagram.wires if w.from_node == ids["servo2"]] == ["addr 2"]
    assert not any(w.label == "addr 1" for w in diagram.wires)
    assert _between(diagram, ids["robot"], bus_line.id)  # the controller ↔ bus line stays
    assert "contains" not in {w.label for w in diagram.wires}


def test_candidates_excluded() -> None:
    e, config = _arm()
    ids = {name: str(entity.id) for name, entity in e.items()}
    edges = _edges(e)
    below, at = CANDIDATE_THRESHOLD - 0.3, CANDIDATE_THRESHOLD
    drawn = [
        _as_inferred(edges["wires"], below),  # a proposal: never drawn
        _as_inferred(edges["powers"], at),  # confirmed by confidence: drawn
        _as_inferred(edges["drives"], below),  # a proposal: servo 1 has no drawn edge then
        edges["contains1"],
        edges["contains2"],
    ]

    diagram = _diagram(e, drawn, config)

    assert _between(diagram, ids["mcu"], ids["driver"]) == []
    assert ids["mcu"] not in {n.id for n in diagram.nodes}  # reached only through a candidate
    assert _between(diagram, ids["supply"], ids["driver"]) == [
        (UNKNOWN_PIN, UNKNOWN_PIN, "+5V", False)
    ]
    assert _between(diagram, ids["bus"], ids["servo1"]) == []
    # With the candidate gone servo 1 has no drawn edge, so the config draws its bus line.
    parts = (ids["servo1"], ids["servo2"])
    assert sorted(w.label for w in diagram.wires if w.from_node in parts) == ["addr 1", "addr 2"]
