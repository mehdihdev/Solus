"""SOLUSDEV-321 P3-T2 — the electrical → electrical cell: `power_budget` reads each rail's line of
the `constraints/budgets` CONFIG (never recomputing it) onto the supplies its `powers` edges name;
`proximity_pair` waits for board positions and then a stated clearance; the cell's other rules
wait for their facts."""

from __future__ import annotations

import logging
import math
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

import pytest
from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers.cells import UnstatedFactRule
from solus_api.checkers.cells.electrical_electrical import (
    CELL,
    MAX_PAIRS,
    MAX_ROLE_PARTS,
    RULES,
    PowerBudget,
    ProximityPair,
)
from solus_api.checkers.fact_store import BoardPosition, FactStore
from solus_api.checkers.interface import Severity
from solus_api.checkers.netlist_motifs import CANDIDATE, CONFIDENT, NetMotif
from solus_api.fingerprint.contract import FingerprintOutput
from solus_api.services.solus_payloads import BudgetLine, Budgets, BudgetStatus

_PARTS: Final = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])
RULE: Final = PowerBudget()
SUPPLY: Final = EntityRead(id=uuid.uuid4(), kind="component", domain="electrical", name="buck")
SINK: Final = EntityRead(id=uuid.uuid4(), kind="component", domain="electrical", name="servos")
POWERED: Final = GraphContext(
    entities=[SUPPLY, SINK],
    edges=[
        EdgeRead(
            src_id=SUPPLY.id,
            dst_id=SINK.id,
            relation_type="powers",
            domain_pair="electrical<->electrical",
            confidence=0.9,
            attrs={"nets": ["+5V"]},
        )
    ],
)


def _power_line(
    status: BudgetStatus, current: float | None, limit: float | None, name: str = "power:+5V"
) -> BudgetLine:
    return BudgetLine(
        name=name, current=current, limit=limit, unit="A", source="powers edges", status=status
    )


def _budgets(*lines: BudgetLine) -> FactStore:
    stamp = datetime(2026, 10, 27, tzinfo=UTC)
    return FactStore(budgets=Budgets(computed_at=stamp, budgets=list(lines)))


def test_an_exceeded_rail_fails_on_its_supplies() -> None:
    over = _power_line("exceeded", 3.0, 2.0)
    mass = BudgetLine(name="mass", current=1.0, limit=2.0, unit="kg", source="parts", status="ok")
    store = _budgets(over, mass)

    (result,) = RULE.results(POWERED, store)

    assert (result.status, result.severity, result.subjects) == (
        "fail",
        Severity.CRITICAL,
        (SUPPLY.id,),
    )
    assert result.evidence == {"budget": over.model_dump(mode="json")}
    assert "3 A" in result.message and "2 A" in result.message
    (warning,) = RULE.check(POWERED, _PARTS, facts=store)
    assert warning.checker_id == "power_budget" and warning.entity_ids == (SUPPLY.id,)


def test_an_ok_rail_passes_and_an_unknown_one_is_inconclusive() -> None:
    store = _budgets(_power_line("ok", 1.0, 2.0), _power_line("unknown", None, 2.0, "power:12V"))

    ok, unknown = RULE.results(POWERED, store)

    assert (ok.status, ok.subjects) == ("pass", (SUPPLY.id,))
    assert (unknown.status, unknown.subjects) == ("inconclusive", ())


def test_power_budget_keeps_its_fail_off_findings() -> None:
    """R60: `budget_exceeded` (services/budgets.py) is THE finding for a rail breach, so the
    rule's `fail` stays on the edge and in the run's report, and the run raises nothing for it."""
    assert PowerBudget.raises_findings is False


def test_without_the_budgets_config_or_a_powers_edge_it_cannot_check() -> None:
    (guard,) = RULE.results(POWERED, FactStore())
    assert guard.missing is not None and guard.missing.name == "budgets"
    unpowered = GraphContext(entities=[SUPPLY, SINK], edges=[])
    (gap,) = RULE.results(unpowered, _budgets(_power_line("ok", 1.0, 2.0)))
    assert gap.missing is not None and gap.missing.name == "powers"


def test_proximity_pair_waits_for_positions_then_for_a_clearance() -> None:
    rule = ProximityPair()
    (positions,) = rule.results(POWERED, FactStore())
    assert positions.missing is not None and positions.missing.name == "pcb_positions"
    placed = FactStore(pcb_positions={SINK.id: BoardPosition(1.0, 2.0, None)})
    (clearance,) = rule.results(POWERED, placed)
    assert clearance.missing is not None and clearance.missing.name == "proximity_clearance_mm"
    assert rule.evaluate(POWERED, placed) == [clearance]


def _component(name: str, behaviour: str | None = None) -> EntityRead:
    attrs = {"behaviour_class": behaviour} if behaviour else {}
    return EntityRead(
        id=uuid.uuid4(), kind="component", domain="electrical", name=name, attrs=attrs
    )


def test_a_switcher_or_heat_source_closer_than_the_clearance_fails() -> None:
    """R73: a part's role is its behaviour class (its attrs here), the clearance is the rules
    entry's, and the distance runs between footprint centres. A switcher 5 mm from precision
    analog under a 6 mm clearance fails. One 50 mm away passes. A heat source 1 mm from a
    capacitor fails."""
    rule = ProximityPair()
    buck, amp = _component("U5", "switcher"), _component("U6", "precision_analog")
    far = _component("U7", "precision_analog")
    regulator, cap = _component("U8", "heat_source"), _component("C4")
    graph = GraphContext(entities=[buck, amp, far, regulator, cap], edges=[])
    at = {buck.id: (0, 0), amp.id: (3, 4), far.id: (30, 40), regulator.id: (10, 0), cap.id: (11, 0)}
    facts = FactStore(
        pcb_positions={i: BoardPosition(float(x), float(y), None) for i, (x, y) in at.items()},
        proximity_clearance_mm=6.0,
    )

    results = {result.subjects: result for result in rule.results(graph, facts)}

    hit = results[(buck.id, amp.id)]
    assert (hit.status, hit.severity) == ("fail", Severity.WARNING)
    assert hit.evidence == {
        "distance_mm": 5.0,
        "clearance_mm": 6.0,
        "aggressor": "switcher",
        "victim": "precision analog",
    }
    assert results[(buck.id, far.id)].status == "pass"
    assert results[(regulator.id, cap.id)].status == "fail"
    assert len(results) == 3  # nothing else is a pair: the capacitor is no analog part
    assert {w.entity_ids for w in rule.check(graph, _PARTS, facts=facts)} == {
        (buck.id, amp.id),
        (regulator.id, cap.id),
    }


def test_a_settled_motif_gives_a_part_its_role_and_a_candidate_does_not() -> None:
    """A settled H-bridge's parts switch, and a settled divider's are precision analog, with no
    behaviour class stated. A candidate motif gives no role."""
    rule = ProximityPair()
    q1, r1 = _component("Q1"), _component("R1")
    graph = GraphContext(entities=[q1, r1], edges=[])
    near = {q1.id: BoardPosition(0.0, 0.0, None), r1.id: BoardPosition(2.0, 0.0, None)}

    def facts(confidence: float) -> FactStore:
        bridge = NetMotif("h_bridge", (q1.id, uuid.uuid4()), confidence, uuid.uuid4())
        divider = NetMotif("divider_adc", (r1.id, uuid.uuid4()), confidence, uuid.uuid4())
        return FactStore(pcb_positions=near, motifs=(bridge, divider), proximity_clearance_mm=5.0)

    (result,) = rule.results(graph, facts(CONFIDENT))
    assert (result.status, result.subjects) == ("fail", (q1.id, r1.id))
    assert rule.results(graph, facts(CANDIDATE)) == []


def test_a_crowded_board_bounds_the_pairs_it_measures(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """R79: 600 switchers and 600 precision-analog parts never make the rule measure, or hold,
    every pair.

    - Each role keeps its first `MAX_ROLE_PARTS` parts, and the cap is logged when it binds.
    - At most `MAX_ROLE_PARTS`² distances are measured per pairing.
    - Only the nearest `MAX_PAIRS` are kept and judged.
    """
    rule = ProximityPair()
    parts = [_component(f"U{n}", "switcher") for n in range(600)]
    parts += [_component(f"U{n + 600}", "precision_analog") for n in range(600)]
    facts = FactStore(
        pcb_positions={p.id: BoardPosition(float(i), 0.0, None) for i, p in enumerate(parts)},
        proximity_clearance_mm=1.0,
    )
    measured = 0
    dist = math.dist

    def counted(a: Sequence[float], b: Sequence[float]) -> float:
        nonlocal measured
        measured += 1
        return dist(a, b)

    monkeypatch.setattr(math, "dist", counted)
    with caplog.at_level(logging.WARNING, logger="solus.checkers.cells.electrical_electrical"):
        results = rule.results(GraphContext(entities=parts, edges=[]), facts)

    assert len(results) == MAX_PAIRS
    assert 0 < measured <= MAX_ROLE_PARTS * MAX_ROLE_PARTS
    assert "600 parts hold the noisy role; judging the first" in caplog.text
    assert "600 parts hold the analog role; judging the first" in caplog.text


def test_the_cells_other_rules_wait_for_their_facts() -> None:
    waiting = [rule for rule in RULES if isinstance(rule, UnstatedFactRule)]
    assert [rule.rule_id for rule in waiting] == [
        "trace_width_vs_current",
        "return_path_over_split",
    ]
    for rule in waiting:
        (only,) = rule.results(POWERED, FactStore())
        assert (only.status, only.missing) == ("unknown_input", rule.needs.facts[0])
    assert all(rule.matrix_cell is CELL for rule in RULES)
