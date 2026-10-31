"""SOLUSDEV-321 P3-T2 — the interaction matrix's nine cells, and what their rules share.

Each cell module (`<src>_<dst>.py`) holds its cell's rules as `RULES`. A rule that cannot judge
says `unknown_input`, naming the fact it lacks and where a person states it, and never guesses:

- an unmet `needs.facts` entry is the base's answer (`MatrixRule.results`);
- an unmet `needs.relations` entry is the rule's own (`relation_gap`). An edge counts only once
  it is a fact (`confirmed_edges`), so an inferred candidate stays a proposal;
- a rule whose fact no source states yet subclasses `UnstatedFactRule`. Its `FactNeed` names no
  `FactStore` field (or one nothing writes yet), so it answers `unknown_input` until a source
  exists;
- a rule judging what a simulation expects of a part subclasses `SimulatedQuantityRule` (P4-T5):
  with no part simulated it names the quantity to simulate, and every verdict carries the band's
  evidence keys the ladder reads (R94). `fix_owner` names the domain a failing quantity's fix
  belongs to: the destination side of the cell whose rule judges it (M141).

This is shared code. It names a relation, a quantity, a definition field or a `.solus` place, and
never a vendor, a connector product or a simulator: both hygiene ratchets sweep this package.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Final, NamedTuple
from uuid import UUID

from solus_contracts.relations import CANDIDATE_THRESHOLD, MatrixCell, RelationType

from solus_api.checkers.matrix_rule import EdgeRef, MatrixRule, RuleResult
from solus_api.graph import kinds
from solus_api.livebench.findings.rules.rule_base import FactNeed
from solus_api.models import Domain

if TYPE_CHECKING:
    from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
    from solus_api.checkers.fact_store import ExpectedValue, FactStore

#: Where each relation a rule judges comes from, as a person brings it into the graph.
RELATION_SOURCES: Final[Mapping[str, str]] = {
    RelationType.COMMANDS: (
        "the hardware review: accept the firmware row that writes the part's `bus_map` address"
    ),
    RelationType.READS: (
        "the hardware review: accept the firmware's analog-read row, then confirm the inferred "
        "reads edge"
    ),
    RelationType.WIRES: "the schematic connector's netlist sync (components on a shared net)",
    RelationType.POWERS: "the schematic connector's netlist sync (a supply on a rail-named net)",
    RelationType.DRIVES: (
        "the hardware review: accept the topology row that connects the bus to the device"
    ),
    RelationType.MOUNTS: (
        "the CAD connector's assembly sync (a fastened mate between a structural part and a "
        "device), then confirm the inferred mounts edge"
    ),
    RelationType.LIMITS: (
        "the graph: confirm the inferred limits edge from the scene model to the code file that "
        "names the joint's constant"
    ),
}


def confirmed_edges(graph: GraphContext, relation: str) -> list[EdgeRead]:
    """The graph's `relation` edges that are facts, at the candidate threshold or above. A
    context built through `to_graph_context` holds no candidate; one built any other way may."""
    return [
        edge
        for edge in graph.edges
        if edge.relation_type == relation and edge.confidence >= CANDIDATE_THRESHOLD
    ]


def unknown_input(
    rule: MatrixRule, need: FactNeed, *subjects: UUID, edge_ref: EdgeRef | None = None
) -> RuleResult:
    """`rule` could not judge `subjects` (the project, without any) because `need` is not
    stated. Worded as the base words its own (`MatrixRule.results`)."""
    return RuleResult(
        status="unknown_input",
        message=f"could not check {rule.rule_id}: {need.name} unknown; set it in {need.set_in}",
        subjects=subjects,
        edge_ref=edge_ref,
        evidence={"missing": need.model_dump()},
        missing=need,
    )


def relation_need(relation: str) -> FactNeed:
    """A relation as the fact a rule lacks, and where it comes from."""
    return FactNeed(name=relation, set_in=RELATION_SOURCES[relation])


def relation_gap(rule: MatrixRule, graph: GraphContext) -> list[RuleResult]:
    """One `unknown_input` for the first of `rule.needs.relations` with no confirmed edge in the
    graph; [] when each has one."""
    missing = next((r for r in rule.needs.relations if not confirmed_edges(graph, r)), None)
    return [] if missing is None else [unknown_input(rule, relation_need(missing))]


def read_pin(edge: EdgeRead) -> str | None:
    """The pin a `reads` edge says the code reads (`attrs.pin`); None when it names none."""
    pin = edge.attrs.get("pin")
    return pin if isinstance(pin, str) and pin else None


def wired_pins(part_id: UUID, wires: list[EdgeRead]) -> dict[UUID, set[str]]:
    """Each component a `wires` edge joins `part_id` to, mapped to the pins on that
    component's side (`attrs.pins[<its id>]`, as the netlist inference writes them)."""
    found: dict[UUID, set[str]] = {}
    for edge in wires:
        if part_id not in (edge.src_id, edge.dst_id):
            continue
        far = edge.dst_id if edge.src_id == part_id else edge.src_id
        pins = edge.attrs.get("pins")
        named = pins.get(str(far)) if isinstance(pins, Mapping) else None
        found.setdefault(far, set()).update(
            str(pin) for pin in (named if isinstance(named, list) else []) if isinstance(pin, str)
        )
    return found


def wires_by_endpoint(wires: list[EdgeRead]) -> dict[UUID, list[EdgeRead]]:
    """The `wires` edges indexed by each endpoint, built once an evaluation (m11, R79). A rule
    reading many parts' wiring then hands `wired_pins` each part's own edges, never all of them.
    The index holds each edge at most twice, so it is bounded by the edges read."""
    index: dict[UUID, list[EdgeRead]] = {}
    for edge in wires:
        for end in {edge.src_id, edge.dst_id}:
            index.setdefault(end, []).append(edge)
    return index


class UnstatedFactRule(MatrixRule):
    """A rule whose fact no source states yet. One of its `needs.facts` entries names nothing a
    `FactStore` holds, so `results` answers `unknown_input` naming the first such fact and where
    a person states it. `evaluate` says the same if asked directly. The rule judges once a
    source exists."""

    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        need = next((n for n in self.needs.facts if not facts.has(n.name)), self.needs.facts[-1])
        return [unknown_input(self, need)]


class Simulated(NamedTuple):
    """What a simulation expects of one subject's quantity, and the rung of the run that says so:
    None when the graph does not hold that run."""

    subject: EntityRead
    quantity: str
    expected: ExpectedValue
    rung: int | None

    @property
    def at(self) -> str:
        """The rung, as a verdict words it."""
        return "an unrecorded rung" if self.rung is None else f"rung {self.rung}"


class SimulatedQuantityRule(MatrixRule):
    """A rule that judges what a simulation expects of a subject (P4-T5): the first of its
    `quantities`, read through `FactStore.expected`, one verdict per subject (`judge`). Its fact is
    named by `evaluate`, not `needs`, as `wall_too_thin`'s is: with no subject simulated it answers
    ONE `unknown_input` naming what to simulate (`to_simulate`). Each verdict carries the band's
    evidence keys (`band_evidence`, R94), so the ladder can climb from an `inconclusive` one. A
    failing one's fix belongs to the destination side of the rule's cell (`fix_owner`, M141)."""

    quantities: ClassVar[tuple[str, ...]]
    to_simulate: ClassVar[FactNeed]

    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        found = self.simulated(graph, facts)
        if not found:
            return [unknown_input(self, self.to_simulate)]
        return [self.judge(one, facts) for one in found]

    @abc.abstractmethod
    def judge(self, found: Simulated, facts: FactStore) -> RuleResult:
        """One simulated subject's verdict."""

    def simulated(self, graph: GraphContext, facts: FactStore) -> list[Simulated]:
        """Each entity of the graph a simulation expects the rule's quantity of, in graph order."""
        quantity = self.quantities[0]
        rungs = {
            str(entity.id): entity.attrs.get("rung")
            for entity in graph.entities
            if entity.kind == kinds.SIM_RESULT
        }
        found: list[Simulated] = []
        for entity in graph.entities:
            expected = facts.expected(entity.id, quantity)
            if expected is None:
                continue
            rung = rungs.get(expected.sim_result_id or "")
            found.append(Simulated(entity, quantity, expected, rung if type(rung) is int else None))
        return found

    @staticmethod
    def band_evidence(found: Simulated, limit: float) -> dict[str, Any]:
        """What the ladder reads off an `inconclusive` result (R94), on every verdict: the
        quantity, its value against the limit as a ceiling, its unit, the run that said so and,
        when the graph holds that run, its rung."""
        evidence: dict[str, Any] = {
            "quantity": found.quantity,
            "value": found.expected.value,
            "limit": limit,
            "comparator": "<=",
            "unit": found.expected.unit,
            "sim_result_id": found.expected.sim_result_id,
        }
        if found.rung is not None:
            evidence["rung"] = found.rung
        return evidence


# The registry. The cell modules import the helpers above, so they are imported after them.
from solus_api.checkers.cells import (  # noqa: E402
    electrical_electrical,
    electrical_mechanical,
    electrical_software,
    mechanical_electrical,
    mechanical_mechanical,
    mechanical_software,
    software_electrical,
    software_mechanical,
    software_software,
)

#: Every cell's rules, in the contracts' cell order (`MatrixCell`). Each cell holds the spec's in
#: its order, then any rule P3-T4 adds there (the manufacturing rules, R76).
MATRIX_RULES: Final[Mapping[MatrixCell, tuple[MatrixRule, ...]]] = {
    MatrixCell.SOFTWARE_SOFTWARE: software_software.RULES,
    MatrixCell.SOFTWARE_ELECTRICAL: software_electrical.RULES,
    MatrixCell.SOFTWARE_MECHANICAL: software_mechanical.RULES,
    MatrixCell.ELECTRICAL_SOFTWARE: electrical_software.RULES,
    MatrixCell.ELECTRICAL_ELECTRICAL: electrical_electrical.RULES,
    MatrixCell.ELECTRICAL_MECHANICAL: electrical_mechanical.RULES,
    MatrixCell.MECHANICAL_SOFTWARE: mechanical_software.RULES,
    MatrixCell.MECHANICAL_ELECTRICAL: mechanical_electrical.RULES,
    MatrixCell.MECHANICAL_MECHANICAL: mechanical_mechanical.RULES,
}
#: Every registered rule by its `rule_id`: the spec's 36, and the rules P3-T4 adds.
RULES_BY_ID: Final[Mapping[str, MatrixRule]] = {
    rule.rule_id: rule for rules in MATRIX_RULES.values() for rule in rules
}


def fix_owner(quantity: str) -> str | None:
    """The domain that owns the fix of a failing simulated `quantity` (M141): the destination side
    of the cell whose rule judges it, as the graph names it (the matrix's `software` is `code`).
    None when no rule judges the quantity."""
    cell = next(
        (
            rule.matrix_cell
            for rule in RULES_BY_ID.values()
            if isinstance(rule, SimulatedQuantityRule) and quantity in rule.quantities
        ),
        None,
    )
    if cell is None:
        return None
    side = cell.value.split("->")[1]
    return Domain.CODE.value if side == "software" else side
