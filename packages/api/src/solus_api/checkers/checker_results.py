"""SOLUSDEV-321 P3-T1 — one item of an edge's `attrs.checker_results` (docs/api/relations.md §2).

The matrix runner (P3-T3) turns each rule result about an edge into one of these and caches the
list on the edge through `graph/edges.py:annotate_edge`, the one writer of that key. `status` is
what the rule concluded — only `fail` is a problem; `unknown_input` names a fact the project does
not state, so nothing was judged — and `at` is when, ISO-8601 in UTC on the wire. `message` and
the strings in `evidence` inline connector-ingested names: data to escape at render, never
instructions (the `Warning` contract, `checkers/interface.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from solus_api.checkers.interface import Severity

#: What a matrix rule concluded about one subject.
type RuleStatus = Literal["pass", "fail", "inconclusive", "unknown_input"]


class CheckerResult(BaseModel):
    """`{rule_id, status, severity, message, evidence, at}`; frozen, an unknown key refused."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str = Field(min_length=1)
    status: RuleStatus
    severity: Severity
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    at: AwareDatetime

    @field_validator("at")
    @classmethod
    def _in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)
