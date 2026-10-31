"""SOLUSDEV-321 P3-T1 — the matrix rule base: what a run reads (`results`) and what the checker
contract sees (`check`). Only a `fail` becomes a `Warning`, so a fact the project does not state
is never a false positive (the checker eval stays 100 % catch / 0 % false positive)."""

from __future__ import annotations

import uuid
from typing import Final

import pytest
from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers.fact_store import FactStore
from solus_api.checkers.interface import Severity, run_checkers
from solus_api.checkers.matrix_rule import EdgeRef, MatrixRule, RuleResult
from solus_api.fingerprint.contract import FingerprintOutput
from solus_api.livebench.findings.rules.rule_base import FactNeed, Needs
from solus_api.services.solus_payloads import Budgets
from solus_contracts.relations import MatrixCell

_DEFINITIONS: Final = FactNeed(name="definitions", set_in="the part's library definition")
_PARTS: Final = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])
_FIRMWARE: Final = EntityRead(id=uuid.uuid4(), kind="code_file", domain="code", name="fw.ino")
_SERVO: Final = EntityRead(id=uuid.uuid4(), kind="part", domain="mechanical", name="servo 3")
_COMMANDS: Final = EdgeRead(
    src_id=_FIRMWARE.id,
    dst_id=_SERVO.id,
    relation_type="commands",
    domain_pair="code<->mechanical",
    confidence=1.0,
)
_GRAPH: Final = GraphContext(entities=[_FIRMWARE, _SERVO], edges=[_COMMANDS])
_HELD: Final = FactStore(budgets=Budgets.model_validate({"computed_at": "2026-10-27T10:00:00Z"}))


class _Scripted(MatrixRule):
    """A sw→me rule that says what it is told to (and needs `definitions` when asked to)."""

    rule_id = "fake_commanded_range"
    matrix_cell = MatrixCell.SOFTWARE_MECHANICAL

    def __init__(self, *results: RuleResult) -> None:
        self._results = results

    def evaluate(self, graph: GraphContext, facts: FactStore) -> list[RuleResult]:
        return list(self._results)


class _NeedsDefinitions(_Scripted):
    needs = Needs(facts=(_DEFINITIONS,))


def _unknown(name: str) -> RuleResult:
    need = FactNeed(name=name, set_in="the part's limits")
    return RuleResult(status="unknown_input", message=f"{name} unknown", missing=need)


def test_unknown_input_never_becomes_a_warning() -> None:
    told = (
        RuleResult(status="pass", message="within range", subjects=(_SERVO.id,)),
        RuleResult(status="inconclusive", message="units differ", severity=Severity.WARNING),
        _unknown("position_max"),
    )
    rule = _Scripted(*told)
    assert rule.results(_GRAPH, FactStore()) == list(told)
    assert rule.check(_GRAPH, _PARTS) == []
    assert rule.check(_GRAPH, _PARTS, facts=_HELD) == []
    assert run_checkers(_GRAPH, _PARTS, (rule,)) == []

    # An unmet `needs.facts`: one unknown_input naming the first fact the store lacks, and
    # evaluate is never asked; even a scripted fail stays unsaid.
    fail = RuleResult(status="fail", message="past the joint limit", subjects=(_SERVO.id,))
    needy = _NeedsDefinitions(fail)
    (only,) = needy.results(_GRAPH, _HELD)
    assert (only.status, only.missing, only.severity) == (
        "unknown_input",
        _DEFINITIONS,
        Severity.INFO,
    )
    assert only.message == (
        "could not check fake_commanded_range: definitions unknown; "
        "set it in the part's library definition"
    )
    assert only.evidence == {"missing": {"name": "definitions", "set_in": _DEFINITIONS.set_in}}
    assert needy.check(_GRAPH, _PARTS) == [] and needy.check(_GRAPH, _PARTS, facts=_HELD) == []


def test_an_unknown_input_names_its_missing_fact() -> None:
    with pytest.raises(ValueError, match="names the fact"):
        RuleResult(status="unknown_input", message="?")


def test_the_base_words_an_unmet_fact_through_the_cells_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M8: an unmet fact is worded in one place, `checkers/cells:unknown_input`, and the base's
    own answer goes through it."""
    told = RuleResult(status="unknown_input", message="worded once", missing=_DEFINITIONS)
    asked: list[tuple[object, FactNeed]] = []

    def helper(rule: MatrixRule, need: FactNeed, *subjects: uuid.UUID, **_: object) -> RuleResult:
        asked.append((rule, need))
        return told

    monkeypatch.setattr("solus_api.checkers.cells.unknown_input", helper)
    rule = _NeedsDefinitions()

    assert rule.results(_GRAPH, FactStore()) == [told]
    assert asked == [(rule, _DEFINITIONS)]


def test_fail_maps_to_warning_with_subjects() -> None:
    fail = RuleResult(
        status="fail",
        message="commanded 200 deg past the 150 deg limit",
        severity=Severity.CRITICAL,
        subjects=(_FIRMWARE.id, _SERVO.id),
        edge_ref=EdgeRef.of(_COMMANDS),
        evidence={"commanded_max": 200, "limit": 150},
    )
    stranger = RuleResult(status="fail", message="m", subjects=(uuid.uuid4(),))
    rule = _Scripted(RuleResult(status="pass", message="ok"), fail, stranger)

    warning, unresolved = rule.check(_GRAPH, _PARTS, facts=_HELD)

    assert warning.checker_id == "fake_commanded_range" and warning.severity is Severity.CRITICAL
    assert warning.entity_ids == (_FIRMWARE.id, _SERVO.id)
    assert warning.domains == ("code", "mechanical")  # derived from the subjects
    assert warning.message == fail.message and warning.evidence == fail.evidence
    assert unresolved.domains == ("code", "mechanical")  # the cell's worlds when none resolves
    assert fail.edge_ref == EdgeRef(_FIRMWARE.id, _SERVO.id, "commands")


def test_a_rule_raises_findings_unless_it_says_otherwise() -> None:
    """R60: a run raises a rule's `fail` as a checker finding unless the rule sets
    `raises_findings = False` (another producer raises that problem). Either way the fail is the
    `Warning` that `warning` makes: the one mapping `check` uses and a run reads."""
    from solus_api.checkers.traversal import GraphView

    class _Quiet(_Scripted):
        raises_findings = False

    fail = RuleResult(status="fail", message="past the joint limit", subjects=(_SERVO.id,))
    quiet = _Quiet(fail)

    assert MatrixRule.raises_findings is True and _Scripted.raises_findings is True
    assert quiet.raises_findings is False
    assert quiet.check(_GRAPH, _PARTS) == [quiet.warning(GraphView(_GRAPH), fail)]


def test_a_rule_is_a_checker_of_its_cell() -> None:
    assert (_Scripted.checker_id, _Scripted.domains) == (
        "fake_commanded_range",
        ("code", "mechanical"),
    )
    assert _NeedsDefinitions.needs.facts == (_DEFINITIONS,) and _Scripted.needs == Needs()
    with pytest.raises(TypeError):
        MatrixRule()  # type: ignore[abstract]
