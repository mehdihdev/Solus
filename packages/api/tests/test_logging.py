"""Application logging has one console sink and retains confirmation timing."""

import io
import json
import logging
import sys

import pytest
from solus_api.core.logging import configure_logging


def test_console_setup_is_idempotent_and_preserves_instrumentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = logging.RootLogger(logging.WARNING)
    console, capture = io.StringIO(), io.StringIO()
    old_console = logging.StreamHandler(console)
    instrumentation = logging.StreamHandler(capture)
    root.handlers = [old_console, instrumentation]
    monkeypatch.setattr(sys, "stderr", console)
    monkeypatch.setattr(logging, "getLogger", lambda name=None: root)

    configure_logging()
    configure_logging()
    root.info("hardware.confirm timings", extra={"write_s": 0.12, "proposal_reused": True})

    assert len(root.handlers) == 2
    assert instrumentation in root.handlers
    assert len(console.getvalue().splitlines()) == 1
    event = json.loads(console.getvalue())
    assert event["message"] == "hardware.confirm timings"
    assert event["write_s"] == 0.12
    assert event["proposal_reused"] is True
    assert capture.getvalue().count("hardware.confirm timings") == 1


def test_console_does_not_serialize_arbitrary_extra_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = logging.RootLogger(logging.WARNING)
    console = io.StringIO()
    monkeypatch.setattr(sys, "stderr", console)
    monkeypatch.setattr(logging, "getLogger", lambda name=None: root)
    configure_logging()

    root.info("operation completed", extra={"request_payload": {"private": "not-for-logs"}})

    event = json.loads(console.getvalue())
    assert event["level"] == "INFO"
    assert "request_payload" not in event
    assert "not-for-logs" not in console.getvalue()
