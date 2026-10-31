"""SOLUSDEV-321 P3-T2 — the software → electrical cell: `pin_in_code_vs_wiring` judges the pin a
confirmed `reads` edge names against the brain-side pins the schematic wires the part to; the
cell's other rules wait for their facts."""

from __future__ import annotations

import uuid
from typing import Any, Final

import pytest
from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers.cells import UnstatedFactRule
from solus_api.checkers.cells.software_electrical import CELL, RULES, PinInCodeVsWiring
from solus_api.checkers.fact_store import FactStore
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import EdgeRef
from solus_api.fingerprint.contract import FingerprintOutput

_PARTS: Final = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])
RULE: Final = PinInCodeVsWiring()


def _node(kind: str, domain: str, name: str) -> EntityRead:
    return EntityRead(id=uuid.uuid4(), kind=kind, domain=domain, name=name)


BRAIN: Final = _node("hardware_brain", "electrical", "brain")
SENSOR: Final = _node("part", "electrical", "pot")
OTHER: Final = _node("part", "electrical", "led")
CODE: Final = _node("code_file", "code", "fw.ino")


def _edge(
    src: EntityRead, dst: EntityRead, relation: str, *, confidence: float = 1.0, **attrs: Any
) -> EdgeRead:
    return EdgeRead(
        src_id=src.id,
        dst_id=dst.id,
        relation_type=relation,
        domain_pair=f"{src.domain}<->{dst.domain}",
        confidence=confidence,
        attrs=attrs,
    )


def _wired(part: EntityRead, *brain_pins: str) -> EdgeRead:
    pins = {str(BRAIN.id): list(brain_pins), str(part.id): ["1"]}
    return _edge(BRAIN, part, "wires", nets=["/SENSE"], pins=pins)


def _graph(*edges: EdgeRead) -> GraphContext:
    return GraphContext(entities=[BRAIN, SENSOR, OTHER, CODE], edges=list(edges))


def test_a_read_pin_the_part_is_not_wired_to_fails() -> None:
    graph = _graph(_edge(CODE, SENSOR, "reads", pin="A1"), _wired(SENSOR, "A0"))

    (result,) = RULE.results(graph, FactStore())

    assert (result.status, result.severity) == ("fail", Severity.WARNING)
    assert result.subjects == (CODE.id, SENSOR.id)
    assert result.edge_ref == EdgeRef(CODE.id, SENSOR.id, "reads")
    assert result.evidence == {"pin": "A1", "wired_pins": ["A0"]}
    (warning,) = RULE.check(graph, _PARTS)
    assert warning.checker_id == "pin_in_code_vs_wiring"


def test_a_read_pin_the_part_is_wired_to_passes() -> None:
    graph = _graph(_edge(CODE, SENSOR, "reads", pin="A0"), _wired(SENSOR, "A0", "D2"))

    (result,) = RULE.results(graph, FactStore())

    assert result.status == "pass" and result.edge_ref == EdgeRef(CODE.id, SENSOR.id, "reads")
    assert RULE.check(graph, _PARTS) == []


def test_a_candidate_read_or_an_unwired_part_is_unknown() -> None:
    candidate = _graph(_edge(CODE, SENSOR, "reads", confidence=0.55, pin="A0"), _wired(SENSOR))
    (gap,) = RULE.results(candidate, FactStore())
    assert (gap.status, gap.missing.name if gap.missing else None) == ("unknown_input", "reads")

    unwired = _graph(_edge(CODE, SENSOR, "reads", pin="A0"), _wired(OTHER, "A0"))
    (missing,) = RULE.results(unwired, FactStore())
    assert missing.status == "unknown_input" and missing.subjects == (CODE.id, SENSOR.id)
    assert missing.missing is not None and missing.missing.name == "wires"
    assert (
        RULE.results(_graph(_edge(CODE, SENSOR, "reads"), _wired(SENSOR, "A0")), FactStore()) == []
    )


def test_each_read_looks_up_only_its_own_parts_wires(monkeypatch: pytest.MonkeyPatch) -> None:
    """m11 (R79): the `wires` edges are indexed by endpoint once an evaluation. 200 reads of one
    sensor among 2,001 wires examine that sensor's wires once, never reads × wires."""
    from solus_api.checkers.cells import software_electrical
    from solus_api.checkers.cells import wired_pins as real

    leds = [_node("part", "electrical", f"led{n}") for n in range(2_000)]
    wires = [_wired(SENSOR, "A0"), *(_wired(led, f"D{n % 10}") for n, led in enumerate(leds))]
    reads = [_edge(CODE, SENSOR, "reads", pin="A0") for _ in range(200)]
    examined = 0

    def counted(part_id: uuid.UUID, edges: list[EdgeRead]) -> dict[uuid.UUID, set[str]]:
        nonlocal examined
        examined += len(edges)
        return real(part_id, edges)

    monkeypatch.setattr(software_electrical, "wired_pins", counted)
    graph = GraphContext(entities=[BRAIN, SENSOR, CODE, *leds], edges=[*wires, *reads])

    results = RULE.results(graph, FactStore())

    assert len(results) == 200 and {result.status for result in results} == {"pass"}
    assert examined <= 2 * len(wires)


def test_the_cells_other_rules_wait_for_their_facts() -> None:
    """`sample_rate_vs_adc_settling` judges since P3-T4 (tests/test_sample_rate_vs_adc.py)."""
    waiting = [rule for rule in RULES if isinstance(rule, UnstatedFactRule)]
    assert [rule.rule_id for rule in waiting] == [
        "commanded_current_vs_driver_supply",
        "pwm_frequency_vs_driver",
    ]
    for rule in waiting:
        (only,) = rule.results(_graph(), FactStore())
        assert (only.status, only.missing) == ("unknown_input", rule.needs.facts[0])
    assert all(rule.matrix_cell is CELL for rule in RULES)
