"""SOLUSDEV-321 P3-T2 — mechanical → software: what the mechanism is, against what the code
assumes it is.

- `joint_limit_vs_code_constant` judges the code constant a confirmed `limits` edge records for a
  joint (`attrs.matches[].value`, with the unit its name states; written by
  `graph/inference/joint_limits.py`). It compares the constant with the joint's `lower` /
  `upper` in the scene model the edge starts at, as the FactStore holds it (`scene_joints`: the
  joint the scene import binds to a part; rad, or m for a prismatic joint), in one unit only:
  - a constant outside the range fails;
  - a constant in another unit is `inconclusive`;
  - a match with no number (a pin constant; a rate or an effort, which the inference records
    none for) states no position limit and is skipped.
- `link_length_vs_kinematic_model`, `mass_inertia_into_gains` (flags only),
  `gear_ratio_backlash_into_scaling` and `sensor_mount_offset_into_calibration` wait for facts
  nothing states yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

from solus_contracts.relations import MatrixCell, RelationType

from solus_api.checkers.cells import UnstatedFactRule, confirmed_edges, relation_gap, unknown_input
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import EdgeRef, MatrixRule, RuleResult
from solus_api.livebench.findings.envelopes import canonical_unit
from solus_api.livebench.findings.rules.rule_base import FactNeed, Needs
from solus_api.livebench.scene.part_bindings import finite_number

if TYPE_CHECKING:
    from solus_api.agent.interfaces import EdgeRead, GraphContext
    from solus_api.checkers.fact_store import FactStore

CELL: Final = MatrixCell.MECHANICAL_SOFTWARE
LIMITS: Final = RelationType.LIMITS.value
JOINT_RANGE: Final = FactNeed(
    name="joint_range",
    set_in=(
        "the scene model's joint `lower` / `upper`, bound to its part (the scene import's bindings)"
    ),
)


class JointLimitVsCodeConstant(MatrixRule):
    """A code constant for a joint against the joint's range in the scene model."""

    rule_id = "joint_limit_vs_code_constant"
    matrix_cell = CELL
    needs = Needs(relations=(LIMITS,))

    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        gap = relation_gap(self, graph)
        if gap:
            return gap
        return [
            self._judge(edge, match, value, facts)
            for edge in confirmed_edges(graph, LIMITS)
            for match, value in _listed(edge)
        ]

    def _judge(
        self, edge: EdgeRead, match: Mapping[str, Any], value: float, facts: FactStore
    ) -> RuleResult:
        subjects, ref = (edge.src_id, edge.dst_id), EdgeRef.of(edge)
        at = (edge.src_id, match["joint"])
        joint = next((j for j in facts.scene_joints.values() if (j.scene_id, j.joint) == at), None)
        if joint is None or joint.lower > joint.upper:
            return unknown_input(self, JOINT_RANGE, *subjects, edge_ref=ref)
        lower, upper, joint_unit = joint.lower, joint.upper, joint.unit
        unit = match.get("unit") if isinstance(match.get("unit"), str) else None
        name, said = match.get("constant"), f"{value:g} {unit or 'raw'}"
        evidence = {
            "joint": match["joint"],
            "constant": name,
            "line": match.get("line"),
            "value": value,
            "unit": unit,
            "lower": lower,
            "upper": upper,
            "joint_unit": joint_unit,
        }
        span = f"{lower:g} to {upper:g} {joint_unit}"
        if canonical_unit(unit) != joint_unit:
            message = f"{name} is {said} and joint {match['joint']} spans {span}: units differ"
            return RuleResult(
                status="inconclusive",
                message=message,
                subjects=subjects,
                edge_ref=ref,
                evidence=evidence,
            )
        if lower <= value <= upper:
            message = f"{name} is {said}, inside joint {match['joint']}'s {span} range"
            return RuleResult(
                status="pass", message=message, subjects=subjects, edge_ref=ref, evidence=evidence
            )
        return RuleResult(
            status="fail",
            severity=Severity.WARNING,
            message=(
                f"{name} is {said}, past joint {match['joint']}'s {span} range: the code allows "
                "motion the mechanism cannot make"
            ),
            subjects=subjects,
            edge_ref=ref,
            evidence=evidence,
        )


def _listed(edge: EdgeRead) -> list[tuple[Mapping[str, Any], float]]:
    """The joint/constant matches a `limits` edge lists that state a number, each with it. One
    with none (a pin constant; a rate or an effort, `NOT_A_POSITION`) states no position limit;
    anything malformed is no match."""
    matches = edge.attrs.get("matches")
    found: list[tuple[Mapping[str, Any], float]] = []
    for match in matches if isinstance(matches, list) else []:
        value = finite_number(match.get("value")) if isinstance(match, Mapping) else None
        if value is not None and isinstance(match.get("joint"), str):
            found.append((match, value))
    return found


class LinkLengthVsKinematicModel(UnstatedFactRule):
    """The links' lengths in the model against the kinematic constants in the code."""

    rule_id = "link_length_vs_kinematic_model"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="link_lengths_m",
                set_in=(
                    "the scene model's links (the scene import), against the kinematic "
                    "constants in the code"
                ),
            ),
        )
    )


class MassInertiaIntoGains(UnstatedFactRule):
    """The links' mass and inertia against the controller gains tuned for them. It flags (never
    fails) once they are stated."""

    rule_id = "mass_inertia_into_gains"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="link_inertia", set_in="the CAD connector's mass properties on each link"
            ),
        )
    )


class GearRatioBacklashIntoScaling(UnstatedFactRule):
    """A joint's gear ratio and backlash against the scaling the code applies to it."""

    rule_id = "gear_ratio_backlash_into_scaling"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="gear_backlash_deg",
                set_in=(
                    "the platform definition's `parts[].gear_ratio` and the part's "
                    "`component.calibration.values`"
                ),
            ),
        )
    )


class SensorMountOffsetIntoCalibration(UnstatedFactRule):
    """Where a sensor is mounted against the offset its calibration assumes."""

    rule_id = "sensor_mount_offset_into_calibration"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="sensor_mount_pose",
                set_in=(
                    "the sensor's mate pose from the CAD connector and its "
                    "`component.calibration.values`"
                ),
            ),
        )
    )


RULES: Final[tuple[MatrixRule, ...]] = (
    JointLimitVsCodeConstant(),
    LinkLengthVsKinematicModel(),
    MassInertiaIntoGains(),
    GearRatioBacklashIntoScaling(),
    SensorMountOffsetIntoCalibration(),
)
