"""Checker interface + Warning contract (SOLUS-CHK-01, SOLUSDEV-115).

Locks the shape the CHK-03/04 warning UI consumes and the invariants the rules rely on:
Warning is an immutable, closed value object; severities order by real-world impact; and
`run_checkers` fans rules over one graph and returns findings most-severe first.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from solus_api.agent.interfaces import GraphContext
from solus_api.checkers.interface import (
    Checker,
    Severity,
    Warning,
    run_checkers,
    severity_rank,
)
from solus_api.fingerprint.contract import FingerprintOutput


def _empty_graph() -> GraphContext:
    return GraphContext(entities=[], edges=[])


def _empty_parts() -> FingerprintOutput:
    return FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])


def test_severity_orders_by_real_world_impact() -> None:
    assert severity_rank(Severity.CRITICAL) > severity_rank(Severity.WARNING)
    assert severity_rank(Severity.WARNING) > severity_rank(Severity.INFO)


def test_warning_is_frozen() -> None:
    w = Warning(
        checker_id="x",
        severity=Severity.WARNING,
        domains=("electrical",),
        message="m",
    )
    with pytest.raises(ValidationError):
        w.message = "mutated"


def test_warning_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Warning(
            checker_id="x",
            severity=Severity.INFO,
            domains=("code",),
            message="m",
            typo_field="oops",  # type: ignore[call-arg]
        )


def test_warning_defaults_are_empty_not_shared() -> None:
    w = Warning(checker_id="x", severity=Severity.INFO, domains=(), message="m")
    assert w.evidence == {}
    assert w.entity_ids == ()
    assert w.suggested_area is None


class _FixedChecker(Checker):
    checker_id = "fixed"
    domains = ("electrical",)

    def __init__(self, severity: Severity) -> None:
        self._severity = severity

    def check(self, graph: GraphContext, parts: FingerprintOutput) -> list[Warning]:
        return [
            Warning(
                checker_id=self.checker_id,
                severity=self._severity,
                domains=self.domains,
                message=self._severity.value,
            )
        ]


def test_run_checkers_returns_most_severe_first() -> None:
    checkers = (_FixedChecker(Severity.INFO), _FixedChecker(Severity.CRITICAL))
    result = run_checkers(_empty_graph(), _empty_parts(), checkers)
    assert [w.severity for w in result] == [Severity.CRITICAL, Severity.INFO]


def test_run_checkers_with_no_checkers_returns_empty() -> None:
    assert run_checkers(_empty_graph(), _empty_parts(), ()) == []


def test_run_checkers_does_not_mutate_inputs() -> None:
    graph = _empty_graph()
    run_checkers(graph, _empty_parts(), (_FixedChecker(Severity.WARNING),))
    assert graph.entities == [] and graph.edges == []


def test_checker_is_abstract() -> None:
    with pytest.raises(TypeError):
        Checker()  # type: ignore[abstract]


def test_warning_entity_ids_accept_uuids() -> None:
    eid = uuid4()
    w = Warning(
        checker_id="x",
        severity=Severity.INFO,
        domains=(),
        message="m",
        entity_ids=(eid,),
    )
    assert w.entity_ids == (eid,)
