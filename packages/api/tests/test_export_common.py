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
