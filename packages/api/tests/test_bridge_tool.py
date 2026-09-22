"""Unit tests for BridgeTool — the W0-04 Tool kind routing via a companion."""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolDescriptor, ToolErrorCode, ToolResult
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry
from solus_api.bridge.service import ingest_result
from solus_api.bridge.tool import BridgeTool

CALL_CAP = 262_144
Scope = tuple[uuid.UUID, uuid.UUID, uuid.UUID]


def _echo_descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        name="mock.echo",
        description="echo",
        params={"type": "object"},
        returns={"type": "object"},
    )


def _live_session(sent: list[str], scope: Scope) -> BridgeSession:
    async def _send(frame: str) -> None:
        sent.append(frame)

    async def _close(code: int) -> None:
        return None

    return BridgeSession(
        session_id=uuid.uuid4().hex,
        user_id=scope[0],
        team_id=scope[1],
        project_id=scope[2],
        companion_instance_id="i-1",
        companion_version="0.1.0",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=(),
        send=_send,
        close=_close,
        max_inflight=8,
    )


def _bridge_tool(sessions: InMemoryBridgeSessionRegistry, scope: Scope) -> BridgeTool:
    return BridgeTool(
        descriptor=_echo_descriptor(),
        sessions=sessions,
        user_id=scope[0],
        team_id=scope[1],
        project_id=scope[2],
        call_cap_bytes=CALL_CAP,
    )


def _fresh_scope() -> Scope:
    return (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())


async def _companion_answers(
    sent: list[str], value: dict[str, Any] | None, session: BridgeSession
) -> None:
    while not sent:
        await asyncio.sleep(0.005)
    call_id = json.loads(sent[0])["data"]["call_id"]
    if value is not None:
        ingest_result(session, ToolResult.success(call_id, value))
    else:
        ingest_result(
            session,
            ToolResult.model_validate(
                {
                    "call_id": call_id,
                    "ok": False,
                    "error": {"code": "unauthorized", "message": "m" * 900, "retryable": False},
                }
            ),
        )


async def test_offline_fails_fast_and_retryable() -> None:
    tool = _bridge_tool(InMemoryBridgeSessionRegistry(), _fresh_scope())
    with pytest.raises(ToolException) as exc_info:
        await tool.invoke({})
    assert exc_info.value.retryable is True
    assert exc_info.value.code is ToolErrorCode.UNAVAILABLE
    assert "bridge offline" in str(exc_info.value)


async def test_happy_invoke_returns_value() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope)
    sessions.bind(session)
    answer = asyncio.create_task(_companion_answers(sent, {"result": "hi"}, session))
    value = await _bridge_tool(sessions, scope).invoke({"text": "hi"})
    await answer
    assert value == {"result": "hi"}


async def test_companion_error_maps_code_retryable_and_caps_message() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope)
    sessions.bind(session)
    answer = asyncio.create_task(_companion_answers(sent, None, session))
    with pytest.raises(ToolException) as exc_info:
        await _bridge_tool(sessions, scope).invoke({})
    await answer
    assert exc_info.value.code is ToolErrorCode.UNAUTHORIZED
    assert exc_info.value.retryable is False
    assert len(str(exc_info.value)) == 500  # untrusted text capped


async def test_cross_scope_session_is_never_used() -> None:
    # A live session for ANOTHER scope must not serve this tool (§3 invariant).
    sessions = InMemoryBridgeSessionRegistry()
    sessions.bind(_live_session([], _fresh_scope()))
    with pytest.raises(ToolException) as exc_info:
        await _bridge_tool(sessions, _fresh_scope()).invoke({})
    assert "bridge offline" in str(exc_info.value)


async def test_through_tool_registry_never_raises_and_times_out() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope)
    sessions.bind(session)
    registry = ToolRegistry(default_timeout=0.05)
    registry.register(_bridge_tool(sessions, scope))
    result = await registry.invoke(ToolCall(tool="mock.echo", args={}))  # never answered
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.TIMEOUT
    assert result.error.retryable is True
    assert session.inflight == {}  # wait_for cancellation popped the wire call


async def test_confirmation_gate_refuses_destructive_dispatch() -> None:
    """SEC-H1: a requires_confirmation tool is structurally un-dispatchable
    until the confirmation flow exists — the central gate refuses it and the
    wire never sees a frame."""
    from solus_api.agent.runtime import confirmation_refusal

    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope)
    sessions.bind(session)
    registry = ToolRegistry()
    flash = BridgeTool(
        descriptor=ToolDescriptor(
            name="mock.flash_firmware",
            description="flash",
            params={"type": "object"},
            returns={"type": "object"},
            requires_confirmation=True,
        ),
        sessions=sessions,
        user_id=scope[0],
        team_id=scope[1],
        project_id=scope[2],
        call_cap_bytes=CALL_CAP,
    )
    registry.register(flash)
    registry.register(_bridge_tool(sessions, scope))  # unflagged sibling

    call = ToolCall(tool="mock.flash_firmware", args={})
    refusal = confirmation_refusal(registry, call)
    assert refusal is not None
    assert refusal.ok is False and refusal.error is not None
    assert refusal.error.code is ToolErrorCode.UNAUTHORIZED
    assert refusal.error.retryable is False
    assert "confirmation" in refusal.error.message
    assert sent == []  # nothing ever reached the wire

    assert confirmation_refusal(registry, ToolCall(tool="mock.echo", args={})) is None
    assert confirmation_refusal(registry, ToolCall(tool="ghost.tool", args={})) is None


async def test_scaffold_runner_consults_the_gate() -> None:
    """The runner path itself refuses flagged calls (dispatch never happens)."""
    from unittest.mock import AsyncMock

    from solus_api.agent.runtime import confirmation_refusal

    registry = ToolRegistry()

    class _Flagged:
        descriptor = ToolDescriptor(
            name="flash",
            description="d",
            params={"type": "object"},
            returns={"type": "object"},
            requires_confirmation=True,
        )
        invoke = AsyncMock()

    registry.register(_Flagged())
    refusal = confirmation_refusal(registry, ToolCall(tool="flash", args={}))
    assert refusal is not None
    _Flagged.invoke.assert_not_awaited()


# --- G2: the card must show what will actually EXECUTE ------------------------
# `machine.run_command` in a conda env silently gains a `conda run -n ...` argv
# prefix, and `install_package` resolves an interpreter the caller never named.
# Argument rows show neither, so the approver was consenting to something other
# than what would run. The opted-in tools re-issue their own call with
# `dry_run: true` and render the resolved plan.

RUN_PLAN: dict[str, Any] = {
    "dry_run": True,
    "argv": ["conda", "run", "-n", "robot", "--no-capture-output", "python", "train.py"],
    "cwd": "/home/e/ws",
    "env": {"PATH": "/usr/bin", "VIRTUAL_ENV": "/home/e/ws/.venv"},
}


@pytest.mark.parametrize(
    "name",
    [
        "create_schematic",
        "add_symbol",
        "add_wire",
        "add_net_label",
        "mark_no_connect",
    ],
)
async def test_schematic_preview_uses_exact_companion_diff(name: str) -> None:
    tool = _machine_tool(InMemoryBridgeSessionRegistry(), _fresh_scope(), f"kicad.{name}")
    assert getattr(tool, "requires_complete_preview", False) is True
    diff = [
        {"label": "Symbol", "before": None, "after": "R1 · 10 kΩ"},
        {"label": "File fingerprint", "before": "old:hash", "after": "new:hash"},
    ]
    rows, seen = await _rows(
        f"kicad.{name}",
        {"schematic_path": "robot.kicad_sch"},
        {
            "dry_run": True,
            "preview": diff,
        },
    )
    assert rows == diff
    assert seen == [{"schematic_path": "robot.kicad_sch", "dry_run": True}]


@pytest.mark.parametrize(
    "diff",
    [
        [{"label": "x", "before": None, "after": "a" * 401}],
        [{"label": "x", "before": None, "after": "x", "command": "untrusted"}],
        [{"label": "x", "before": [], "after": "x"}],
        [{"label": "x", "before": None, "after": "x"}] * 41,
    ],
)
def test_malformed_companion_diff_cannot_be_rendered_as_consent(diff) -> None:
    from solus_api.bridge.tool import _plan_rows

    assert _plan_rows({"dry_run": True, "preview": diff}) == []


async def test_required_schematic_preview_never_accepts_legacy_command_rows() -> None:
    rows, _ = await _rows(
        "kicad.add_symbol",
        {"schematic_path": "robot.kicad_sch"},
        {"dry_run": True, "argv": ["unrelated"], "path": "unrelated"},
    )
    assert rows == []


@pytest.mark.parametrize("name", ["code.git_commit", "code.git_push"])
async def test_git_operations_require_complete_state_bound_previews(name: str) -> None:
    tool = _machine_tool(InMemoryBridgeSessionRegistry(), _fresh_scope(), name)
    assert tool.requires_complete_preview is True
    diff = [{"label": "Repository state", "before": "old", "after": "new"}]
    rows, seen = await _rows(
        name, {"expected_head": "observed"}, {"dry_run": True, "preview": diff}
    )
    assert rows == diff
    assert seen == [{"expected_head": "observed", "dry_run": True}]
    rows, _ = await _rows(name, {}, {"dry_run": True, "argv": ["git", "commit"]})
    assert rows == []


async def test_complete_git_preview_preserves_indentation_and_newlines() -> None:
    patch = "@@ -1 +1 @@\n-    run()\n+\trun()\n"
    diff = [{"label": "Complete staged diff", "before": None, "after": patch}]
    rows, _ = await _rows("code.git_commit", {}, {"dry_run": True, "preview": diff})
    assert rows == diff


@pytest.mark.parametrize("control", ["\x00", "\x1b", "\u202e"])
async def test_complete_preview_refuses_hidden_control_characters(control: str) -> None:
    rows, _ = await _rows(
        "code.git_commit",
        {},
        {
            "dry_run": True,
            "preview": [{"label": "Change", "before": None, "after": "safe" + control + "hidden"}],
        },
    )
    assert rows == []


def _machine_tool(sessions: InMemoryBridgeSessionRegistry, scope: Scope, name: str) -> BridgeTool:
    return BridgeTool(
        descriptor=ToolDescriptor(
            name=name,
            description="d",
            params={"type": "object"},
            returns={"type": "object"},
            requires_confirmation=True,
            consent_summary="does something on your machine",
        ),
        sessions=sessions,
        user_id=scope[0],
        team_id=scope[1],
        project_id=scope[2],
        call_cap_bytes=CALL_CAP,
    )


async def _fake_companion(
    sent: list[str],
    session: BridgeSession,
    reply: dict[str, Any],
    seen: list[dict[str, Any]],
    *,
    fail: bool = False,
) -> None:
    """Answers one call with `reply`, recording the args it was really given."""
    while len(sent) <= len(seen):
        await asyncio.sleep(0.005)
    data = json.loads(sent[len(seen)])["data"]
    seen.append(data["args"])
    if fail:
        ingest_result(
            session,
            ToolResult.model_validate(
                {
                    "call_id": data["call_id"],
                    "ok": False,
                    "error": {"code": "internal", "message": "boom", "retryable": False},
                }
            ),
        )
    else:
        ingest_result(session, ToolResult.success(data["call_id"], reply))


async def _rows(
    name: str, args: dict[str, Any], reply: dict[str, Any], *, fail: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from solus_api.agent.confirmations import _build_preview

    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope)
    sessions.bind(session)
    seen: list[dict[str, Any]] = []
    answer = asyncio.create_task(_fake_companion(sent, session, reply, seen, fail=fail))
    try:
        rows = await _build_preview(_machine_tool(sessions, scope, name), args)
    finally:
        answer.cancel()
    return rows, seen


async def test_preview_shows_the_resolved_argv_cwd_and_environment() -> None:
    rows, seen = await _rows(
        "machine.run_command",
        {"argv": ["python", "train.py"], "env_name": "robot"},
        RUN_PLAN,
    )
    # The preview is the SAME call with one added flag — nothing else changes.
    assert seen == [{"argv": ["python", "train.py"], "env_name": "robot", "dry_run": True}]
    by = {row["label"]: row["after"] for row in rows}
    assert by["command"] == "conda run -n robot --no-capture-output python train.py"
    assert by["cwd"] == "/home/e/ws"
    assert by["environment"] == "/home/e/ws/.venv"


async def test_preview_shows_the_interpreter_an_install_runs_into() -> None:
    rows, _ = await _rows(
        "machine.install_package",
        {"manager": "pip", "package": "numpy"},
        {
            "dry_run": True,
            "argv": ["/ws/.venv/bin/python", "-m", "pip", "install", "numpy"],
            "cwd": "/ws",
            "env": {},
        },
    )
    by = {row["label"]: row["after"] for row in rows}
    assert by["command"] == "/ws/.venv/bin/python -m pip install numpy"


async def test_preview_shows_every_step_of_a_multi_step_plan() -> None:
    rows, _ = await _rows(
        "machine.create_environment",
        {"kind": "venv", "name": "vision", "packages": ["torch"]},
        {
            "dry_run": True,
            "kind": "venv",
            "name": "vision",
            "path": "/ws/vision",
            "steps": [
                ["/usr/bin/python3", "-m", "venv", "/ws/vision"],
                ["/ws/vision/bin/python", "-m", "pip", "install", "torch"],
            ],
        },
    )
    by = {row["label"]: row["after"] for row in rows}
    assert by["path"] == "/ws/vision"
    assert by["step 1"] == "/usr/bin/python3 -m venv /ws/vision"
    assert by["step 2"] == "/ws/vision/bin/python -m pip install torch"


async def test_a_tool_without_the_flag_is_never_called_with_dry_run() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    sessions.bind(_live_session(sent, scope))
    tool = _machine_tool(sessions, scope, "machine.write_file")
    assert getattr(tool, "preview", None) is None  # not advertised ⇒ not sent

    from solus_api.agent.confirmations import _build_preview

    rows = await _build_preview(tool, {"path": "a.txt", "content": "hi"})
    assert sent == []
    assert rows == [
        {"label": "content", "before": None, "after": "hi"},
        {"label": "path", "before": None, "after": "a.txt"},
    ]


async def test_a_failing_dry_run_degrades_to_argument_rows() -> None:
    rows, seen = await _rows("machine.run_command", {"argv": ["rm", "-rf", "x"]}, {}, fail=True)
    assert seen == [{"argv": ["rm", "-rf", "x"], "dry_run": True}]
    assert rows == [{"label": "argv", "before": None, "after": '["rm", "-rf", "x"]'}]


async def test_a_companion_that_ignores_dry_run_never_becomes_the_card() -> None:
    # `dry_run: false` back means it RAN, not that it planned — refuse to render
    # an execution result as a preview; the args (which do execute) stand instead.
    rows, _ = await _rows(
        "machine.run_command",
        {"argv": ["make"]},
        {"dry_run": False, "argv": ["make"], "cwd": "/ws", "exit_code": 0},
    )
    assert rows == [{"label": "argv", "before": None, "after": '["make"]'}]


async def test_incremental_output_is_correlated_and_never_finishes_call() -> None:
    from solus_api.agent.command_output import OutputBuffer, current_output
    from solus_api.bridge.frames import ToolOutputData
    from solus_api.bridge.service import dispatch, ingest_output

    sent: list[str] = []
    session = _live_session(sent, _fresh_scope())
    output = OutputBuffer()
    token = current_output.set(output)
    try:
        task = asyncio.create_task(dispatch(session, "code.run", {}, call_cap_bytes=CALL_CAP))
        await asyncio.sleep(0)
        call_id = json.loads(sent[0])["data"]["call_id"]
        chunk = ToolOutputData(call_id=call_id, sequence=1, stream="stdout", text="first\n")
        ingest_output(_live_session([], _fresh_scope()), chunk)
        assert output.chunks == []
        ingest_output(session, chunk)
        ingest_output(session, chunk)
        assert output.chunks[0]["text"] == "first\n" and not task.done()
        ingest_result(session, ToolResult.success(call_id, {"exit_code": 0}))
        await task
        ingest_output(session, chunk.model_copy(update={"sequence": 2}))
        assert len(output.chunks) == 1
        assert not session.output_sinks and not session.output_limits
    finally:
        current_output.reset(token)


async def test_output_byte_budget_and_sender_marker_are_explicit() -> None:
    from solus_api.agent.command_output import OutputBuffer, current_output
    from solus_api.bridge.frames import ToolOutputData
    from solus_api.bridge.service import dispatch, ingest_output

    sent: list[str] = []
    session = _live_session(sent, _fresh_scope())
    output = OutputBuffer()
    token = current_output.set(output)
    task = asyncio.create_task(dispatch(session, "code.run", {}, call_cap_bytes=CALL_CAP))
    try:
        await asyncio.sleep(0)
        call_id = json.loads(sent[0])["data"]["call_id"]
        for sequence in range(1, 35):
            ingest_output(
                session,
                ToolOutputData(
                    call_id=call_id, sequence=sequence, stream="stdout", text="😀" * 2047 + "\n"
                ),
            )
        assert output.truncated
        assert len(str(output.chunks)) < 270000
        ingest_result(session, ToolResult.success(call_id, {}))
        await task
    finally:
        task.cancel()
        current_output.reset(token)
