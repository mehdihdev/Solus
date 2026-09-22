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


def test_webhook_access_credentials_are_redacted_before_every_handler(monkeypatch):
    from uvicorn.logging import AccessFormatter

    original_factory = logging.getLogRecordFactory()
    monkeypatch.setattr(logging, "_logRecordFactory", original_factory)
    logger = logging.Logger("uvicorn.access", logging.INFO)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(AccessFormatter("%(request_line)s", use_colors=False))
    logger.addHandler(handler)
    configure_logging()
    logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1",
        "POST",
        "/api/v1/webhooks/onshape/source-id/credential-test-value?extra=private",
        "1.1",
        204,
    )
    assert "credential-test-value" not in output.getvalue()
    assert "private" not in output.getvalue()
    assert "POST /api/v1/webhooks/onshape/source-id/[redacted] HTTP/1.1" in output.getvalue()


def test_webhook_url_in_exception_is_redacted_for_plain_file_handler(monkeypatch):
    monkeypatch.setattr(logging, "_logRecordFactory", logging.getLogRecordFactory())
    logger = logging.Logger("solus.exception", logging.INFO)
    output = io.StringIO()
    logger.addHandler(logging.StreamHandler(output))
    configure_logging()
    try:
        raise RuntimeError(
            "failed https://api.example/api/v1/webhooks/onshape/source-id/credential-test-value"
        )
    except RuntimeError:
        logger.exception("Failed request")
    assert "RuntimeError" in output.getvalue()
    assert "credential-test-value" not in output.getvalue()


def test_url_assembled_from_format_arguments_is_redacted_without_format_error(monkeypatch):
    monkeypatch.setattr(logging, "_logRecordFactory", logging.getLogRecordFactory())
    logger = logging.Logger("solus.format", logging.INFO)
    output = io.StringIO()
    logger.addHandler(logging.StreamHandler(output))
    configure_logging()
    logger.info("/api/v1/webhooks/onshape/%s/%s", "source", "credential-test-value")
    assert output.getvalue() == "/api/v1/webhooks/onshape/source/[redacted]\n"


@pytest.mark.parametrize(
    "path",
    [
        "/%61pi/v1/webhooks/%6fnshape/source/credential-test-value",
        "/api%2fv1/webhooks/onshape/source%2fcredential-test-value",
        "/api/v1/webhooks/%6fnshape/source/credential-test-value%20tail?value=private",
    ],
)
def test_percent_encoded_webhook_prefix_is_redacted_in_access_record(monkeypatch, path):
    from uvicorn.logging import AccessFormatter

    monkeypatch.setattr(logging, "_logRecordFactory", logging.getLogRecordFactory())
    logger = logging.Logger("uvicorn.access", logging.INFO)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(AccessFormatter("%(request_line)s", use_colors=False))
    logger.addHandler(handler)
    configure_logging()
    logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1",
        "POST",
        path,
        "1.1",
        204,
    )
    assert "credential-test-value" not in output.getvalue()
    assert "[redacted]" in output.getvalue()
