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
