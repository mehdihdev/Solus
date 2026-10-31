"""SOLUSDEV-321 P3-T2 — the mechanical → software cell: `joint_limit_vs_code_constant` judges the
code constant a confirmed `limits` edge records for a joint (`matches[].value`) against that
joint's range as the FactStore holds it (`scene_joints`, bound to its part by the scene import),
in one unit only; the cell's other rules wait for their facts."""

from __future__ import annotations

import uuid
from typing import Any, Final

from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers.cells import UnstatedFactRule
from solus_api.checkers.cells.mechanical_software import (
    CELL,
    JOINT_RANGE,
    RULES,
    JointLimitVsCodeConstant,
)
from solus_api.checkers.fact_store import FactStore
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import EdgeRef
from solus_api.fingerprint.contract import FingerprintOutput
from solus_api.livebench.scene.part_bindings import JointRange

_PARTS: Final = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])
RULE: Final = JointLimitVsCodeConstant()
SCENE: Final = EntityRead(
    id=uuid.uuid4(), kind="bench_scene_model", domain="simulation", name="arm"
)
CODE: Final = EntityRead(id=uuid.uuid4(), kind="code_file", domain="code", name="arm.ino")
#: The scene's joints as the FactStore holds them, each bound to a part by the scene import.
FACTS: Final = FactStore(
    scene_joints={
        uuid.uuid4(): JointRange(SCENE.id, "elbow", -2.0, 2.0, "rad"),
        uuid.uuid4(): JointRange(SCENE.id, "slide", 0.0, 0.3, "m"),
    }
)


def _match(joint: str, constant: str, value: float | None = None, unit: str = "") -> dict[str, Any]:
    found: dict[str, Any] = {"joint": joint, "constant": constant, "line": 12}
    return found if value is None else {**found, "value": value, "unit": unit}


def _graph(*matches: dict[str, Any], confidence: float = 1.0) -> GraphContext:
    """The scene and the code, joined by one `limits` edge listing `matches`."""
    first = matches[0] if matches else {"joint": "elbow", "constant": "?", "line": 1}
    limits = EdgeRead(
        src_id=SCENE.id,
        dst_id=CODE.id,
        relation_type="limits",
        domain_pair="code<->simulation",
        confidence=confidence,
        attrs={**{k: first[k] for k in ("joint", "constant", "line")}, "matches": list(matches)},
    )
    return GraphContext(entities=[SCENE, CODE], edges=[limits])


def test_a_constant_past_the_joints_range_fails() -> None:
    graph = _graph(_match("elbow", "SERVO_ELBOW_MAX_RAD", 2.5, "rad"))

    (result,) = RULE.results(graph, FACTS)

    assert (result.status, result.severity) == ("fail", Severity.WARNING)
    assert result.subjects == (SCENE.id, CODE.id)
    assert result.edge_ref == EdgeRef(SCENE.id, CODE.id, "limits")
    assert result.evidence == {
        "joint": "elbow",
        "constant": "SERVO_ELBOW_MAX_RAD",
        "line": 12,
        "value": 2.5,
        "unit": "rad",
        "lower": -2.0,
        "upper": 2.0,
        "joint_unit": "rad",
    }
    (warning,) = RULE.check(graph, _PARTS, FACTS)
    assert warning.checker_id == "joint_limit_vs_code_constant"


def test_a_constant_inside_the_joints_range_passes() -> None:
    (result,) = RULE.results(_graph(_match("elbow", "ELBOW_MIN_RAD", -1.5, "rad")), FACTS)
    assert result.status == "pass"


def test_a_unit_gap_is_inconclusive_and_names_both_units() -> None:
    deg, raw = (
        _match("elbow", "ELBOW_MAX_DEG", 170.0, "deg"),
        _match("slide", "SLIDE_MAX", 9, "raw"),
    )

    in_deg, in_raw = RULE.results(_graph(deg, raw), FACTS)

    assert in_deg.status == "inconclusive" and "deg" in in_deg.message and "rad" in in_deg.message
    assert in_raw.status == "inconclusive" and in_raw.evidence["joint_unit"] == "m"


def test_a_constant_without_a_number_is_skipped_and_a_joint_the_scene_lacks_is_unknown() -> None:
    """M2: a match with no number (a pin constant; a rate or an effort, which the inference records
    none for) states no position limit, so it gets no answer and no hint nobody can act on."""
    pin, stranger = _match("elbow", "ELBOW_PIN"), _match("wrist", "WRIST_MAX_RAD", 1.0, "rad")

    (no_joint,) = RULE.results(_graph(pin, stranger), FACTS)

    assert (no_joint.missing, no_joint.subjects) == (JOINT_RANGE, (SCENE.id, CODE.id))


def test_the_range_is_the_scene_joint_the_fact_store_holds_for_the_edges_scene() -> None:
    """M7: the joint reader is the FactStore's, the one the envelopes share. Another scene's joint
    of that name, a reversed range, or no joint at all is no range."""
    graph = _graph(_match("elbow", "SERVO_ELBOW_MAX_RAD", 2.5, "rad"))
    elsewhere = JointRange(uuid.uuid4(), "elbow", -2.0, 2.0, "rad")
    backwards = JointRange(SCENE.id, "elbow", 2.0, -2.0, "rad")

    for facts in (
        FactStore(scene_joints={uuid.uuid4(): elsewhere}),
        FactStore(),
        FactStore(scene_joints={uuid.uuid4(): backwards}),
    ):
        (unknown,) = RULE.results(graph, facts)
        assert (unknown.status, unknown.missing) == ("unknown_input", JOINT_RANGE)


def test_a_candidate_limits_edge_is_a_relation_gap() -> None:
    graph = _graph(_match("elbow", "SERVO_ELBOW_MAX_RAD", 2.5, "rad"), confidence=0.5)
    (gap,) = RULE.results(graph, FactStore())
    assert gap.missing is not None and gap.missing.name == "limits"


def test_the_cells_other_rules_wait_for_their_facts() -> None:
    waiting = [rule for rule in RULES if isinstance(rule, UnstatedFactRule)]
    assert [rule.rule_id for rule in waiting] == [
        "link_length_vs_kinematic_model",
        "mass_inertia_into_gains",
        "gear_ratio_backlash_into_scaling",
        "sensor_mount_offset_into_calibration",
    ]
    for rule in waiting:
        (only,) = rule.results(_graph(), FactStore())
        assert (only.status, only.missing) == ("unknown_input", rule.needs.facts[0])
    assert all(rule.matrix_cell is CELL for rule in RULES)
