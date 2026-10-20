"""Build auto-run for a no-risk `code.exec` (SOLUSDEV-317 follow-up).

docs/api/code-command-execution.md §10.1 and the ADR-031 amendment of
2026-10-19. Pure helpers, no authority of their own: `BuildExecutionPolicy`
asks `auto_eligible` BEFORE any preview, then requires two identical complete
previews whose plan says `program_scope: "system"`. Anything that fails a
check falls through to the normal park gate, so a risky call gets its card.

The other two helpers shape an auto-run's result: `stream_view` is what the
desktop renders from the SSE `tool_result` frame, `model_result` is what the
model reads in the same turn (the 3000-char outcome tail of §5.3, not the raw
16 KiB tails).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from solus_api.agent.command_gate import event_program
from solus_api.agent.command_outcome import command_outcome_text
from solus_api.agent.command_policy import classify
from solus_api.agent.tools.shapes import ToolErrorCode, ToolResult
from solus_api.agent.tools.untrusted import redact_text

AUTO_COMMAND_TOOL: Final = "code.exec"
#: §11.2: a bare Enter to a waiting interactive process may skip its card.
AUTO_INPUT_TOOL: Final = "code.process_input"
#: The code-owned tools Build may run without a card, each re-judged per call.
AUTO_TOOLS: Final = frozenset({AUTO_COMMAND_TOOL, AUTO_INPUT_TOOL})
#: The only `code.plan` `program_scope` that may skip the card (§10.1).
SYSTEM_SCOPE: Final = "system"
#: Each stream tail is capped at the server's own tail size.
STREAM_TAIL_BYTES: Final = 16 * 1024
_OUTCOME_PREFIX: Final = "ran automatically in Build"
#: Raw tails (too long for the model) and the keys `model_result` writes itself.
_NOT_FOR_MODEL: Final = frozenset({"stdout_tail", "stderr_tail", "auto", "outcome"})
_ARGS: Final = frozenset({"argv", "cwd", "environment", "profile", "timeout_seconds"})
_MAX_TIMEOUT: Final = 600
_INPUT_ARGS: Final = frozenset({"process_id", "text", "enter"})


def _relative_dir(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not value.startswith(("/", "~"))
        and ".." not in value.split("/")
    )


def _optional_name(value: object) -> bool:
    return value is None or (isinstance(value, str) and bool(value))


def auto_eligible(args: Mapping[str, Any]) -> bool:
    """Whether a `code.exec` call MAY skip its card, judged on its arguments
    alone: the spec's argument shape exactly (nothing a widened schema could
    add) and a CommandPolicy verdict with no risk (project code is a risk)."""
    if not set(args) <= _ARGS or "argv" not in args:
        return False
    timeout = args.get("timeout_seconds", 1)
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        return False
    if not 1 <= timeout <= _MAX_TIMEOUT or not _relative_dir(args.get("cwd", ".")):
        return False
    if not (_optional_name(args.get("environment")) and _optional_name(args.get("profile"))):
        return False
    verdict = classify(args["argv"])
    return not verdict.denied and not verdict.risks


def enter_only_eligible(args: Mapping[str, Any]) -> bool:
    """Whether a `code.process_input` call MAY skip its card (§11.2): exactly a
    process id and a bare Enter — `text` empty or absent, `enter` true or absent.
    Whether the process is interactive and waiting is the preview's to decide."""
    if not set(args) <= _INPUT_ARGS or not isinstance(args.get("process_id"), str):
        return False
    return args.get("text", "") == "" and args.get("enter", True) is True


def auto_judge(tool: str, args: Mapping[str, Any]) -> bool:
    """The per-call, argument-only eligibility for each Build auto tool."""
    if tool == AUTO_COMMAND_TOOL:
        return auto_eligible(args)
    return tool == AUTO_INPUT_TOOL and enter_only_eligible(args)


def _value(result: ToolResult) -> dict[str, Any]:
    return result.value if result.ok and isinstance(result.value, dict) else {}


def _status(result: ToolResult) -> str:
    if not result.ok:
        timed_out = result.error is not None and result.error.code is ToolErrorCode.TIMEOUT
        return "timed out" if timed_out else "was not run"
    value = _value(result)
    if value.get("timed_out") is True:
        return "timed out"
    code = value.get("exit_code")
    return f"exited {code}" if type(code) is int else "was not run"


def _tail(text: object) -> str:
    """Printable, redacted, and at most `STREAM_TAIL_BYTES` of UTF-8 — the END
    of the output, which is where a failure says what went wrong."""
    if not isinstance(text, str):
        return ""
    printable = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    data = redact_text(printable).encode()[-STREAM_TAIL_BYTES:]
    return data.decode(errors="ignore")


def stream_view(result: ToolResult, argv: object) -> dict[str, Any]:
    """The desktop's fields for an auto-run, merged into its `tool_result` frame."""
    value = _value(result)
    return {
        "tool": AUTO_COMMAND_TOOL,
        "auto": True,
        "program": event_program(value.get("argv")) or event_program(argv),
        "status": _status(result),
        "stdout_tail": _tail(value.get("stdout_tail")),
        "stderr_tail": _tail(value.get("stderr_tail")),
    }


def model_result(result: ToolResult) -> ToolResult:
    """What the model reads: the §5.3 outcome clause (≤ 3000-char tail) first,
    then the command facts — without the raw tails, which would overflow the
    tool-result cap and cut off the end of the output."""
    if not result.ok or not isinstance(result.value, dict):
        return result
    outcome = command_outcome_text(result.value, tool=AUTO_COMMAND_TOOL) or ""
    facts = {k: v for k, v in result.value.items() if k not in _NOT_FOR_MODEL}
    value = {"auto": True, "outcome": _OUTCOME_PREFIX + outcome, **facts}
    return result.model_copy(update={"value": value})
