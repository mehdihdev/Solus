"""SOLUSDEV-321 P3-T2 — the software → mechanical cell: `commanded_range_vs_joint_limit` judges the
commanded fact on a `commands` edge against the part's position limit, comparing in one unit only;
the cell's other rules wait for their facts."""

from __future__ import annotations

import uuid
from typing import Any, Final

from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers.cells import UnstatedFactRule
from solus_api.checkers.cells.software_mechanical import (
    CELL,
    COMMANDED,
    RULES,
    CommandedRangeVsJointLimit,
)
from solus_api.checkers.fact_store import FactStore
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import EdgeRef
from solus_api.fingerprint.contract import FingerprintOutput
from solus_api.hardware.config import (
    FieldProvenance,
    HardwareConfig,
    PartConfig,
    PartLimits,
    ProvenanceRecord,
    TelemetryChannel,
)
from solus_api.hardware.library import PartDefinition, PartLimitsSpec
from solus_api.livebench.findings.rules.rule_base import fact_need
from solus_api.livebench.scene.part_bindings import JointRange

_PARTS: Final = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])
RULE: Final = CommandedRangeVsJointLimit()
ROBOT: Final = uuid.uuid4()
CODE: Final = EntityRead(id=uuid.uuid4(), kind="code_file", domain="code", name="fw.ino")
SERVO: Final = EntityRead(id=uuid.uuid4(), kind="part", domain="electrical", name="servo 3")
GOAL: Final = {
    "min": 200.0,
    "max": 200.0,
    "unit": "deg",
    "min_ref": "fw.ino:13",
    "max_ref": "fw.ino:13",
}
LIMITS: Final[dict[str, float | int]] = {"position_min": -150, "position_max": 150}


def _commands(**commanded: Any) -> EdgeRead:
    return EdgeRead(
        src_id=CODE.id,
        dst_id=SERVO.id,
        relation_type="commands",
        domain_pair="code<->electrical",
        confidence=0.8,
        attrs={"commanded": commanded} if commanded else {},
    )


def _graph(*edges: EdgeRead) -> GraphContext:
    return GraphContext(entities=[CODE, SERVO], edges=list(edges))


def _store(
    limits: dict[str, float | int] | None, unit: str | None = "deg", **facts: Any
) -> FactStore:
    """The servo in its robot's runtime config: its `position` channel (in `unit`) and limits."""
    channels = [TelemetryChannel(name="servo3.position", unit=unit)] if unit else []
    stated = PartLimits(values=limits) if limits is not None else None
    config = HardwareConfig(
        robot_entity_id=ROBOT,
        parts={str(SERVO.id): PartConfig(telemetry=channels, limits=stated)},
        provenance={"parts": ProvenanceRecord(by=FieldProvenance.USER)},
    )
    return FactStore(runtime_configs={ROBOT: config}, **facts)


def test_a_goal_past_the_position_limit_fails() -> None:
    graph, store = _graph(_commands(**GOAL)), _store(LIMITS)

    (result,) = RULE.results(graph, store)

    assert (result.status, result.severity) == ("fail", Severity.WARNING)
    assert result.subjects == (CODE.id, SERVO.id)
    assert result.edge_ref == EdgeRef(CODE.id, SERVO.id, "commands")
    assert result.evidence == {
        "commanded_min": 200.0,
        "commanded_max": 200.0,
        "unit": "deg",
        "code_ref": "fw.ino:13",
        "limit_lo": -150.0,
        "limit_hi": 150.0,
        "limit_unit": "deg",
        "limit_source": "config",
    }
    (warning,) = RULE.check(graph, _PARTS, facts=store)
    assert warning.entity_ids == (CODE.id, SERVO.id) and "200 deg" in warning.message


def test_a_goal_inside_the_limit_passes() -> None:
    inside = {**GOAL, "min": -90.0, "max": 120.0}
    (result,) = RULE.results(_graph(_commands(**inside)), _store(LIMITS))
    assert result.status == "pass" and result.edge_ref == EdgeRef(CODE.id, SERVO.id, "commands")


def test_the_finding_names_the_line_of_the_end_that_breaches() -> None:
    """M1: `code_ref` is the min's line when only the low end is past the limit, else the max's."""
    span = {**GOAL, "min": -170.0, "max": 90.0, "min_ref": "fw.ino:23", "max_ref": "fw.ino:24"}

    (low,) = RULE.results(_graph(_commands(**span)), _store(LIMITS))
    (both,) = RULE.results(_graph(_commands(**{**span, "max": 170.0})), _store(LIMITS))

    assert (low.status, low.evidence["code_ref"]) == ("fail", "fw.ino:23")
    assert "at fw.ino:23" in low.message
    assert (both.status, both.evidence["code_ref"]) == ("fail", "fw.ino:24")


def test_a_unit_gap_is_inconclusive_and_names_both_units() -> None:
    raw = {**GOAL, "min": 2048.0, "max": 2048.0, "unit": "raw"}
    (result,) = RULE.results(_graph(_commands(**raw)), _store(LIMITS))
    assert result.status == "inconclusive"
    assert "raw" in result.message and "deg" in result.message
    # bare limits with no position channel state no unit: nothing to compare a goal with
    (unstated,) = RULE.results(_graph(_commands(**GOAL)), _store(LIMITS, unit=None))
    assert unstated.status == "inconclusive" and unstated.evidence["limit_unit"] is None


def test_the_limit_comes_from_the_config_then_the_definition_then_the_scene() -> None:
    suffixed = _store({"position_min_deg": -120, "position_max_deg": 120}, unit=None)
    (from_keys,) = RULE.results(_graph(_commands(**GOAL)), suffixed)
    assert (from_keys.status, from_keys.evidence["limit_hi"]) == ("fail", 120.0)

    definition = PartDefinition(
        id="fake-servo",
        name="fake servo",
        category="actuators",
        limits=PartLimitsSpec(position_min=-90, position_max=90),
    )
    defined = _store(None, definitions={SERVO.id: definition})
    (from_definition,) = RULE.results(_graph(_commands(**GOAL)), defined)
    assert (from_definition.status, from_definition.evidence["limit_source"]) == (
        "fail",
        "definition",
    )

    joint = JointRange(uuid.uuid4(), "joint_3", -2.6, 2.6, "rad")
    scened = _store(None, scene_joints={SERVO.id: joint})
    (from_scene,) = RULE.results(_graph(_commands(**GOAL)), scened)
    assert (from_scene.status, from_scene.evidence["limit_source"]) == ("inconclusive", "scene")


def test_no_limit_no_goal_no_config_or_no_commands_edge_cannot_be_judged() -> None:
    (unknown,) = RULE.results(_graph(_commands(**GOAL)), _store(None))
    assert (unknown.status, unknown.missing) == ("unknown_input", fact_need("position", "limit"))
    assert unknown.subjects == (CODE.id, SERVO.id)
    # M5: a commands edge with no literal goal (none written, or cleared to None) says where one is
    cleared = _commands().model_copy(update={"attrs": {"commanded": None}})
    for edge in (_commands(), cleared):
        (no_goal,) = RULE.results(_graph(edge), _store(LIMITS))
        assert (no_goal.status, no_goal.missing) == ("unknown_input", COMMANDED)
        assert no_goal.edge_ref == EdgeRef(CODE.id, SERVO.id, "commands")
    (guard,) = RULE.results(_graph(_commands(**GOAL)), FactStore())
    assert guard.missing is not None and guard.missing.name == "runtime_configs"
    (gap,) = RULE.results(_graph(), _store(LIMITS))
    assert gap.missing is not None and gap.missing.name == "commands"


def test_an_angular_rate_goal_call_commands_no_position() -> None:
    """M108: a goal call that names an angular rate (`omega`, `rad/s`, `rpm`) states no position,
    so this cell never compares a speed with the joint's range. A plain position goal still does."""
    import json

    from solus_api.graph.inference.firmware_edges import GOAL_CALL, goal_literal

    def row(name: str) -> dict[str, Any]:
        detail = json.dumps({"kind": GOAL_CALL, "value": 3.0})
        return {"provenance": [{"entity_ref": name, "source_ref": "fw.ino:9", "detail": detail}]}

    for rate in ("setOmega", "set_rad_per_s", "set_goal_rad_s", "write_rpm"):
        assert goal_literal(row(rate)) is None, rate
    assert goal_literal(row("setGoalPositionDeg")) is not None
    # Round 2, new issue 7: plural radians and a camelCase `rpM` are positions, not rates.
    for position in ("setGoalRads", "setWarpModePosition"):
        assert goal_literal(row(position)) is not None, position


def test_the_cells_other_rules_wait_for_their_facts() -> None:
    waiting = [rule for rule in RULES if isinstance(rule, UnstatedFactRule)]
    assert [rule.rule_id for rule in waiting] == [
        "speed_accel_vs_structural_load",
        "duty_cycle_vs_thermal_rating",
        "gains_vs_resonance",
    ]
    for rule in waiting:
        (only,) = rule.results(_graph(), FactStore())
        assert (only.status, only.missing) == ("unknown_input", rule.needs.facts[0])
    assert all(rule.matrix_cell is CELL for rule in RULES)
