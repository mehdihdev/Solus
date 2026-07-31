"""Channel: handshake, dispatch wiring, close-code policy, redial backoff."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult
from solus_companion.channel import (
    STOP_MAX_ATTEMPTS,
    STOP_SUPERSEDED,
    STOP_UPDATE_REQUIRED,
    run_channel,
)
from solus_companion.config import CompanionConfig, TokenBox, apply_token_line
from websockets.asyncio.server import ServerConnection, serve

ACK = '{"type":"hello_ack","data":{"protocol_version":1}}'
Handler = Callable[[ServerConnection], Awaitable[None]]


class FakeSupervisor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.status_changed = asyncio.Event()
        self._states: dict[str, str] = {"mock": "ready"}

    def set_state(self, name: str, state: str) -> None:
        self._states[name] = state
        self.status_changed.set()

    def status_snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "state": state,
                "detail": None,
                "updated_at": "2026-07-23T00:00:00+00:00",
            }
            for name, state in self._states.items()
        ]

    def inventory(self) -> list[dict[str, Any]]:
        return [
            {
                "server": "mock",
                "tools": [
                    {
                        "name": "echo",
                        "description": "",
                        "input_schema": {"type": "object"},
                        "output_schema": None,
                    }
                ],
            }
        ]

    async def call_tool(self, server: str, tool: str, args: dict[str, Any]) -> CallToolResult:
        self.calls.append((server, tool, args))
        return CallToolResult(content=[], structuredContent={"result": "ok"}, isError=False)


def _config(url: str, token_source: Callable[[], str] | None = None) -> CompanionConfig:
    return CompanionConfig(
        url=url,
        token_source=token_source if token_source is not None else lambda: "tok-1",
        integrations_root=Path("."),
        instance_id="a" * 32,
        ping_interval=30.0,  # keep pings out of these tests
    )


async def _recv_type(ws: ServerConnection, frame_type: str) -> dict[str, Any]:
    """Skip interleaved frames (e.g. status) until `frame_type` arrives."""
    while True:
        frame: dict[str, Any] = json.loads(await ws.recv())
        if frame["type"] == frame_type:
            return frame


@asynccontextmanager
async def stub_server(handler: Handler) -> AsyncIterator[str]:
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


async def _run(config: CompanionConfig, supervisor: FakeSupervisor, **kwargs: Any) -> Any:
    return await asyncio.wait_for(
        run_channel(config, supervisor, backoff_base=0.01, backoff_cap=0.05, **kwargs),
        timeout=10,
    )


async def test_sends_auth_header_and_hello_inventory() -> None:
    captured: dict[str, Any] = {}

    async def handler(ws: ServerConnection) -> None:
        captured["auth"] = ws.request.headers.get("Authorization") if ws.request else None
        captured["hello"] = json.loads(await ws.recv())
        await ws.send(ACK)
        await ws.close(4409, "superseded")

    supervisor = FakeSupervisor()
    async with stub_server(handler) as url:
        state = await _run(_config(url), supervisor, max_attempts=3)
    assert captured["auth"] == "Bearer tok-1"
    hello = captured["hello"]
    assert hello["type"] == "hello"
    assert hello["data"]["protocol_version"] == 1
    assert hello["data"]["companion_instance_id"] == "a" * 32
    assert hello["data"]["servers"] == supervisor.inventory()
    assert state.stop_reason == STOP_SUPERSEDED


async def test_tool_call_gets_tool_result() -> None:
    captured: dict[str, Any] = {}

    async def handler(ws: ServerConnection) -> None:
        await ws.recv()  # hello
        await ws.send(ACK)
        await ws.send(
            '{"type":"tool_call","data":{"tool":"mock.echo","args":{"text":"hi"},"call_id":"c1"}}'
        )
        captured["result"] = await _recv_type(ws, "tool_result")
        await ws.close(4409, "superseded")

    supervisor = FakeSupervisor()
    async with stub_server(handler) as url:
        state = await _run(_config(url), supervisor, max_attempts=3)
    assert state.stop_reason == STOP_SUPERSEDED
    assert captured["result"] == {
        "type": "tool_result",
        "data": {"call_id": "c1", "ok": True, "value": {"result": "ok"}},
    }
    assert supervisor.calls == [("mock", "echo", {"text": "hi"})]


async def test_4409_stops_without_redial() -> None:
    connections = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        await ws.recv()  # hello
        await ws.close(4409, "superseded")

    async with stub_server(handler) as url:
        state = await _run(_config(url), FakeSupervisor(), max_attempts=5)
    assert state.stop_reason == STOP_SUPERSEDED
    assert state.attempts == 1
    assert connections == 1


async def test_4400_stops_with_update_required() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()  # hello
        error = {"code": "unsupported_protocol_version", "message": "supported: 1"}
        await ws.send(json.dumps({"type": "error", "data": error}))
        await ws.close(4400, "unsupported")

    async with stub_server(handler) as url:
        state = await _run(_config(url), FakeSupervisor(), max_attempts=5)
    assert state.stop_reason == STOP_UPDATE_REQUIRED
    assert state.attempts == 1


async def test_4401_refreshes_token_and_redials() -> None:
    tokens_served = 0
    seen_tokens: list[str | None] = []

    def token_source() -> str:
        nonlocal tokens_served
        tokens_served += 1
        return f"tok-{tokens_served}"

    async def handler(ws: ServerConnection) -> None:
        seen_tokens.append(ws.request.headers.get("Authorization") if ws.request else None)
        await ws.recv()  # hello
        await ws.close(4401, "expired")

    async with stub_server(handler) as url:
        state = await _run(_config(url, token_source), FakeSupervisor(), max_attempts=3)
    assert state.stop_reason == STOP_MAX_ATTEMPTS
    assert tokens_served == 3
    assert seen_tokens == ["Bearer tok-1", "Bearer tok-2", "Bearer tok-3"]


async def test_generic_close_redials_with_backoff() -> None:
    connections = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        await ws.recv()  # hello
        await ws.close()  # normal close: not a stop code

    async with stub_server(handler) as url:
        state = await _run(_config(url), FakeSupervisor(), max_attempts=3)
    assert state.stop_reason == STOP_MAX_ATTEMPTS
    assert state.attempts == 3
    assert connections == 3


async def test_unknown_frame_is_ignored() -> None:
    captured: dict[str, Any] = {}

    async def handler(ws: ServerConnection) -> None:
        await ws.recv()  # hello
        await ws.send(ACK)
        await ws.send('{"type":"weird_new_frame","data":{"x":1}}')
        await ws.send('{"type":"tool_call","data":{"tool":"mock.echo","args":{},"call_id":"c2"}}')
        captured["result"] = await _recv_type(ws, "tool_result")
        await ws.close(4409, "superseded")

    async with stub_server(handler) as url:
        state = await _run(_config(url), FakeSupervisor(), max_attempts=3)
    assert state.stop_reason == STOP_SUPERSEDED
    assert captured["result"]["data"]["call_id"] == "c2"
    assert captured["result"]["data"]["ok"] is True


async def test_status_snapshot_sent_after_hello_ack() -> None:
    captured: dict[str, Any] = {}

    async def handler(ws: ServerConnection) -> None:
        await ws.recv()  # hello
        await ws.send(ACK)
        captured["status"] = json.loads(await ws.recv())  # first post-ack frame
        await ws.close(4409, "superseded")

    supervisor = FakeSupervisor()
    async with stub_server(handler) as url:
        state = await _run(_config(url), supervisor, max_attempts=3)
    assert state.stop_reason == STOP_SUPERSEDED
    assert captured["status"]["type"] == "status"
    assert captured["status"]["data"] == {"servers": supervisor.status_snapshot()}


async def test_status_burst_coalesces_to_latest_state() -> None:
    frames_seen: list[dict[str, Any]] = []
    supervisor = FakeSupervisor()

    async def handler(ws: ServerConnection) -> None:
        await ws.recv()  # hello
        await ws.send(ACK)
        frames_seen.append(await _recv_type(ws, "status"))  # initial snapshot
        for burst_state in ("busy", "ready", "busy", "error"):
            supervisor.set_state("mock", burst_state)  # rapid burst, no awaits
        frames_seen.append(await _recv_type(ws, "status"))  # ONE coalesced frame
        try:  # and no third frame within another coalesce window
            frames_seen.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=0.15)))
        except TimeoutError:
            pass
        await ws.close(4409, "superseded")

    async with stub_server(handler) as url:
        state = await _run(_config(url), supervisor, max_attempts=3, status_coalesce=0.05)
    assert state.stop_reason == STOP_SUPERSEDED
    assert len(frames_seen) == 2
    assert frames_seen[0]["data"]["servers"][0]["state"] == "ready"
    assert frames_seen[1]["data"]["servers"][0]["state"] == "error"  # latest wins


async def test_token_line_updates_next_dial_auth() -> None:
    box = TokenBox("tok-old")
    auths: list[str | None] = []

    async def handler(ws: ServerConnection) -> None:
        auths.append(ws.request.headers.get("Authorization") if ws.request else None)
        await ws.recv()  # hello
        if len(auths) == 1:
            apply_token_line(box, b'{"type":"token","access_token":"tok-new"}')
            await ws.close(4401, "expired")
        else:
            await ws.close(4409, "superseded")

    async with stub_server(handler) as url:
        state = await _run(_config(url, box), FakeSupervisor(), max_attempts=5)
    assert state.stop_reason == STOP_SUPERSEDED
    assert auths == ["Bearer tok-old", "Bearer tok-new"]


async def test_signout_idles_until_new_token_arrives() -> None:
    box = TokenBox()  # empty: signed out from the start
    connections = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        await ws.recv()  # hello
        await ws.close(4409, "superseded")

    async with stub_server(handler) as url:
        channel = asyncio.create_task(
            run_channel(_config(url, box), FakeSupervisor(), backoff_base=0.01, max_attempts=5)
        )
        await asyncio.sleep(0.2)
        assert connections == 0  # idles instead of dialing with a blank token
        box.set("tok-fresh")
        state = await asyncio.wait_for(channel, timeout=10)
    assert connections == 1
    assert state.attempts == 1
    assert state.stop_reason == STOP_SUPERSEDED
