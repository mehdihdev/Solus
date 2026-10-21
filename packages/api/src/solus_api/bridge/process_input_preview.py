"""The `code.process_input` approval card (SOLUSDEV-317 §11.2).

The card is read back from the machine: one `code.process_status {process_id}`
read names the process and the prompt it is waiting at. Rows, in order:
`process`, `prompt` (the redacted tail), `input` (the exact text, or `⏎ Enter`)
and `plan fingerprint` over `{process_id, prompt_seq, text, enter}`.

Refused (`PreviewRefusal`, nothing parked) when the arguments are out of
bounds, when redaction would change the input row (the person must see exactly
what is typed), or when the process is unknown, not interactive, not running
or not waiting for input. The same argument rules guard the person's own input
route (`input_problem`).
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.tools.untrusted import redact_text

STATUS_TOOL: Final = "code.process_status"
INPUT_TOOL: Final = "code.process_input"
#: §11.1: text is at most 1024 printable characters; a newline only via `enter`.
MAX_INPUT_CHARS: Final = 1024
ENTER_LABEL: Final = "⏎ Enter"
PROCESS_ID: Final = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ROW_CAP: Final = 500
_CHUNK: Final = 400
_NAME_CAP: Final = 120
_NOTHING: Final = "Nothing was parked or sent."
_ARGS: Final = frozenset({"process_id", "text", "enter"})


@dataclass(frozen=True)
class WaitingProcess:
    """A `code.process_status` entry that is interactive, running and waiting."""

    process_id: str
    label: str
    prompt_seq: int
    prompt_tail: str


def _refuse(detail: str) -> PreviewRefusal:
    return PreviewRefusal(f"{detail} {_NOTHING}")


def input_problem(text: object, enter: object) -> str | None:
    """Why `{text, enter}` cannot be sent, or None. No control character at all:
    a newline comes only from `enter` (§11.1)."""
    if not isinstance(text, str) or len(text) > MAX_INPUT_CHARS:
        return f"text must be a string of at most {MAX_INPUT_CHARS} characters"
    if not all(ch.isprintable() for ch in text):
        return "text must be printable, with no control characters or newlines"
    if not isinstance(enter, bool):
        return "enter must be true or false"
    if not text and not enter:
        return "there is nothing to send"
    return None


def _args(args: Mapping[str, Any]) -> tuple[str, str, bool]:
    process_id = args.get("process_id")
    text, enter = args.get("text", ""), args.get("enter", True)
    if (
        not set(args) <= _ARGS
        or not isinstance(process_id, str)
        or not PROCESS_ID.fullmatch(process_id)
    ):
        raise _refuse("The process input arguments are invalid.")
    problem = input_problem(text, enter)
    if problem is not None:
        raise _refuse(f"The process input is invalid: {problem}.")
    assert isinstance(text, str) and isinstance(enter, bool)
    return process_id, text, enter


def _clean(text: object) -> str:
    if not isinstance(text, str):
        return ""
    return "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")


def _label(entry: Mapping[str, Any]) -> str:
    name = entry.get("name")
    if isinstance(name, str) and name.strip():
        return redact_text(_clean(name).strip())[:_NAME_CAP]
    argv = entry.get("argv")
    if isinstance(argv, list) and argv and isinstance(argv[0], str):
        return redact_text(_clean(posixpath.basename(argv[0])))[:_NAME_CAP] or "process"
    return "process"


def waiting_process(value: object, process_id: str) -> WaitingProcess | None:
    """The entry for `process_id` when it is interactive, running and waiting;
    None otherwise. Raises nothing — callers decide what absence means."""
    entry = find_process(value, process_id)
    if entry is None:
        return None
    seq = entry.get("prompt_seq")
    if (
        entry.get("interactive") is not True
        or entry.get("state") != "running"
        or entry.get("awaiting_input") is not True
        or type(seq) is not int
        or seq < 0
    ):
        return None
    tail = redact_text(_clean(entry.get("prompt_tail")))
    return WaitingProcess(process_id, _label(entry), seq, tail)


def find_process(value: object, process_id: str) -> Mapping[str, Any] | None:
    rows = value.get("processes") if isinstance(value, Mapping) else None
    if not isinstance(rows, list):
        return None
    return next(
        (row for row in rows if isinstance(row, Mapping) and row.get("process_id") == process_id),
        None,
    )


def input_fingerprint(process_id: str, prompt_seq: int, text: str, enter: bool) -> str:
    canonical = json.dumps(
        {"enter": enter, "process_id": process_id, "prompt_seq": prompt_seq, "text": text},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return ":".join(digest[start : start + 16] for start in range(0, 64, 16))


def _row(label: str, after: str) -> dict[str, Any]:
    return {"label": label, "before": None, "after": after}


def _input_rows(text: str) -> list[dict[str, Any]]:
    if not text:
        return [_row("input", ENTER_LABEL)]
    chunks = [text[start : start + _CHUNK] for start in range(0, len(text), _CHUNK)]
    if len(chunks) == 1:
        return [_row("input", text)]
    return [_row(f"input {i + 1}/{len(chunks)}", chunk) for i, chunk in enumerate(chunks)]


def input_rows(status: object, args: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The card rows, or `PreviewRefusal` (nothing parked, nothing sent)."""
    process_id, text, enter = _args(args)
    if redact_text(text) != text:
        raise _refuse(
            "Refused: the input contains secret-shaped values that cannot be shown on the "
            "approval card; ask the person to type it into the process themselves."
        )
    if status is None:
        raise _refuse("The process status is unavailable, so its approval card cannot be shown.")
    if find_process(status, process_id) is None:
        raise _refuse("No such process on this machine.")
    waiting = waiting_process(status, process_id)
    if waiting is None:
        raise _refuse("The process is not waiting for input.")
    prompt = waiting.prompt_tail[-_ROW_CAP:] or "(no prompt text)"
    return [
        _row("process", waiting.label),
        _row("prompt", prompt),
        *_input_rows(text),
        _row("plan fingerprint", input_fingerprint(process_id, waiting.prompt_seq, text, enter)),
    ]
