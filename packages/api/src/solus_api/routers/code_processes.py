"""Running processes on the caller's own machine (SOLUSDEV-317,
docs/api/code-command-execution.md §6).

Every route goes over the AUTHENTICATED caller's own bridge session for this
project, matched to `machine_id` (`local_folder._live_session`): a teammate's
request resolves to the teammate's session, never another member's, so
processes are never visible or stoppable across members. Stop is the person's
own click — it dispatches `code.process_stop` directly (a user action, not a
model proposal) and is logged as `code.process.stopped {via: "ui"}`.
Process text arrives already redacted at bridge ingress (`ingest_result`).

Input (§11.2) is the person's own typing into an interactive process that is
waiting: it dispatches `code.process_input` directly (no card) after a live
status check, and is logged as `code.process.input {via: "ui"}` — never the text.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Final

from fastapi import APIRouter, Path, Query, Request
from pydantic import Field, StrictBool, StrictStr, model_validator

from solus_api.agent.command_gate import input_payload, stopped_payload
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.process_input_preview import (
    INPUT_TOOL,
    MAX_INPUT_CHARS,
    find_process,
    input_problem,
    waiting_process,
)
from solus_api.bridge.registry import BridgeSession
from solus_api.bridge.service import dispatch
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import BridgeSessionsDep, ProjectCtx, SessionDep, SettingsDep, require_role
from solus_api.extensions.ratelimit import get_or_create_limiter, rate_limited_response
from solus_api.models import Role
from solus_api.routers.local_folder import _live_session
from solus_api.schemas import StrictModel
from solus_api.services.events import emit_event

logger = logging.getLogger("solus.routers.code_processes")

router = APIRouter(prefix="/api/v1/projects/{project_id}/code/processes")

STATUS_TOOL: Final = "code.process_status"
STOP_TOOL: Final = "code.process_stop"
#: The desktop polls the strip and one process's output; stops are clicks.
READ_LIMIT: Final = 120
STOP_LIMIT: Final = 20
#: §11.2: the person's typing, per user and project.
INPUT_LIMIT: Final = 60
_WINDOW_SECONDS: Final = 60
_TIMEOUT_SECONDS: Final = 15.0
_MAX_PROCESSES: Final = 16
#: The server's own answer for a process it does not know (`processes.stop`).
_UNKNOWN: Final = "unknown process"
_PROCESS_KEYS: Final = (
    "process_id",
    "name",
    "argv",
    "cwd",
    "state",
    "pid",
    "exit_code",
    "started_at",
    "ended_at",
    "sandbox",
)

MachineId = Annotated[str, Query(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")]
ProcessId = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


def _limited(request: Request, ctx: ProjectCtx, kind: str, limit: int) -> bool:
    limiter = get_or_create_limiter(
        request.app.state, f"code_process_{kind}_limiter", _WINDOW_SECONDS
    )
    return limiter.bump(f"{ctx.user.id}:{ctx.project.id}") > limit


def _offers(live: BridgeSession | None, tool: str) -> bool:
    return live is not None and any(spec.descriptor.name == tool for spec in live.inventory)


async def _call(
    live: BridgeSession, tool: str, args: dict[str, Any], call_cap: int
) -> dict[str, Any] | None:
    try:
        async with asyncio.timeout(_TIMEOUT_SECONDS):
            result = await dispatch(live, tool, args, call_cap_bytes=call_cap)
    except (TimeoutError, ToolException):
        logger.info("%s declined", tool)
        return None
    return result.value if result.ok and isinstance(result.value, dict) else None


def _processes(value: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = value.get("processes") if value is not None else None
    if not isinstance(rows, list):
        return []
    return [_process_row(row) for row in rows[:_MAX_PROCESSES] if isinstance(row, dict)]


def _process_row(row: dict[str, Any]) -> dict[str, Any]:
    """The strip's row; the §11.1 interactive fields default to "not waiting"."""
    seq, tail = row.get("prompt_seq"), row.get("prompt_tail")
    return {
        **{key: row.get(key) for key in _PROCESS_KEYS},
        "interactive": row.get("interactive") is True,
        "awaiting_input": row.get("awaiting_input") is True,
        "prompt_seq": seq if type(seq) is int and seq >= 0 else 0,
        "prompt_tail": tail if isinstance(tail, str) else "",
    }


@router.get("")
async def list_processes(
    request: Request,
    ctx: ProjectCtx,
    sessions: BridgeSessionsDep,
    settings: SettingsDep,
    machine_id: MachineId,
) -> Any:
    require_role(ctx, Role.MEMBER)
    if _limited(request, ctx, "read", READ_LIMIT):
        return rate_limited_response("Too many process checks; wait a minute", _WINDOW_SECONDS)
    live = _live_session(sessions, ctx, machine_id)
    if live is None:
        return envelope({"bridge": {"connected": False}, "processes": []})
    value = (
        await _call(live, STATUS_TOOL, {}, settings.bridge_tool_call_max_bytes)
        if _offers(live, STATUS_TOOL)
        else None
    )
    return envelope({"bridge": {"connected": True}, "processes": _processes(value)})


@router.get("/{process_id}/output")
async def process_output(
    request: Request,
    ctx: ProjectCtx,
    sessions: BridgeSessionsDep,
    settings: SettingsDep,
    process_id: ProcessId,
    machine_id: MachineId,
    cursor: Annotated[int, Query(ge=0)] = 0,
) -> Any:
    require_role(ctx, Role.MEMBER)
    if _limited(request, ctx, "read", READ_LIMIT):
        return rate_limited_response("Too many process checks; wait a minute", _WINDOW_SECONDS)
    live = _live_session(sessions, ctx, machine_id)
    value = (
        await _call(
            live,
            STATUS_TOOL,
            {"process_id": process_id, "cursor": cursor},
            settings.bridge_tool_call_max_bytes,
        )
        if live is not None and _offers(live, STATUS_TOOL)
        else None
    )
    output = value.get("output") if value is not None else None
    if not isinstance(output, dict) or output.get("process_id") != process_id:
        raise APIError(404, "not_found", "No such process.")
    return envelope({"output": output})


@router.post("/{process_id}/stop")
async def stop_process(
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    sessions: BridgeSessionsDep,
    settings: SettingsDep,
    process_id: ProcessId,
    machine_id: MachineId,
) -> Any:
    require_role(ctx, Role.MEMBER)
    if _limited(request, ctx, "stop", STOP_LIMIT):
        return rate_limited_response("Too many stop requests; wait a minute", _WINDOW_SECONDS)
    live = _live_session(sessions, ctx, machine_id)
    if live is None or not _offers(live, STOP_TOOL):
        raise APIError(409, "bridge_offline", "This machine is not connected.")
    value = await _call(
        live, STOP_TOOL, {"process_id": process_id}, settings.bridge_tool_call_max_bytes
    )
    if value is not None and value.get("ok") is not True and value.get("reason") == _UNKNOWN:
        raise APIError(404, "not_found", "No such running process.")
    if value is None or value.get("ok") is not True:
        # §9 item 14: no confirmed result within the bound — it may have landed.
        raise APIError(
            504, "stop_unconfirmed", "The stop was sent but not confirmed; check the process list."
        )
    emit_event(
        session,
        user=ctx.user,
        event_type="code.process.stopped",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload=stopped_payload("ui", value),
    )
    await session.commit()
    return envelope({key: value.get(key) for key in ("ok", "process_id", "state", "exit_code")})


class ProcessInput(StrictModel):
    """`{text, enter}` (§11.1 bounds): printable text, a newline only via `enter`."""

    text: StrictStr = Field(default="", max_length=MAX_INPUT_CHARS)
    enter: StrictBool = True

    @model_validator(mode="after")
    def _bounded(self) -> ProcessInput:
        problem = input_problem(self.text, self.enter)
        if problem is not None:
            raise ValueError(problem)
        return self


def _not_waiting() -> APIError:
    return APIError(409, "not_waiting", "This process is not waiting for input.")


@router.post("/{process_id}/input")
async def send_process_input(
    request: Request,
    body: ProcessInput,
    ctx: ProjectCtx,
    session: SessionDep,
    sessions: BridgeSessionsDep,
    settings: SettingsDep,
    process_id: ProcessId,
    machine_id: MachineId,
) -> Any:
    """The person's own input box or Enter button (§11.2): a user action, no card."""
    require_role(ctx, Role.MEMBER)
    if _limited(request, ctx, "input", INPUT_LIMIT):
        return rate_limited_response("Too much input; wait a minute", _WINDOW_SECONDS)
    live = _live_session(sessions, ctx, machine_id)
    if live is None or not (_offers(live, INPUT_TOOL) and _offers(live, STATUS_TOOL)):
        raise APIError(409, "bridge_offline", "This machine is not connected.")
    cap = settings.bridge_tool_call_max_bytes
    status = await _call(live, STATUS_TOOL, {"process_id": process_id}, cap)
    if status is None:
        raise APIError(409, "bridge_offline", "This machine did not answer.")
    if find_process(status, process_id) is None:
        raise APIError(404, "not_found", "No such process.")
    if waiting_process(status, process_id) is None:
        raise _not_waiting()
    args = {"process_id": process_id, "text": body.text, "enter": body.enter}
    value = await _call(live, INPUT_TOOL, args, cap)
    if value is None:
        raise APIError(
            504, "input_unconfirmed", "The input was sent but not confirmed; check the process."
        )
    if value.get("ok") is not True:
        if value.get("reason") == _UNKNOWN:
            raise APIError(404, "not_found", "No such process.")
        raise _not_waiting()
    emit_event(
        session,
        user=ctx.user,
        event_type="code.process.input",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload=input_payload("ui", value, auto=False),
    )
    await session.commit()
    sent = value.get("sent_chars")
    return envelope(
        {"ok": True, "process_id": process_id, "sent_chars": sent if type(sent) is int else 0}
    )
