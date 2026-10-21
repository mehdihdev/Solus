"""What a confirmed COMMAND did, in the words the next model reads.

SOLUSDEV-250 introduced the outcome clause; SOLUSDEV-317
(docs/api/code-command-execution.md §5.3) widens the tail for the commands
whose output IS the answer (`code.exec`, `code.run`, `code.test`: 3000 chars),
reports a started process, and warns when a command touched `.git/hooks` or
`.git/config`. Every piece of machine text goes through `redact_text`.
"""

from __future__ import annotations

from typing import Any, Final

from solus_api.agent.errors_filing import UNCERTAIN_COMMAND_OUTCOME, command_failure
from solus_api.agent.tools.untrusted import redact_text

_OUTCOME_TAIL_CAP: Final = 400
#: §5.3: the commands whose printed output is what SOL must reason over.
_LONG_TAIL_CAP: Final = 3000
LONG_TAIL_TOOLS: Final = frozenset({"code.exec", "code.run", "code.test"})
_REASON_CAP: Final = 200
_ID_CAP: Final = 64
_GIT_WARNING: Final = "; WARNING: the command modified .git/hooks or .git/config"


def output_tail(value: dict[str, Any], cap: int) -> str:
    """The last `cap` characters of what the command printed — stdout then
    stderr. pytest reports its FAILED lines on stdout; a crashing script puts
    its traceback on stderr; keeping only one of them loses the other.

    Security review H3: this text is persisted (Error logging, the tool turn)
    and replayed into the next prompt's history block, so it goes through the
    same scalar redaction as every other untrusted machine text, and control
    characters never ride along."""
    parts = [
        str(value[key]).strip()
        for key in ("stdout_tail", "stderr_tail")
        if isinstance(value.get(key), str) and str(value[key]).strip()
    ]
    joined = "\n".join(parts)
    printable = "".join(ch for ch in joined if ch.isprintable() or ch == "\n")
    return redact_text(printable)[-cap:]


def _single(value: object, cap: int) -> str:
    return output_tail({"stderr_tail": str(value)}, cap).replace("\n", " ")


def _process_started(value: dict[str, Any]) -> str:
    process_id = value.get("process_id")
    if value.get("ok") is True and isinstance(process_id, str) and process_id:
        pid = value.get("pid")
        pid_text = f" (pid {pid})" if type(pid) is int else ""
        return f"; started process {_single(process_id, _ID_CAP)}{pid_text}"
    reason = _single(value.get("reason") or "unknown reason", _REASON_CAP)
    return f"; the server refused to run it: {reason}"


def _input_sent(value: dict[str, Any]) -> str:
    """§11.2: what an approved `code.process_input` did — a count, never the text."""
    process_id = value.get("process_id")
    sent = value.get("sent_chars")
    if value.get("ok") is True and isinstance(process_id, str) and type(sent) is int:
        return f"; sent {sent} characters to process {_single(process_id, _ID_CAP)}"
    reason = _single(value.get("reason") or "unknown reason", _REASON_CAP)
    return f"; the server refused the input: {reason}"


def command_outcome_text(value: dict[str, Any], *, tool: str | None = None) -> str | None:
    """A short clause naming what a confirmed COMMAND did, for the tool turn
    the next model reads (SOLUSDEV-250). `ToolResult.ok` is the transport; the
    command's own exit lives in the value, and without it the model can only
    say "applied ok" about a test run that failed. Command evidence includes
    exit codes, timeouts, uncertainty, or failed ordered results. A null exit
    without evidence of execution retains the legacy refusal meaning. A reason
    alone is not command evidence (`local.open_in_tool` may return one)."""
    if tool == "code.process_start":
        return _process_started(value)
    if tool == "code.process_input":
        return _input_sent(value)
    long_tail = tool in LONG_TAIL_TOOLS
    clause = _command_clause(
        value, _LONG_TAIL_CAP if long_tail else _OUTCOME_TAIL_CAP, success_tail=long_tail
    )
    if clause is not None and value.get("git_metadata_changed") is True:
        return clause + _GIT_WARNING
    return clause


def _command_clause(value: dict[str, Any], cap: int, *, success_tail: bool = False) -> str | None:
    """`success_tail` (§9 item 7): exec/run/test print the answer, so exit 0
    carries its output tail too."""
    if value.get("uncertain") is True:
        return "; " + UNCERTAIN_COMMAND_OUTCOME
    if value.get("timed_out") is True:
        return _timeout_outcome(value, cap)
    if "exit_code" not in value:
        failure = command_failure(value)
        if failure is None:
            return None
        return "; the command " + output_tail({"stderr_tail": failure}, _OUTCOME_TAIL_CAP)
    exit_code = value["exit_code"]
    reason = output_tail({"stderr_tail": str(value.get("reason") or "unknown reason")}, _REASON_CAP)
    if value.get("ok") is False and (
        (value.get("started") is True and exit_code is None)
        or (type(exit_code) is int and exit_code == 0)
    ):
        tail = output_tail(value, cap)
        return f"; the command failed: {reason}" + (f" — output tail: {tail}" if tail else "")
    if exit_code is None:
        return f"; the server refused to run it: {reason}"
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        return None
    if exit_code == 0:
        if value.get("ok") is True and value.get("started") is False:
            return "; verified existing result; no command was started"
        tail = output_tail(value, cap) if success_tail else ""
        return "; the command exited 0" + (f" — output tail: {tail}" if tail else "")
    tail = output_tail(value, cap)
    return f"; the command exited {exit_code}" + (f" — output tail: {tail}" if tail else "")


def _timeout_outcome(value: dict[str, Any], cap: int) -> str:
    if value.get("started") is False:
        return "; the command did not start before its deadline"
    tail = output_tail(value, cap)
    return "; the command timed out" + (f" — output tail: {tail}" if tail else "")
