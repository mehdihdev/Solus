"""SOLUSDEV-321 P3-T4 — manufacturing rules (`checkers/manufacturing_rules.py`, R76).

**Process intent** is what the project's style constraints intend for a part. The process is the
part's own `attrs.process`, a CAD feature, or else the one the applying `constraints/style`
entry's words name. The minimum wall is that entry's quantified `min_wall_thickness_mm` bound.

**`wall_too_thin`** fires only with thickness facts:
- with no part stating `wall_thickness_mm`, it answers ONE `unknown_input` naming that fact;
- a part that states one but has no applying minimum is that part's `unknown_input`;
- otherwise a part under the minimum fails.
"""

from __future__ import annotations

import uuid
from typing import Final

from solus_api.agent.interfaces import EntityRead, GraphContext
from solus_api.checkers.fact_store import FactStore, StyleEntry
from solus_api.checkers.interface import Severity
from solus_api.checkers.manufacturing_rules import (
    MIN_WALL,
    WALL_THICKNESS,
    ProcessIntent,
    WallTooThin,
    process_intent,
)
from solus_api.fingerprint.contract import FingerprintOutput
from solus_api.services.solus_payloads import ConstraintMeta
from solus_contracts.relations import MatrixCell

_PARTS: Final = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])
RULE: Final = WallTooThin()


def _cad_part(name: str, **attrs: object) -> EntityRead:
    return EntityRead(id=uuid.uuid4(), kind="part", domain="mechanical", name=name, attrs=attrs)


def _min_wall_entry(
    text: str,
    limit: float,
    *,
    scope: tuple[uuid.UUID, ...] = (),
    comparator: str = ">=",
    unit: str = "mm",
) -> StyleEntry:
    meta = ConstraintMeta.model_validate(
        {
            "quantity": "min_wall_thickness_mm",
            "limit": limit,
            "unit": unit,
            "comparator": comparator,
            "scope_entity_ids": list(scope),
        }
    )
    return StyleEntry(uuid.uuid4(), text, meta)


def test_wall_too_thin_only_with_thickness() -> None:
    bracket = _cad_part("bracket", wall_thickness_mm=0.8)
    cover = _cad_part("cover", wall_thickness_mm=2.0)
    plate = _cad_part("plate")  # states no thickness: never judged, never an unknown of its own
    min_wall = _min_wall_entry("FDM brackets: walls of 1.2 mm or more", 1.2)

    (unstated,) = RULE.results(
        GraphContext(entities=[plate], edges=[]), FactStore(style=(min_wall,))
    )
    assert (unstated.status, unstated.missing, unstated.subjects) == (
        "unknown_input",
        WALL_THICKNESS,
        (),
    )

    (no_min,) = RULE.results(GraphContext(entities=[bracket, plate], edges=[]), FactStore())
    assert (no_min.status, no_min.missing, no_min.subjects) == (
        "unknown_input",
        MIN_WALL,
        (bracket.id,),
    )

    graph = GraphContext(entities=[bracket, cover, plate], edges=[])
    facts = FactStore(style=(min_wall,))
    results = {result.subjects: result for result in RULE.results(graph, facts)}
    thin = results[(bracket.id,)]
    assert (thin.status, thin.severity) == ("fail", Severity.WARNING)
    assert thin.evidence == {
        "wall_thickness_mm": 0.8,
        "min_wall_thickness_mm": 1.2,
        "process": "fdm",
        "style_entry_id": str(min_wall.entry_id),
    }
    assert results[(cover.id,)].status == "pass" and len(results) == 2
    (warning,) = RULE.check(graph, _PARTS, facts=facts)
    assert warning.checker_id == "wall_too_thin" and warning.entity_ids == (bracket.id,)
    assert RULE.matrix_cell is MatrixCell.MECHANICAL_MECHANICAL


def test_process_intent_from_the_part_and_the_style_constraints() -> None:
    """An entry scoped to the part wins over a project-wide one. A project-wide entry naming
    another process than the part's does not apply. A part that states no process takes the one
    the entry names. Only a lower bound in mm is a minimum wall."""
    printed = _cad_part("bracket", process="FDM")
    milled = _cad_part("mount", process="cnc")
    unstated = _cad_part("panel")
    fdm = _min_wall_entry("FDM parts: 1.2 mm walls", 1.2)
    machined = _min_wall_entry("this mount is machined: 0.5 mm", 0.5, scope=(milled.id,))
    anything = _min_wall_entry("every wall 2 mm or more", 2.0)

    assert process_intent(printed, (fdm, anything)) == ProcessIntent("fdm", 1.2, fdm.entry_id)
    assert process_intent(milled, (fdm, machined, anything)) == ProcessIntent(
        "cnc", 0.5, machined.entry_id
    )
    assert process_intent(unstated, (fdm,)) == ProcessIntent("fdm", 1.2, fdm.entry_id)
    assert process_intent(milled, (fdm,)) == ProcessIntent("cnc", None, None)
    upper = _min_wall_entry("walls under 9 mm", 9.0, comparator="<=")
    in_cm = _min_wall_entry("walls of 0.2 cm", 0.2, unit="cm")
    assert process_intent(unstated, (upper, in_cm)) == ProcessIntent(None, None, None)


def test_a_part_that_states_no_process_gets_no_guessed_minimum() -> None:
    """m3: project-wide minima for different processes (FDM 1.2 mm, CNC 0.5 mm) leave a part that
    states none undecided. Its minimum depends on its process, so the rule asks for that
    (`unknown_input` naming `process`), never the oldest entry's. One minimum applies when every
    applying entry agrees, or when the part states its process; then the entry naming that
    process wins over a neutral one."""
    from solus_api.checkers.manufacturing_rules import PROCESS

    bracket = _cad_part("bracket", wall_thickness_mm=0.8)
    fdm = _min_wall_entry("FDM parts: 1.2 mm walls", 1.2)
    cnc = _min_wall_entry("CNC parts: 0.5 mm walls", 0.5)

    (asked,) = RULE.results(GraphContext(entities=[bracket], edges=[]), FactStore(style=(fdm, cnc)))
    assert (asked.status, asked.missing, asked.subjects) == (
        "unknown_input",
        PROCESS,
        (bracket.id,),
    )
    resin = _min_wall_entry("SLA parts: 1.2 mm walls", 1.2)
    assert process_intent(bracket, (fdm, resin)).min_wall_mm == 1.2
    milled = _cad_part("mount", wall_thickness_mm=0.8, process="CNC")
    assert process_intent(milled, (fdm, cnc)) == ProcessIntent("cnc", 0.5, cnc.entry_id)
    neutral = _min_wall_entry("every wall 1.0 mm or more", 1.0)
    printed = _cad_part("cover", wall_thickness_mm=0.8, process="FDM")
    assert process_intent(printed, (neutral, fdm)) == ProcessIntent("fdm", 1.2, fdm.entry_id)
