"""SOLUSDEV-321 P3-T2, P4-T5 — the mechanical → mechanical cell.

Two of its rules wait for a fact no source states yet (`tolerance_stack`, `fastener_engagement`):
each answers `unknown_input` naming its fact and where a person states it, and never a warning.
Since P4-T5 the two that waited for P4's simulations judge what a simulation expects of a part
(`FactStore.expected`, which `record_sim_result` writes):

- `bracket_strength_at_joint` reads `yield_fraction`, the stress over the yield it is judged
  against. It fails at or past the yield, is `inconclusive` inside the ladder's own band below it,
  and passes with margin. Every verdict carries the band's evidence keys (R94), so the ladder climbs
  from an inconclusive one;
- `interference_through_range` reads `interference_mm`, the mesh check's depth: any depth fails, and
  none passes.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any, Final

import pytest
from solus_api.agent.interfaces import EntityRead, GraphContext
from solus_api.checkers.cells import UnstatedFactRule
from solus_api.checkers.cells.mechanical_mechanical import (
    CELL,
    INTERFERENCE,
    INTERFERENCE_NEED,
    RULES,
    STRESS,
    STRESS_NEED,
    YIELD_FRACTION,
    BracketStrengthAtJoint,
    InterferenceThroughRange,
)
from solus_api.checkers.fact_store import ExpectedValue, FactStore
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import MatrixRule
from solus_api.fingerprint.contract import FingerprintOutput
from solus_api.graph import kinds
from solus_api.orchestration.config import SimulationConfig
from solus_api.simulation.providers.deterministic_mech import DeterministicMech
from solus_api.simulation.providers.mesh_interference import MeshInterference
from solus_api.simulation.sim_ladder import LadderContext, SimProposal, should_simulate

_EMPTY: Final = GraphContext(entities=[], edges=[])
_PARTS: Final = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])
_BRACKET: Final = BracketStrengthAtJoint()
_INTERFERENCE: Final = InterferenceThroughRange()
#: The P4 bracket's facts (tests/fixtures/sim_bracket.py), so a rung above can answer for it.
_ATTRS: Final[dict[str, Any]] = {
    "section": {"shape": "rect", "dims_mm": [30.0, 5.0]},
    "load": {"force_n": 1173.0, "arm_m": 0.025},
    "material": {"name": "fake-6061", "yield_mpa": 276.0, "density_kg_m3": 2700.0},
}
_YIELD_MPA: Final = 276.0

WAITING: Final = tuple(rule for rule in RULES if isinstance(rule, UnstatedFactRule))


def _part(name: str = "bracket", **attrs: Any) -> EntityRead:
    return EntityRead(id=uuid.uuid4(), kind=kinds.PART, domain="mechanical", name=name, attrs=attrs)


def _run_of(subject: EntityRead, rung: int) -> EntityRead:
    """The `sim_result` a simulation of `subject` left, as `record_sim_result` writes it."""
    return EntityRead(
        id=uuid.uuid4(),
        kind=kinds.SIM_RESULT,
        domain="simulation",
        name=f"yield_fraction — {subject.name}",
        attrs={"subject_id": str(subject.id), "rung": rung},
    )


def _bracket(
    fraction: float, *, rung: int | None = 1
) -> tuple[GraphContext, FactStore, EntityRead, str]:
    """A bracket a simulation found at `fraction` of its yield, and the facts that say so. With
    `rung=None` the graph does not hold the run the value names."""
    part = _part(**_ATTRS)
    run = _run_of(part, rung or 1)
    sim_id = str(run.id)
    expected = {
        YIELD_FRACTION: ExpectedValue(fraction, None, sim_id),
        STRESS: ExpectedValue(fraction * _YIELD_MPA, "MPa", sim_id),
    }
    entities = [part] if rung is None else [part, run]
    return (
        GraphContext(entities=entities, edges=[]),
        FactStore(expected_values={part.id: expected}),
        part,
        sim_id,
    )


def test_the_cell_holds_its_four_rules_then_the_manufacturing_rules() -> None:
    """R76: P3-T4's manufacturing rule joins the spec's four in this cell
    (tests/test_manufacturing_rules.py); since P4-T5 only two of the four wait."""
    assert [rule.rule_id for rule in RULES] == [
        "tolerance_stack",
        "interference_through_range",
        "bracket_strength_at_joint",
        "fastener_engagement",
        "wall_too_thin",
    ]
    assert [rule.rule_id for rule in WAITING] == ["tolerance_stack", "fastener_engagement"]


@pytest.mark.parametrize("rule", WAITING, ids=[rule.rule_id for rule in WAITING])
def test_each_rule_waits_for_its_fact(rule: MatrixRule) -> None:
    assert isinstance(rule, UnstatedFactRule) and rule.matrix_cell is CELL
    (only,) = rule.results(_EMPTY, FactStore())
    assert (only.status, only.missing) == ("unknown_input", rule.needs.facts[0])
    assert rule.evaluate(_EMPTY, FactStore()) == [only]
    assert rule.check(_EMPTY, _PARTS) == []


@pytest.mark.parametrize(
    ("rule", "need"),
    [(_BRACKET, STRESS_NEED), (_INTERFERENCE, INTERFERENCE_NEED)],
    ids=["bracket", "interference"],
)
def test_with_nothing_simulated_a_p4_rule_names_what_to_simulate(
    rule: MatrixRule, need: object
) -> None:
    """ONE `unknown_input` for the project, never one per part: the part states its inputs, and no
    simulation has run on it yet."""
    graph = GraphContext(entities=[_part(**_ATTRS), _part("plate")], edges=[])
    (only,) = rule.results(graph, FactStore())
    assert (only.status, only.missing, only.subjects) == ("unknown_input", need, ())
    assert rule.matrix_cell is CELL and rule.check(graph, _PARTS) == []


@pytest.mark.parametrize(
    ("fraction", "status"),
    [
        pytest.param(0.15, "pass", id="15pct-has-margin"),
        pytest.param(0.79, "pass", id="just-under-the-band"),
        pytest.param(0.85, "inconclusive", id="85pct-inside-the-band"),
        pytest.param(1.0, "fail", id="at-the-yield"),
        pytest.param(300 / 276, "fail", id="past-the-yield"),
    ],
)
def test_a_bracket_passes_with_margin_is_inconclusive_in_the_band_and_fails_at_its_yield(
    fraction: float, status: str
) -> None:
    graph, facts, part, sim_id = _bracket(fraction)

    (result,) = _BRACKET.results(graph, facts)

    assert (result.status, result.subjects, result.edge_ref) == (status, (part.id,), None)
    assert result.severity is (Severity.WARNING if status == "fail" else Severity.INFO)
    assert result.evidence == {
        "quantity": YIELD_FRACTION,
        "value": fraction,
        "limit": 1.0,
        "comparator": "<=",
        "unit": None,
        "sim_result_id": sim_id,
        "rung": 1,
        "stress_mpa": fraction * _YIELD_MPA,
    }
    assert result.message.startswith(f"bracket's simulated stress is {fraction:.0%} of its yield")
    assert "MPa" in result.message and "at rung 1" in result.message
    fails = [warning.checker_id for warning in _BRACKET.check(graph, _PARTS, facts)]
    assert fails == (["bracket_strength_at_joint"] if status == "fail" else [])


def _climbs(fraction: float, rung: int) -> list[SimProposal]:
    graph, facts, _, _ = _bracket(fraction, rung=rung)
    providers = (DeterministicMech(), MeshInterference())
    context = LadderContext(
        config=facts.simulation,
        graph=graph,
        providers=providers,
        available=frozenset(provider.name for provider in providers),
    )
    return should_simulate(_BRACKET.results(graph, facts), trigger="rule", context=context)


def test_the_ladder_climbs_from_an_inconclusive_bracket_and_stops_where_it_settles() -> None:
    """R94: the band keys on an inconclusive verdict are what the ladder reads. Inside the band at
    rung 1 it proposes the rung-3 mesh check, which runs on the bracket's own facts. A bracket with
    margin proposes nothing, and nor does one inside the band at rung 3, the highest rung that
    computes its stress."""
    (climb,) = _climbs(0.85, 1)

    assert (climb.trigger, climb.quantity, climb.rung) == ("rule", YIELD_FRACTION, 3)
    assert (climb.target, climb.decision, climb.available) == ("mesh_interference", "run", True)
    assert climb.reason == "yield_fraction is at 85% of its limit at rung 1: inside its 0.8 band"
    assert _climbs(0.15, 1) == []
    assert _climbs(0.85, 3) == []


def test_the_band_is_the_ladders_own_for_the_quantity() -> None:
    """The verdict reads the ladder's band from the store (`simulation.band`), so a band the yaml
    narrows for `yield_fraction` moves the line between a pass and an inconclusive."""
    graph, facts, _, _ = _bracket(0.6)
    narrowed = replace(facts, simulation=SimulationConfig(bands={YIELD_FRACTION: 0.5}))

    assert [result.status for result in _BRACKET.results(graph, facts)] == ["pass"]
    assert [result.status for result in _BRACKET.results(graph, narrowed)] == ["inconclusive"]


@pytest.mark.parametrize(
    ("rung", "why"),
    [
        pytest.param(1, "which a higher rung settles", id="the-mesh-check-is-above-rung-1"),
        pytest.param(None, "which a higher rung settles", id="an-unrecorded-rung-may-climb"),
        pytest.param(3, "unresolved: no higher rung computes it", id="nothing-is-above-rung-3"),
    ],
)
def test_an_inconclusive_bracket_says_whether_a_higher_rung_settles_it(
    rung: int | None, why: str
) -> None:
    """Minor 5: the verdict promises a higher rung only where a provider the ladder ranks
    computes the yield fraction above the rung the value came from: the mesh check above rung 1,
    and nothing above its own rung 3 in the shipped yaml, whose one target does not compute it."""
    graph, facts, _, _ = _bracket(0.85, rung=rung)

    (result,) = _BRACKET.results(graph, facts)

    assert result.message.endswith(f"inside the ladder's 0.8 band, {why}")


def test_a_value_whose_run_the_graph_does_not_hold_states_no_rung() -> None:
    """Empty beats invented: the evidence states no rung, so the ladder starts from the cheapest one
    that computes the quantity, and the message says the rung is not known."""
    graph, facts, _, _ = _bracket(0.85, rung=None)

    (result,) = _BRACKET.results(graph, facts)

    assert result.status == "inconclusive" and "rung" not in result.evidence
    assert "at an unrecorded rung" in result.message


@pytest.mark.parametrize(
    ("depth", "status"),
    [pytest.param(0.0, "pass", id="no-depth-clears"), pytest.param(1.5, "fail", id="any-depth")],
)
def test_interference_fails_on_any_depth_and_passes_on_none(depth: float, status: str) -> None:
    part, plate = _part(), _part("plate")
    run = _run_of(part, 3)
    expected = {INTERFERENCE: ExpectedValue(depth, "mm", str(run.id))}
    graph = GraphContext(entities=[part, plate, run], edges=[])

    (result,) = _INTERFERENCE.results(graph, FactStore(expected_values={part.id: expected}))

    assert (result.status, result.subjects) == (status, (part.id,))
    assert result.severity is (Severity.WARNING if status == "fail" else Severity.INFO)
    assert result.evidence == {
        "quantity": INTERFERENCE,
        "value": depth,
        "limit": 0.0,
        "comparator": "<=",
        "unit": "mm",
        "sim_result_id": str(run.id),
        "rung": 3,
    }
    assert ("interpenetrate by up to 1.5 mm" in result.message) is (status == "fail")
