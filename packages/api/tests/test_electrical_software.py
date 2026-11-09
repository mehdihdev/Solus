"""SOLUSDEV-321 P3-T2 — the electrical → software cell: `pin_capability_vs_firmware_use` judges an
analog read against the capabilities the brain's library definition gives that pin; the cell's
other rules wait for their facts."""

from __future__ import annotations

import uuid
from typing import Any, Final

from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers.cells import UnstatedFactRule
from solus_api.checkers.cells.electrical_software import (
    CELL,
    PINS,
    RULES,
    PinCapabilityVsFirmwareUse,
)
from solus_api.checkers.fact_store import FactStore
from solus_api.checkers.interface import Severity
from solus_api.checkers.matrix_rule import EdgeRef
from solus_api.fingerprint.contract import FingerprintOutput
from solus_api.hardware.library import PartDefinition, PinSpec

_PARTS: Final = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])
RULE: Final = PinCapabilityVsFirmwareUse()
BRAIN: Final = EntityRead(id=uuid.uuid4(), kind="hardware_brain", domain="electrical", name="mcu")
SENSOR: Final = EntityRead(id=uuid.uuid4(), kind="part", domain="electrical", name="pot")
CODE: Final = EntityRead(id=uuid.uuid4(), kind="code_file", domain="code", name="fw.ino")
DEFINED: Final = FactStore(
    definitions={
        BRAIN.id: PartDefinition(
            id="fake-brain",
            name="fake brain",
            category="controllers",
            pins=[
                PinSpec(name="A0", capabilities=["adc", "gpio"]),
                PinSpec(name="D2", capabilities=["gpio", "pwm"]),
            ],
        )
    }
)


def _edge(
    src: EntityRead, dst: EntityRead, relation: str, *, confidence: float = 1.0, **attrs: Any
) -> EdgeRead:
    return EdgeRead(
        src_id=src.id,
        dst_id=dst.id,
        relation_type=relation,
        domain_pair=f"{src.domain}<->{dst.domain}",
        confidence=confidence,
        attrs=attrs,
    )


def _reading(pin: str, *, confidence: float = 1.0) -> GraphContext:
    """The code reads `pin`; the schematic wires the sensor to the brain on it."""
    wired = _edge(BRAIN, SENSOR, "wires", pins={str(BRAIN.id): [pin], str(SENSOR.id): ["1"]})
    read = _edge(CODE, SENSOR, "reads", confidence=confidence, pin=pin)
    return GraphContext(entities=[BRAIN, SENSOR, CODE], edges=[read, wired])


def test_an_analog_read_on_a_pin_without_an_adc_fails() -> None:
    (result,) = RULE.results(_reading("D2"), DEFINED)

    assert (result.status, result.severity) == ("fail", Severity.CRITICAL)
    assert result.subjects == (BRAIN.id, CODE.id)
    assert result.edge_ref == EdgeRef(CODE.id, SENSOR.id, "reads")
    assert result.evidence == {"pin": "D2", "capabilities": ["gpio", "pwm"]}
    (warning,) = RULE.check(_reading("D2"), _PARTS, facts=DEFINED)
    assert warning.checker_id == "pin_capability_vs_firmware_use"


def test_an_analog_read_on_an_adc_pin_passes() -> None:
    (result,) = RULE.results(_reading("A0"), DEFINED)
    assert result.status == "pass" and result.subjects == (BRAIN.id, CODE.id)


def test_a_pin_the_brains_definition_does_not_state_is_unknown() -> None:
    (result,) = RULE.results(_reading("A5"), DEFINED)
    assert (result.status, result.missing, result.subjects) == (
        "unknown_input",
        PINS,
        (BRAIN.id, CODE.id),
    )


def test_no_definitions_or_no_confirmed_read_cannot_be_judged() -> None:
    (guard,) = RULE.results(_reading("A0"), FactStore())
    assert guard.missing is not None and guard.missing.name == "definitions"
    (gap,) = RULE.results(_reading("A0", confidence=0.55), DEFINED)
    assert gap.missing is not None and gap.missing.name == "reads"


def test_the_cells_other_rules_wait_for_their_facts() -> None:
    waiting = [rule for rule in RULES if isinstance(rule, UnstatedFactRule)]
    assert [rule.rule_id for rule in waiting] == [
        "bus_bandwidth_caps_loop_rate",
        "brownout_is_uncommanded_reboot",
    ]
    for rule in waiting:
        (only,) = rule.results(_reading("A0"), FactStore())
        assert (only.status, only.missing) == ("unknown_input", rule.needs.facts[0])
    assert all(rule.matrix_cell is CELL for rule in RULES)
