"""`BridgeFolderAcquirer` (SOLUSDEV-249) — every decline path plus the happy path,
with a fake bridge session (mirrors `test_mcp_acquire.py`). No DB."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from solus_api.agent.tools.shapes import ToolDescriptor, ToolError, ToolErrorCode, ToolResult
from solus_api.bridge.allowlist import BridgeToolSpec
from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry
from solus_api.bridge.service import ingest_result
from solus_api.connectors.local_acquire import BridgeFolderAcquirer
from solus_api.connectors.local_folder import DIGEST_TOOL, SCAN_TOOL

MACHINE = "b" * 32
Scope = tuple[uuid.UUID, uuid.UUID, uuid.UUID]


def _scope() -> Scope:
    return (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())


def _spec(name: str) -> BridgeToolSpec:
    server, _, tool = name.partition(".")
    return BridgeToolSpec(
        server=server,
        remote_name=tool,
        descriptor=ToolDescriptor(
            name=name, description="d", params={"type": "object"}, returns={"type": "object"}
        ),
    )


def _session(
    sent: list[str], scope: Scope, *, machine: str = MACHINE, tools: tuple[str, ...] = ()
) -> BridgeSession:
    async def _send(frame: str) -> None:
        sent.append(frame)

    async def _close(code: int) -> None:
        return None

    return BridgeSession(
        session_id=uuid.uuid4().hex,
        user_id=scope[0],
        team_id=scope[1],
        project_id=scope[2],
        companion_instance_id=machine,
        companion_version="0.1.0",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=tuple(_spec(t) for t in tools),
        send=_send,
        close=_close,
        max_inflight=8,
    )


def _acquirer(
    sessions: InMemoryBridgeSessionRegistry, scope: Scope, *, user: uuid.UUID | None = None
) -> BridgeFolderAcquirer:
    return BridgeFolderAcquirer(
        sessions=sessions,
        project_id=scope[2],
        team_id=scope[1],
        acting_user_id=scope[0] if user is None else user,
        call_cap_bytes=262_144,
        dispatch_timeout_seconds=0.5,
    )


def _config(machine: str = MACHINE, user: uuid.UUID | None = None) -> dict[str, Any]:
    return {
        "machine_id": machine,
        "machine_name": "mbp",
        "folder_name": "rover",
        "user_id": str(user) if user else None,
    }


def _scan_value() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "root_name": "rover",
        "git": None,
        "files": [{"parts": ["a.py"], "size": 1, "hash": None, "tool": "python"}],
        "digest": "ab" * 16,
        "truncated": False,
        "tools_installed": {"kicad": False},
    }


async def _answer(sent: list[str], session: BridgeSession, value: dict[str, Any]) -> None:
    while not sent:
        await asyncio.sleep(0.005)
    call = json.loads(sent[0])["data"]
    ingest_result(session, ToolResult.success(call["call_id"], value))


async def _fail(sent: list[str], session: BridgeSession) -> None:
    while not sent:
        await asyncio.sleep(0.005)
    call = json.loads(sent[0])["data"]
    ingest_result(
        session,
        ToolResult.failure(
            call["call_id"], ToolError(code=ToolErrorCode.TOOL_ERROR, message="boom")
        ),
    )


async def test_declines_without_acting_user() -> None:
    sessions = InMemoryBridgeSessionRegistry()
    scope = _scope()
    acquirer = BridgeFolderAcquirer(
        sessions=sessions,
        project_id=scope[2],
        team_id=scope[1],
        acting_user_id=None,
        call_cap_bytes=1000,
        dispatch_timeout_seconds=0.2,
    )
    assert await acquirer.scan(_config(user=scope[0])) is None
    assert await acquirer.digest(_config(user=scope[0])) is None


async def test_declines_when_source_belongs_to_another_user() -> None:
    """Security review H1: a member's companion never scans into a teammate's source."""
    sessions = InMemoryBridgeSessionRegistry()
    scope = _scope()
    sent: list[str] = []
    sessions.bind(_session(sent, scope, tools=(SCAN_TOOL, DIGEST_TOOL)))
    assert await _acquirer(sessions, scope).scan(_config(user=uuid.uuid4())) is None
    assert sent == []


async def test_declines_when_bridge_offline() -> None:
    sessions = InMemoryBridgeSessionRegistry()
    scope = _scope()
    assert await _acquirer(sessions, scope).scan(_config(user=scope[0])) is None


async def test_declines_when_machine_does_not_match_the_source() -> None:
    sessions = InMemoryBridgeSessionRegistry()
    scope = _scope()
    sent: list[str] = []
    sessions.bind(_session(sent, scope, machine="c" * 32, tools=(SCAN_TOOL, DIGEST_TOOL)))
    assert await _acquirer(sessions, scope).scan(_config(user=scope[0])) is None
    assert sent == []  # never dispatched to the wrong machine


async def test_declines_when_tool_not_offered() -> None:
    sessions = InMemoryBridgeSessionRegistry()
    scope = _scope()
    sent: list[str] = []
    sessions.bind(_session(sent, scope, tools=()))
    assert await _acquirer(sessions, scope).scan(_config(user=scope[0])) is None
    assert sent == []


async def test_declines_on_bad_machine_id_in_config() -> None:
    sessions = InMemoryBridgeSessionRegistry()
    scope = _scope()
    sent: list[str] = []
    sessions.bind(_session(sent, scope, tools=(SCAN_TOOL,)))
    assert await _acquirer(sessions, scope).scan({"machine_id": "nope"}) is None
    assert sent == []


async def test_declines_on_timeout() -> None:
    sessions = InMemoryBridgeSessionRegistry()
    scope = _scope()
    sent: list[str] = []
    sessions.bind(_session(sent, scope, tools=(SCAN_TOOL,)))
    assert await _acquirer(sessions, scope).scan(_config(user=scope[0])) is None
    assert len(sent) == 1


async def test_declines_on_tool_failure() -> None:
    sessions = InMemoryBridgeSessionRegistry()
    scope = _scope()
    sent: list[str] = []
    session = _session(sent, scope, tools=(SCAN_TOOL,))
    sessions.bind(session)
    task = asyncio.create_task(_fail(sent, session))
    assert await _acquirer(sessions, scope).scan(_config(user=scope[0])) is None
    await task


async def test_declines_on_malformed_scan() -> None:
    sessions = InMemoryBridgeSessionRegistry()
    scope = _scope()
    sent: list[str] = []
    session = _session(sent, scope, tools=(SCAN_TOOL,))
    sessions.bind(session)
    hostile = {**_scan_value(), "artifact_path": "/tmp/x"}
    task = asyncio.create_task(_answer(sent, session, hostile))
    assert await _acquirer(sessions, scope).scan(_config(user=scope[0])) is None
    await task


async def test_scan_round_trip() -> None:
    sessions = InMemoryBridgeSessionRegistry()
    scope = _scope()
    sent: list[str] = []
    session = _session(sent, scope, tools=(SCAN_TOOL, DIGEST_TOOL))
    sessions.bind(session)
    task = asyncio.create_task(_answer(sent, session, _scan_value()))
    scan = await _acquirer(sessions, scope).scan(_config(user=scope[0]))
    await task
    assert scan is not None
    assert scan.root_name == "rover"
    frame = json.loads(sent[0])
    assert frame["type"] == "tool_call"
    assert frame["data"]["tool"] == SCAN_TOOL
    assert frame["data"]["args"] == {}


async def test_digest_round_trip() -> None:
    sessions = InMemoryBridgeSessionRegistry()
    scope = _scope()
    sent: list[str] = []
    session = _session(sent, scope, tools=(SCAN_TOOL, DIGEST_TOOL))
    sessions.bind(session)
    task = asyncio.create_task(_answer(sent, session, {"digest": "cd" * 16, "truncated": False}))
    digest = await _acquirer(sessions, scope).digest(_config(user=scope[0]))
    await task
    assert digest == "cd" * 16
    assert json.loads(sent[0])["data"]["tool"] == DIGEST_TOOL
