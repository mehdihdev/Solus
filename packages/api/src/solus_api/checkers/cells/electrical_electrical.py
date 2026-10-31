"""SOLUSDEV-321 P3-T2 — electrical → electrical: one circuit's demand against another's supply,
placement or plane.

- `power_budget` reads each rail's `power:<rail>` line of the `constraints/budgets` CONFIG.
  - It never recomputes the line; `services/budgets.py` does that after each sync.
  - It judges each line on the supplies that the rail's confirmed `powers` edges name.
  - Over their rating fails, within it passes, and a draw or rating nobody states is
    inconclusive.
  - Its fail stays on the edge: `budget_exceeded` is the finding (R60).
- `proximity_pair` (P3-T4) judges a disturbing part against a sensitive one, between the board's
  footprint positions and the clearance a `constraints/rules` entry states. A switcher disturbs
  precision analog, and a heat source disturbs a capacitor.
- `trace_width_vs_current` and `return_path_over_split` (flags only) wait for facts nothing
  states yet.
"""

from __future__ import annotations

import heapq
import logging
import math
from itertools import islice
from typing import TYPE_CHECKING, Final, NamedTuple

from solus_contracts.relations import MatrixCell, RelationType

from solus_api.checkers.cells import (
    UnstatedFactRule,
    confirmed_edges,
    relation_gap,
    unknown_input,
)
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import MatrixRule, RuleResult
from solus_api.checkers.netlist_motifs import designator_letter
from solus_api.graph import kinds
from solus_api.livebench.findings.rules.rule_base import FactNeed, Needs
from solus_api.services.budgets import _safe_net_name

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from uuid import UUID

    from solus_api.agent.interfaces import EntityRead, GraphContext
    from solus_api.checkers.checker_results import RuleStatus
    from solus_api.checkers.fact_store import BoardPosition, FactStore
    from solus_api.services.solus_payloads import BudgetLine, BudgetStatus

CELL: Final = MatrixCell.ELECTRICAL_ELECTRICAL
POWERS: Final = RelationType.POWERS.value
WIRES: Final = RelationType.WIRES.value
BUDGETS: Final = FactNeed(
    name="budgets",
    set_in=(
        "the `.solus` constraints/budgets CONFIG (recomputed after each sync from the `powers` "
        "edges)"
    ),
)
#: A rail's budget line is named `power:<the net's safe name>` (`services/budgets.py`).
POWER_LINE: Final = "power:"
_STATUS: Final[dict[BudgetStatus, RuleStatus]] = {
    "exceeded": "fail",
    "ok": "pass",
    "unknown": "inconclusive",
}
POSITIONS: Final = FactNeed(
    name="pcb_positions",
    set_in="the board-layout connector's footprint positions (P3-T4)",
)
CLEARANCE: Final = FactNeed(
    name="proximity_clearance_mm",
    set_in="a `.solus` constraints/rules entry with `quantity: proximity_clearance_mm`",
)
#: The behaviour classes (`hardware/library.py:BehaviourClass`) that disturb precision analog.
NOISY: Final = frozenset({"switcher", "magnetic", "high_speed"})
HOT: Final = "heat_source"
ANALOG: Final = "precision_analog"
#: The role a settled motif gives each of its parts, and the words the evidence uses for it.
MOTIF_ROLES: Final[dict[str, tuple[str, str]]] = {
    "h_bridge": ("noisy", "switcher"),
    "divider_adc": ("analog", "precision analog"),
    "rc_on_input": ("analog", "precision analog"),
}
#: Who disturbs whom: (aggressor role, victim role).
_PAIRED: Final = (("noisy", "analog"), ("hot", "capacitor"))
#: At most this many pairs are judged a run, nearest first. ponytail: a board with more
#: aggressor-victim pairs keeps the nearest; a spatial index is the upgrade.
MAX_PAIRS: Final = 64
#: At most this many parts hold one role a run (R79), in the run's entity order, logged when it
#: binds. It bounds the distances measured to MAX_ROLE_PARTS² for each pairing.
MAX_ROLE_PARTS: Final = 256

logger = logging.getLogger("solus.checkers.cells.electrical_electrical")


class PowerBudget(MatrixRule):
    """Each rail's budget line as the budgets CONFIG states it, judged on the rail's supplies."""

    rule_id = "power_budget"
    matrix_cell = CELL
    needs = Needs(relations=(POWERS,), facts=(BUDGETS,))
    #: R60: `budget_exceeded` (services/budgets.py) is the one finding for a rail breach.
    raises_findings = False

    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        gap = relation_gap(self, graph)
        if gap or facts.budgets is None:
            return gap
        supplies = _supplies_by_rail(graph)
        return [
            _judged(line, supplies.get(line.name.removeprefix(POWER_LINE), ()))
            for line in facts.budgets.budgets
            if line.name.startswith(POWER_LINE)
        ]


def _supplies_by_rail(graph: GraphContext) -> dict[str, tuple[UUID, ...]]:
    """Each rail's supplies, keyed by the name its budget line carries: the sources of the
    confirmed `powers` edges whose `attrs.nets` name the rail. ponytail: this maps through
    `_safe_net_name`, the one spelling `services/budgets.py` writes. It becomes public when a
    second reader needs it."""
    rails: dict[str, set[UUID]] = {}
    for edge in confirmed_edges(graph, POWERS):
        nets = edge.attrs.get("nets")
        for net in nets if isinstance(nets, list) else []:
            if isinstance(net, str) and net:
                rails.setdefault(_safe_net_name(net), set()).add(edge.src_id)
    return {rail: tuple(sorted(ids, key=str)) for rail, ids in rails.items()}


def _judged(line: BudgetLine, supplies: tuple[UUID, ...]) -> RuleResult:
    status = _STATUS[line.status]
    rail = line.name.removeprefix(POWER_LINE)
    evidence = {"budget": line.model_dump(mode="json")}
    if status == "fail":
        message = (
            f"rail {rail} draws {_figure(line.current)} {line.unit} against its supplies' "
            f"{_figure(line.limit)} {line.unit} rating (the budgets CONFIG)"
        )
        return RuleResult(
            status=status,
            severity=Severity.CRITICAL,
            message=message,
            subjects=supplies,
            evidence=evidence,
        )
    message = (
        f"rail {rail} is within its supplies' rating (the budgets CONFIG)"
        if status == "pass"
        else f"rail {rail}: the budgets CONFIG knows no draw or no rating for every member"
    )
    return RuleResult(status=status, message=message, subjects=supplies, evidence=evidence)


def _figure(value: float | None) -> str:
    return f"{value:g}" if value is not None else "an unstated"


class ProximityPair(MatrixRule):
    """A switcher next to precision analog, or a heat source next to a capacitor, closer than the
    clearance a `constraints/rules` entry states.

    - **Roles.** A part's role is its behaviour class (its attrs, else its library definition's),
      or its settled motif: an H-bridge's parts switch, and a divider's or RC input's parts are
      precision analog. A capacitor is a part whose designator says so.
    - **Distance.** It runs between footprint positions, in the board's units (millimetres for the
      board connector). Positions on two boards of one project are compared as one board: a
      ceiling until a position names its board.
    """

    rule_id = "proximity_pair"
    matrix_cell = CELL
    needs = Needs(facts=(POSITIONS, CLEARANCE))

    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        clearance = facts.proximity_clearance_mm
        if clearance is None:
            return [unknown_input(self, CLEARANCE)]
        # R79: the pairs are generated lazily from capped roles, and only the nearest
        # `MAX_PAIRS` are held, so a crowded board costs at most MAX_ROLE_PARTS² distances a
        # pairing, never a list of every pair.
        roles = _capped(_roles(graph, facts))
        pairs = heapq.nsmallest(MAX_PAIRS, _pairs(roles, facts.pcb_positions))
        return [_proximity(pair, clearance) for pair in pairs]


class _Pair(NamedTuple):
    """One aggressor and one victim, how far apart they sit, and the words for their roles."""

    distance: float
    aggressor: UUID
    victim: UUID
    aggressor_role: str
    victim_role: str


def _roles(graph: GraphContext, facts: FactStore) -> dict[str, dict[UUID, str]]:
    """The positioned components holding each role (`noisy`, `hot`, `analog`, `capacitor`),
    each mapped to the words its evidence uses."""
    found: dict[str, dict[UUID, str]] = {
        role: {} for role in ("noisy", "hot", "analog", "capacitor")
    }
    for entity in graph.entities:
        if entity.kind != kinds.COMPONENT or entity.id not in facts.pcb_positions:
            continue
        behaviour = _behaviour(entity, facts)
        if behaviour in NOISY:
            found["noisy"][entity.id] = str(behaviour).replace("_", " ")
        elif behaviour == HOT:
            found["hot"][entity.id] = "heat source"
        elif behaviour == ANALOG:
            found["analog"][entity.id] = "precision analog"
        if designator_letter(entity.name) == "C":
            found["capacitor"][entity.id] = "capacitor"
    for motif in facts.motifs:
        role = MOTIF_ROLES.get(motif.kind) if motif.settled else None
        for member in motif.members if role is not None else ():
            if role is not None and member in facts.pcb_positions:
                found[role[0]].setdefault(member, role[1])
    return found


def _behaviour(entity: EntityRead, facts: FactStore) -> str | None:
    """The part's behaviour class: its attrs', else its library definition's."""
    stated = entity.attrs.get("behaviour_class")
    if isinstance(stated, str):
        return stated
    definition = facts.definitions.get(entity.id)
    return definition.behaviour_class if definition is not None else None


def _capped(roles: dict[str, dict[UUID, str]]) -> dict[str, dict[UUID, str]]:
    """Each role's first `MAX_ROLE_PARTS` parts, in the run's entity order (R79), with a log
    line for each role the cap binds."""
    for role, parts in roles.items():
        if len(parts) > MAX_ROLE_PARTS:
            logger.warning(
                "proximity_pair: %d parts hold the %s role; judging the first %d",
                len(parts),
                role,
                MAX_ROLE_PARTS,
            )
    return {role: dict(islice(parts.items(), MAX_ROLE_PARTS)) for role, parts in roles.items()}


def _pairs(
    roles: dict[str, dict[UUID, str]], positions: Mapping[UUID, BoardPosition]
) -> Iterator[_Pair]:
    """Every (aggressor, victim) of the capped roles, one at a time: never a list (R79)."""
    for ag, vi in _PAIRED:
        for a, aggressor_role in roles[ag].items():
            for v, victim_role in roles[vi].items():
                if a != v:
                    distance = math.dist(_xy(positions[a]), _xy(positions[v]))
                    yield _Pair(distance, a, v, aggressor_role, victim_role)


def _xy(position: BoardPosition) -> tuple[float, float]:
    return position.x, position.y


def _proximity(pair: _Pair, clearance: float) -> RuleResult:
    subjects = (pair.aggressor, pair.victim)
    distance = round(pair.distance, 3)
    evidence = {
        "distance_mm": distance,
        "clearance_mm": clearance,
        "aggressor": pair.aggressor_role,
        "victim": pair.victim_role,
    }
    where = f"the {pair.aggressor_role} sits {distance:g} mm from the {pair.victim_role}"
    if pair.distance >= clearance:
        message = f"{where}, outside the {clearance:g} mm clearance the rules state"
        return RuleResult(status="pass", message=message, subjects=subjects, evidence=evidence)
    return RuleResult(
        status="fail",
        severity=Severity.WARNING,
        message=f"{where}, inside the {clearance:g} mm clearance the rules state",
        subjects=subjects,
        evidence=evidence,
    )


class TraceWidthVsCurrent(UnstatedFactRule):
    """A net's track width against the current it carries."""

    rule_id = "trace_width_vs_current"
    matrix_cell = CELL
    needs = Needs(
        relations=(WIRES,),
        facts=(
            FactNeed(
                name="trace_width_mm",
                set_in="the board-layout connector's track widths on the net",
            ),
        ),
    )


class ReturnPathOverSplit(UnstatedFactRule):
    """A signal routed over a split in its return plane: it flags (never fails) once the planes
    are stated."""

    rule_id = "return_path_over_split"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="plane_splits",
                set_in="the board-layout connector's ground and power planes",
            ),
        )
    )


RULES: Final[tuple[MatrixRule, ...]] = (
    PowerBudget(),
    ProximityPair(),
    TraceWidthVsCurrent(),
    ReturnPathOverSplit(),
)
