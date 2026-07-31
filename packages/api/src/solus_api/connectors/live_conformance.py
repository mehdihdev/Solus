"""The reusable LiveConnection conformance suite (MCP-02, mirroring W0-05 §10).

Package-importable — every `LiveConnection`'s own test imports `assert_live_connection_contract`
and runs it (CLAUDE.md §6: contract implementations pass the contract suite), so the invariants
are checked identically across the live roster (ROS, serial, Foxglove, sim). It asserts the
contract's invariants and raises `AssertionError` on the first violation. Asserts are the tool
here on purpose (this IS a test helper); `S101` is ignored repo-wide.

It also mechanically guards the Pattern-2 hard rule: telemetry is NEVER forced through an MCP
tool interface — a `LiveConnection` must not satisfy the W0-04 `Tool` protocol.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from solus_api.agent.interfaces import TelemetryWindow, TelemetryWindowSummary
from solus_api.connectors.live import LiveConnection, LiveStatus

_PATTERN_2 = (
    "Pattern 2 (docs/contracts/live-connection.md): telemetry is NEVER forced through an MCP "
    "tool interface — a LiveConnection must not satisfy the W0-04 `Tool` protocol "
    "(`descriptor` property + `invoke` coroutine)"
)


def _assert_not_a_tool(conn: LiveConnection) -> None:
    has_descriptor = hasattr(type(conn), "descriptor")
    invoke = getattr(conn, "invoke", None)
    has_invoke_coroutine = invoke is not None and inspect.iscoroutinefunction(invoke)
    assert not (has_descriptor and has_invoke_coroutine), _PATTERN_2


async def assert_live_connection_contract(
    conn: LiveConnection,
    *,
    emit: Callable[[], Awaitable[None]],
    window: TelemetryWindow | None = None,
) -> None:
    """Run the full live-connection contract suite against `conn`. Raises `AssertionError` on
    the first violated invariant.

    `emit` is the test-side driver: an async callable that causes `conn` to complete at least
    one window (for `NoopLiveConnection`, wrap its test-only `feed`; a real implementation's
    test pushes a window through its own transport). The suite verifies: subscribe returns a
    handle; delivered payloads are `TelemetryWindowSummary` (batch-summarized windows, never a
    raw-sample firehose); no delivery after unsubscribe; a sane status lifecycle; and the
    Pattern-2 not-a-Tool rule.

    Built on `assert`, so it MUST run with assertions enabled — never under `python -O` /
    PYTHONOPTIMIZE, which strips asserts and would turn every check into a silent no-op (a
    false "conforms"). The guard below fails loudly instead.
    """
    if not __debug__:
        raise RuntimeError(
            "assert_live_connection_contract requires assertions enabled (not under -O)"
        )

    assert isinstance(conn, LiveConnection), "must be a LiveConnection"
    _assert_not_a_tool(conn)
    assert isinstance(conn.status(), LiveStatus), "status() must return a LiveStatus"

    received: list[TelemetryWindowSummary] = []

    async def _collect(summary: TelemetryWindowSummary) -> None:
        received.append(summary)

    handle = await conn.subscribe(window or TelemetryWindow(duration_seconds=1.0))
    assert isinstance(handle, str), "subscribe() must return an opaque str handle"
    assert handle, "subscribe() handle must be non-empty"
    assert conn.status() is not LiveStatus.DISCONNECTED, (
        "an active subscription implies a live link — status() must not be DISCONNECTED"
    )

    conn.on_batch(handle, _collect)
    await emit()
    assert received, "emit() must deliver at least one completed window to the callback"
    assert all(isinstance(s, TelemetryWindowSummary) for s in received), (
        "delivered payloads must be TelemetryWindowSummary — batch-summarized windows, never "
        "raw samples (raw data only via raw_ref: ArtifactRef)"
    )
    assert conn.status() is LiveStatus.STREAMING, "delivery must be reflected as STREAMING"

    await conn.unsubscribe(handle)
    delivered_before = len(received)
    await emit()
    assert len(received) == delivered_before, "no delivery after unsubscribe"
    assert isinstance(conn.status(), LiveStatus), "status() must return a LiveStatus"
