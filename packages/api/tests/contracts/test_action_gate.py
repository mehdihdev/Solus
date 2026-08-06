"""SOLUSDEV-218 (CTR-03) — the destructive-action gate contract, Python half.

This validates the SAME fixture files that `packages/shared-types/src/
action-gate.test.ts` type-checks. That pairing is the drift guard: these
contracts have no route yet, so they cannot go through the OpenAPI pipeline,
and two hand-maintained definitions of one shape would drift silently. One
artefact, two enforcers — a field added on either side breaks one of the suites.

It also pins the contract against the SHIPPED gate on branch
SOLUSDEV-60/ons-ui01-confirmation-surface. CTR-03 documents that gate; it does
not redesign it.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.contracts.action_gate import (
    CONFIRMATION_TTL_MINUTES,
    ConfirmationDecisionRequest,
    ConfirmationOutcomeEnvelope,
    ConfirmationStatus,
    ToolConfirmationEvent,
    confirmation_decision_path,
)

FIXTURES = Path(__file__).resolve().parents[3] / "shared-types" / "fixtures" / "action-gate"

PENDING = ["pending-with-diff", "pending-args-only"]
OUTCOMES = [
    "outcome-approved",
    "outcome-rejected",
    "outcome-expired",
    "outcome-stale",
    "outcome-already-decided",
    "outcome-tool-gone",
    "outcome-not-found",
]


def load(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return loaded


def test_the_fixture_directory_is_the_one_typescript_reads() -> None:
    # If this path moves, the two halves of the drift guard stop guarding the
    # same thing — and would both keep passing.
    assert FIXTURES.is_dir(), FIXTURES
    assert (FIXTURES.parents[1] / "src" / "action-gate.test.ts").is_file()


@pytest.mark.parametrize("name", PENDING)
def test_pending_fixtures_validate(name: str) -> None:
    event = ToolConfirmationEvent.model_validate(load(name))
    # A user cannot meaningfully approve an opaque id: the concrete action travels.
    assert event.summary
    assert event.args
    assert event.tool


@pytest.mark.parametrize("name", OUTCOMES)
def test_outcome_fixtures_validate(name: str) -> None:
    envelope = ConfirmationOutcomeEnvelope.model_validate(load(name))
    assert (envelope.data.error is None) is envelope.data.ok
    assert (envelope.data.value is None) is not envelope.data.ok


def test_a_diff_carrying_action_renders_before_and_after() -> None:
    event = ToolConfirmationEvent.model_validate(load("pending-with-diff"))
    assert [row.label for row in event.preview] == ["motor_mount_width", "mount_hole_spacing"]
    assert event.preview[0].before == "58.0 mm"
    assert event.preview[0].after == "62.0 mm"


def test_an_action_with_no_describable_change_still_shows_its_arguments() -> None:
    # A flash, a shell command and a robot move do not REPLACE a value. The rows
    # are argument rows, derived from the same stored args that execute.
    event = ToolConfirmationEvent.model_validate(load("pending-args-only"))
    assert all(row.before is None for row in event.preview)
    assert [row.label for row in event.preview] == ["board", "port", "sketch"]


def test_exactly_one_outcome_fixture_succeeded() -> None:
    oks = [ConfirmationOutcomeEnvelope.model_validate(load(n)).data.ok for n in OUTCOMES]
    assert oks.count(True) == 1


def test_a_rejection_is_a_refusal_not_a_success() -> None:
    # The trap this contract exists to document: HTTP 200 does not mean it ran.
    envelope = ConfirmationOutcomeEnvelope.model_validate(load("outcome-rejected"))
    assert envelope.data.ok is False
    assert envelope.data.error is not None
    assert envelope.data.error.code is ToolErrorCode.UNAUTHORIZED


def test_stale_and_expired_are_distinguishable() -> None:
    stale = ConfirmationOutcomeEnvelope.model_validate(load("outcome-stale"))
    expired = ConfirmationOutcomeEnvelope.model_validate(load("outcome-expired"))
    assert stale.data.error is not None and expired.data.error is not None
    assert "changed since it was shown" in stale.data.error.message
    assert "expired" in expired.data.error.message


def test_no_refusal_is_retryable() -> None:
    for name in OUTCOMES:
        error = ConfirmationOutcomeEnvelope.model_validate(load(name)).data.error
        assert error is None or error.retryable is False


# ── the properties the shipped gate guarantees ───────────────────────────────


def test_a_decision_is_approve_or_reject_and_nothing_else() -> None:
    assert ConfirmationDecisionRequest(decision="approve").decision == "approve"
    assert ConfirmationDecisionRequest(decision="reject").decision == "reject"
    # The `type: ignore` is an ASSERTION, not a suppression: `strict = true`
    # implies `warn_unused_ignores`, so if "amend" ever became constructible the
    # ignore would go unused and mypy would fail. Type-level and runtime, both.
    with pytest.raises(ValidationError):
        ConfirmationDecisionRequest(decision="amend")  # type: ignore[arg-type]


def test_a_decision_body_carrying_arguments_is_rejected() -> None:
    # THE load-bearing property. If a client could re-supply args at approval
    # time, a user could approve "change width" and a client execute "change
    # everything" (schemas.py:166-175 sets extra="forbid" for exactly this).
    with pytest.raises(ValidationError):
        ConfirmationDecisionRequest.model_validate(
            {"decision": "approve", "args": {"value_mm": 999}}
        )


def test_the_status_enum_matches_the_shipped_one() -> None:
    # models.py:176-190. STALE is distinct from EXPIRED on purpose: time did not
    # run out, the world moved.
    assert [s.value for s in ConfirmationStatus] == [
        "pending",
        "approved",
        "rejected",
        "expired",
        "stale",
    ]


def test_the_ttl_matches_the_server_constant() -> None:
    assert CONFIRMATION_TTL_MINUTES == 30


def test_the_decision_path_matches_the_shipped_route() -> None:
    assert (
        confirmation_decision_path("proj-1", "conf-2")
        == "/api/v1/projects/proj-1/sol/confirmations/conf-2"
    )


def test_an_unknown_field_on_a_pending_event_is_rejected() -> None:
    # extra="forbid" on both sides is what makes the fixtures a real drift guard:
    # a field added in TypeScript and not here fails HERE.
    with pytest.raises(ValidationError):
        ToolConfirmationEvent.model_validate({**load("pending-with-diff"), "surprise": 1})
