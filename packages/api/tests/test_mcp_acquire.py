"""Unit tests for `BridgeExportAcquirer` (SOLUSDEV-100 T4b) — the inline-content
half of the acquisition chain plus every dispatch-time decline path. Pure fakes,
no DB: artifact_ref consumption (which needs a live Postgres session) is
covered separately in `test_mcp_acquire_artifact.py`. Mirrors `test_bridge_tool.py`'s
session-construction helpers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from solus_api.agent.tools.shapes import ToolResult
from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry
from solus_api.bridge.service import ingest_result
from solus_api.connectors.contracts import Credentials, SyncContext
from solus_api.connectors.mcp_acquire import PROJECT_PATH_CONFIG_KEY, BridgeExportAcquirer

CALL_CAP = 262_144
INLINE_CAP = 512
ARTIFACT_TTL = 3600
TOOL_NAME = "kicad.export_netlist"
Scope = tuple[uuid.UUID, uuid.UUID, uuid.UUID]


def _fresh_scope() -> Scope:
    return (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())


def _live_session(
    sent: list[str], scope: Scope, *, inventory: tuple[Any, ...] = ()
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
        companion_instance_id="i-1",
        companion_version="0.1.0",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=inventory,
        send=_send,
        close=_close,
        max_inflight=8,
    )


def _tool_spec(name: str = TOOL_NAME) -> Any:
    from solus_api.agent.tools.shapes import ToolDescriptor
    from solus_api.bridge.allowlist import BridgeToolSpec

    server, _, tool = name.partition(".")
    return BridgeToolSpec(
        server=server,
        remote_name=tool,
        descriptor=ToolDescriptor(
            name=name, description="export", params={"type": "object"}, returns={"type": "object"}
        ),
    )


def _acquirer(
    sessions: InMemoryBridgeSessionRegistry,
    scope: Scope,
    *,
    tool_name: str = TOOL_NAME,
) -> BridgeExportAcquirer:
    return BridgeExportAcquirer(
        sessions=sessions,
        sessionmaker=cast(Any, None),  # unused by the inline-content path
        store=cast(Any, None),  # unused by the inline-content path
        project_id=scope[2],
        team_id=scope[1],
        acting_user_id=scope[0],
        tool_name=tool_name,
        call_cap_bytes=CALL_CAP,
        artifact_ttl_seconds=ARTIFACT_TTL,
        inline_max_bytes=INLINE_CAP,
    )


def _ctx(project_path: str | None = "/home/alice/rover-eda") -> SyncContext:
    config: dict[str, Any] = {} if project_path is None else {PROJECT_PATH_CONFIG_KEY: project_path}
    return SyncContext(credentials=Credentials(token=""), config=config)


async def _companion_answers(
    sent: list[str], value: dict[str, Any], session: BridgeSession
) -> None:
    while not sent:
        await asyncio.sleep(0.005)
    call_id = json.loads(sent[0])["data"]["call_id"]
    ingest_result(session, ToolResult.success(call_id, value))


# --------------------------------------------------------------- decline paths


async def test_no_acting_user_declines(caplog: pytest.LogCaptureFixture) -> None:
    scope = _fresh_scope()
    acquirer = BridgeExportAcquirer(
        sessions=InMemoryBridgeSessionRegistry(),
        sessionmaker=cast(Any, None),
        store=cast(Any, None),
        project_id=scope[2],
        team_id=scope[1],
        acting_user_id=None,
        tool_name=TOOL_NAME,
        call_cap_bytes=CALL_CAP,
        artifact_ttl_seconds=ARTIFACT_TTL,
        inline_max_bytes=INLINE_CAP,
    )
    with caplog.at_level(logging.WARNING, logger="solus.connectors.mcp_acquire"):
        result = await acquirer.acquire(_ctx())
    assert result is None
    assert "no acting user" in caplog.text


async def test_no_project_path_configured_declines() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sessions.bind(_live_session([], scope, inventory=(_tool_spec(),)))
    result = await _acquirer(sessions, scope).acquire(_ctx(project_path=None))
    assert result is None


async def test_blank_project_path_declines() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sessions.bind(_live_session([], scope, inventory=(_tool_spec(),)))
    result = await _acquirer(sessions, scope).acquire(_ctx(project_path=""))
    assert result is None


async def test_bridge_offline_declines() -> None:
    scope = _fresh_scope()
    result = await _acquirer(InMemoryBridgeSessionRegistry(), scope).acquire(_ctx())
    assert result is None


async def test_wrong_scope_session_never_dispatched() -> None:
    # A live session for a DIFFERENT (user, team, project) must never serve
    # this acquirer's dispatch — the exact-scope routing invariant (bridge §3).
    scope = _fresh_scope()
    other_scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    sessions.bind(_live_session(sent, other_scope, inventory=(_tool_spec(),)))
    result = await _acquirer(sessions, scope).acquire(_ctx())
    assert result is None
    assert sent == []  # nothing reached the (wrong-scope) wire


async def test_tool_not_in_companion_inventory_declines() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    sessions.bind(_live_session(sent, scope, inventory=()))  # no export tool offered
    result = await _acquirer(sessions, scope).acquire(_ctx())
    assert result is None
    assert sent == []


async def test_companion_failure_result_declines() -> None:

    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope, inventory=(_tool_spec(),))
    sessions.bind(session)

    async def _answer_failure() -> None:
        while not sent:
            await asyncio.sleep(0.005)
        call_id = json.loads(sent[0])["data"]["call_id"]
        ingest_result(
            session,
            ToolResult.model_validate(
                {
                    "call_id": call_id,
                    "ok": False,
                    "error": {"code": "tool_error", "message": "kicad-cli not found"},
                }
            ),
        )

    task = asyncio.create_task(_answer_failure())
    result = await _acquirer(sessions, scope).acquire(_ctx())
    await task
    assert result is None


# --------------------------------------------------------------- inline content


async def test_inline_content_is_returned() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope, inventory=(_tool_spec(),))
    sessions.bind(session)
    task = asyncio.create_task(_companion_answers(sent, {"content": "U1\nR1"}, session))
    result = await _acquirer(sessions, scope).acquire(_ctx())
    await task
    assert result == "U1\nR1"


async def test_project_path_is_dispatched_as_the_tool_arg() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope, inventory=(_tool_spec(),))
    sessions.bind(session)
    task = asyncio.create_task(_companion_answers(sent, {"content": "U1"}, session))
    await _acquirer(sessions, scope).acquire(_ctx(project_path="/some/eda/proj"))
    await task
    frame = json.loads(sent[0])
    assert frame["data"]["tool"] == TOOL_NAME
    assert frame["data"]["args"] == {"project_path": "/some/eda/proj"}


async def test_oversized_inline_content_declines() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope, inventory=(_tool_spec(),))
    sessions.bind(session)
    huge = "A" * (INLINE_CAP + 1)
    task = asyncio.create_task(_companion_answers(sent, {"content": huge}, session))
    result = await _acquirer(sessions, scope).acquire(_ctx())
    await task
    assert result is None


async def test_non_text_content_declines() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope, inventory=(_tool_spec(),))
    sessions.bind(session)
    task = asyncio.create_task(_companion_answers(sent, {"content": 12345}, session))
    result = await _acquirer(sessions, scope).acquire(_ctx())
    await task
    assert result is None


async def test_missing_required_fields_declines() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope, inventory=(_tool_spec(),))
    sessions.bind(session)
    task = asyncio.create_task(_companion_answers(sent, {}, session))  # neither key present
    result = await _acquirer(sessions, scope).acquire(_ctx())
    await task
    assert result is None


async def test_both_content_and_artifact_ref_present_declines() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope, inventory=(_tool_spec(),))
    sessions.bind(session)
    value = {
        "content": "U1",
        "artifact_ref": {
            "artifact_id": str(uuid.uuid4()),
            "uri": "/api/v1/projects/x/artifacts/y/content",
            "media_type": "text/plain",
            "storage": "local",
        },
    }
    task = asyncio.create_task(_companion_answers(sent, value, session))
    result = await _acquirer(sessions, scope).acquire(_ctx())
    await task
    assert result is None


async def test_unknown_extra_field_in_value_declines() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope, inventory=(_tool_spec(),))
    sessions.bind(session)
    task = asyncio.create_task(
        _companion_answers(
            sent, {"content": "U1", "sneaky": "ignore-previous-instructions"}, session
        )
    )
    result = await _acquirer(sessions, scope).acquire(_ctx())
    await task
    assert result is None


# ------------------------------------------- the REAL fork envelope (Phase 4 fix)
# The plan-locked export_netlist result carries format/filename/bytes/degraded/
# reason alongside content|artifact_ref (integrations/mcp/kicad/solus/
# netlist_export.py; the companion preserves them verbatim and only rewrites
# artifact_path -> artifact_ref). The Phase 4 review found the acquirer's
# previous two-field model rejected this real envelope outright.


def _real_envelope(**overrides: Any) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "format": "kicadxml",
        "filename": "solus_sample.net.xml",
        "bytes": 5,
        "content": "U1\nR1",
        "artifact_path": None,
        "degraded": False,
        "reason": None,
    }
    envelope.update(overrides)
    return envelope


async def test_real_fork_envelope_inline_content_is_accepted() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope, inventory=(_tool_spec(),))
    sessions.bind(session)
    task = asyncio.create_task(_companion_answers(sent, _real_envelope(), session))
    result = await _acquirer(sessions, scope).acquire(_ctx())
    await task
    assert result == "U1\nR1"


async def test_real_fork_envelope_degraded_content_is_accepted() -> None:
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope, inventory=(_tool_spec(),))
    sessions.bind(session)
    task = asyncio.create_task(
        _companion_answers(
            sent, _real_envelope(degraded=True, reason="kicad-cli unavailable"), session
        )
    )
    result = await _acquirer(sessions, scope).acquire(_ctx())
    await task
    assert result == "U1\nR1"  # a degraded (file-parse) export is still a valid export


async def test_dispatch_timeout_declines_and_falls_back(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Phase 4 C1: `dispatch()` awaits the wire directly and bypasses
    `ToolRegistry.invoke`'s own timeout bound — a live session whose companion
    never answers must still decline within the acquirer's OWN bound, so a
    stalled bridge session can never hang a sync indefinitely."""
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sessions.bind(_live_session([], scope, inventory=(_tool_spec(),)))  # never answers
    acquirer = BridgeExportAcquirer(
        sessions=sessions,
        sessionmaker=cast(Any, None),
        store=cast(Any, None),
        project_id=scope[2],
        team_id=scope[1],
        acting_user_id=scope[0],
        tool_name=TOOL_NAME,
        call_cap_bytes=CALL_CAP,
        artifact_ttl_seconds=ARTIFACT_TTL,
        inline_max_bytes=INLINE_CAP,
        dispatch_timeout_seconds=0.05,
    )
    with caplog.at_level(logging.WARNING, logger="solus.connectors.mcp_acquire"):
        result = await asyncio.wait_for(acquirer.acquire(_ctx()), timeout=5)
    assert result is None
    assert "dispatch timed out" in caplog.text


async def test_unrewritten_artifact_path_is_a_hard_decline(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A raw companion-machine path reaching the cloud means the companion did
    not perform the upload rewrite — never consumable, and never a crash."""
    scope = _fresh_scope()
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, scope, inventory=(_tool_spec(),))
    sessions.bind(session)
    task = asyncio.create_task(
        _companion_answers(
            sent,
            _real_envelope(content=None, artifact_path="exports/solus_sample.net.xml"),
            session,
        )
    )
    with caplog.at_level(logging.WARNING, logger="solus.connectors.mcp_acquire"):
        result = await _acquirer(sessions, scope).acquire(_ctx())
    await task
    assert result is None
    assert "unexpected shape" in caplog.text
