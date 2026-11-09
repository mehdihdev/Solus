"""SOLUSDEV-321 P3-T2 — software → electrical: what the code asks of a pin, an ADC or a driver,
against what the circuit gives.

- `pin_in_code_vs_wiring` compares the pin a confirmed `reads` edge names (`attrs.pin`) with the
  pins the schematic wires the part to (the far side of its `wires` edges). A pin the part is not
  wired to fails. Wiring that states no pin answers `unknown_input`.
- `sample_rate_vs_adc_settling` (P3-T4) compares how often the code samples an ADC input with the
  5·RC its net settles through.
  - The RC is the settled divider's or RC filter's on the net that the confirmed `reads` edge
    lands on (`FactStore.rc_settling_s`).
  - The rate is the code entity's `loop_rate_hz`.
  - A sample period shorter than 5·RC fails.
- `commanded_current_vs_driver_supply` and `pwm_frequency_vs_driver` wait for facts nothing
  states yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from solus_contracts.relations import MatrixCell, RelationType

from solus_api.checkers.attributes import LOOP_RATE_HZ, attr_float
from solus_api.checkers.cells import (
    UnstatedFactRule,
    confirmed_edges,
    read_pin,
    relation_gap,
    relation_need,
    unknown_input,
    wired_pins,
    wires_by_endpoint,
)
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import EdgeRef, MatrixRule, RuleResult
from solus_api.checkers.traversal import GraphView
from solus_api.livebench.findings.rules.rule_base import FactNeed, Needs

if TYPE_CHECKING:
    from uuid import UUID

    from solus_api.agent.interfaces import EdgeRead, GraphContext
    from solus_api.checkers.fact_store import FactStore, RcSettling

CELL: Final = MatrixCell.SOFTWARE_ELECTRICAL
READS: Final = RelationType.READS.value
WIRES: Final = RelationType.WIRES.value
COMMANDS: Final = RelationType.COMMANDS.value
#: The RC an ADC input settles through: `FactStore.rc_settling_s`, from the settled divider or RC
#: filter the schematic's motifs find on the input's net.
RC_SETTLING: Final = FactNeed(
    name="rc_settling_s",
    set_in=("the R and C values on the ADC input net (the schematic connector's component values)"),
)
#: How often the code samples, as its code entity states it.
LOOP_RATE: Final = FactNeed(
    name=LOOP_RATE_HZ,
    set_in=(
        "the code entity's `loop_rate_hz`, how often the firmware samples the input; no connector "
        "or route writes it yet"
    ),
)
#: An input has settled after five time constants: to within 0.7 % of its final value.
SETTLING_TAUS: Final = 5


class PinInCodeVsWiring(MatrixRule):
    """The pin the code reads against the pins the schematic wires the part to."""

    rule_id = "pin_in_code_vs_wiring"
    matrix_cell = CELL
    needs = Needs(relations=(READS, WIRES))

    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        gap = relation_gap(self, graph)
        if gap:
            return gap
        by_part = wires_by_endpoint(confirmed_edges(graph, WIRES))  # m11: once, not per read
        reads = [
            (r, pin) for r in confirmed_edges(graph, READS) if (pin := read_pin(r)) is not None
        ]
        wired = {
            part: sorted(
                {p for pins in wired_pins(part, by_part.get(part, [])).values() for p in pins}
            )
            for part in {read.dst_id for read, _ in reads}
        }
        return [self._judge(read, pin, wired[read.dst_id]) for read, pin in reads]

    def _judge(self, read: EdgeRead, pin: str, wired: list[str]) -> RuleResult:
        subjects, ref = (read.src_id, read.dst_id), EdgeRef.of(read)
        if not wired:
            return unknown_input(self, relation_need(WIRES), *subjects, edge_ref=ref)
        evidence = {"pin": pin, "wired_pins": wired}
        if pin in wired:
            message = f"the code reads pin {pin}, which the schematic wires the part to"
            return RuleResult(
                status="pass", message=message, subjects=subjects, edge_ref=ref, evidence=evidence
            )
        return RuleResult(
            status="fail",
            severity=Severity.WARNING,
            message=(
                f"the code reads pin {pin}, but the schematic wires the part to {', '.join(wired)}"
            ),
            subjects=subjects,
            edge_ref=ref,
            evidence=evidence,
        )


class CommandedCurrentVsDriverSupply(UnstatedFactRule):
    """A current the code commands against the supply its driver is rated for."""

    rule_id = "commanded_current_vs_driver_supply"
    matrix_cell = CELL
    needs = Needs(
        relations=(COMMANDS,),
        facts=(
            FactNeed(
                name="commanded_current_a",
                set_in=(
                    "the driver's `limits.current_a` in its library definition, against a "
                    "current goal in the firmware's hardware review"
                ),
            ),
        ),
    )


class SampleRateVsAdcSettling(MatrixRule):
    """How often the code samples an ADC input against the 5·RC its input net settles through.
    Each confirmed `reads` edge is judged on the input its target sits on."""

    rule_id = "sample_rate_vs_adc_settling"
    matrix_cell = CELL
    needs = Needs(relations=(READS,), facts=(RC_SETTLING,))

    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        gap = relation_gap(self, graph)
        if gap:
            return gap
        view = GraphView(graph)
        return [self._judge(read, view, facts) for read in confirmed_edges(graph, READS)]

    def _judge(self, read: EdgeRead, view: GraphView, facts: FactStore) -> RuleResult:
        subjects, ref = (read.src_id, read.dst_id), EdgeRef.of(read)
        settling = facts.rc_settling_s.get(read.dst_id)
        if settling is None:
            return unknown_input(self, RC_SETTLING, *subjects, edge_ref=ref)
        code = view.entity(read.src_id)
        rate = attr_float(code, LOOP_RATE_HZ) if code is not None else None
        if rate is None or rate <= 0:
            return unknown_input(self, LOOP_RATE, *subjects, edge_ref=ref)
        return self._compared(settling, rate, subjects, ref)

    def _compared(
        self, settling: RcSettling, rate: float, subjects: tuple[UUID, UUID], ref: EdgeRef
    ) -> RuleResult:
        settle_s, period_s = SETTLING_TAUS * settling.tau_s, 1 / rate
        evidence = {
            "r_ohm": settling.r_ohm,
            "c_f": settling.c_f,
            "tau_s": settling.tau_s,
            "settle_s": settle_s,
            "sample_period_s": period_s,
            "loop_rate_hz": rate,
            "net_id": str(settling.net_id),
        }
        if settle_s <= period_s:
            message = (
                f"the input settles in 5·RC = {_ms(settle_s)}, within the code's "
                f"{_ms(period_s)} sample period"
            )
            return RuleResult(
                status="pass", message=message, subjects=subjects, edge_ref=ref, evidence=evidence
            )
        return RuleResult(
            status="fail",
            severity=Severity.WARNING,
            message=(
                f"the code samples this input every {_ms(period_s)} ({rate:g} Hz), but its RC "
                f"settles in 5·RC = {_ms(settle_s)}: it reads the input before it has settled"
            ),
            subjects=subjects,
            edge_ref=ref,
            evidence=evidence,
        )


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:.3g} ms"


class PwmFrequencyVsDriver(UnstatedFactRule):
    """The PWM frequency the firmware sets against the most the driver accepts."""

    rule_id = "pwm_frequency_vs_driver"
    matrix_cell = CELL
    needs = Needs(
        relations=(COMMANDS,),
        facts=(
            FactNeed(
                name="pwm_frequency_hz",
                set_in=(
                    "the driver's `specs.pwm_frequency_max_hz` in its library definition and "
                    "the part's `component.firmware.pwm_frequency_hz`"
                ),
            ),
        ),
    )


RULES: Final[tuple[MatrixRule, ...]] = (
    CommandedCurrentVsDriverSupply(),
    SampleRateVsAdcSettling(),
    PinInCodeVsWiring(),
    PwmFrequencyVsDriver(),
)
