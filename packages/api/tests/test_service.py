"""Unit + integration tests for the bridge channel service (contract §3/§5/§7)."""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools.shapes import ToolResult
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry
from solus_api.bridge.service import (
    SUPERSEDED_EVENT,
    ConnectRateLimiter,
    TokenBucket,
    dispatch,
    fail_inflight,
    ingest_result,
    supersede,
)
from solus_api.models import DataEvent, User
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

CALL_CAP = 262_144


def _session(
    sent: list[str] | None = None, closed: list[int] | None = None, **overrides: Any
) -> BridgeSession:
    async def _send(frame: str) -> None:
        if sent is None:
            raise ConnectionError("socket gone")
        sent.append(frame)

    async def _close(code: int) -> None:
        if closed is not None:
            closed.append(code)

    fields: dict[str, Any] = {
        "session_id": uuid.uuid4().hex,
        "user_id": uuid.uuid4(),
        "team_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "companion_instance_id": "instance-a",
        "companion_version": "0.1.0",
        "protocol_version": 1,
        "connected_at": datetime.now(UTC),
        "token_exp": datetime.now(UTC),
        "inventory": (),
        "send": _send,
        "close": _close,
        "max_inflight": 8,
    }
    fields.update(overrides)
    return BridgeSession(**fields)


def _wire_call_id(frame: str) -> str:
    call_id = json.loads(frame)["data"]["call_id"]
    assert isinstance(call_id, str)
    return call_id


async def test_dispatch_round_trip_redacts_and_cleans_up() -> None:
    sent: list[str] = []
    session = _session(sent)
    task = asyncio.create_task(
        dispatch(session, "mock.echo", {"text": "hi"}, call_cap_bytes=CALL_CAP)
    )
    await asyncio.sleep(0.01)
    call_id = _wire_call_id(sent[0])
    ingest_result(
        session,
        ToolResult.success(call_id, {"text": "hi", "api_key": "leaked", "n": 1}),
    )
    result = await task
    assert result.ok and result.value == {"text": "hi", "api_key": "[REDACTED]", "n": 1}
    assert session.inflight == {}  # cleaned up


async def test_dispatch_failure_result_passes_through() -> None:
    sent: list[str] = []
    session = _session(sent)
    task = asyncio.create_task(dispatch(session, "mock.boom", {}, call_cap_bytes=CALL_CAP))
    await asyncio.sleep(0.01)
    failure = ToolResult.model_validate(
        {
            "call_id": _wire_call_id(sent[0]),
            "ok": False,
            "error": {"code": "tool_error", "message": "kaboom", "retryable": False},
        }
    )
    ingest_result(session, failure)
    result = await task
    assert result.ok is False and result.error is not None and result.error.message == "kaboom"


async def test_unknown_and_duplicate_results_are_dropped() -> None:
    sent: list[str] = []
    session = _session(sent)
    ingest_result(session, ToolResult.success("never-issued", {"x": 1}))  # no crash
    task = asyncio.create_task(dispatch(session, "mock.echo", {}, call_cap_bytes=CALL_CAP))
    await asyncio.sleep(0.01)
    call_id = _wire_call_id(sent[0])
    ingest_result(session, ToolResult.success(call_id, {"first": True}))
    ingest_result(session, ToolResult.success(call_id, {"second": True}))  # dropped
    result = await task
    assert result.value == {"first": True}


async def test_overflow_fails_fast_retryable() -> None:
    session = _session([])
    session.entered = session.max_inflight * 2
    with pytest.raises(ToolException) as exc_info:
        await dispatch(session, "mock.echo", {}, call_cap_bytes=CALL_CAP)
    assert exc_info.value.retryable is True
    assert "busy" in str(exc_info.value)


async def test_oversize_args_fail_permanently() -> None:
    session = _session([])
    with pytest.raises(ToolException) as exc_info:
        await dispatch(session, "mock.echo", {"blob": "x" * CALL_CAP}, call_cap_bytes=CALL_CAP)
    assert exc_info.value.retryable is False
    assert session.inflight == {}


async def test_send_failure_is_retryable_disconnect() -> None:
    session = _session(sent=None)  # send raises
    with pytest.raises(ToolException) as exc_info:
        await dispatch(session, "mock.echo", {}, call_cap_bytes=CALL_CAP)
    assert exc_info.value.retryable is True
    assert session.inflight == {}


async def test_fail_inflight_resolves_pending_retryable() -> None:
    sent: list[str] = []
    session = _session(sent)
    task = asyncio.create_task(dispatch(session, "mock.echo", {}, call_cap_bytes=CALL_CAP))
    await asyncio.sleep(0.01)
    fail_inflight(session, "bridge disconnected")
    with pytest.raises(ToolException) as exc_info:
        await task
    assert exc_info.value.retryable is True
    assert session.inflight == {}


async def test_cancelled_dispatch_drops_late_result() -> None:
    sent: list[str] = []
    session = _session(sent)
    task = asyncio.create_task(dispatch(session, "mock.sleepy", {}, call_cap_bytes=CALL_CAP))
    await asyncio.sleep(0.01)
    call_id = _wire_call_id(sent[0])
    task.cancel()  # what ToolRegistry.invoke's wait_for does on timeout
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.inflight == {}
    ingest_result(session, ToolResult.success(call_id, {"late": True}))  # dropped, no crash


def test_token_bucket_burst_then_sustained() -> None:
    bucket = TokenBucket(rate=20.0, burst=3)
    assert [bucket.allow() for _ in range(4)] == [True, True, True, False]
    bucket.updated -= 1.0  # a second passes → 20 tokens refill (capped at burst)
    assert bucket.allow() is True


def test_connect_rate_limiter_per_key_window() -> None:
    limiter = ConnectRateLimiter(limit_per_minute=2)
    assert limiter.allow("u1") and limiter.allow("u1")
    assert limiter.allow("u1") is False
    assert limiter.allow("u2") is True  # separate key unaffected
    window_start, count = limiter._counts["u1"]
    limiter._counts["u1"] = (window_start - 61.0, count)  # window expires
    assert limiter.allow("u1") is True


async def test_supersede_closes_4409_fails_calls_and_emits_event(
    app: FastAPI, client: AsyncClient, engine: AsyncEngine, alice_headers: dict[str, str]
) -> None:
    me = (await client.get("/api/v1/users/me", headers=alice_headers)).json()["data"]
    user_id = uuid.UUID(me["id"])
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as db:
        await db.execute(
            update(User).where(User.id == user_id).values(data_collection_consent=True)
        )
        await db.commit()
    team_id, project_id = uuid.uuid4(), uuid.uuid4()
    sent: list[str] = []
    closed: list[int] = []
    old = _session(sent, closed, user_id=user_id, team_id=team_id, project_id=project_id)
    new = _session(
        [],
        None,
        user_id=user_id,
        team_id=team_id,
        project_id=project_id,
        companion_instance_id="instance-b",
    )
    pending = asyncio.create_task(dispatch(old, "mock.echo", {}, call_cap_bytes=CALL_CAP))
    await asyncio.sleep(0.01)
    await supersede(old, new, sessionmaker)
    with pytest.raises(ToolException) as exc_info:
        await pending
    assert exc_info.value.retryable is True
    assert closed == [4409]
    async with sessionmaker() as db:
        row = (
            await db.execute(select(DataEvent).where(DataEvent.event_type == SUPERSEDED_EVENT))
        ).scalar_one()
    assert row.payload["old_companion_instance_id"] == "instance-a"
    assert row.payload["new_companion_instance_id"] == "instance-b"


def test_registry_bind_supersede_and_remove_semantics() -> None:
    registry = InMemoryBridgeSessionRegistry()
    a = _session([])
    assert registry.bind(a) is None
    assert registry.get(a.user_id, a.team_id, a.project_id) is a
    b = _session([], user_id=a.user_id, team_id=a.team_id, project_id=a.project_id)
    assert registry.bind(b) is a  # same scope → supersede
    registry.remove(a)  # late cleanup of the OLD session must not evict b
    assert registry.get(a.user_id, a.team_id, a.project_id) is b
    registry.remove(b)
    assert registry.get(a.user_id, a.team_id, a.project_id) is None
    assert registry.count_for_team(a.team_id) == 0


async def test_error_message_is_redacted_at_ingress() -> None:
    # SEC-M3: secrets in a FAILED result's message never reach a consumer.
    sent: list[str] = []
    session = _session(sent)
    task = asyncio.create_task(dispatch(session, "mock.boom", {}, call_cap_bytes=CALL_CAP))
    await asyncio.sleep(0.01)
    failure = ToolResult.model_validate(
        {
            "call_id": _wire_call_id(sent[0]),
            "ok": False,
            "error": {"code": "tool_error", "message": "boom api_key=sk-EXFIL retry later"},
        }
    )
    ingest_result(session, failure)
    result = await task
    assert result.error is not None
    assert "sk-EXFIL" not in result.error.message
    assert "[REDACTED]" in result.error.message
