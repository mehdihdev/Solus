"""SOLUSDEV-317 — `code.exec` streams like `code.run`/`code.test`, and no command
tool that may already have acted is ever replayed after a transport failure
(docs/api/code-command-execution.md §2.3, §5.4)."""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.shared.session import ProgressFnT
from mcp.types import CallToolResult
from solus_companion.dispatch import STREAMING_CODE_TOOLS, Dispatcher
from solus_companion.frames import ToolCallIn
from solus_companion.supervisor import NEVER_REPLAYED_CODE_TOOLS, Supervisor

#: Unbound so fakes can stand in for the supervisor and the handle.
CALL_ON: Any = Supervisor._call_on

NEVER_REPLAYED = {
    "run",
    "test",
    "exec",
    "process_start",
    "process_stop",
    "profile_capture",
    "profile_delete",
    "install",
    "create_environment",
}


def test_streaming_and_never_replayed_sets_are_the_documented_ones() -> None:
    assert STREAMING_CODE_TOOLS == frozenset({"run", "test", "exec"})
    assert NEVER_REPLAYED_CODE_TOOLS == frozenset(NEVER_REPLAYED)


async def test_exec_progress_is_relayed_before_the_result() -> None:
    sent: list[dict[str, Any]] = []

    class FakeSupervisor:
        async def call_tool(
            self,
            server: str,
            tool: str,
            args: dict[str, Any],
            *,
            progress_callback: ProgressFnT | None = None,
        ) -> CallToolResult:
            assert (server, tool) == ("code", "exec")
            assert progress_callback is not None
            await progress_callback(1, None, json.dumps({"stream": "stderr", "text": "built\n"}))
            return CallToolResult(content=[], structuredContent={"ok": True})

    async def send(raw: str) -> None:
        sent.append(json.loads(raw))

    dispatcher = Dispatcher(FakeSupervisor(), send)
    dispatcher.handle_tool_call(ToolCallIn(call_id="c1", tool="code.exec", args={"argv": ["ls"]}))
    await dispatcher.wait_idle()
    assert [row["type"] for row in sent] == ["tool_output", "tool_result"]
    assert sent[0]["data"]["stream"] == "stderr" and sent[0]["data"]["text"] == "built\n"


@pytest.mark.parametrize("tool", ["process_start", "profile_capture", "process_status"])
async def test_non_streaming_command_tools_get_no_progress_callback(tool: str) -> None:
    seen: list[object] = []

    class FakeSupervisor:
        async def call_tool(
            self,
            server: str,
            tool: str,
            args: dict[str, Any],
            *,
            progress_callback: ProgressFnT | None = None,
        ) -> CallToolResult:
            seen.append(progress_callback)
            return CallToolResult(content=[], structuredContent={"ok": True})

    async def send(_raw: str) -> None:
        return None

    dispatcher = Dispatcher(FakeSupervisor(), send)
    dispatcher.handle_tool_call(ToolCallIn(call_id="c1", tool=f"code.{tool}", args={}))
    await dispatcher.wait_idle()
    assert seen == [None]


@pytest.mark.parametrize("tool", sorted(NEVER_REPLAYED))
async def test_failed_command_tool_errors_are_not_retryable(tool: str) -> None:
    sent: list[dict[str, Any]] = []

    class FakeSupervisor:
        async def call_tool(self, *_args: Any, **_kwargs: Any) -> CallToolResult:
            raise OSError("connection lost after the command started")

    async def send(raw: str) -> None:
        sent.append(json.loads(raw))

    dispatcher = Dispatcher(FakeSupervisor(), send)
    dispatcher.handle_tool_call(ToolCallIn(call_id="c1", tool=f"code.{tool}", args={}))
    await dispatcher.wait_idle()
    (result,) = sent
    assert result["data"]["error"]["retryable"] is False, tool


@pytest.mark.parametrize("tool", sorted(NEVER_REPLAYED))
async def test_supervisor_never_replays_an_acting_command_tool(tool: str) -> None:
    calls: list[str] = []

    class Session:
        async def call_tool(self, name: str, args: dict[str, Any], **_kwargs: Any) -> Any:
            calls.append(name)
            raise OSError("connection lost after the command started")

    class Harness:
        async def _revive(self, *_args: Any, **_kwargs: Any) -> Session:
            calls.append("revive")
            return Session()

    with pytest.raises(OSError):
        await CALL_ON(Harness(), SimpleNamespace(session=Session()), "code", tool, {})
    assert calls == [tool]


@pytest.mark.parametrize("tool", ["process_status", "profile_list", "plan"])
async def test_read_tools_still_get_one_restart(tool: str) -> None:
    calls: list[str] = []

    class Dead:
        async def call_tool(self, name: str, args: dict[str, Any], **_kwargs: Any) -> Any:
            calls.append(name)
            raise OSError("gone")

    class Fresh:
        async def call_tool(self, name: str, args: dict[str, Any], **_kwargs: Any) -> Any:
            calls.append(f"fresh:{name}")
            return CallToolResult(content=[], structuredContent={"ok": True})

    class Harness:
        async def _revive(self, *_args: Any, **_kwargs: Any) -> Fresh:
            calls.append("revive")
            return Fresh()

    await CALL_ON(Harness(), SimpleNamespace(session=Dead()), "code", tool, {})
    assert calls == [tool, "revive", f"fresh:{tool}"]
