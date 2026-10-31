"""SOLUSDEV-321 P3-T2 — software → mechanical: what the code commands a mechanism to do against
what the mechanism can take.

- `commanded_range_vs_joint_limit` reads the literal goal range a `commands` edge carries
  (`attrs.commanded`, written by `graph/inference/firmware_edges.py`). It compares that range
  with the part's position limit, taken from the first source that states one:
  - its config: the unit-suffixed `position_<min|max>_<unit>` pair, else the bare pair;
  - its library definition's limit;
  - the scene joint bound to it.

  A bare key is in the unit of the part's position channel, as the envelopes read it. The rule
  compares only within one unit; a goal in another unit is `inconclusive`, naming both units. A
  fail names the code line of the end that breaches (`code_ref`). A `commands` edge that states
  no literal goal is `unknown_input`, naming `commanded`.
- `speed_accel_vs_structural_load`, `duty_cycle_vs_thermal_rating` and `gains_vs_resonance`
  (which flags only once a resonance is stated) wait for facts nothing states yet.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final, NamedTuple

from solus_contracts.relations import MatrixCell, RelationType

from solus_api.checkers.cells import UnstatedFactRule, confirmed_edges, relation_gap, unknown_input
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import EdgeRef, MatrixRule, RuleResult
from solus_api.livebench.findings.envelopes import canonical_unit
from solus_api.livebench.findings.rules.rule_base import FactNeed, Needs, fact_need
from solus_api.livebench.scene.part_bindings import channel_for_quantity, finite_number

if TYPE_CHECKING:
    from uuid import UUID

    from solus_api.agent.interfaces import EdgeRead, GraphContext
    from solus_api.checkers.fact_store import FactStore

CELL: Final = MatrixCell.SOFTWARE_MECHANICAL
COMMANDS: Final = RelationType.COMMANDS.value
RUNTIME_CONFIGS: Final = FactNeed(
    name="runtime_configs",
    set_in="the robot's v2 hardware config: `bus_map` and each part's `component.limits.values`",
)
#: The envelopes' own hint for a position limit (`rule_base.fact_need`).
LIMIT: Final = fact_need("position", "limit")
COMMANDED: Final = FactNeed(
    name="commanded",
    set_in=(
        "a literal goal in the firmware call that commands the part (`write*` / `setGoal*` / "
        "`setTarget*(address, value)`), accepted from its hardware review row"
    ),
)
_SUFFIXED: Final = re.compile(r"^position_(min|max)_(\S+)$")


class Commanded(NamedTuple):
    """A `commands` edge's commanded fact: the literal goal range, its unit and the code line of
    each end."""

    lo: float
    hi: float
    unit: str
    lo_ref: str
    hi_ref: str


class PositionLimit(NamedTuple):
    """The part's position limit, the unit it is stated in (None when the source states none) and
    the source that states it."""

    lo: float | None
    hi: float | None
    unit: str | None
    source: str


class CommandedRangeVsJointLimit(MatrixRule):
    """A literal goal the code commands against the part's position limit."""

    rule_id = "commanded_range_vs_joint_limit"
    matrix_cell = CELL
    needs = Needs(relations=(COMMANDS,), facts=(RUNTIME_CONFIGS,))

    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        gap = relation_gap(self, graph)
        if gap:
            return gap
        return [self._judge(edge, facts) for edge in confirmed_edges(graph, COMMANDS)]

    def _judge(self, edge: EdgeRead, facts: FactStore) -> RuleResult:
        subjects, ref = (edge.src_id, edge.dst_id), EdgeRef.of(edge)
        goal = commanded_of(edge)
        if goal is None:
            return unknown_input(self, COMMANDED, *subjects, edge_ref=ref)
        limit = position_limit(facts, edge.dst_id)
        if limit is None:
            return unknown_input(self, LIMIT, *subjects, edge_ref=ref)
        return _compared(goal, limit, subjects, ref)


def _compared(
    goal: Commanded, limit: PositionLimit, subjects: tuple[UUID, UUID], ref: EdgeRef
) -> RuleResult:
    """The goal range against the limit, in one unit only. `code_ref` is the line of the end that
    breaches: the min's when only the low end is past the limit, else the max's."""
    same_unit = canonical_unit(goal.unit) == limit.unit
    high = same_unit and limit.hi is not None and goal.hi > limit.hi
    low = same_unit and limit.lo is not None and goal.lo < limit.lo
    code_ref = goal.lo_ref if low and not high else goal.hi_ref
    evidence = {
        "commanded_min": goal.lo,
        "commanded_max": goal.hi,
        "unit": goal.unit,
        "code_ref": code_ref,
        "limit_lo": limit.lo,
        "limit_hi": limit.hi,
        "limit_unit": limit.unit,
        "limit_source": limit.source,
    }
    said = _said(goal.lo, goal.hi, goal.unit)
    if not same_unit:
        message = (
            f"the code commands {said} at {code_ref}, and the part's position limit is in "
            f"{limit.unit or 'no stated unit'}: the two do not compare"
        )
        return RuleResult(
            status="inconclusive",
            message=message,
            subjects=subjects,
            edge_ref=ref,
            evidence=evidence,
        )
    bounds = _said(limit.lo, limit.hi, limit.unit)
    if not (high or low):
        message = f"the code commands {said}, inside the part's {bounds} position limit"
        return RuleResult(
            status="pass", message=message, subjects=subjects, edge_ref=ref, evidence=evidence
        )
    return RuleResult(
        status="fail",
        severity=Severity.WARNING,
        message=(
            f"the code commands {said} at {code_ref}, past the part's {bounds} position limit "
            f"(from its {limit.source})"
        ),
        subjects=subjects,
        edge_ref=ref,
        evidence=evidence,
    )


def commanded_of(edge: EdgeRead) -> Commanded | None:
    """The commanded fact a `commands` edge carries. None when the edge states none, or when what
    it states does not read: attrs are never trusted."""
    raw = edge.attrs.get("commanded")
    if not isinstance(raw, Mapping):
        return None
    lo, hi = finite_number(raw.get("min")), finite_number(raw.get("max"))
    unit, lo_ref, hi_ref = raw.get("unit"), raw.get("min_ref"), raw.get("max_ref")
    if lo is None or hi is None or lo > hi:
        return None
    if not (isinstance(unit, str) and isinstance(lo_ref, str) and isinstance(hi_ref, str)):
        return None
    return Commanded(lo, hi, unit, lo_ref, hi_ref)


def position_limit(facts: FactStore, part_id: UUID) -> PositionLimit | None:
    """The part's position limit from the first source that states one: its config, then its
    library definition, then the scene joint bound to it. A bare key is in the unit of the
    part's `<role>.position` channel, as the envelopes read it."""
    config = facts.part_config(part_id)
    channel = channel_for_quantity(config.telemetry, "position") if config is not None else None
    channel_unit = canonical_unit(channel.unit) if channel is not None else None
    values = config.limits.values if config is not None and config.limits is not None else {}
    definition = facts.definitions.get(part_id)
    spec = definition.limits if definition is not None else None
    joint = facts.scene_joints.get(part_id)
    found = (
        _suffixed(values, channel_unit),
        _bounds(values.get("position_min"), values.get("position_max"), channel_unit, "config"),
        _bounds(spec.position_min, spec.position_max, channel_unit, "definition")
        if spec is not None
        else None,
        _bounds(joint.lower, joint.upper, canonical_unit(joint.unit), "scene")
        if joint is not None
        else None,
    )
    return next((limit for limit in found if limit is not None), None)


def _suffixed(values: Mapping[str, Any], channel_unit: str | None) -> PositionLimit | None:
    """The `position_<min|max>_<unit>` pair for one unit: the channel's unit when the keys state
    it, else the only unit they state. Several units, and nothing to say which is meant: None."""
    by_unit: dict[str, dict[str, float]] = {}
    for key, raw in values.items():
        match, number = _SUFFIXED.match(key), finite_number(raw)
        unit = canonical_unit(match[2]) if match else None
        if match and number is not None and unit is not None:
            by_unit.setdefault(unit, {})[match[1]] = number
    if channel_unit is not None and channel_unit in by_unit:
        unit = channel_unit
    elif len(by_unit) == 1:
        unit = next(iter(by_unit))
    else:
        return None
    return _bounds(by_unit[unit].get("min"), by_unit[unit].get("max"), unit, "config")


def _bounds(lo: object, hi: object, unit: str | None, source: str) -> PositionLimit | None:
    """The limit two stated edges make; None when neither is a number, or they are reversed."""
    low, high = finite_number(lo), finite_number(hi)
    if low is None and high is None:
        return None
    if low is not None and high is not None and low > high:
        return None
    return PositionLimit(low, high, unit, source)


def _said(lo: float | None, hi: float | None, unit: str | None) -> str:
    """`200 deg`, `-90 to 120 deg`, `up to 150 deg`, `from -150 deg`."""
    tail = f" {unit}" if unit else ""
    if lo is not None and hi is not None:
        return f"{lo:g}{tail}" if lo == hi else f"{lo:g} to {hi:g}{tail}"
    if hi is not None:
        return f"up to {hi:g}{tail}"
    return f"from {lo:g}{tail}"


class SpeedAccelVsStructuralLoad(UnstatedFactRule):
    """The speed and acceleration the code commands against the load the driven link can carry."""

    rule_id = "speed_accel_vs_structural_load"
    matrix_cell = CELL
    needs = Needs(
        relations=(COMMANDS,),
        facts=(
            FactNeed(
                name="structural_load_n",
                set_in=(
                    "the link's `material`, `section` and `load` attributes on the CAD "
                    "connector's part (P4 rung 1)"
                ),
            ),
        ),
    )


class DutyCycleVsThermalRating(UnstatedFactRule):
    """The duty cycle the code drives an actuator at against its continuous thermal rating."""

    rule_id = "duty_cycle_vs_thermal_rating"
    matrix_cell = CELL
    needs = Needs(
        relations=(COMMANDS,),
        facts=(
            FactNeed(
                name="duty_cycle",
                set_in=(
                    "the actuator's `limits.temp_c` in its library definition and the part's "
                    "`component.firmware.duty_cycle`"
                ),
            ),
        ),
    )


class GainsVsResonance(UnstatedFactRule):
    """The control gains against the structure's first resonance: it flags (never fails) once a
    resonance is stated."""

    rule_id = "gains_vs_resonance"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="resonance_hz",
                set_in=(
                    "a `.solus` constraints/rules entry with `quantity: resonance_hz`, or a P4 "
                    "simulation result"
                ),
            ),
        )
    )


RULES: Final[tuple[MatrixRule, ...]] = (
    CommandedRangeVsJointLimit(),
    SpeedAccelVsStructuralLoad(),
    DutyCycleVsThermalRating(),
    GainsVsResonance(),
)
