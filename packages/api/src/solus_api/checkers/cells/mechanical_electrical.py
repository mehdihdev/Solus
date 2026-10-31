"""SOLUSDEV-321 P3-T2 — mechanical → electrical: what the mechanism asks of the circuit: current
for a load torque, derating inside an enclosure, voltage lost along a cable, room around a
connector.

No source states these facts yet. Each rule answers `unknown_input` naming its fact and where a
person states it, and it judges once a source exists.
"""

from __future__ import annotations

from typing import Final

from solus_contracts.relations import MatrixCell

from solus_api.checkers.cells import UnstatedFactRule
from solus_api.checkers.matrix_rule import MatrixRule
from solus_api.livebench.findings.rules.rule_base import FactNeed, Needs

CELL: Final = MatrixCell.MECHANICAL_ELECTRICAL


class LoadTorqueCurrentIntoSizing(UnstatedFactRule):
    """The current a joint's load torque draws against the motor and driver sized for it."""

    rule_id = "load_torque_current_into_sizing"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="load_torque_nm",
                set_in=(
                    "a `.solus` constraints/rules entry with `quantity: load_torque_nm`, or a P4 "
                    "simulation result"
                ),
            ),
        )
    )


class EnclosureThermalDerating(UnstatedFactRule):
    """The parts inside an enclosure derated for its internal temperature. It flags (never fails)
    once the temperature is stated."""

    rule_id = "enclosure_thermal_derating"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="enclosure_ambient_c",
                set_in="a `.solus` constraints/rules entry with `quantity: enclosure_ambient_c`",
            ),
        )
    )


class CableLengthVoltageDrop(UnstatedFactRule):
    """The voltage a cable's length and gauge drop between a supply and its load."""

    rule_id = "cable_length_voltage_drop"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="cable_length_m",
                set_in="the harness cable's `specs.length_m` and gauge in its library definition",
            ),
        )
    )


class ConnectorClearance(UnstatedFactRule):
    """The room around a connector against the keep-out its mating plug needs."""

    rule_id = "connector_clearance"
    matrix_cell = CELL
    needs = Needs(
        facts=(
            FactNeed(
                name="connector_keepout_mm",
                set_in="the connector's `specs.keepout_mm` in its library definition",
            ),
        )
    )


RULES: Final[tuple[MatrixRule, ...]] = (
    LoadTorqueCurrentIntoSizing(),
    EnclosureThermalDerating(),
    CableLengthVoltageDrop(),
    ConnectorClearance(),
)
