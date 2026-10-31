"""SOLUSDEV-321 P3-T2 — the electrical → mechanical cell: none of its rules has a fact any source
states yet, so each answers `unknown_input` naming its fact and where a person states it, and
never a warning."""

from __future__ import annotations

from typing import Final

import pytest
from solus_api.agent.interfaces import GraphContext
from solus_api.checkers.cells import UnstatedFactRule
from solus_api.checkers.cells.electrical_mechanical import CELL, RULES
from solus_api.checkers.fact_store import FactStore
from solus_api.checkers.matrix_rule import MatrixRule
from solus_api.fingerprint.contract import FingerprintOutput

_EMPTY: Final = GraphContext(entities=[], edges=[])
_PARTS: Final = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])


def test_the_cell_holds_its_four_rules_in_order() -> None:
    assert [rule.rule_id for rule in RULES] == [
        "driver_heat_into_mount",
        "torque_constant_times_current_vs_load",
        "harness_through_joint",
        "board_mass_into_com",
    ]


@pytest.mark.parametrize("rule", RULES, ids=[rule.rule_id for rule in RULES])
def test_each_rule_waits_for_its_fact(rule: MatrixRule) -> None:
    assert isinstance(rule, UnstatedFactRule) and rule.matrix_cell is CELL
    (only,) = rule.results(_EMPTY, FactStore())
    assert (only.status, only.missing) == ("unknown_input", rule.needs.facts[0])
    assert rule.evaluate(_EMPTY, FactStore()) == [only]
    assert rule.check(_EMPTY, _PARTS) == []
