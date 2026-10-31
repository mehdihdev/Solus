"""SOLUSDEV-321 P3-T4 — manufacturing rules: whether a part can be made as drawn by the process the
project's style constraints intend for it.

These rules are MatrixRule-shaped and live in the mechanical → mechanical cell beside the spec's
four (R76: `checkers/cells/mechanical_mechanical.py` registers them).

**Process intent** (`process_intent`) is what the style constraints intend for a part:

- **The process.** It is the part's own `attrs.process` when its CAD states one (a feature of the
  part). Otherwise it is the process the applying `constraints/style` entry's words name, from a
  closed list (`PROCESSES`).
- **The minimum wall.** It is that entry's quantified bound, `quantity: min_wall_thickness_mm`
  (`>=` or `>`, unit mm).
- An entry scoped to the part (`scope_entity_ids`) wins over a project-wide one.
- A project-wide entry naming a process other than the part's does not apply, and one naming the
  part's process wins over a neutral one.
- A part that states no process takes a project-wide minimum only when every applying entry
  states the same one (m3). When they differ, its minimum depends on its process, so the intent is
  `undecided` and the rule asks for the process.

**`wall_too_thin`** fires only with thickness facts:

- with no part stating `wall_thickness_mm` (nothing writes it yet), it answers ONE `unknown_input`
  naming it, never one per part;
- a part that states one but has no applying minimum is that part's `unknown_input` naming
  `min_wall_thickness_mm`, or naming `process` when its intent is undecided;
- otherwise it fails (WARNING) under the minimum and passes at or above it.

The rules are pure: graph and facts in, results out. The style entries are the fact store's
(`FactStore.style`). This is shared code, so it names a process and never a vendor or a tool.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, NamedTuple

from solus_contracts.relations import MatrixCell

from solus_api.checkers.attributes import attr_nonneg_float
from solus_api.checkers.fact_store import lower_bound_mm
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import MatrixRule, RuleResult
from solus_api.graph import kinds
from solus_api.livebench.findings.rules.rule_base import FactNeed

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from solus_api.agent.interfaces import EntityRead, GraphContext
    from solus_api.checkers.fact_store import FactStore, StyleEntry

WALL_THICKNESS: Final = FactNeed(
    name="wall_thickness_mm",
    set_in="the part's `wall_thickness_mm`, its thinnest wall; no CAD connector computes it yet",
)
MIN_WALL: Final = FactNeed(
    name="min_wall_thickness_mm",
    set_in=(
        "a `.solus` constraints/style entry with `quantity: min_wall_thickness_mm` (unit mm, "
        "`>=`), scoped to the part or to the whole project"
    ),
)
#: m3: asked for when project-wide minima differ by process and the part states none.
PROCESS: Final = FactNeed(
    name="process",
    set_in=(
        "a `.solus` constraints/style entry scoped to the part (`scope_entity_ids`) that names its "
        "process and its `min_wall_thickness_mm`"
    ),
)
#: The processes a part or a style entry may name, by the words that say them.
PROCESSES: Final[dict[str, re.Pattern[str]]] = {
    "fdm": re.compile(r"\bfdm\b|\bfff\b|3d[- ]?print", re.IGNORECASE),
    "sla": re.compile(r"\bsla\b|\bresin\b", re.IGNORECASE),
    "sls": re.compile(r"\bsls\b|\bmjf\b", re.IGNORECASE),
    "cnc": re.compile(r"\bcnc\b|machin|\bmill", re.IGNORECASE),
    "sheet_metal": re.compile(r"sheet[- _]?metal", re.IGNORECASE),
    "injection_molding": re.compile(r"injection|\bmou?ld(?:ed|ing)\b", re.IGNORECASE),
    "laser_cut": re.compile(r"laser", re.IGNORECASE),
}


class ProcessIntent(NamedTuple):
    """What the style constraints intend for a part: its process, that process's minimum wall in
    mm, and the entry that states it (each None when nothing does)."""

    process: str | None
    min_wall_mm: float | None
    entry_id: UUID | None
    #: m3: the part states no process, and the applying project-wide minima differ.
    undecided: bool = False


def process_intent(part: EntityRead, style: Sequence[StyleEntry]) -> ProcessIntent:
    """The module docstring says how the process and its minimum wall are read."""
    stated = _process_in(part.attrs.get("process"))
    bounds = [(entry, wall) for entry in style if (wall := _min_wall(entry)) is not None]
    scoped = [(entry, wall) for entry, wall in bounds if part.id in wall[1]]
    wide = [
        (entry, wall)
        for entry, wall in bounds
        if not wall[1] and _applies(_process_in(entry.text), stated)
    ]
    if not (scoped or wide):
        return ProcessIntent(stated, None, None)
    if not scoped and stated is None and len({limit for _, (limit, _) in wide}) > 1:
        return ProcessIntent(None, None, None, undecided=True)  # its process decides: ask for it
    named = [(entry, wall) for entry, wall in wide if _process_in(entry.text) == stated]
    entry, (limit, _) = (scoped or (named if stated else []) or wide)[0]
    return ProcessIntent(stated or _process_in(entry.text), limit, entry.entry_id)


def _process_in(text: object) -> str | None:
    """The first process whose words `text` holds; None for none, or for no text."""
    if not isinstance(text, str):
        return None
    return next((name for name, words in PROCESSES.items() if words.search(text)), None)


def _min_wall(entry: StyleEntry) -> tuple[float, tuple[UUID, ...]] | None:
    """The entry's minimum wall in mm and its scope, when it states one as a lower bound."""
    limit = lower_bound_mm(entry.meta, MIN_WALL.name)
    if limit is None or entry.meta is None:
        return None
    return limit, tuple(entry.meta.scope_entity_ids)


def _applies(named: str | None, stated: str | None) -> bool:
    """A project-wide entry applies unless it names a process other than the part's."""
    return named is None or stated is None or named == stated


class ManufacturingRule(MatrixRule):
    """A rule about whether a part can be made as drawn: mechanical → mechanical (R76)."""

    matrix_cell = MatrixCell.MECHANICAL_MECHANICAL


class WallTooThin(ManufacturingRule):
    """A part's thinnest wall against the minimum its process's style constraint states. Its
    facts are named by `evaluate`, not `needs`: the thickness is per part, the minimum per
    process."""

    rule_id = "wall_too_thin"

    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        walls = [
            (part, wall)
            for part in graph.entities
            if part.kind == kinds.PART and (wall := _wall_of(part)) is not None
        ]
        if not walls:
            return [_unknown(self, WALL_THICKNESS)]
        return [self._judge(part, wall, process_intent(part, facts.style)) for part, wall in walls]

    def _judge(self, part: EntityRead, wall: float, intent: ProcessIntent) -> RuleResult:
        if intent.undecided:
            return _unknown(self, PROCESS, part.id)
        if intent.min_wall_mm is None:
            return _unknown(self, MIN_WALL, part.id)
        evidence = {
            "wall_thickness_mm": wall,
            "min_wall_thickness_mm": intent.min_wall_mm,
            "process": intent.process,
            "style_entry_id": str(intent.entry_id),
        }
        process = intent.process or "style"
        if wall >= intent.min_wall_mm:
            message = (
                f"{part.name}'s {wall:g} mm wall meets the {intent.min_wall_mm:g} mm minimum its "
                f"{process} constraint states"
            )
            return RuleResult(
                status="pass", message=message, subjects=(part.id,), evidence=evidence
            )
        return RuleResult(
            status="fail",
            severity=Severity.WARNING,
            message=(
                f"{part.name} has a {wall:g} mm wall, under the {intent.min_wall_mm:g} mm minimum "
                f"its {process} constraint states"
            ),
            subjects=(part.id,),
            evidence=evidence,
        )


def _wall_of(part: EntityRead) -> float | None:
    wall = attr_nonneg_float(part, WALL_THICKNESS.name)
    return wall if wall is not None and wall > 0 else None


def _unknown(rule: MatrixRule, need: FactNeed, *subjects: UUID) -> RuleResult:
    """The cells' one wording of an unmet fact. It is imported here because the cells import this
    module: they register its rules."""
    from solus_api.checkers.cells import unknown_input

    return unknown_input(rule, need, *subjects)


#: Every manufacturing rule, as the mechanical → mechanical cell registers them.
MANUFACTURING_RULES: Final[tuple[MatrixRule, ...]] = (WallTooThin(),)
