"""SYS-02 tool-call execution layer (`agent/tools/exec.py`).

The executor composes the existing safety sequence — it must not weaken it:
the §7 destructive gate is consulted BEFORE dispatch, the registry keeps the
only per-call clock, every failure is `ToolResult(ok=False)` (never a raise),
and observability logs identifiers/counts only — never tool args or values.
"""

import asyncio
import logging
import subprocess
import sys
from typing import Any
from unittest.mock import AsyncMock

import pytest
from solus_api.agent.tools import (
    InProcessTool,
    ToolCall,
    ToolDescriptor,
    ToolErrorCode,
    ToolRegistry,
)
from solus_api.agent.tools.exec import DEFAULT_MAX_CONCURRENCY, run_tool, run_tool_calls

_ARGS_SENTINEL = "DO-NOT-LOG-args-sentinel-abc"
_VALUE_SENTINEL = "DO-NOT-LOG-value-sentinel-xyz"


async def _ok(args: dict[str, Any]) -> dict[str, Any]:
    return {"echoed": args, "secret": _VALUE_SENTINEL}


def _tool(
    name: str,
    handler: Any,
    *,
    timeout: float | None = None,
    requires_confirmation: bool = False,
) -> InProcessTool:
    return InProcessTool(
        ToolDescriptor(
            name=name,
            description="t",
            params={"type": "object"},
            returns={"type": "object"},
            timeout_seconds=timeout,
            requires_confirmation=requires_confirmation,
        ),
        handler,
    )


async def test_gated_tool_is_refused_and_never_dispatched() -> None:
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
    result = await run_tool(registry, ToolCall(tool="flash", args={}))
    assert result.ok is False and result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED
    _Flagged.invoke.assert_not_awaited()  # dispatch never happened


async def test_successful_call_passes_through_registry_result() -> None:
    registry = ToolRegistry()
    registry.register(_tool("echo", _ok))
    call = ToolCall(tool="echo", args={"x": "1"})
    result = await run_tool(registry, call)
    assert result.ok is True
    assert result.call_id == call.call_id
    assert result.value == {"echoed": {"x": "1"}, "secret": _VALUE_SENTINEL}


async def test_timeout_returns_failed_result_without_raising() -> None:
    async def hang(_args: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(60)
        return {}

    registry = ToolRegistry()
    registry.register(_tool("slow", hang, timeout=0.02))
    result = await run_tool(registry, ToolCall(tool="slow", args={}))
    assert result.ok is False and result.error is not None
    assert result.error.code is ToolErrorCode.TIMEOUT
    assert result.error.retryable is True


async def test_crashing_tool_returns_failed_result_without_raising() -> None:
    async def boom(_args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("internal-detail-that-must-not-surface")

    registry = ToolRegistry()
    registry.register(_tool("boom", boom))
    result = await run_tool(registry, ToolCall(tool="boom", args={}))
    assert result.ok is False and result.error is not None
    assert result.error.code is ToolErrorCode.TOOL_ERROR
    assert "internal-detail" not in result.error.message


async def test_run_tool_calls_preserves_call_order_under_concurrency() -> None:
    async def slow(args: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(float(args["delay"]))
        return {"name": args["name"]}

    registry = ToolRegistry()
    registry.register(_tool("slow", slow))
    calls = [
        ToolCall(tool="slow", args={"name": "first", "delay": "0.05"}),
        ToolCall(tool="slow", args={"name": "second", "delay": "0.0"}),
    ]
    results = await run_tool_calls(registry, calls)
    assert [r.call_id for r in results] == [c.call_id for c in calls]
    assert results[0].value == {"name": "first"}  # order by input, not completion


async def test_run_tool_calls_bounds_concurrency() -> None:
    inflight = 0
    peak = 0

    async def tracked(_args: dict[str, Any]) -> dict[str, Any]:
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.01)
        inflight -= 1
        return {}

    registry = ToolRegistry()
    registry.register(_tool("tracked", tracked))
    calls = [ToolCall(tool="tracked", args={}) for _ in range(6)]
    results = await run_tool_calls(registry, calls, max_concurrency=2)
    assert all(r.ok for r in results)
    assert peak <= 2
    assert DEFAULT_MAX_CONCURRENCY == 4  # the documented MCP-subprocess fan-out cap


async def test_batch_budget_expiry_yields_timeout_results_not_exception() -> None:
    async def fast(_args: dict[str, Any]) -> dict[str, Any]:
        return {"done": "yes"}

    async def hang(_args: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(60)
        return {}

    registry = ToolRegistry()
    registry.register(_tool("fast", fast))
    registry.register(_tool("hang", hang))
    calls = [ToolCall(tool="fast", args={}), ToolCall(tool="hang", args={})]
    results = await run_tool_calls(registry, calls, budget_seconds=0.1)
    assert results[0].ok is True and results[0].value == {"done": "yes"}
    assert results[1].ok is False and results[1].error is not None
    assert results[1].error.code is ToolErrorCode.TIMEOUT
    assert results[1].error.retryable is True


async def test_log_lines_never_contain_args_or_values(caplog: pytest.LogCaptureFixture) -> None:
    registry = ToolRegistry()
    registry.register(_tool("echo", _ok))
    with caplog.at_level(logging.INFO, logger="solus.tools.exec"):
        await run_tool(registry, ToolCall(tool="echo", args={"x": _ARGS_SENTINEL}))
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert _ARGS_SENTINEL not in joined
    assert _VALUE_SENTINEL not in joined
    assert "tool='echo'" in joined  # %.128r bounds + escapes the identifier
    assert "duration_ms=" in joined and "outcome=ok" in joined and "args_bytes=" in joined


async def test_crafted_tool_name_cannot_forge_log_lines(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """MCP tool names are remote-influenced: a newline in the name must appear
    ESCAPED in the log record, never as a second forged line (sec review L1)."""
    registry = ToolRegistry()
    with caplog.at_level(logging.INFO, logger="solus.tools.exec"):
        result = await run_tool(registry, ToolCall(tool="evil\ninjected log line", args={}))
    assert result.ok is False  # NOT_FOUND — but observed either way
    (message,) = [r.getMessage() for r in caplog.records]
    assert "\n" not in message  # no forged second line
    assert "evil\\ninjected" in message  # repr-escaped, visible for debugging


async def test_sentry_capture_is_tags_only_and_never_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, dict[str, str] | None]] = []

    def fake_capture(message: str, level: str | None = None, **kwargs: Any) -> None:
        captured.append((message, kwargs.get("tags")))

    monkeypatch.setattr("sentry_sdk.capture_message", fake_capture)

    registry = ToolRegistry()
    registry.register(
        InProcessTool(
            ToolDescriptor(
                name="strict",
                description="d",
                params={
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                    "required": ["x"],
                    "additionalProperties": False,
                },
                returns={"type": "object"},
            ),
            _ok,
        )
    )
    # INVALID_ARGS whose jsonschema message echoes the offending value.
    result = await run_tool(registry, ToolCall(tool="strict", args={"x": 42, "extra": "no"}))
    assert result.ok is False

    assert len(captured) == 1
    message, tags = captured[0]
    assert "42" not in message and "extra" not in message  # our own string, never error.message
    assert tags is not None
    assert tags["tool"] == "strict"
    assert tags["error_code"] == ToolErrorCode.INVALID_ARGS.value


def test_exec_import_graph_is_mcp_free() -> None:
    """Ratchet (clone of test_mcp_tool's): importing the executor must not pull
    the MCP SDK into the process."""
    code = "import sys; import solus_api.agent.tools.exec; assert 'mcp' not in sys.modules"
    completed = subprocess.run(  # noqa: S603 — fixed argv, no user input
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
