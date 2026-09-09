"""Shared export-parsing helpers used by both connector families (SOLUS-CAD-00).

Extracted from `eda.py` when the mechanical family needed the same bounded
error collection and content hashing; these tests pin the behaviour both
families now depend on.
"""

from __future__ import annotations

from solus_api.connectors.export_common import (
    MAX_SYNC_ERRORS,
    ErrorRecorder,
    content_sha,
    label,
)


def test_records_errors_below_the_cap_verbatim() -> None:
    recorder = ErrorRecorder()

    recorder.record("U1", "duplicate designator")

    assert [(e.item, e.message) for e in recorder.finish()] == [("U1", "duplicate designator")]


def test_overflow_collapses_into_a_single_truncation_note() -> None:
    recorder = ErrorRecorder()

    for i in range(MAX_SYNC_ERRORS + 5):
        recorder.record(f"item{i}", "boom")

    errors = recorder.finish()

    assert len(errors) == MAX_SYNC_ERRORS + 1
    assert errors[-1].item == "parse"
    assert "5 further issue(s) truncated" in errors[-1].message


def test_no_truncation_note_when_exactly_at_the_cap() -> None:
    recorder = ErrorRecorder()

    for i in range(MAX_SYNC_ERRORS):
        recorder.record(f"item{i}", "boom")

    assert len(recorder.finish()) == MAX_SYNC_ERRORS


def test_content_sha_is_stable_and_content_sensitive() -> None:
    assert content_sha("abc") == content_sha("abc")
    assert content_sha("abc") != content_sha("abd")


def test_content_sha_survives_lone_surrogates() -> None:
    """Adversarial exports can carry unpaired surrogates; hashing must not raise."""
    assert content_sha("bad \ud800 byte")


def test_label_truncates_an_over_long_adversarial_token() -> None:
    assert len(label("x" * 500)) <= 64 + 1
    assert label("U1") == "U1"


# --- SOLUSDEV-252 Phase 4 (S2): per-message and aggregate byte budgets ---


def test_message_is_clipped_to_the_message_limit() -> None:
    from solus_api.connectors.export_common import MESSAGE_LIMIT

    recorder = ErrorRecorder()

    recorder.record("R1", "v" * 5_000)
    recorder.record("R2", "w" * MESSAGE_LIMIT)

    clipped, exact = recorder.finish()
    assert len(clipped.message) == MESSAGE_LIMIT
    assert clipped.message.endswith("…")
    assert clipped.message.startswith("vvv")
    assert exact.message == "w" * MESSAGE_LIMIT  # at the limit is kept verbatim


def test_aggregate_byte_budget_suppresses_further_records() -> None:
    from solus_api.connectors.export_common import MESSAGE_LIMIT, TOTAL_BYTES_LIMIT

    recorder = ErrorRecorder()
    # 100 records × (600-char item + 512-char message) would persist ~111 KB;
    # the aggregate budget stops that well before MAX_SYNC_ERRORS does.
    for i in range(MAX_SYNC_ERRORS):
        recorder.record(f"{i:0>600}", "m" * MESSAGE_LIMIT)

    errors = recorder.finish()

    persisted = sum(len(e.item) + len(e.message) for e in errors)
    assert persisted <= TOTAL_BYTES_LIMIT
    assert len(errors) < MAX_SYNC_ERRORS
    assert errors[-1].item == "parse"
    suppressed = MAX_SYNC_ERRORS - (len(errors) - 1)
    assert errors[-1].message == f"{suppressed} further issue(s) truncated"


def test_count_cap_and_byte_budget_share_one_suppression_note() -> None:
    recorder = ErrorRecorder()

    for i in range(MAX_SYNC_ERRORS + 5):
        recorder.record(f"item{i}", "boom")

    errors = recorder.finish()

    assert len(errors) == MAX_SYNC_ERRORS + 1  # MAX_SYNC_ERRORS behaviour unchanged
    assert sum(1 for e in errors if "truncated" in e.message) == 1
