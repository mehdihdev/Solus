"""The one constructor of SOL's read-only retrieval tools (SOLUSDEV-321 P1-T4).

The retrieval tools let the model look things up itself: workspace entities, `.solus` entries,
the practice corpus, a finding, a run, the environment divergences, a machine, the project's
history. What they return is tenant data bound for the model's context, so each is built here
and the bounds and the failure shape are one piece of code, not eight:

* **Bounded.** A handler returns rows, or one block of text. At most `MAX_ROWS` rows are
  rendered, a Mapping row as one compact JSON object on one line in which a secret-named key,
  read as its producer wrote it, masks its value and every string, a key too, is then redacted,
  flattened and cut at `FIELD_CAP`; and the whole result is cut to `result_cap` characters AS THE
  PROMPT LAYER SENDS IT (ASCII JSON, where `<`, quotes and non-ASCII grow), ending in
  `…[truncated]` so a cut is never silent. The descriptor carries the same cap, so the prompt
  layer's own cut, which leaves no marker, never lands.
* **Typed failures.** A handler's `ToolException` passes through; an `APIError` 404 becomes
  `not_found` in the loader's own words; anything else, any other `APIError` included, is logged
  with its traceback and becomes `error: <tool> failed`. The registry turns each into a
  `ToolResult(ok=False)`, so no exception text reaches the model and nothing escapes as a raw
  exception. Cancellation and task groups are the registry's to classify and pass straight
  through.
* **Read-only, ungated.** The descriptor says it reads and sets `requires_confirmation` and
  `files_errors` to False. A handler never writes and never calls a model.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Final

from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.agent.tools.untrusted import redact_text, redact_value
from solus_api.core.errors import APIError

logger = logging.getLogger("solus.agent.tools.read")

#: Rows one result renders; also the most a model may ask a search for.
MAX_ROWS: Final = 20
DEFAULT_LIMIT: Final = 10
#: A result's length as the prompt layer sends it — about 2,000 tokens, twice the shared default.
RESULT_CAP: Final = 8_000
#: One string of a row, a key too, so a long note cannot take the rows after it.
FIELD_CAP: Final = 500
#: The search route's bound on a query.
QUERY_CAP: Final = 255
TRUNCATED: Final = "…[truncated]"
#: The row `page_rows` adds when the limit hid some: a cut is never silent.
MORE: Final = "+more results exist past this limit; raise limit or narrow the request"
NO_RESULTS: Final = "no results"
_TAIL: Final = "\n" + TRUNCATED

QUERY_PARAM: Final[dict[str, Any]] = {
    "type": "string",
    "minLength": 1,
    "maxLength": QUERY_CAP,
    "description": "What to look for.",
}
LIMIT_PARAM: Final[dict[str, Any]] = {
    "type": "integer",
    "minimum": 1,
    "maximum": MAX_ROWS,
    "description": f"Most rows to return, at most {MAX_ROWS}; {DEFAULT_LIMIT} if omitted.",
}
_RETURNS: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}

Row = str | Mapping[str, Any]
#: Rows, or one block of text that counts as a single row (flattened to one line like any
#: other: a handler with several lines of text returns them as a list).
ReadResult = str | Sequence[Row]
ReadHandler = Callable[[dict[str, Any]], Awaitable[ReadResult]]


def uuid_arg(args: Mapping[str, Any], key: str) -> uuid.UUID:
    """The UUID the model passed as `key`; the schema checks the format, this makes it a UUID."""
    try:
        return uuid.UUID(str(args[key]))
    except (KeyError, ValueError):
        raise ToolException(f"{key} must be a UUID", code=ToolErrorCode.INVALID_ARGS) from None


def uuid_params(key: str, description: str) -> dict[str, Any]:
    """The params schema of a tool that takes exactly one UUID, `key`."""
    return {
        "type": "object",
        "properties": {key: {"type": "string", "format": "uuid", "description": description}},
        "required": [key],
        "additionalProperties": False,
    }


def int_arg(args: Mapping[str, Any], key: str, *, default: int, high: int) -> int:
    """`key` clamped to 1..`high`, whatever was asked; `default` when absent or not a number."""
    try:
        asked = int(args.get(key, default))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(1, min(asked, high))


def limit_arg(args: Mapping[str, Any]) -> int:
    """`limit`, clamped to 1..`MAX_ROWS` whatever the model asked."""
    return int_arg(args, "limit", default=DEFAULT_LIMIT, high=MAX_ROWS)


def page_rows(found: Sequence[Row], limit: int) -> list[Row]:
    """The first `limit` rows of `found`, which a handler fetched with ONE extra row for this: its
    existence is the answer to "are there more", it is never shown, and `MORE` says so. At the
    `MAX_ROWS` ceiling that marker is the 21st row, so the factory's own cut says it instead."""
    shown: list[Row] = list(found[:limit])
    return [*shown, MORE] if len(found) > limit else shown


def query_arg(args: Mapping[str, Any]) -> str:
    """The query, trimmed and held to `QUERY_CAP`; a blank one is refused, not searched."""
    asked = args.get("q")
    text = asked.strip()[:QUERY_CAP] if isinstance(asked, str) else ""
    if not text:
        raise ToolException("q must not be empty", code=ToolErrorCode.INVALID_ARGS)
    return text


def bounded_read_tool(
    name: str,
    description: str,
    params: dict[str, Any],
    handler: ReadHandler,
    *,
    result_cap: int = RESULT_CAP,
) -> InProcessTool:
    """Build one retrieval tool: `handler(args)` returns rows or text, this bounds and renders
    them. The tool's result is `{"text": ...}`."""
    descriptor = ToolDescriptor(
        name=name,
        description=(
            f"{description} Read-only; at most {MAX_ROWS} rows, and a longer result ends with "
            f"{TRUNCATED}."
        ),
        params=params,
        returns=_RETURNS,
        requires_confirmation=False,
        files_errors=False,
        result_cap=result_cap,
    )

    async def read(args: dict[str, Any]) -> dict[str, Any]:
        try:
            return {"text": _result_text(await handler(args), result_cap)}
        except (ToolException, BaseExceptionGroup):
            raise
        except Exception as exc:
            if isinstance(exc, APIError) and exc.status_code == 404:
                raise ToolException(exc.message, code=ToolErrorCode.NOT_FOUND) from None
            logger.exception("read tool %s failed", name)
            raise ToolException(f"error: {name} failed", code=ToolErrorCode.TOOL_ERROR) from None

    return InProcessTool(descriptor, read)


def _result_text(result: ReadResult, result_cap: int) -> str:
    rows: list[Row] = [result] if isinstance(result, str) else list(result)
    text = "\n".join(_row_text(row) for row in rows[:MAX_ROWS]) or NO_RESULTS
    if len(rows) > MAX_ROWS:
        text += _TAIL
    return _fit_to_cap(text, result_cap)


def _row_text(row: Row) -> str:
    """A string row is a note, redacted and on one line. A Mapping row is ONE compact JSON object
    on one line — the prompt layer's own rule for untrusted values (`contain_result`) — so a
    `|` or a newline in a value can forge no field. Three passes, in this order: `_plain` makes
    the row plain data and touches no string; `redact_value` masks the value of every
    secret-named key and every entropic string while each key still reads as its producer wrote
    it (normalised first, a 40-character key swapped for `[REDACTED]` or a 500-character key cut
    would no longer match); `_normalised` then redacts, flattens and caps every string and key."""
    if isinstance(row, str):
        return _one_line(row)
    fields = _normalised(redact_value(_plain(row)))
    kept = {key: value for key, value in fields.items() if value not in (None, "")}
    return json.dumps(kept, ensure_ascii=False, separators=(",", ":"))


def _plain(value: Any) -> Any:
    """`value` as plain JSON data and nothing more: Mappings become dicts (keys as `str`), tuples
    lists, a datetime its ISO string, any other leaf that is not a string, a number, a bool or
    None its `str`. No string is touched, so a key is still exactly what its producer wrote."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, str | bool | int | float):
        return value
    return str(value)


def _normalised(value: Any) -> Any:
    """Plain `value` with every string, a key too, redacted, flattened to one line and cut at
    `FIELD_CAP`. A key still goes through `redact_text`, so a secret-shaped key never leaks."""
    if isinstance(value, str):
        return _one_line(value, FIELD_CAP)
    if isinstance(value, dict):
        return {_one_line(key, FIELD_CAP): _normalised(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalised(item) for item in value]
    return value


def _one_line(text: str, cap: int | None = None) -> str:
    """Redacted, flattened to one line (a tenant's newline cannot forge a row), then cut: a
    secret cut in half no longer reads as one."""
    flat = " ".join(redact_text(text).split())
    return flat if cap is None or len(flat) <= cap else flat[: cap - 1] + "…"


def _wire_length(text: str) -> int:
    """The result's length once the prompt layer has encoded it (`prompt.contain_result`):
    compact ASCII JSON of `{"ok": true, "value": {"text": ...}}`, `<` written `\\u003c`. Each
    character is escaped alone, so the length never shrinks as the text grows."""
    payload = {"ok": True, "value": {"text": text}}
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return len(encoded.replace("<", "\\u003c"))


def _fit_to_cap(text: str, cap: int) -> str:
    """`text` when it fits `cap` on the wire; else its longest head that still leaves room for
    the marker, cut between rows when it can be, and the marker."""
    if _wire_length(text) <= cap:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if _wire_length(text[:mid] + _TAIL) <= cap:
            low = mid
        else:
            high = mid - 1
    head = text[:low]
    if "\n" in head and text[low : low + 1] != "\n":  # the cut fell inside a row: drop it
        head = head.rsplit("\n", 1)[0]
    return "\n".join(part for part in (head, TRUNCATED) if part)
