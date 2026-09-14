"""Progress binds to the live command; it cannot impersonate another call."""

import json
from typing import Any

from mcp.types import CallToolResult
from solus_companion.dispatch import Dispatcher
from solus_companion.frames import ToolCallIn


async def test_only_valid_command_progress_is_forwarded_before_result() -> None:
    sent = []

    class Supervisor:
        async def call_tool(
            self, server: str, tool: str, args: dict[str, Any], *, progress_callback=None
        ) -> CallToolResult:
            assert progress_callback is not None
            await progress_callback(1, None, json.dumps({"stream": "stdout", "text": "early\n"}))
            await progress_callback(
                2, None, json.dumps({"stream": "stdout", "text": "forged", "call_id": "other"})
            )
            await progress_callback(3, None, json.dumps({"stream": "stderr", "text": "x" * 2049}))
            return CallToolResult(content=[], structuredContent={"ok": True})

    async def send(raw: str) -> None:
        sent.append(json.loads(raw))

    dispatcher = Dispatcher(Supervisor(), send)
    dispatcher.handle_tool_call(ToolCallIn(call_id="owned", tool="code.run", args={}))
    await dispatcher.wait_idle()
    assert [row["type"] for row in sent] == ["tool_output", "tool_result"]
    assert sent[0]["data"] == {
        "call_id": "owned",
        "sequence": 1,
        "stream": "stdout",
        "text": "early\n",
    }


async def test_command_transport_failure_is_never_replayed() -> None:
    from types import SimpleNamespace

    from solus_companion.supervisor import Supervisor

    calls = []

    class Session:
        async def call_tool(self, tool, args, **kwargs):
            calls.append(tool)
            raise OSError("connection lost after command started")

    class Harness:
        async def _revive(self, *args, **kwargs):
            calls.append("revive")
            return Session()

    import pytest

    with pytest.raises(OSError):
        await Supervisor._call_on(Harness(), SimpleNamespace(session=Session()), "code", "run", {})
    assert calls == ["run"]


async def test_callback_after_result_and_disconnect_is_ignored() -> None:
    captured = []
    sent = []

    class Supervisor:
        async def call_tool(self, server, tool, args, *, progress_callback=None):
            captured.append(progress_callback)
            return CallToolResult(content=[], structuredContent={"ok": True})

    async def send(raw):
        sent.append(json.loads(raw))

    dispatcher = Dispatcher(Supervisor(), send)
    dispatcher.handle_tool_call(ToolCallIn(call_id="owned", tool="code.test", args={}))
    await dispatcher.wait_idle()
    await captured[0](1, None, '{"stream":"stdout","text":"late"}')
    dispatcher.cancel_all()
    await captured[0](2, None, '{"stream":"stdout","text":"late"}')
    assert len(sent) == 1 and sent[0]["type"] == "tool_result"


async def test_output_budget_reserves_explicit_truncation_marker(monkeypatch) -> None:

    sent = []

    class Supervisor:
        async def call_tool(self, server, tool, args, *, progress_callback=None):
            for _ in range(400):
                await progress_callback(
                    1, None, json.dumps({"stream": "stdout", "text": "界" * 2048})
                )
            return CallToolResult(content=[], structuredContent={"ok": True})

    async def send(raw):
        sent.append(json.loads(raw))
        dispatcher._next_progress = 0.0

    dispatcher = Dispatcher(Supervisor(), send)
    dispatcher.handle_tool_call(ToolCallIn(call_id="owned", tool="code.run", args={}))
    await dispatcher.wait_idle()
    outputs = [row["data"] for row in sent if row["type"] == "tool_output"]
    assert len(outputs) <= 256
    assert outputs[-1]["truncated"] is True
    assert sum(len(row["text"].encode()) for row in outputs) <= 256 * 1024
    assert [row["sequence"] for row in outputs] == list(range(1, len(outputs) + 1))


async def test_queued_progress_cannot_follow_terminal_result() -> None:
    import asyncio
    import time

    sent = []
    pending = []

    class Supervisor:
        async def call_tool(self, server, tool, args, *, progress_callback=None):
            pending.append(
                asyncio.create_task(progress_callback(1, None, '{"stream":"stdout","text":"late"}'))
            )
            await asyncio.sleep(0.01)
            return CallToolResult(content=[], structuredContent={"ok": True})

    async def send(raw):
        sent.append(json.loads(raw))
        if sent[-1]["type"] == "tool_result":
            await asyncio.sleep(0.1)

    dispatcher = Dispatcher(Supervisor(), send)
    dispatcher._next_progress = time.monotonic() + 0.05
    dispatcher.handle_tool_call(ToolCallIn(call_id="owned", tool="code.run", args={}))
    await dispatcher.wait_idle()
    await asyncio.gather(*pending)
    assert [row["type"] for row in sent] == ["tool_result"]
