"""SOLUSDEV-72: the bench SessionManager — in-process LiveConnection sessions that
tee every packet into the existing TelemetryPlumbing sink (one telemetry path).

Pure unit tests: a fake tappable connection + the in-memory buffer/dict resolver.
Route-level coverage (auth, cross-tenant 404s, config validation) lives in
`test_bench_session_routes.py`.
"""

import asyncio
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from solus_api.agent.interfaces import TelemetryWindow, TelemetryWindowSummary
from solus_api.connectors.live import BatchCallback, LiveStatus
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.packet import TelemetryPacket
from solus_api.graph.resolver import DictEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.livebench.sessions import (
    SessionManager,
    SessionNotFoundError,
    SessionStillStartingError,
    TooManySessionsError,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _packet(device: str, sec: float, **values: float) -> TelemetryPacket:
    return TelemetryPacket(device_id=device, timestamp=T0 + timedelta(seconds=sec), values=values)


class FakeConn:
    """A tappable LiveConnection double the manager can drive end to end."""

    def __init__(self) -> None:
        self.tap: Any = None
        self.project_id: uuid.UUID | None = None
        self.window: TelemetryWindow | None = None
        self.callback: BatchCallback | None = None
        self.closed = False
        self._status = LiveStatus.DISCONNECTED

    async def subscribe(self, window: TelemetryWindow) -> str:
        self.window = window
        self._status = LiveStatus.CONNECTED
        return "h1"

    def on_batch(self, handle: str, callback: BatchCallback) -> None:
        self.callback = callback

    async def unsubscribe(self, handle: str) -> None:  # pragma: no cover - manager never calls
        raise AssertionError("manager must tear down via aclose, never unsubscribe")

    def status(self) -> LiveStatus:
        return self._status

    async def aclose(self) -> None:
        self.closed = True
        self._status = LiveStatus.DISCONNECTED

    async def drive(self, *packets: TelemetryPacket) -> None:
        self._status = LiveStatus.STREAMING
        for p in packets:
            await self.tap(p)


def _manager(
    project: uuid.UUID, resolved: dict[str, uuid.UUID] | None = None, **kwargs: Any
) -> tuple[SessionManager, TelemetryPlumbing]:
    mapping = {(project, dev): ent for dev, ent in (resolved or {}).items()}
    plumbing = TelemetryPlumbing(InMemoryTelemetryBuffer(), DictEntityResolver(mapping))
    return SessionManager(plumbing, **kwargs), plumbing


async def _start(manager: SessionManager, project: uuid.UUID, conn: FakeConn, **kwargs: Any) -> Any:
    async def open_conn() -> FakeConn:
        return conn

    defaults: dict[str, Any] = {
        "mode": "sim",
        "provider": "mujoco",
        "label": "test session",
        "open_conn": open_conn,
    }
    defaults.update(kwargs)
    return await manager.start(project, **defaults)


async def test_start_subscribes_taps_into_plumbing_and_counts() -> None:
    project, entity = uuid.uuid4(), uuid.uuid4()
    manager, plumbing = _manager(project, resolved={"demo/rod": entity})
    conn = FakeConn()
    record = await _start(manager, project, conn, window_seconds=2.0)

    assert record.status == "active"
    assert conn.window is not None and conn.window.duration_seconds == 2.0
    await conn.drive(_packet("demo/rod", 0.0, qvel=1.0), _packet("serial:mystery", 0.1, v=2.0))

    view = await plumbing.get_recent_values(project, entity)
    assert [p.value for s in view.signals for p in s.points] == [1.0]
    device_view = await plumbing.get_device_recent(project, "serial:mystery")
    assert device_view.signals  # the unresolved stream is viewable, keyed by device

    out = manager.get(project, record.id)
    assert out.counts == {"ingested": 1, "unresolved": 1}
    assert out.device_ids == ["demo/rod", "serial:mystery"]
    assert out.link == "streaming"


async def test_last_summary_is_retained_from_on_batch() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project)
    conn = FakeConn()
    record = await _start(manager, project, conn)
    assert conn.callback is not None
    await conn.callback(
        TelemetryWindowSummary(
            window_start=T0, window_end=T0 + timedelta(seconds=1), summary="1 signal(s)"
        )
    )
    out = manager.get(project, record.id)
    assert out.last_summary is not None and out.last_summary["summary"] == "1 signal(s)"


async def test_session_cap_refuses_and_open_failure_frees_the_slot() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project, max_active_per_project=1)
    await _start(manager, project, FakeConn())
    with pytest.raises(TooManySessionsError):
        await _start(manager, project, FakeConn())

    other = uuid.uuid4()

    async def broken_open() -> FakeConn:
        raise RuntimeError("no such simulator")

    with pytest.raises(RuntimeError):
        await manager.start(other, mode="sim", provider="mujoco", label="x", open_conn=broken_open)
    assert manager.list(other) == []  # the failed placeholder never lingers
    await _start(manager, other, FakeConn())  # and the slot is reusable


async def test_stop_is_idempotent_and_closes_the_connection() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project)
    conn = FakeConn()
    record = await _start(manager, project, conn)

    stopped = await manager.stop(project, record.id)
    assert stopped.status == "ended" and stopped.ended_at is not None
    assert conn.closed
    again = await manager.stop(project, record.id)  # idempotent, still the ended record
    assert again.status == "ended"


async def test_close_failure_logs_type_without_private_driver_text(caplog: Any) -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project)

    class BrokenClose(FakeConn):
        async def aclose(self) -> None:
            raise RuntimeError("/private/calibration-close-sentinel")

    record = await _start(manager, project, BrokenClose())
    stopped = await manager.stop(project, record.id)
    assert stopped.status == "ended"
    assert "RuntimeError" in caplog.text
    assert str(project) in caplog.text and str(record.id) in caplog.text
    assert "/private/calibration-close-sentinel" not in caplog.text


async def test_stop_while_starting_refuses() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project)
    gate: asyncio.Future[FakeConn] = asyncio.get_running_loop().create_future()

    async def slow_open() -> FakeConn:
        return await gate

    task = asyncio.create_task(
        manager.start(project, mode="sim", provider="mujoco", label="slow", open_conn=slow_open)
    )
    await asyncio.sleep(0)
    (pending,) = manager.list(project)
    with pytest.raises(SessionStillStartingError):
        await manager.stop(project, pending.id)
    gate.set_result(FakeConn())
    await task


async def test_lookup_is_project_scoped_and_unknown_ids_raise() -> None:
    project_a, project_b = uuid.uuid4(), uuid.uuid4()
    manager, _ = _manager(project_a)
    record = await _start(manager, project_a, FakeConn())

    with pytest.raises(SessionNotFoundError):
        manager.get(project_b, record.id)
    with pytest.raises(SessionNotFoundError):
        await manager.stop(project_b, record.id)
    with pytest.raises(SessionNotFoundError):
        manager.get(project_a, uuid.uuid4())


async def test_list_filters_by_status_and_mode_and_ended_ring_is_bounded() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project, ended_kept=2)
    kept = await _start(manager, project, FakeConn(), mode="real", provider="serial")
    for _ in range(3):
        record = await _start(manager, project, FakeConn())
        await manager.stop(project, record.id)

    assert {r.id for r in manager.list(project, status="active")} == {kept.id}
    assert [r.mode for r in manager.list(project, mode="real")] == ["real"]
    assert len(manager.list(project, status="ended")) == 2  # bounded, oldest evicted


async def test_aclose_all_closes_every_active_session() -> None:
    project_a, project_b = uuid.uuid4(), uuid.uuid4()
    manager, _ = _manager(project_a)
    conn_a, conn_b = FakeConn(), FakeConn()
    await _start(manager, project_a, conn_a)
    await _start(manager, project_b, conn_b)

    await manager.aclose_all()
    assert conn_a.closed and conn_b.closed
    assert manager.list(project_a, status="active") == []
    assert manager.list(project_b, status="active") == []


async def test_shutdown_closes_a_late_open_that_suppresses_cancellation() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project)
    entered = asyncio.Event()
    release = asyncio.Event()
    conn = FakeConn()

    async def opening() -> FakeConn:
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            return conn
        return conn

    task = asyncio.create_task(
        manager.start(project, mode="real", provider="robot", label="late", open_conn=opening)
    )
    await entered.wait()
    closing = asyncio.create_task(manager.aclose_all())
    await asyncio.sleep(0)
    release.set()
    await closing
    assert task.done()
    assert conn.closed
    assert manager.list(project, status="active") == []


async def test_subscribe_failure_closes_acquired_connection() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project)

    class Broken(FakeConn):
        async def subscribe(self, window: TelemetryWindow) -> str:
            raise ValueError("subscription unavailable")

    conn = Broken()
    with pytest.raises(ValueError):
        await _start(manager, project, conn)
    assert conn.closed
    assert manager.list(project, status="active") == []


async def test_cancellation_drains_thread_acquisition_and_closes_its_result() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project)
    entered, release = threading.Event(), threading.Event()
    conn = FakeConn()

    def acquire() -> FakeConn:
        entered.set()
        release.wait()
        return conn

    async def opening() -> FakeConn:
        return await asyncio.to_thread(acquire)

    task = asyncio.create_task(
        manager.start(project, mode="real", provider="robot", label="thread", open_conn=opening)
    )
    await asyncio.to_thread(entered.wait)
    task.cancel()
    await asyncio.sleep(0)
    try:
        assert not task.done(), "Cancellation must retain the real in-flight acquisition"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert conn.closed
    assert manager.list(project, status="active") == []


async def test_repeated_cancellation_cannot_interrupt_acquired_connection_close() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project)
    entered, released, closing, closed = (asyncio.Event() for _ in range(4))

    class SlowClose(FakeConn):
        async def aclose(self) -> None:
            closing.set()
            await closed.wait()
            await super().aclose()

    conn = SlowClose()

    async def opening() -> FakeConn:
        entered.set()
        await released.wait()
        return conn

    task = asyncio.create_task(
        manager.start(project, mode="real", provider="robot", label="repeat", open_conn=opening)
    )
    await entered.wait()
    task.cancel()
    released.set()
    await closing.wait()
    task.cancel()
    await asyncio.sleep(0)
    try:
        assert not task.done()
    finally:
        closed.set()
        await asyncio.gather(task, return_exceptions=True)
    assert conn.closed


async def test_tap_binds_the_requesting_project_never_packet_content() -> None:
    # Isolation (§7): a session opened under project A must never feed project B,
    # no matter what device ids the stream claims.
    project_a, project_b = uuid.uuid4(), uuid.uuid4()
    entity_b = uuid.uuid4()
    mapping = {(project_b, "shared/dev"): entity_b}
    plumbing = TelemetryPlumbing(InMemoryTelemetryBuffer(), DictEntityResolver(mapping))
    manager = SessionManager(plumbing)
    conn = FakeConn()

    async def open_conn() -> FakeConn:
        return conn

    await manager.start(project_a, mode="sim", provider="mujoco", label="a", open_conn=open_conn)
    await conn.drive(_packet("shared/dev", 0.0, v=1.0))

    assert (await plumbing.get_recent_values(project_b, entity_b)).signals == []
    assert (await plumbing.get_device_recent(project_a, "shared/dev")).signals  # under A


async def test_device_ids_are_bounded() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project, device_ids_kept=3)
    conn = FakeConn()
    record = await _start(manager, project, conn)
    await conn.drive(*(_packet(f"dev/{i}", float(i), v=1.0) for i in range(6)))
    out = manager.get(project, record.id)
    assert len(out.device_ids) == 3


# ── Phase-4 review fixes (SOLUSDEV-72) ──────────────────────────────────────────


class SlowCloseConn(FakeConn):
    """aclose yields once mid-teardown — the interleaving window of the race."""

    def __init__(self) -> None:
        super().__init__()
        self.close_entries = 0

    async def aclose(self) -> None:
        self.close_entries += 1
        await asyncio.sleep(0)  # park here so a concurrent stop can interleave
        await super().aclose()


async def test_concurrent_stops_tear_down_exactly_once() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project)
    conn = SlowCloseConn()
    record = await _start(manager, project, conn)

    first, second = await asyncio.gather(
        manager.stop(project, record.id), manager.stop(project, record.id)
    )
    assert first.status == "ended" and second.status == "ended"
    assert conn.close_entries == 1  # never double-closed
    assert len(manager.list(project, status="ended")) == 1  # never duplicated


async def test_dead_pump_session_frees_its_cap_slot() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project, max_active_per_project=1)
    dead = FakeConn()
    record = await _start(manager, project, dead)
    dead._status = LiveStatus.DISCONNECTED  # pump finished (duration/replay elapsed)

    replacement = await _start(manager, project, FakeConn())  # sweeps, not 409
    assert replacement.status == "active"
    swept = manager.get(project, record.id)
    assert swept.status == "ended"
    assert dead.closed  # its port/subprocess was actually released


async def test_repeated_cancel_during_subscribe_failure_cleanup_drains_close() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project)
    subscribing, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Deferred(FakeConn):
        async def subscribe(self, window: TelemetryWindow) -> str:
            subscribing.set()
            await asyncio.Event().wait()
            return "unused"

        async def aclose(self) -> None:
            closing.set()
            await release.wait()
            await super().aclose()

    conn = Deferred()
    task = asyncio.create_task(_start(manager, project, conn))
    await subscribing.wait()
    task.cancel()
    await closing.wait()
    task.cancel()
    await asyncio.sleep(0)
    try:
        assert not task.done()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert conn.closed


async def test_shutdown_waits_for_already_closing_session() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project)
    closing, release = asyncio.Event(), asyncio.Event()

    class Deferred(FakeConn):
        async def aclose(self) -> None:
            closing.set()
            await release.wait()
            await super().aclose()

    conn = Deferred()
    record = await _start(manager, project, conn)
    stop = asyncio.create_task(manager.stop(project, record.id))
    await closing.wait()
    shutdown = asyncio.create_task(manager.aclose_all())
    await asyncio.sleep(0)
    try:
        assert not shutdown.done()
    finally:
        release.set()
        await asyncio.gather(stop, shutdown)
    assert conn.closed
