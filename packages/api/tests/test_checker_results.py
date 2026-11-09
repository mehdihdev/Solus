"""SOLUSDEV-321 P3-T1 — one item of an edge's `attrs.checker_results` (docs/api/relations.md §2):
`{rule_id, status, severity, message, evidence, at}`, `at` ISO-8601 in UTC on the wire."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Final

import pytest
from pydantic import ValidationError
from solus_api.checkers.checker_results import CheckerResult
from solus_api.checkers.interface import Severity

_FIELDS: Final[dict[str, Any]] = {
    "rule_id": "pin_in_code_vs_wiring",
    "severity": "critical",
    "message": "pin 9 is commanded but not wired",
    "evidence": {"pin": "9"},
}
_AT: Final = datetime(2026, 10, 27, 12, 0, tzinfo=timezone(timedelta(hours=2)))


def test_an_item_round_trips_as_json_with_at_in_utc() -> None:
    result = CheckerResult(**_FIELDS, status="fail", at=_AT)
    dumped = result.model_dump(mode="json")
    assert dumped == {**_FIELDS, "status": "fail", "at": "2026-10-27T10:00:00Z"}
    assert result.severity is Severity.CRITICAL and result.at.tzinfo is UTC
    assert CheckerResult.model_validate(dumped) == result


@pytest.mark.parametrize("status", ["pass", "fail", "inconclusive", "unknown_input"])
def test_the_four_statuses_are_the_vocabulary(status: str) -> None:
    assert CheckerResult.model_validate({**_FIELDS, "status": status, "at": _AT}).status == status


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "ok"},
        {"status": "warning"},
        {"at": "2026-10-27T10:00:00"},  # naive: no zone, so not a UTC instant
        {"rule_id": ""},
        {"edge_ref": "x"},  # an unknown key is a bug, not data
    ],
)
def test_a_malformed_item_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CheckerResult.model_validate({**_FIELDS, "status": "pass", "at": _AT, **bad})


def test_an_item_is_frozen_and_evidence_defaults_empty() -> None:
    result = CheckerResult(
        rule_id="power_budget", status="pass", severity=Severity.INFO, message="ok", at=_AT
    )
    assert result.evidence == {}
    with pytest.raises(ValidationError):
        result.status = "fail"
