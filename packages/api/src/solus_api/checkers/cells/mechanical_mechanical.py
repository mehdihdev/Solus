"""SOLUSDEV-321 P3-T2, P4-T5 — mechanical → mechanical: one part against another: a stack of
tolerances, a collision over a joint's range, a bracket's strength, a fastener's engagement.

`tolerance_stack` and `fastener_engagement` wait for a fact no source states yet. Each answers
`unknown_input` naming its fact and where a person states it, and it judges once a source exists.

Since P4-T5 the two that waited for P4's simulation ladder judge what a simulation expects of a
part (`SimulatedQuantityRule`, through `FactStore.expected`), one verdict per simulated part:

- `bracket_strength_at_joint` reads `yield_fraction`, the simulated stress over the yield it is
  judged against (rung 1's bending formula, which the rung-3 mesh check reuses). It fails (WARNING)
  at or past the yield, is `inconclusive` inside the ladder's own band below it
  (`FactStore.simulation.band`), so the ladder climbs from it, and passes with margin;
- `interference_through_range` reads `interference_mm`, the depth the rung-3 mesh check found over
  the poses it sampled: any depth fails (WARNING), and none passes.

With no part simulated, each answers ONE `unknown_input` naming the quantity to simulate. P3-T4's
manufacturing rules (`checkers/manufacturing_rules.py`: `wall_too_thin`) follow the spec's four in
`RULES` (R76).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from solus_contracts.relations import MatrixCell

from solus_api.checkers.cells import Simulated, SimulatedQuantityRule, UnstatedFactRule
from solus_api.checkers.interface import Severity
from solus_api.checkers.manufacturing_rules import MANUFACTURING_RULES
from solus_api.checkers.matrix_rule import MatrixRule, RuleResult
from solus_api.livebench.findings.rules.rule_base import FactNeed, Needs, amount, shown
from solus_api.simulation.sim_ladder import climbs

if TYPE_CHECKING:
    from solus_api.checkers.checker_results import RuleStatus
    from solus_api.checkers.fact_store import FactStore

CELL: Final = MatrixCell.MECHANICAL_MECHANICAL
#: The simulated quantities the P4 rules judge, spelled as the providers compute them (P4-T2/T3).
YIELD_FRACTION: Final = "yield_fraction"
STRESS: Final = "stress_mpa"
INTERFERENCE: Final = "interference_mm"
#: What each is judged against: the whole of the yield, and no depth at all.
YIELD: Final = 1.0
NO_DEPTH: Final = 0.0
STRESS_NEED: Final = FactNeed(
    name=YIELD_FRACTION,
    set_in=(
        "a simulation of the bracket's stress: simulate yield_fraction on the part (rung 1 reads "
        "its `material`, `section` and `load`)"
    ),
)
INTERFERENCE_NEED: Final = FactNeed(
    name=INTERFERENCE,
    set_in=(
        "a mesh interference simulation of the part: simulate interference_mm on it (rung 3 reads "
        "its `mesh`, and `meshes` and `poses` for a joint's range)"
    ),
)


class ToleranceStack(UnstatedFactRule):
    """The tolerances of mated parts stacked up against the fit they need."""

    rule_id = "tolerance_stack"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="tolerances",
                set_in="the CAD connector's feature tolerances on the mated parts",
            ),
        )
    )


class InterferenceThroughRange(SimulatedQuantityRule):
    """Two bodies of a part that collide somewhere in a joint's range of motion (the mesh check)."""

    rule_id = "interference_through_range"
    matrix_cell = CELL
    quantities = (INTERFERENCE,)
    to_simulate = INTERFERENCE_NEED

    def judge(self, found: Simulated, facts: FactStore) -> RuleResult:
        depth = found.expected.value
        evidence = self.band_evidence(found, NO_DEPTH)
        name = shown(found.subject.name)
        if depth > NO_DEPTH:
            return RuleResult(
                status="fail",
                severity=Severity.WARNING,
                message=(
                    f"{name}'s bodies interpenetrate by up to {amount(depth, found.expected.unit)} "
                    f"in the poses simulated at {found.at}"
                ),
                subjects=(found.subject.id,),
                evidence=evidence,
            )
        return RuleResult(
            status="pass",
            message=f"{name}'s bodies clear each other in the poses simulated at {found.at}",
            subjects=(found.subject.id,),
            evidence=evidence,
        )


class BracketStrengthAtJoint(SimulatedQuantityRule):
    """A bracket's simulated stress at a joint against its material's yield (P4 rung 1, or the
    mesh check's reuse of its formula)."""

    rule_id = "bracket_strength_at_joint"
    matrix_cell = CELL
    quantities = (YIELD_FRACTION, STRESS)
    to_simulate = STRESS_NEED

    def judge(self, found: Simulated, facts: FactStore) -> RuleResult:
        fraction, band = found.expected.value, facts.simulation.band(YIELD_FRACTION)
        evidence = self.band_evidence(found, YIELD)
        stress = facts.expected(found.subject.id, STRESS)
        stated = ""
        if stress is not None:
            evidence[STRESS] = stress.value
            stated = f" ({amount(stress.value, stress.unit)})"
        said = (
            f"{shown(found.subject.name)}'s simulated stress is {fraction:.0%} of its "
            f"yield{stated} at {found.at}"
        )
        status: RuleStatus
        if fraction >= YIELD:
            status, severity, why = "fail", Severity.WARNING, "at or past its yield"
        elif fraction >= band:
            # Minor 5: a higher rung is promised only where one computes the fraction.
            higher = climbs(YIELD_FRACTION, found.rung or 0, facts.simulation)
            settles = (
                "which a higher rung settles"
                if higher
                else "unresolved: no higher rung computes it"
            )
            status, severity, why = (
                "inconclusive",
                Severity.INFO,
                f"inside the ladder's {band:g} band, {settles}",
            )
        else:
            status, severity, why = "pass", Severity.INFO, "with margin under it"
        return RuleResult(
            status=status,
            severity=severity,
            message=f"{said}: {why}",
            subjects=(found.subject.id,),
            evidence=evidence,
        )


class FastenerEngagement(UnstatedFactRule):
    """How much of a fastener's thread the tapped depth engages."""

    rule_id = "fastener_engagement"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="thread_engagement_mm",
                set_in="the CAD connector's fastener length and tapped depth on the mate",
            ),
        )
    )


RULES: Final[tuple[MatrixRule, ...]] = (
    ToleranceStack(),
    InterferenceThroughRange(),
    BracketStrengthAtJoint(),
    FastenerEngagement(),
    *MANUFACTURING_RULES,
)
