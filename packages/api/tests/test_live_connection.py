"""LiveConnection — the streaming sibling of `Connector`, proven both ways (MCP-02).

The `NoopLiveConnection` PASSES the live-connection conformance suite; deliberately-broken
implementations FAIL it — proving the suite actually catches the invariants: delivered
payloads are batch-summarized `TelemetryWindowSummary` windows (never raw samples), delivery
stops at unsubscribe, status reflects the lifecycle, and — the Pattern-2 hard rule — a
`LiveConnection` never satisfies the W0-04 `Tool` protocol (telemetry is never forced through
an MCP tool interface). Pure unit — no DB. The suite is imported from the package, proving it
ships importable like `assert_connector_contract`.
"""

import inspect
import re
from datetime import UTC, datetime, timedelta

import pytest
from solus_api.agent.interfaces import TelemetryWindow, TelemetryWindowSummary
from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.connectors.contracts import Connector
from solus_api.connectors.live import LiveStatus, NoopLiveConnection
from solus_api.connectors.live_conformance import assert_live_connection_contract


def _window() -> TelemetryWindow:
    return TelemetryWindow(duration_seconds=1.0, signals=["imu.accel"])


def _summary(text: str = "idle") -> TelemetryWindowSummary:
    start = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    return TelemetryWindowSummary(
        window_start=start,
        window_end=start + timedelta(seconds=1),
        summary=text,
        signals={"imu.accel": {"mean": 0.0}},
    )


# --------------------------------------------------------------------- the four operations


async def test_subscribe_returns_handle_and_connects() -> None:
    conn = NoopLiveConnection()
    assert conn.status() is LiveStatus.DISCONNECTED
    handle = await conn.subscribe(_window())
    assert isinstance(handle, str)
    assert handle
    assert conn.status() is LiveStatus.CONNECTED


async def test_on_batch_delivers_completed_window_summaries() -> None:
    conn = NoopLiveConnection()
    handle = await conn.subscribe(_window())
    received: list[TelemetryWindowSummary] = []

    async def collect(summary: TelemetryWindowSummary) -> None:
        received.append(summary)

    conn.on_batch(handle, collect)
    fed = _summary()
    await conn.feed(fed)
    assert received == [fed]
    assert all(isinstance(s, TelemetryWindowSummary) for s in received)


async def test_unsubscribe_stops_delivery() -> None:
    conn = NoopLiveConnection()
    handle = await conn.subscribe(_window())
    received: list[TelemetryWindowSummary] = []

    async def collect(summary: TelemetryWindowSummary) -> None:
        received.append(summary)

    conn.on_batch(handle, collect)
    await conn.feed(_summary())
    await conn.unsubscribe(handle)
    await conn.feed(_summary("late"))
    assert len(received) == 1  # nothing delivered after unsubscribe


async def test_unknown_handle_raises() -> None:
    conn = NoopLiveConnection()

    async def collect(summary: TelemetryWindowSummary) -> None:  # pragma: no cover
        raise AssertionError("never delivered")

    with pytest.raises(KeyError):
        conn.on_batch("bogus", collect)
    with pytest.raises(KeyError):
        await conn.unsubscribe("bogus")


async def test_status_lifecycle() -> None:
    # disconnected → connected (subscribe) → streaming (delivery) → disconnected (last unsubscribe)
    conn = NoopLiveConnection()
    assert conn.status() is LiveStatus.DISCONNECTED
    handle = await conn.subscribe(_window())
    assert conn.status() is LiveStatus.CONNECTED

    async def collect(summary: TelemetryWindowSummary) -> None:
        return None

    conn.on_batch(handle, collect)
    await conn.feed(_summary())
    assert conn.status() is LiveStatus.STREAMING
    await conn.unsubscribe(handle)
    assert conn.status() is LiveStatus.DISCONNECTED


# ------------------------------------------------------------------ the sibling boundary


def test_live_connection_is_not_a_connector() -> None:
    # LiveConnection is the DISTINCT sibling of Connector (W0-05 §1, ADR-030 boundary):
    # live runtime data never rides the design-artifact sync path.
    conn = NoopLiveConnection()
    assert not isinstance(conn, Connector)
    assert not hasattr(conn, "sync")
    assert not hasattr(conn, "detect_changes")


def test_live_module_imports_nothing_mcp() -> None:
    # Pattern 2 hard rule: telemetry is never forced through an MCP tool interface.
    from solus_api.connectors import live

    source = inspect.getsource(live)
    assert not re.search(r"^\s*(from|import)\s+\S*mcp", source, re.MULTILINE | re.IGNORECASE)


# ----------------------------------------------------------------- the conformance suite


async def test_conformance_suite_passes_noop() -> None:
    conn = NoopLiveConnection()

    async def emit() -> None:
        await conn.feed(_summary())

    await assert_live_connection_contract(conn, emit=emit, window=_window())


class _ToolishLive(NoopLiveConnection):
    """A LiveConnection that grew the W0-04 Tool surface — the Pattern-2 violation."""

    @property
    def descriptor(self) -> ToolDescriptor:  # pragma: no cover — presence is the violation
        raise NotImplementedError

    async def invoke(self, args: dict[str, object]) -> dict[str, object]:  # pragma: no cover
        raise NotImplementedError


async def test_conformance_catches_a_toolish_live_connection() -> None:
    conn = _ToolishLive()

    async def emit() -> None:  # pragma: no cover — the suite fails before emitting
        await conn.feed(_summary())

    with pytest.raises(AssertionError, match="Pattern 2"):
        await assert_live_connection_contract(conn, emit=emit)


class _LeakyLive(NoopLiveConnection):
    """Keeps delivering after unsubscribe — the delivery-stops violation."""

    async def unsubscribe(self, handle: str) -> None:
        if handle not in self._subscriptions:
            raise KeyError(handle)
        # deliberately forgets to remove the subscription/callback


async def test_conformance_catches_delivery_after_unsubscribe() -> None:
    conn = _LeakyLive()

    async def emit() -> None:
        await conn.feed(_summary())

    with pytest.raises(AssertionError, match="unsubscribe"):
        await assert_live_connection_contract(conn, emit=emit)


class _RawSampleLive(NoopLiveConnection):
    """Delivers a raw sample dict instead of a TelemetryWindowSummary — the firehose violation."""

    async def feed(self, summary: TelemetryWindowSummary) -> None:
        for handle in list(self._subscriptions):
            callback = self._callbacks.get(handle)
            if callback is not None:
                await callback({"t": 0.0, "imu.accel": 9.81})  # type: ignore[arg-type]
        self._status = LiveStatus.STREAMING


async def test_conformance_catches_raw_sample_payloads() -> None:
    conn = _RawSampleLive()

    async def emit() -> None:
        await conn.feed(_summary())

    with pytest.raises(AssertionError, match="TelemetryWindowSummary"):
        await assert_live_connection_contract(conn, emit=emit)
