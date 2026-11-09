"""SOLUSDEV-321 P3-T2 — electrical → software: what the circuit allows the code to do with a pin,
a bus or a rail.

- `pin_capability_vs_firmware_use`: an analog read (a confirmed `reads` edge naming a pin) on a
  brain pin whose library definition gives it no ADC (`pins[].capabilities`) fails. A pin the
  definition does not state is `unknown_input`. The brain is the far end of the part's `wires`
  edge that carries the read pin.
- `bus_bandwidth_caps_loop_rate` and `brownout_is_uncommanded_reboot` wait for facts nothing
  states yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from solus_contracts.relations import MatrixCell, RelationType

from solus_api.checkers.cells import (
    UnstatedFactRule,
    confirmed_edges,
    read_pin,
    relation_gap,
    unknown_input,
    wired_pins,
)
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import EdgeRef, MatrixRule, RuleResult
from solus_api.livebench.findings.rules.rule_base import FactNeed, Needs

if TYPE_CHECKING:
    from uuid import UUID

    from solus_api.agent.interfaces import EdgeRead, GraphContext
    from solus_api.checkers.fact_store import FactStore

CELL: Final = MatrixCell.ELECTRICAL_SOFTWARE
READS: Final = RelationType.READS.value
WIRES: Final = RelationType.WIRES.value
DEFINITIONS: Final = FactNeed(
    name="definitions", set_in="the brain's library definition (`pins[].capabilities`)"
)
PINS: Final = FactNeed(
    name="pins",
    set_in="the brain's library definition: `pins[].capabilities` of the pin the code reads",
)
#: The capability an analog read needs. ponytail: a `reads` edge that names a pin is an analog
#: read, because `firmware_edges` writes one only for an analog row. A digital read gets its own
#: kind when something writes one.
ANALOG_CAPABILITY: Final = "adc"


class PinCapabilityVsFirmwareUse(MatrixRule):
    """An analog read on a brain pin whose definition gives it no ADC."""

    rule_id = "pin_capability_vs_firmware_use"
    matrix_cell = CELL
    needs = Needs(relations=(READS, WIRES), facts=(DEFINITIONS,))

    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        gap = relation_gap(self, graph)
        if gap:
            return gap
        wires = confirmed_edges(graph, WIRES)
        return [
            self._judge(read, pin, brain, facts)
            for read in confirmed_edges(graph, READS)
            if (pin := read_pin(read)) is not None
            for brain, pins in wired_pins(read.dst_id, wires).items()
            if pin in pins
        ]

    def _judge(self, read: EdgeRead, pin: str, brain: UUID, facts: FactStore) -> RuleResult:
        subjects, ref = (brain, read.src_id), EdgeRef.of(read)
        definition = facts.definitions.get(brain)
        stated = (definition.pins or []) if definition is not None else []
        spec = next((item for item in stated if item.name == pin), None)
        if spec is None:
            return unknown_input(self, PINS, *subjects, edge_ref=ref)
        capabilities = list(spec.capabilities)
        evidence = {"pin": pin, "capabilities": capabilities}
        if ANALOG_CAPABILITY in capabilities:
            message = f"the code reads pin {pin} as analog, and the brain gives it an ADC"
            return RuleResult(
                status="pass", message=message, subjects=subjects, edge_ref=ref, evidence=evidence
            )
        return RuleResult(
            status="fail",
            severity=Severity.CRITICAL,
            message=(
                f"the code reads pin {pin} as analog, but the brain's definition gives it no ADC "
                f"({', '.join(capabilities) or 'no capability'})"
            ),
            subjects=subjects,
            edge_ref=ref,
            evidence=evidence,
        )


class BusBandwidthCapsLoopRate(UnstatedFactRule):
    """The bytes a control loop moves over a bus against the bus's bit rate."""

    rule_id = "bus_bandwidth_caps_loop_rate"
    matrix_cell = CELL
    needs = Needs(
        relations=(RelationType.DRIVES.value,),
        facts=(
            FactNeed(
                name="bus_bitrate_hz",
                set_in="the robot's v2 config `protocol.params.bitrate_hz`",
            ),
        ),
    )


class BrownoutIsUncommandedReboot(UnstatedFactRule):
    """A rail sag below the brain's brown-out threshold, which reads as a reboot nobody commanded
    (it ties to the live rules of P2)."""

    rule_id = "brownout_is_uncommanded_reboot"
    matrix_cell = CELL
    needs = Needs(
        relations=(RelationType.POWERS.value,),
        facts=(
            FactNeed(
                name="brownout_v",
                set_in="the brain's `limits.voltage_min_v` in its library definition",
            ),
        ),
    )


RULES: Final[tuple[MatrixRule, ...]] = (
    PinCapabilityVsFirmwareUse(),
    BusBandwidthCapsLoopRate(),
    BrownoutIsUncommandedReboot(),
)
