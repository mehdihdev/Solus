"""SOLUSDEV-321 P4-T1 — the simulation ladder only proposes.

- When: an inconclusive result inside its band, a change that needs an expected value, the person,
  or a real-world action about to run. Never a sync or a save.
- Cheap first: a value with margin stops where it is.
- Whether: derive → ask once → run the covered part → missing_input.
- Where: style → available → cost → fidelity.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, cast

import pytest
from pydantic import ValidationError
from solus_api.agent.interfaces import EntityRead, GraphContext
from solus_api.checkers.checker_results import RuleStatus
from solus_api.checkers.fact_store import FactStore, StyleEntry
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import RuleResult
from solus_api.livebench.findings.rules.rule_base import FactNeed
from solus_api.orchestration.config import SimTargetConfig, SimulationConfig
from solus_api.simulation.sim_capability import MissingInputs, SimInput, SimQuestion, SimResult
from solus_api.simulation.sim_ladder import (
    LOCAL_PROVIDERS,
    MISSING_INPUT_RULE,
    LadderContext,
    SimProposal,
    SimTrigger,
    asked_names,
    available_targets,
    climbs,
    ladder_context,
    missing_input_finding,
    precheck_real_world_action,
    proposal_line,
    propose_for,
    should_simulate,
)

BRACKET: Final = uuid.uuid4()
MATERIAL: Final = FactNeed(name="material", set_in="the part's `material` attr: {name, yield_mpa}")
LOAD: Final = FactNeed(name="load", set_in="the part's `load` attr: {force_n, arm_m}")
TRIGGERS: Final[tuple[SimTrigger, ...]] = ("rule", "expected_value", "user", "real_world_action")


@dataclass(frozen=True)
class _Provider:
    """A provider double. The ladder never runs one: it only asks `can_answer`."""

    name: str
    rung: int
    quantities: frozenset[str] = frozenset({"stress_mpa"})
    domain: str = "mechanical"
    lacks: MissingInputs = field(default_factory=MissingInputs)

    def can_answer(self, question: SimQuestion) -> MissingInputs:
        return self.lacks

    def run(self, inputs: Mapping[str, SimInput]) -> SimResult:
        raise AssertionError(f"the ladder ran {self.name}: it only proposes")


BEAM: Final = _Provider("beam", 1)  # the closed form
REMOTE: Final = _Provider("remote_fea", 2)  # an external target, not connected unless said
MESH: Final = _Provider("mesh", 3, frozenset({"stress_mpa", "interference_mm", "clearance_mm"}))
FULL: Final = _Provider("full_sim", 4)
CONFIG: Final = SimulationConfig(
    bands={"interference_mm": 0.5},
    targets=(
        SimTargetConfig(name="remote_fea", rung=2, domain="mechanical", quantities=("stress_mpa",)),
    ),
)
SUBJECT: Final = EntityRead(
    id=BRACKET, kind="part", domain="mechanical", name="bracket", attrs={"section": {"w": 4}}
)
GRAPH: Final = GraphContext(entities=[SUBJECT], edges=[])


def _ladder(**overrides: Any) -> LadderContext:
    """The bracket's ladder: four providers, with the closed form and the mesh check connected."""
    given: dict[str, Any] = {
        "config": CONFIG,
        "graph": GRAPH,
        "providers": (BEAM, REMOTE, MESH, FULL),
        "available": frozenset({"beam", "mesh"}),
        **overrides,
    }
    return LadderContext(**given)


def _near(
    ratio: float,
    *,
    rung: int | None = None,
    quantity: str = "stress_mpa",
    status: RuleStatus = "inconclusive",
) -> RuleResult:
    """A rule's result about the bracket, its value at `ratio` of a 100 MPa limit."""
    evidence: dict[str, Any] = {
        "quantity": quantity,
        "value": round(ratio * 100, 6),
        "limit": 100.0,
        "unit": "MPa",
    }
    if rung is not None:
        evidence["rung"] = rung
    return RuleResult(
        status=status,
        message="the estimate is close to the limit",
        subjects=(BRACKET,),
        evidence=evidence,
    )


def _about_the_bracket(evidence: dict[str, Any]) -> RuleResult:
    return RuleResult(status="inconclusive", message="near", subjects=(BRACKET,), evidence=evidence)


def _routing_target(
    name: str, rung: int, *, cost: float | None = None, fidelity: float | None = None
) -> SimTargetConfig:
    return SimTargetConfig(
        name=name,
        rung=rung,
        domain="mechanical",
        quantities=("stress_mpa",),
        cost=cost,
        fidelity=fidelity,
    )


def _style_entry(text: str) -> StyleEntry:
    return StyleEntry(uuid.uuid4(), text, None)


def test_stop_at_rung_1_with_margin() -> None:
    """A rung-1 value with margin proposes nothing, whoever asks: the bracket at 15 % of yield
    stops at rung 1."""
    for trigger in TRIGGERS:
        assert should_simulate([_near(0.15, rung=1)], trigger=trigger, context=_ladder()) == []
    passed = _near(0.15, rung=1, status="pass")
    assert should_simulate([passed], trigger="user", context=_ladder()) == []


def test_escalate_inside_band_at_0_8() -> None:
    """At or past 0.8 of its limit, a rung-1 value climbs to the cheapest connected rung above it:
    the bracket at 85 % goes to the mesh check, and the unconnected rung-2 target ranks after it.
    Each quantity has its own band, and a floor compares the other way."""
    climb = _ladder()
    assert should_simulate([_near(0.79, rung=1)], trigger="rule", context=climb) == []
    [at_band] = should_simulate([_near(0.8, rung=1)], trigger="rule", context=climb)
    assert (at_band.rung, at_band.target, at_band.available, at_band.decision) == (
        3,
        "mesh",
        True,
        "run",
    )
    assert at_band.alternatives == ("remote_fea", "full_sim")
    assert at_band.reason == "stress_mpa is at 80% of its limit at rung 1: inside its 0.8 band"
    [high] = should_simulate([_near(0.85, rung=1)], trigger="real_world_action", context=climb)
    assert (high.trigger, high.target) == ("real_world_action", "mesh")
    banded = [_near(0.6, rung=1, quantity="interference_mm")]
    assert [p.target for p in should_simulate(banded, trigger="rule", context=climb)] == ["mesh"]
    loose = [_near(0.45, rung=1, quantity="interference_mm")]
    assert should_simulate(loose, trigger="rule", context=climb) == []
    floor = {"quantity": "clearance_mm", "value": 3.6, "limit": 3.0, "comparator": ">=", "rung": 1}
    near_floor = [_about_the_bracket(floor)]  # 3.6 mm left of a 3 mm clearance: 83 %
    assert [p.target for p in should_simulate(near_floor, trigger="rule", context=climb)] == [
        "mesh"
    ]
    clear = [_about_the_bracket({**floor, "value": 5.0})]
    assert should_simulate(clear, trigger="rule", context=climb) == []
    assert should_simulate([_near(0.95, rung=4)], trigger="rule", context=climb) == []


def test_inconclusive_within_20pct_proposes() -> None:
    """An inconclusive rule within 20 % of a limit, before any simulation, proposes rung 1.
    Nothing else proposes: a value with margin, evidence that states no value against a limit, no
    subject, a pass or a fail."""
    [first] = should_simulate([_near(0.85)], trigger="rule", context=_ladder())
    assert (first.trigger, first.subject_id, first.quantity, first.rung, first.target) == (
        "rule",
        BRACKET,
        "stress_mpa",
        1,
        "beam",
    )
    assert (first.decision, first.available, first.missing) == ("run", True, ())
    assert first.reason == "stress_mpa is at 85% of its limit at rung 0: inside its 0.8 band"
    assert first.remember_as == "simulate stress_mpa with beam"
    stated = {"quantity": "stress_mpa", "value": 90.0, "limit": 100.0}
    quiet = [
        _near(0.5),
        _about_the_bracket({"joint": "elbow", "value": 90.0, "lower": -1.5, "upper": 1.5}),
        RuleResult(status="inconclusive", message="near", evidence=stated),  # no subject
        _near(1.2, status="fail"),
        _near(0.9, status="pass"),
        _near(0.85, quantity="Stress MPa"),  # a quantity a style line could not name back
        _about_the_bracket({**stated, "rung": "1"}),
        _about_the_bracket({**stated, "limit": 0.0}),
        _about_the_bracket({**stated, "comparator": "=="}),
    ]
    assert should_simulate(quiet, trigger="rule", context=_ladder()) == []
    twice = should_simulate([_near(0.85), _near(0.95)], trigger="rule", context=_ladder())
    assert [p.reason for p in twice] == [first.reason]  # the first result that asks wins
    elsewhere = _ladder(graph=GraphContext(entities=[], edges=[]))
    assert should_simulate([_near(0.85)], trigger="rule", context=elsewhere) == []


def test_a_change_or_the_person_proposes_what_no_simulation_answered_yet() -> None:
    """`expected_value` and `user` read a rule's unknown input when a provider computes the
    quantity it lacks. The person's own question arrives straight, through `propose_for`."""
    unanswered = RuleResult(
        status="unknown_input",
        message="could not check bracket_strength_at_joint",
        subjects=(BRACKET,),
        missing=FactNeed(name="stress_mpa", set_in="a rung-1 stress estimate"),
    )
    assert should_simulate([unanswered], trigger="rule", context=_ladder()) == []
    # a real-world action's pre-check reads only what is near a limit, never an unknown input
    assert should_simulate([unanswered], trigger="real_world_action", context=_ladder()) == []
    wanting: tuple[SimTrigger, ...] = ("expected_value", "user")
    for trigger in wanting:
        [proposal] = should_simulate([unanswered], trigger=trigger, context=_ladder())
        assert (proposal.trigger, proposal.rung, proposal.target) == (trigger, 1, "beam")
        assert proposal.reason == "stress_mpa has no expected value yet"
    unstated = RuleResult(
        status="unknown_input", message="no material", subjects=(BRACKET,), missing=MATERIAL
    )
    assert should_simulate([unstated], trigger="expected_value", context=_ladder()) == []
    question = SimQuestion(subject_id=BRACKET, quantity="stress_mpa")
    asked = propose_for(question, trigger="user", context=_ladder())
    assert asked is not None
    assert (asked.rung, asked.target, asked.reason) == (1, "beam", "the person asked for it")
    assert propose_for(question, trigger="user", context=_ladder(), above_rung=4) is None
    unmodelled = SimQuestion(subject_id=BRACKET, quantity="mass_kg")
    assert propose_for(unmodelled, trigger="user", context=_ladder()) is None


def test_sync_and_save_never_trigger() -> None:
    """A sync or a save is not a trigger: the ladder refuses both, even with nothing to read. For
    every trigger there is, it asks `can_answer` and never runs a provider (each double here
    raises on `run`)."""
    results = [_near(0.85), _near(0.85, rung=1)]
    question = SimQuestion(subject_id=BRACKET, quantity="stress_mpa")
    for refused in ("sync", "save"):
        trigger = cast(SimTrigger, refused)
        for given in ([], results):
            with pytest.raises(ValueError, match="a sync or a save"):
                should_simulate(given, trigger=trigger, context=_ladder())
        with pytest.raises(ValueError, match="a sync or a save"):
            propose_for(question, trigger=trigger, context=_ladder())
    for trigger in TRIGGERS:
        should_simulate(results, trigger=trigger, context=_ladder())
        assert propose_for(question, trigger=trigger, context=_ladder()) is not None


def test_where_prefers_style_entry() -> None:
    """Where, in order: a `constraints/style` entry (even for a target that is not connected),
    then connected and configured, then cost, then fidelity. The newest entry wins, `*` stands for
    any quantity, and the proposal carries the line an override is remembered as."""
    climb = [_near(0.85, rung=1)]

    def chosen(**overrides: Any) -> tuple[str, bool, tuple[str, ...]]:
        [proposal] = should_simulate(climb, trigger="rule", context=_ladder(**overrides))
        return proposal.target, proposal.available, proposal.alternatives

    assert chosen() == ("mesh", True, ("remote_fea", "full_sim"))
    every = frozenset({"beam", "remote_fea", "mesh", "full_sim"})
    assert chosen(available=every) == ("remote_fea", True, ("mesh", "full_sim"))
    priced = SimulationConfig(targets=(_routing_target("full_sim", 4, cost=0.5),))
    assert chosen(available=every, config=priced)[0] == "full_sim"
    tied = SimulationConfig(targets=(_routing_target("remote_fea", 2, cost=3, fidelity=1),))
    assert chosen(available=every, config=tied)[0] == "mesh"  # cost 3 each: fidelity 3 beats 1
    preferring = (_style_entry("simulate stress_mpa with remote_fea"),)
    assert chosen(style=preferring) == ("remote_fea", False, ("mesh", "full_sim"))
    newer = (*preferring, _style_entry("Simulate * with FULL_SIM"))
    assert chosen(style=newer)[0] == "full_sim"
    unrelated = (
        _style_entry("simulate interference_mm with remote_fea"),
        _style_entry("keep brackets light"),
    )
    assert chosen(style=unrelated)[0] == "mesh"
    [proposal] = should_simulate(climb, trigger="rule", context=_ladder(style=preferring))
    assert proposal.remember_as == "simulate stress_mpa with remote_fea"


def test_missing_input_finding_and_nothing_runs() -> None:
    """The no-material bracket (P4 acceptance). Its material was asked for once already, and
    without it the provider can still compute mass and centre of mass, but not the stress asked
    for. So the proposal is `missing_input` and names the field. It words as the standing info
    finding the caller raises, and no provider runs."""
    unstated = _Provider(
        "beam", 1, lacks=MissingInputs(missing=(MATERIAL,), covered=("mass_kg", "com_m"))
    )
    once = _ladder(providers=(unstated,), asked=frozenset({(BRACKET, "material")}))
    [proposal] = should_simulate([_near(0.85)], trigger="rule", context=once)
    assert (proposal.decision, proposal.missing, proposal.leaves_out) == (
        "missing_input",
        (MATERIAL,),
        (),
    )
    spec = missing_input_finding(proposal, SUBJECT)
    assert (spec.rule_id, spec.severity, spec.source, spec.subjects, spec.bucket) == (
        MISSING_INPUT_RULE,
        Severity.INFO,
        "simulation",
        [BRACKET],
        "stress_mpa",
    )
    assert spec.headline == (
        "could not simulate stress_mpa for bracket: material unknown; "
        "set it in the part's `material` attr: {name, yield_mpa}"
    )
    assert spec.evidence == {
        "missing": [MATERIAL.model_dump()],
        "quantity": "stress_mpa",
        "rung": 1,
        "target": "beam",
    }
    assert spec.domain.value == "mechanical"
    first_time = _ladder(providers=(unstated,))
    [asking] = should_simulate([_near(0.85)], trigger="rule", context=first_time)
    assert (asking.decision, asking.missing) == ("ask", (MATERIAL,))
    with pytest.raises(ValueError, match="missing_input"):  # an ask is not a finding
        missing_input_finding(asking, SUBJECT)
    with pytest.raises(ValueError, match="missing_input"):
        missing_input_finding(proposal, SUBJECT.model_copy(update={"id": uuid.uuid4()}))
    with pytest.raises(ValidationError):  # a missing_input names what is missing
        SimProposal.model_validate({**proposal.model_dump(), "missing": ()})


@pytest.mark.parametrize(
    ("lacks", "asked", "decision", "missing", "leaves_out"),
    [
        (MissingInputs(), frozenset(), "run", (), ()),
        (
            MissingInputs(missing=(MATERIAL,), derivable=("material",)),
            frozenset(),
            "derive",
            (MATERIAL,),
            (),
        ),
        (
            MissingInputs(missing=(MATERIAL, LOAD)),
            frozenset({(BRACKET, "material")}),
            "ask",
            (LOAD,),
            (),
        ),
        (
            MissingInputs(missing=(LOAD,), covered=("stress_mpa", "mass_kg")),
            frozenset({(BRACKET, "load")}),
            "run",
            (LOAD,),
            ("load",),
        ),
        (
            MissingInputs(missing=(LOAD,), covered=("mass_kg", "com_m")),
            frozenset({(BRACKET, "load")}),
            "missing_input",
            (LOAD,),
            (),
        ),
        (
            MissingInputs(missing=(MATERIAL, LOAD), derivable=("load",)),
            frozenset({(BRACKET, "material")}),
            "missing_input",
            (MATERIAL,),
            (),
        ),
    ],
    ids=[
        "nothing-missing-runs",
        "all-derivable-derives",
        "asks-once-for-what-was-not-asked",
        "the-asked-quantity-still-covered-runs-stating-the-gap",
        "only-other-quantities-covered-is-missing",
        "asked-and-uncovered-is-missing",
    ],
)
def test_whether_derives_asks_once_runs_the_covered_part_or_stops(
    lacks: MissingInputs,
    asked: frozenset[tuple[uuid.UUID, str]],
    decision: str,
    missing: tuple[FactNeed, ...],
    leaves_out: tuple[str, ...],
) -> None:
    """The whether-rule, row by row, for a stress question: derive → ask once → run when the
    provider still covers stress, stating the gap → missing_input. Covering only other quantities
    is not covering the question."""
    provider = _Provider("beam", 1, lacks=lacks)
    question = SimQuestion(subject_id=BRACKET, quantity="stress_mpa")
    context = _ladder(providers=(provider,), asked=asked)
    proposal = propose_for(question, trigger="user", context=context)
    assert proposal is not None
    assert (proposal.decision, proposal.missing, proposal.leaves_out) == (
        decision,
        missing,
        leaves_out,
    )


# --------------------------------- P4-T5: a matrix run's ladder, a gated action's pre-check


def test_a_matrix_run_and_a_gated_action_rank_every_provider_solus_runs() -> None:
    """`ladder_context`: the store's bands and style entries, and every provider Solus runs
    beside the yaml's targets. Which can run now is `simulate`'s own reading
    (`available_targets`, Minor 8): rung 1 always, rung 3 only with a job queue to take its
    bounded job, and no external target, since no turn's registry holds their gated routine
    tools here."""
    facts = FactStore(simulation=CONFIG, style=(_style_entry("simulate * with mesh_interference"),))

    context = ladder_context(GRAPH, facts, queued=False)
    queued = ladder_context(GRAPH, facts, queued=True)

    local = [provider.name for provider in LOCAL_PROVIDERS]
    assert local == [
        "deterministic_mech",
        "deterministic_elec",
        "deterministic_robot",
        "mesh_interference",
        "spice_transient",
        "rigid_body_trajectory",
    ]
    rung_1 = frozenset({"deterministic_mech", "deterministic_elec", "deterministic_robot"})
    assert [provider.name for provider in context.providers] == [*local, "remote_fea"]
    assert (context.available, queued.available) == (rung_1, frozenset(local))
    assert available_targets(queued=False, connected={"remote_fea"}) == {*rung_1, "remote_fea"}
    assert (context.config, context.graph, context.style) == (CONFIG, GRAPH, facts.style)


def test_what_a_person_was_asked_counts_for_its_own_quantity() -> None:
    """Minor 8: a subject records, per quantity, the inputs a person was asked for
    (`attrs.sim_asked`), and the ladder reads it per quantity as `simulate` does: the material
    asked for the stress is not asked again for the stress, and is asked for the mass."""
    asks = {"stress_mpa": ["material", 3], "bad": "material"}
    subject = EntityRead(
        id=BRACKET, kind="part", domain="mechanical", name="b", attrs={"sim_asked": asks}
    )
    lacking = _Provider(
        "beam", 1, frozenset({"stress_mpa", "mass_kg"}), lacks=MissingInputs(missing=(MATERIAL,))
    )
    context = _ladder(graph=GraphContext(entities=[subject], edges=[]), providers=(lacking,))

    stress, mass = (
        should_simulate([_near(0.9, quantity=quantity)], trigger="rule", context=context)[0]
        for quantity in ("stress_mpa", "mass_kg")
    )

    assert asked_names(subject.attrs, "stress_mpa") == ["material"]
    assert asked_names(subject.attrs, "bad") == asked_names({}, "stress_mpa") == []
    assert (stress.decision, mass.decision) == ("missing_input", "ask")


def test_a_band_climbs_only_where_a_higher_rung_computes_its_quantity() -> None:
    """Minor 5: a value inside its band can be settled above its rung only by a provider the
    ladder ranks that computes the quantity up there: the mesh check's bending above rung 1, the
    yaml's rung-2 target for the stress, and nothing above the mesh check's own rung 3."""
    assert climbs("yield_fraction", 1, CONFIG) and climbs("stress_mpa", 1, CONFIG)
    assert not climbs("yield_fraction", 3, CONFIG)
    assert not climbs("no_such_quantity", 0, CONFIG)


def test_the_pre_check_proposes_only_for_what_the_action_touches() -> None:
    """R99: before a gated real-world action, the same ladder reads the matrix's inconclusive
    results whose subject the action touches, under `real_world_action`. A result about another
    entity, or one with margin, proposes nothing."""
    beside = EntityRead(id=uuid.uuid4(), kind="part", domain="mechanical", name="plate")
    context = _ladder(graph=GraphContext(entities=[SUBJECT, beside], edges=[]))
    near_beside = RuleResult(
        status="inconclusive",
        message="near",
        subjects=(beside.id,),
        evidence={"quantity": "stress_mpa", "value": 90.0, "limit": 100.0, "rung": 1},
    )

    [proposal] = precheck_real_world_action(
        [_near(0.85, rung=1), near_beside], {BRACKET}, context=context
    )

    assert (proposal.trigger, proposal.subject_id, proposal.rung) == (
        "real_world_action",
        BRACKET,
        3,
    )
    assert precheck_real_world_action([_near(0.85, rung=1)], {beside.id}, context=context) == []
    assert precheck_real_world_action([_near(0.15, rung=1)], {BRACKET}, context=context) == []


def test_a_proposal_reads_as_one_line_on_a_card() -> None:
    """The line a gated action's card shows (R99): whose quantity, why, and the run the ladder
    proposes first, with what it still needs or that its target is not connected. The subject's
    name is shown on one line."""
    near = [_near(0.85, rung=1)]
    [run] = should_simulate(near, trigger="real_world_action", context=_ladder())
    lacking = _Provider("mesh", 3, lacks=MissingInputs(missing=(MATERIAL, LOAD)))
    [ask] = should_simulate(
        near, trigger="real_world_action", context=_ladder(providers=(lacking,))
    )
    [remote] = should_simulate(
        near, trigger="real_world_action", context=_ladder(providers=(REMOTE,))
    )
    unqueued = _Provider("mesh_interference", 3)  # a run Solus does, with no job queue to take it
    [waiting] = should_simulate(
        near, trigger="real_world_action", context=_ladder(providers=(unqueued,))
    )

    assert proposal_line(waiting, "bracket").endswith(
        "with mesh_interference first; no job queue runs it here"
    )
    assert proposal_line(run, "bracket") == (
        "bracket: stress_mpa is at 85% of its limit at rung 1: inside its 0.8 band. "
        "Simulate stress_mpa at rung 3 with mesh first"
    )
    assert proposal_line(ask, "brac\nket").startswith("brac ket: stress_mpa is at 85%")
    assert proposal_line(ask, "bracket").endswith("with mesh first; it needs material, load")
    assert proposal_line(remote, "bracket").endswith(
        "with remote_fea first; that target is not connected"
    )
