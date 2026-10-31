"""SOLUSDEV-321 P3-T2 — electrical → mechanical: what a circuit does to the structure around
it, such as heat into a mount, torque into a load, a harness through a joint or mass into the
centre of mass.

No source states these facts yet. Each rule answers `unknown_input` naming its fact and where a
person states it, and it judges once a source exists.
"""

from __future__ import annotations

from typing import Final

from solus_contracts.relations import MatrixCell, RelationType

from solus_api.checkers.cells import UnstatedFactRule
from solus_api.checkers.matrix_rule import MatrixRule
from solus_api.livebench.findings.rules.rule_base import FactNeed, Needs

CELL: Final = MatrixCell.ELECTRICAL_MECHANICAL


class DriverHeatIntoMount(UnstatedFactRule):
    """The heat a driver dissipates into the structure that `mounts` it."""

    rule_id = "driver_heat_into_mount"
    matrix_cell = CELL
    needs = Needs(
        relations=(RelationType.MOUNTS.value,),
        facts=(
            FactNeed(
                name="dissipation_w",
                set_in="the driver's `specs.dissipation_w` in its library definition",
            ),
        ),
    )


class TorqueConstantTimesCurrentVsLoad(UnstatedFactRule):
    """A motor's torque constant times its current against the load the mechanism puts on it."""

    rule_id = "torque_constant_times_current_vs_load"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="torque_constant_nm_per_a",
                set_in="the motor's `specs.torque_constant_nm_per_a` in its library definition",
            ),
        )
    )


class HarnessThroughJoint(UnstatedFactRule):
    """A cable harness routed through a joint's range of motion."""

    rule_id = "harness_through_joint"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="harness_route",
                set_in="the CAD connector's harness route across the assembly's joints",
            ),
        )
    )


class BoardMassIntoCom(UnstatedFactRule):
    """A board's mass, placed in the assembly, moving the robot's centre of mass."""

    rule_id = "board_mass_into_com"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="board_mass_g",
                set_in=(
                    "the board's `mass_g` in its library definition, placed by the CAD "
                    "connector's assembly"
                ),
            ),
        )
    )


RULES: Final[tuple[MatrixRule, ...]] = (
    DriverHeatIntoMount(),
    TorqueConstantTimesCurrentVsLoad(),
    HarnessThroughJoint(),
    BoardMassIntoCom(),
)
