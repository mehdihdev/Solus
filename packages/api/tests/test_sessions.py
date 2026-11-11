"""SOLUSDEV-72: the bench SessionManager — in-process LiveConnection sessions that
tee every packet into the existing TelemetryPlumbing sink (one telemetry path).

Pure unit tests: a fake tappable connection + the in-memory buffer/dict resolver.
Route-level coverage (auth, cross-tenant 404s, config validation) lives in
`test_bench_session_routes.py`.
"""

import asyncio
import logging
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
    DEFAULT_CHANNELS_KEPT,
    SessionManager,
    SessionNotFoundError,
    SessionStillStartingError,
    SessionView,
    TooManySessionsError,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _packet(device: str, sec: float, **values: float) -> TelemetryPacket:
    return TelemetryPacket(device_id=device, timestamp=T0 + timedelta(seconds=sec), values=values)


class FakeConn:
    """A tappable LiveConnection double the manager can drive end to end."""

    #: What a real connection reports about its devices. A test sets it where it matters;
    #: the manager reads it with `getattr`, so an unset one is simply absent.
    device_facts: dict[str, Any]

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


async def test_display_roles_require_observed_device_and_isolate_projects() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project)
    conn = FakeConn()
    conn.device_facts = {"channel_roles": {"device": {"health": "diagnostic", "other": "bogus"}}}
    record = await _start(manager, project, conn)
    assert manager.channel_roles(project, "device") == {}
    await conn.drive(_packet("device", 0, health=1))
    assert manager.channel_roles(project, "device") == {"health": "diagnostic"}
    assert manager.channel_roles(uuid.uuid4(), "device") == {}
    assert manager.channel_roles(project, "other") == {}
    await manager.stop(project, record.id)
    assert manager.channel_roles(project, "device") == {}


async def test_conflicting_session_channel_roles_remain_unknown() -> None:
    project = uuid.uuid4()
    manager, _ = _manager(project)
    for role in ("diagnostic", "primary"):
        conn = FakeConn()
        conn.device_facts = {"channel_roles": {"device": {"health": role}}}
        await _start(manager, project, conn)
        await conn.drive(_packet("device", 0, health=1))
    assert manager.channel_roles(project, "device") == {}
    await manager.aclose_all()


# ── SOLUSDEV-321 P2-T3: a robot session runs its window evaluator ──────────────


class _Evaluator:
    """A window-evaluator double: keeps the view it was started on; its ticker sleeps until
    cancelled — or, `stubborn`, swallows the cancel and waits for `release`."""

    def __init__(self, *, stubborn: bool = False) -> None:
        self.views: list[SessionView] = []
        self.task: asyncio.Task[None] | None = None
        self.stubborn = stubborn
        self.release = asyncio.Event()

    def start(self, view: SessionView) -> asyncio.Task[None]:
        self.views.append(view)
        self.task = asyncio.create_task(self._ticks())
        return self.task

    async def _ticks(self) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            if not self.stubborn:
                raise
            await self.release.wait()


async def _robot_session(
    manager: SessionManager, project: uuid.UUID, conn: FakeConn, **kwargs: Any
) -> Any:
    return await _start(manager, project, conn, mode="real", provider="robot", **kwargs)


async def test_a_robot_session_starts_its_evaluator_and_stop_cancels_it() -> None:
    project, robot, owner = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    evaluator = _Evaluator()
    manager, _ = _manager(project, evaluator_factory=lambda view: evaluator)
    record = await _robot_session(
        manager, project, FakeConn(), robot_entity_id=robot, owner_user_id=owner
    )

    (view,) = evaluator.views
    assert (view.project_id, view.session_id, view.robot_entity_id, view.owner_user_id) == (
        project,
        record.id,
        robot,
        owner,
    )
    assert record.robot_entity_id == robot
    task = evaluator.task
    assert task is not None and not task.done()

    stopped = await manager.stop(project, record.id)
    assert task.cancelled()  # cancelled, and awaited before the stop returned
    assert stopped.robot_entity_id == robot


async def test_a_session_without_a_robot_runs_no_evaluator() -> None:
    project = uuid.uuid4()
    evaluator = _Evaluator()
    manager, _ = _manager(project, evaluator_factory=lambda view: evaluator)
    record = await _start(manager, project, FakeConn())
    assert evaluator.views == []
    assert record.robot_entity_id is None
    await manager.aclose_all()


async def test_the_view_holds_each_resolved_part_with_the_event_time_each_channel_began() -> None:
    project, servo, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    evaluator = _Evaluator()
    manager, _ = _manager(
        project,
        resolved={"arm/3": servo, "arm/4": other},
        evaluator_factory=lambda view: evaluator,
    )
    conn = FakeConn()
    await _robot_session(manager, project, conn, robot_entity_id=uuid.uuid4())
    await conn.drive(
        _packet("arm/3", 1.0, a=1.0, b=2.0),
        _packet("arm/3", 2.0, a=1.0, c=3.0),
        _packet("arm/4", 3.0, d=4.0),
        _packet("stray", 4.0, e=5.0),  # unresolved: not a part
    )

    (view,) = evaluator.views
    second = timedelta(seconds=1)
    assert view.parts == {
        servo: {"a": T0 + second, "b": T0 + second, "c": T0 + 2 * second},
        other: {"d": T0 + 3 * second},
    }
    await manager.aclose_all()


async def test_the_resolved_parts_and_their_channels_are_bounded() -> None:
    project = uuid.uuid4()
    entities = {f"arm/{i}": uuid.uuid4() for i in range(4)}
    evaluator = _Evaluator()
    manager, _ = _manager(
        project, resolved=entities, device_ids_kept=2, evaluator_factory=lambda view: evaluator
    )
    conn = FakeConn()
    await _robot_session(manager, project, conn, robot_entity_id=uuid.uuid4())
    wide = {f"s{j}": 1.0 for j in range(DEFAULT_CHANNELS_KEPT + 8)}
    await conn.drive(*(_packet(f"arm/{i}", float(i), **wide) for i in range(4)))

    (view,) = evaluator.views
    assert list(view.parts) == [entities["arm/0"], entities["arm/1"]]
    assert all(len(channels) == DEFAULT_CHANNELS_KEPT for channels in view.parts.values())
    await manager.aclose_all()


async def test_stop_waits_for_the_evaluator_only_within_its_bound(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("solus_api.livebench.sessions.EVALUATOR_STOP_SECONDS", 0.05)
    project = uuid.uuid4()
    evaluator = _Evaluator(stubborn=True)
    manager, _ = _manager(project, evaluator_factory=lambda view: evaluator)
    record = await _robot_session(manager, project, FakeConn(), robot_entity_id=uuid.uuid4())
    await asyncio.sleep(0)  # the ticker is running when the stop comes

    stopped = await asyncio.wait_for(manager.stop(project, record.id), 5)

    assert stopped.status == "ended"
    assert "did not stop" in caplog.text and str(record.id) in caplog.text
    evaluator.release.set()
    assert evaluator.task is not None
    await evaluator.task


class _SourceRecordingResolver:
    """Keeps the `source` each lookup carried (SOLUSDEV-322 P5-T2)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def resolve(
        self, project_id: uuid.UUID, device_id: str, *, source: str | None = None
    ) -> uuid.UUID | None:
        self.calls.append((device_id, source))
        return None


async def test_sim_session_tap_passes_its_provider_as_source() -> None:
    """A sim session's packets resolve under its provider — the tag that lets the resolver read a
    part's `sim_aliases` — and a real session's under none, whatever its provider is called."""
    project = uuid.uuid4()
    resolver = _SourceRecordingResolver()
    manager = SessionManager(TelemetryPlumbing(InMemoryTelemetryBuffer(), resolver))
    sim, real = FakeConn(), FakeConn()
    await _start(manager, project, sim, mode="sim", provider="sim-provider-a")
    await _start(manager, project, real, mode="real", provider="serial-driver")

    await sim.drive(_packet("world/arm/elbow", 0.0, q=1.0))
    await real.drive(_packet("usb:ARM/3", 0.0, q=1.0))

    assert resolver.calls == [("world/arm/elbow", "sim-provider-a"), ("usb:ARM/3", None)]
    await manager.aclose_all()


# ── SOLUSDEV-322 P5-T3: a sim session adopts the robot of its resolved parts ───────────────


class _Robots:
    """A `robot_of_part` double: part → robot, counting lookups."""

    def __init__(self, robots: dict[uuid.UUID, uuid.UUID | None]) -> None:
        self.robots, self.calls = robots, list[uuid.UUID]()

    async def __call__(self, project_id: uuid.UUID, part_id: uuid.UUID) -> uuid.UUID | None:
        self.calls.append(part_id)
        return self.robots.get(part_id)


async def test_sim_session_adopts_the_robot_of_its_first_resolved_part_and_starts_the_evaluator() -> None:  # noqa: E501 # fmt: skip
    project, robot, elbow, wrist = (uuid.uuid4() for _ in range(4))
    evaluator, robots = _Evaluator(), _Robots({elbow: robot, wrist: robot})
    manager, _ = _manager(
        project,
        resolved={"w/arm/elbow": elbow, "w/arm/wrist": wrist},
        evaluator_factory=lambda view: evaluator,
        robot_of_part=robots,
    )
    conn = FakeConn()
    record = await _start(manager, project, conn, provider="sim-provider-a")
    assert record.robot_entity_id is None and evaluator.views == []

    await conn.drive(
        _packet("stray", 0.5, x=1.0),  # unresolved: no lookup
        _packet("w/arm/elbow", 1.0, **{"elbow.position": 0.1}),
        _packet("w/arm/elbow", 2.0, **{"elbow.position": 0.2}),  # tried once, not again
        _packet("w/arm/wrist", 3.0, **{"wrist.position": 0.3}),
    )

    (view,) = evaluator.views
    assert (view.robot_entity_id, view.sim) == (robot, True)
    assert manager.get(project, record.id).robot_entity_id == robot
    assert robots.calls == [elbow, wrist]
    assert view.parts == {
        elbow: {"elbow.position": T0 + timedelta(seconds=1)},
        wrist: {"wrist.position": T0 + timedelta(seconds=3)},
    }
    task = evaluator.task
    assert task is not None and not task.done()
    await manager.stop(project, record.id)
    assert task.cancelled()


async def test_sim_session_with_parts_of_two_robots_adopts_none_and_logs(caplog: Any) -> None:
    project, robot_a, robot_b, elbow, other = (uuid.uuid4() for _ in range(5))
    evaluator = _Evaluator()
    manager, _ = _manager(
        project,
        resolved={"w/a/elbow": elbow, "w/b/elbow": other},
        evaluator_factory=lambda view: evaluator,
        robot_of_part=_Robots({elbow: robot_a, other: robot_b}),
    )
    conn = FakeConn()
    record = await _start(manager, project, conn, provider="sim-provider-a")
    with caplog.at_level(logging.WARNING, logger="solus_api.livebench.sessions"):
        await conn.drive(
            _packet("w/a/elbow", 1.0, **{"elbow.position": 0.1}),
            _packet("w/b/elbow", 2.0, **{"elbow.position": 0.2}),
            _packet("w/a/elbow", 3.0, **{"elbow.position": 0.3}),
        )

    assert manager.get(project, record.id).robot_entity_id is None
    assert evaluator.task is not None and evaluator.task.cancelled()
    (warning,) = [r for r in caplog.records if "two robots" in r.getMessage()]
    assert str(record.id) in warning.getMessage()
    await manager.aclose_all()


async def test_a_real_session_never_looks_a_robot_up() -> None:
    project, part = uuid.uuid4(), uuid.uuid4()
    robots = _Robots({part: uuid.uuid4()})
    manager, _ = _manager(project, resolved={"arm/1": part}, robot_of_part=robots)
    conn = FakeConn()
    record = await _start(manager, project, conn, mode="real", provider="robot")
    await conn.drive(_packet("arm/1", 1.0, a=1.0))
    assert robots.calls == [] and manager.get(project, record.id).robot_entity_id is None
    await manager.aclose_all()
