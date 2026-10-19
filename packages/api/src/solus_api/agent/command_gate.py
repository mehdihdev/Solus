"""The cloud CommandPolicy at the confirmation gate, and the command events.

docs/api/code-command-execution.md §4, §5.1 and §5.6. `request_confirmation`
calls `policy_refusal` BEFORE anything is previewed or parked, so a denied
argv never reaches the machine (not even its read-only `code.plan`), never
lands in Postgres and never renders on a card. Event payloads carry the program
BASENAME only — never the argv, its arguments or profile variable names.
"""

from __future__ import annotations

import posixpath
import re
import uuid
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.command_policy import CommandVerdict, classify
from solus_api.agent.tools.shapes import ToolCall, ToolError, ToolErrorCode, ToolResult
from solus_api.models import User
from solus_api.services.events import emit_event

#: Tools whose model-proposed argv the policy judges (§4).
ARGV_TOOLS: Final = frozenset({"code.exec", "code.process_start"})
#: Tools whose card is the server's complete `code.plan` (§5.1): a failed plan
#: refuses, and a card row that redaction would alter refuses too (§9 item 2).
COMPLETE_PREVIEW_TOOLS: Final = ARGV_TOOLS | frozenset({"code.profile_capture"})
#: Tools a resume may follow and whose approved result is a command outcome (§5.5).
COMMAND_TOOLS: Final = ARGV_TOOLS | frozenset(
    {
        "code.run",
        "code.test",
        "code.install",
        "code.create_environment",
        "code.profile_capture",
    }
)
_SANDBOX_KIND: Final = re.compile(r"^(?:sandbox-exec|landlock(?:-abi[0-9]{1,2})?)$")


def _basename(argv: object) -> str | None:
    if isinstance(argv, list | tuple) and argv and isinstance(argv[0], str) and argv[0]:
        return posixpath.basename(argv[0])[:128] or None
    return None


def denial_message(verdict: CommandVerdict) -> str:
    return (
        f"This command was refused before approval: {verdict.reason}. Propose a direct argv "
        "instead — one program and its arguments, no shell, no &&, no pipes, no redirection. "
        "Nothing was parked or run."
    )


async def policy_refusal(
    session: AsyncSession,
    call: ToolCall,
    *,
    user_id: uuid.UUID,
    team_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ToolResult | None:
    """The INVALID_ARGS refusal for a denied argv, or None to continue."""
    if call.tool not in ARGV_TOOLS:
        return None
    verdict = classify(call.args.get("argv"))
    if not verdict.denied:
        return None
    await record_proposed(
        session,
        call.tool,
        call.args.get("argv"),
        verdict,
        user_id=user_id,
        team_id=team_id,
        project_id=project_id,
    )
    return ToolResult.failure(
        call.call_id,
        ToolError(
            code=ToolErrorCode.INVALID_ARGS, message=denial_message(verdict), retryable=False
        ),
    )


async def record_proposed(
    session: AsyncSession,
    tool: str,
    argv: object,
    verdict: CommandVerdict,
    *,
    user_id: uuid.UUID,
    team_id: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """`sol.command.proposed` — called for a denial and (with the verdict of the
    parked argv) when a command card is parked."""
    user = await session.get(User, user_id)
    if user is None:
        return
    emit_event(
        session,
        user=user,
        event_type="sol.command.proposed",
        team_id=team_id,
        project_id=project_id,
        payload={
            "tool": tool,
            "program": _basename(argv),
            "risks": [risk.value for risk in verdict.risks],
            "denied": verdict.denied,
        },
    )


def completion_events(
    tool: str, args: dict[str, Any], value: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    """Events for an APPROVED command tool that returned `value` (§5.6)."""
    events: list[tuple[str, dict[str, Any]]] = []
    if tool in COMMAND_TOOLS:
        sandbox = value.get("sandbox")
        events.append(
            (
                "sol.command.completed",
                {
                    "tool": tool,
                    "program": _basename(value.get("argv")) or _basename(args.get("argv")),
                    "exit_code": value.get("exit_code")
                    if type(value.get("exit_code")) is int
                    else None,
                    "timed_out": value.get("timed_out") is True,
                    "duration_ms": value.get("duration_ms")
                    if type(value.get("duration_ms")) is int
                    else None,
                    "sandbox": sandbox
                    if isinstance(sandbox, str) and _SANDBOX_KIND.fullmatch(sandbox)
                    else None,
                    "git_metadata_changed": value.get("git_metadata_changed") is True,
                },
            )
        )
    if tool == "code.process_stop" and value.get("ok") is True:
        events.append(("code.process.stopped", stopped_payload("sol", value)))
    if tool == "code.profile_capture" and value.get("ok") is True:
        events.append(
            (
                "code.profile.captured",
                {
                    "variable_count": _count(value.get("variables")),
                    "dropped_count": _count(value.get("dropped")),
                },
            )
        )
    return events


def stopped_payload(via: str, value: dict[str, Any]) -> dict[str, Any]:
    state = value.get("state")
    return {"via": via, "state": state if isinstance(state, str) else None}


def _count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0
