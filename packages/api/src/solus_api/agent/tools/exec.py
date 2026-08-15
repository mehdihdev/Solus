"""SYS-02 tool-call execution layer — observe the gated dispatch.

Composes the existing safety sequence instead of wrapping a parallel one:

- The §7 destructive gate lives INSIDE the `dispatch` callable this module is
  handed (`runtime.build_dispatch` fuses gate-then-invoke into one closure), so
  there is no registry and no gate here — `run_tool` cannot skip a gate it
  never held. This module is the observability wrapper `build_dispatch` routes
  every dispatch through: one observable path for every runner (SYS-02), and
  the only production holders of `registry.invoke` stay `runtime.py` and
  `confirmations.py` (ratchet-tested).
- Per-call safety (timeout, arg validation, exception trapping) belongs to
  `ToolRegistry.invoke` — the registry owns the ONLY per-call clock
  (registry.py's `asyncio.wait_for`); nothing here re-times a call. The layer
  this module adds is the BATCH: bounded concurrency (an `MCPTool` spawns a
  fresh subprocess per call with no pool — the semaphore is what caps that
  fan-out) and an optional wall-clock budget (`asyncio.timeout`, the
  routers/sol.py idiom).
- NEVER raises, end to end: every failure — gate refusal, timeout, crash,
  budget expiry, cancellation — is `ToolResult(ok=False)` data.
- Observability logs identifiers, counts, and sizes ONLY (CLAUDE.md §7): tool
  args and results carry customer CAD data and potentially credentials, so they
  never enter a log line or a Sentry event. Sentry captures are OUR OWN message
  string with tags — never `error.message`, which (e.g. jsonschema INVALID_ARGS)
  can echo argument values.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import sentry_sdk

from solus_api.agent.tools.shapes import ToolCall, ToolError, ToolErrorCode, ToolResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    #: Structural twin of `runtime.DispatchFn` — typed locally so this module
    #: never imports runtime (runtime imports this one; the old function-local
    #: import cycle is gone).
    DispatchFn = Callable[[ToolCall], Awaitable[ToolResult]]

logger = logging.getLogger("solus.tools.exec")

# ponytail: caps MCP subprocess fan-out (mcp_tool.py spawns one process per
# call with no pool); raise if real workloads need more.
DEFAULT_MAX_CONCURRENCY = 4


def _json_size(obj: Any) -> int:
    """Byte-ish size for observability without ever logging content. -1 = unsizeable."""
    try:
        return len(json.dumps(obj, default=str))
    except Exception:  # noqa: BLE001 — sizing is best-effort observability only
        return -1


def _capture_failure(call: ToolCall, error: ToolError, duration_ms: int) -> None:
    """Sentry capture with tags only. A no-op when the SDK is uninitialized (no
    SOLUS_SENTRY_DSN); guarded so observability can never break the never-raises seam."""
    try:
        sentry_sdk.capture_message(
            "tool call failed",  # our own string — never error.message (may echo args)
            level="warning",
            tags={
                # MCP tool names / call ids are remote- or caller-influenced: bound them.
                "tool": call.tool[:128],
                "call_id": call.call_id[:128],
                "error_code": error.code.value,
                "retryable": str(error.retryable),
                "duration_ms": str(duration_ms),
            },
        )
    except Exception:  # noqa: BLE001 — never let telemetry break the tool path
        logger.warning("sentry capture failed for tool %s", call.tool, exc_info=True)


async def run_tool(dispatch: DispatchFn, call: ToolCall) -> ToolResult:
    """Observe one gated dispatch. NEVER raises (see module docstring)."""
    started = time.monotonic()
    result = await dispatch(call)
    duration_ms = int((time.monotonic() - started) * 1000)
    outcome = "ok" if result.ok else (result.error.code.value if result.error else "unknown")
    # §7 logging: identifiers, counts, and sizes only — never args or values.
    # %.128r bounds and escapes the remote-/caller-influenced identifiers so a
    # crafted name cannot forge log lines (house idiom: mcp_tool._skip).
    logger.info(
        "tool call done tool=%.128r call_id=%.128r duration_ms=%d outcome=%s "
        "args_bytes=%d value_bytes=%d",
        call.tool,
        call.call_id,
        duration_ms,
        outcome,
        _json_size(call.args),
        _json_size(result.value),
    )
    if not result.ok and result.error is not None:
        _capture_failure(call, result.error, duration_ms)
    return result


async def run_tool_calls(
    dispatch: DispatchFn,
    calls: Sequence[ToolCall],
    *,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    budget_seconds: float | None = None,
) -> list[ToolResult]:
    """Run a batch concurrently under a semaphore and an optional wall-clock
    budget. Results are ordered as `calls`. Budget expiry: finished calls keep
    their real results; unfinished ones are cancelled and become
    `ToolResult(ok=False, TIMEOUT, retryable=True)`. NEVER raises."""
    semaphore = asyncio.Semaphore(max_concurrency)
    results: list[ToolResult | None] = [None] * len(calls)

    async def _one(index: int, call: ToolCall) -> None:
        async with semaphore:
            # `dispatch` (from `build_dispatch`) is already the observed gated
            # path — wrapping it in `run_tool` again would double-log every call.
            results[index] = await dispatch(call)

    try:
        # asyncio.timeout(None) never expires — one code path for both cases.
        async with asyncio.timeout(budget_seconds), asyncio.TaskGroup() as group:
            for index, call in enumerate(calls):
                group.create_task(_one(index, call))
    except TimeoutError:
        logger.warning(
            "tool batch budget expired budget_s=%.2f completed=%d total=%d",
            budget_seconds if budget_seconds is not None else -1.0,
            sum(result is not None for result in results),
            len(calls),
        )
    return [
        result
        if result is not None
        else ToolResult.failure(
            call.call_id,
            ToolError(
                code=ToolErrorCode.TIMEOUT,
                message=f"batch budget of {budget_seconds}s expired before this call completed",
                retryable=True,
            ),
        )
        for result, call in zip(results, calls, strict=True)
    ]
