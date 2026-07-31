"""Tool-call dispatch: cloud `tool_call` frames → local MCP → `tool_result`.

Each call runs as its own asyncio task so a slow tool never blocks the
receive loop. Exactly one `tool_result` goes back per `tool_call`; a
duplicate LIVE call_id is a protocol violation and is dropped. After a
disconnect (`cancel_all`) nothing is buffered or sent — the cloud already
failed those calls, and a reconnect is a new session (contract §5).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from mcp.types import CallToolResult, TextContent

from solus_companion.frames import ToolCallIn, tool_result_error, tool_result_ok
from solus_companion.supervisor import UnknownToolError

logger = logging.getLogger("solus.companion.dispatch")

SendFn = Callable[[str], Awaitable[None]]
NON_TEXT_NOTE = "non-text content omitted (ArtifactRef plumbing pending)"


class ToolCaller(Protocol):
    """What dispatch needs from the supervisor (tests use fakes)."""

    async def call_tool(self, server: str, tool: str, args: dict[str, Any]) -> CallToolResult: ...


def map_result(call_id: str, result: CallToolResult) -> str:
    """Mirror the cloud MCPTool's `_map_result` into a tool_result frame."""
    if result.isError:
        text = " ".join(block.text for block in result.content if isinstance(block, TextContent))
        return tool_result_error(
            call_id, "tool_error", text or "MCP tool reported an error", retryable=False
        )
    if isinstance(result.structuredContent, dict):
        return tool_result_ok(call_id, result.structuredContent)
    blocks: list[dict[str, Any]] = []
    for block in result.content:
        if isinstance(block, TextContent):
            blocks.append(block.model_dump(mode="json"))
        else:
            # Binary/non-text payloads are NEVER inlined (W0-04 ArtifactRef rule).
            blocks.append({"type": block.type, "inlined": False, "note": NON_TEXT_NOTE})
    return tool_result_ok(call_id, {"content": blocks})


class Dispatcher:
    """Tracks in-flight calls for one connection and sends their results."""

    def __init__(self, supervisor: ToolCaller, send: SendFn) -> None:
        self._supervisor = supervisor
        self._send = send
        self._inflight: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    def handle_tool_call(self, call: ToolCallIn) -> None:
        """Start one call as its own task; exactly one result will be sent."""
        if self._closed:
            logger.warning("tool_call %.64s after disconnect; dropped", call.call_id)
            return
        if call.call_id in self._inflight:
            logger.warning(
                "duplicate live call_id %.64s dropped (protocol violation)", call.call_id
            )
            return
        task = asyncio.create_task(self._run(call))
        self._inflight[call.call_id] = task
        task.add_done_callback(lambda _task: self._inflight.pop(call.call_id, None))

    async def _execute(self, call: ToolCallIn) -> str:
        server, _, tool = call.tool.partition(".")
        if not server or not tool:
            return tool_result_error(
                call.call_id, "not_found", f"malformed tool name {call.tool!r}", retryable=False
            )
        try:
            result = await self._supervisor.call_tool(server, tool, call.args)
        except UnknownToolError as exc:
            return tool_result_error(call.call_id, "not_found", str(exc), retryable=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("call %.64s failed: %s", call.call_id, type(exc).__name__)
            return tool_result_error(
                call.call_id, "tool_error", str(exc) or type(exc).__name__, retryable=True
            )
        return map_result(call.call_id, result)

    async def _run(self, call: ToolCallIn) -> None:
        payload = await self._execute(call)
        if self._closed:
            return  # never send after a disconnect
        try:
            await self._send(payload)
        except Exception:
            logger.warning("result for %.64s not sent: connection gone", call.call_id)

    def cancel_all(self) -> None:
        """Disconnect: cancel in-flight work; results are never buffered."""
        self._closed = True
        for task in self._inflight.values():
            task.cancel()

    async def wait_idle(self) -> None:
        """Test helper: wait until no calls are in flight."""
        while self._inflight:
            await asyncio.sleep(0.005)
