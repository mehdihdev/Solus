"""One application console sink, with bounded structured timing fields."""

import json
import logging
import sys

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
        return json.dumps(event)


def configure_logging() -> None:
    """Replace console sinks while preserving instrumentation and file handlers."""
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
