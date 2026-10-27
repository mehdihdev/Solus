"""Outline geometry for the desktop's amber outline (sol-drive.md §3, slice 3).

The companion's stdout carries exactly these lines and nothing else (logging
goes to stderr): `{"type":"drive_window","bounds":{x,y,width,height}}`.
Only the four numbers are copied out of a helper reply — never a title, a
bundle id or a path — and anything malformed or non-finite gives no line.
"""

import json
import logging
import math
import sys
from collections.abc import Callable
from typing import Any, TextIO

logger = logging.getLogger("solus.companion.drive")

_KEYS = ("x", "y", "width", "height")
#: Global points; matches the server's coordinate bound.
_LIMIT = 100_000

Emit = Callable[[str], None]


def _number(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and abs(value) <= _LIMIT
    )


def outline_line(bounds: Any) -> str | None:
    """The one stdout line for these bounds, or None when they are not valid."""
    if not isinstance(bounds, dict):
        return None
    if not all(_number(bounds.get(key)) for key in _KEYS):
        return None
    values: dict[str, float] = {key: bounds[key] for key in _KEYS}
    if values["width"] <= 0 or values["height"] <= 0:
        return None
    return json.dumps({"type": "drive_window", "bounds": values}, separators=(",", ":"))


def stdout_writer(stream: TextIO | None = None) -> Emit:
    """Write one line and flush; a closed or broken pipe never fails a call."""

    def emit(line: str) -> None:
        target = stream if stream is not None else sys.stdout
        try:
            target.write(line + "\n")
            target.flush()
        except (OSError, ValueError) as exc:
            logger.warning("drive outline line not written: %s", type(exc).__name__)

    return emit
