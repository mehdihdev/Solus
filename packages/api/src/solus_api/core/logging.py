"""One application console sink, with bounded structured timing fields."""

import json
import logging
import re
import sys
import traceback
from collections.abc import Callable
from typing import Any

# Match the credential-bearing suffix, including a query/path continuation.
# Invalid source IDs must be sanitized too: access logging precedes validation.
_WEBHOOK_PREFIX = "".join(
    f"(?:{re.escape(char)}|%{ord(char):02x})" for char in "/api/v1/webhooks/onshape/"
)
_WEBHOOK_URL = re.compile(rf"({_WEBHOOK_PREFIX}[^/\s?]+?(?:/|%2f))[^\s\"'<>]+", re.IGNORECASE)


def redact_webhook_url(value: str) -> str:
    # Recognize percent-encoded prefix characters without decoding the secret,
    # including encoded separators. Redact the whole raw suffix/query at once.
    return _WEBHOOK_URL.sub(r"\1[redacted]", value)


def _redact_log_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return tuple(_redact_log_value(item) for item in value)
    if isinstance(value, dict):
        return {key: _redact_log_value(item) for key, item in value.items()}
    if isinstance(value, str):
        return redact_webhook_url(value)
    return value


class _WebhookRecordFactory:
    """Sanitize before console, access, file and instrumentation handlers receive it."""

    def __init__(self, previous: Callable[..., logging.LogRecord]) -> None:
        self.previous = previous

    def __call__(self, *args: Any, **kwargs: Any) -> logging.LogRecord:
        record = self.previous(*args, **kwargs)
        rendered = record.getMessage()
        sanitized_message = redact_webhook_url(rendered)
        if sanitized_message != rendered and record.name != "uvicorn.access":
            record.msg, record.args = sanitized_message, ()
        else:
            # Uvicorn's formatter unpacks these five values; preserve their shape.
            record.msg = redact_webhook_url(str(record.msg))
            record.args = _redact_log_value(record.args)
        if record.exc_info:
            original = "".join(traceback.format_exception(*record.exc_info))
            sanitized = redact_webhook_url(original)
            if sanitized != original:
                record.exc_info = None
                record.exc_text = sanitized
        if record.exc_text:
            record.exc_text = redact_webhook_url(record.exc_text)
        return record


_TIMING_FIELDS = ("propose_s", "write_s", "session_s", "proposal_reused")


class _ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, object] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _TIMING_FIELDS:
            value = getattr(record, field, None)
            if isinstance(value, (bool, int, float)):
                event[field] = value
        if record.exc_info:
            event["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            event["exception"] = record.exc_text
        return json.dumps(event)


def configure_logging() -> None:
    """Replace console sinks while preserving instrumentation and file handlers."""
    factory = logging.getLogRecordFactory()
    if not isinstance(factory, _WebhookRecordFactory):
        logging.setLogRecordFactory(_WebhookRecordFactory(factory))
    root = logging.getLogger()
    for handler in root.handlers[:]:
        stream = getattr(handler, "stream", None)
        if handler.name == "solus.console" or (
            type(handler) is logging.StreamHandler
            and (stream is sys.stderr or stream is sys.stdout)
        ):
            root.removeHandler(handler)
            handler.close()
    console = logging.StreamHandler(sys.stderr)
    console.name = "solus.console"
    console.setFormatter(_ConsoleFormatter())
    root.addHandler(console)
    root.setLevel(logging.INFO)
