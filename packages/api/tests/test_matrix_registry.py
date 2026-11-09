"""SOLUSDEV-321 P3-T2 — the matrix registry.

- The spec's 36 rules sit in their nine cells, each with the needs it declares.
- P3-T4's extras follow in their cells: the manufacturing rules (R76).
- On empty facts each rule answers one `unknown_input` naming its field and where a person
  sets it.
- The parametrised ids are the rule table: `cell|rule_id|field`.
"""

from __future__ import annotations

from typing import Final, cast

import pytest
from solus_api.agent.interfaces import GraphContext
from solus_api.checkers.cells import (
    MATRIX_RULES,
    RELATION_SOURCES,
    RULES_BY_ID,
    Simulated,
    SimulatedQuantityRule,
    UnstatedFactRule,
    fix_owner,
    relation_need,
)
from solus_api.checkers.fact_store import FACT_NAMES, FactStore
from solus_api.checkers.matrix_rule import MatrixRule, RuleResult
from solus_api.fingerprint.contract import FingerprintOutput
from solus_api.livebench.findings.rules.rule_base import FactNeed
from solus_contracts.relations import MatrixCell, RelationType

#: The spec's first rules, cell by cell and in its order (the P3-T2 brief's table).
TABLE: Final[dict[MatrixCell, tuple[str, ...]]] = {
    MatrixCell.SOFTWARE_SOFTWARE: (
        "package_version_conflict",
        "module_contract_mismatch",
        "loop_rate_latency",
        "config_protocol_mismatch",
    ),
    MatrixCell.SOFTWARE_ELECTRICAL: (
        "commanded_current_vs_driver_supply",
        "sample_rate_vs_adc_settling",
        "pin_in_code_vs_wiring",
        "pwm_frequency_vs_driver",
    ),
    MatrixCell.SOFTWARE_MECHANICAL: (
        "commanded_range_vs_joint_limit",
        "speed_accel_vs_structural_load",
        "duty_cycle_vs_thermal_rating",
        "gains_vs_resonance",
    ),
    MatrixCell.ELECTRICAL_SOFTWARE: (
        "pin_capability_vs_firmware_use",
        "bus_bandwidth_caps_loop_rate",
        "brownout_is_uncommanded_reboot",
    ),
    MatrixCell.ELECTRICAL_ELECTRICAL: (
        "power_budget",
        "proximity_pair",
        "trace_width_vs_current",
        "return_path_over_split",
    ),
    MatrixCell.ELECTRICAL_MECHANICAL: (
        "driver_heat_into_mount",
        "torque_constant_times_current_vs_load",
        "harness_through_joint",
        "board_mass_into_com",
    ),
    MatrixCell.MECHANICAL_SOFTWARE: (
        "joint_limit_vs_code_constant",
        "link_length_vs_kinematic_model",
        "mass_inertia_into_gains",
        "gear_ratio_backlash_into_scaling",
        "sensor_mount_offset_into_calibration",
    ),
    MatrixCell.MECHANICAL_ELECTRICAL: (
        "load_torque_current_into_sizing",
        "enclosure_thermal_derating",
        "cable_length_voltage_drop",
        "connector_clearance",
    ),
    MatrixCell.MECHANICAL_MECHANICAL: (
        "tolerance_stack",
        "interference_through_range",
        "bracket_strength_at_joint",
        "fastener_engagement",
    ),
}
#: The rules registered beside the spec's 36, by cell: P3-T4's manufacturing rules (R76).
EXTRAS: Final[dict[MatrixCell, tuple[str, ...]]] = {
    MatrixCell.MECHANICAL_MECHANICAL: ("wall_too_thin",),
}
#: The rules that judge today: P3-T2's six, then P3-T4's three (R72, R76) on the facts the board,
#: the schematic and the style constraints now state, then P4-T5's two on what a simulation
#: expects of a part, then P6's one on the software reader's module interfaces. The other 25
#: wait for a fact no source states yet.
RUNNABLE: Final = frozenset(
    {
        "module_contract_mismatch",
        "package_version_conflict",
        "pin_in_code_vs_wiring",
        "commanded_range_vs_joint_limit",
        "pin_capability_vs_firmware_use",
        "power_budget",
        "joint_limit_vs_code_constant",
        "sample_rate_vs_adc_settling",
        "proximity_pair",
        "wall_too_thin",
        "interference_through_range",
        "bracket_strength_at_joint",
    }
)
_EMPTY: Final = GraphContext(entities=[], edges=[])
_PARTS: Final = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])
RULES: Final = tuple(RULES_BY_ID.values())


def _table_row(rule: MatrixRule) -> str:
    """`cell|rule_id|field`: what the rule names when it has no facts."""
    found = rule.results(_EMPTY, FactStore())
    field = found[0].missing.name if len(found) == 1 and found[0].missing else "?"
    return f"{rule.matrix_cell.value}|{rule.rule_id}|{field}"


def test_all_36_rules_registered_with_cell_and_needs() -> None:
    """The spec's 36, by id and in each cell's order, then each cell's extras (R76)."""
    registered = {
        cell: tuple(rule.rule_id for rule in rules) for cell, rules in MATRIX_RULES.items()
    }
    assert registered == {cell: ids + EXTRAS.get(cell, ()) for cell, ids in TABLE.items()}
    assert list(MATRIX_RULES) == list(MatrixCell)
    assert sum(len(rule_ids) for rule_ids in TABLE.values()) == 36
    assert len(RULES_BY_ID) == 36 + sum(len(rule_ids) for rule_ids in EXTRAS.values())
    relations = {relation.value for relation in RelationType}
    for cell, rules in MATRIX_RULES.items():
        for rule in rules:
            assert isinstance(rule, MatrixRule) and rule.matrix_cell is cell
            assert rule.checker_id == rule.rule_id and RULES_BY_ID[rule.rule_id] is rule
            assert set(rule.needs.relations) <= relations
            assert all(need.name and need.set_in for need in rule.needs.facts)
            names = {need.name for need in rule.needs.facts}
            if rule.rule_id in RUNNABLE:
                assert not isinstance(rule, UnstatedFactRule) and names <= FACT_NAMES
            else:
                # one of its facts is no `FactStore` field: nothing holds it until a source does
                assert isinstance(rule, UnstatedFactRule) and names - FACT_NAMES


class _SimulatedLoopRate(SimulatedQuantityRule):
    """A stand-in rule judging a simulated quantity in a cell whose destination is software."""

    rule_id = "simulated_loop_rate"
    matrix_cell = MatrixCell.ELECTRICAL_SOFTWARE
    quantities = ("loop_rate_hz",)
    to_simulate = FactNeed(name="loop_rate_hz", set_in="a simulation")

    def judge(self, found: Simulated, facts: FactStore) -> RuleResult:
        raise AssertionError("never judged here")


def test_a_failing_simulated_quantity_is_fixed_in_its_rules_destination_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M141: nothing writes `attrs.owning_domain`, so the backward loop reads the domain that owns
    a failing simulated quantity's fix off the cell of the rule that judges it: its destination
    side, as the graph names it (`software` is `code`). A quantity no rule judges has none."""
    judged = ("yield_fraction", "stress_mpa", "interference_mm", "mass_kg", "loop_rate_hz")
    assert [fix_owner(quantity) for quantity in judged] == [
        "mechanical",
        "mechanical",
        "mechanical",
        None,
        None,
    ]
    registry = cast(dict[str, MatrixRule], RULES_BY_ID)
    monkeypatch.setitem(registry, _SimulatedLoopRate.rule_id, _SimulatedLoopRate())
    assert fix_owner("loop_rate_hz") == "code"


def test_every_relation_a_rule_reads_says_where_it_comes_from() -> None:
    """M9: each relation a rule declares names the place a person brings it from, so
    `relation_need` answers for it the day its rule reports the gap."""
    declared = {relation for rule in RULES for relation in rule.needs.relations}

    assert declared <= set(RELATION_SOURCES)
    assert all(relation_need(r).set_in == RELATION_SOURCES[r] for r in declared)


@pytest.mark.parametrize("rule", RULES, ids=[_table_row(rule) for rule in RULES])
def test_each_rule_emits_one_unknown_input_naming_its_field_and_set_in_on_empty_facts(
    rule: MatrixRule,
) -> None:
    (only,) = rule.results(_EMPTY, FactStore())

    assert only.status == "unknown_input" and only.missing is not None
    assert only.missing.name and only.missing.set_in
    assert only.evidence == {"missing": only.missing.model_dump()}
    assert only.message == (
        f"could not check {rule.rule_id}: {only.missing.name} unknown; "
        f"set it in {only.missing.set_in}"
    )
    assert rule.check(_EMPTY, _PARTS) == []
