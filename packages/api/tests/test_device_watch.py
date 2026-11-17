"""SOLUSDEV-250 Phase 1 — hot-detect: the local API diffs `detect_devices()` at ~1 Hz and
delivers a FULL current device list to every subscribed project's stream, on this machine only.

The frame goes through `publish_local` (never Redis): one machine's device list must never fan
out to another machine's session. Nothing here opens a port.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.graph.live import Channel, LiveHub, Subscription
from solus_api.hardware import device_watch
from solus_api.hardware.device_memory import remember_devices
from solus_api.hardware.device_watch import DeviceWatcher, watcher_wanted
from sqlalchemy.ext.asyncio import AsyncSession
from test_device_memory import _backfilled_robot, _fresh_machine, _machine, _team, _usb_device
from test_device_memory import host as host
from test_hardware_detect import DEVICE_REF, _wire_device


class FakeLocal:
    def __init__(self, devices: list[dict[str, Any]] | None = None) -> None:
        self.devices = devices or []
        self.calls = 0
        self.fail_next = False

    def detect_devices(self) -> list[dict[str, Any]]:
        self.calls += 1
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("enumeration exploded")
        return list(self.devices)


class RedisMustNotBeUsed(LiveHub):
    """A hub whose cross-process leg would fail loudly if the watcher ever took it."""

    def __init__(self) -> None:
        class Broken:
            async def publish(self, *a: object, **k: object) -> None:
                raise AssertionError("device frames must never go through redis")

        super().__init__(Broken())
        self.published: list[uuid.UUID] = []

    async def publish(self, project_id: uuid.UUID, frame: dict[str, Any]) -> None:
        raise AssertionError("watcher used publish(), not publish_local()")


def _frames(queue: asyncio.Queue[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    while not queue.empty():
        out.append(json.loads(queue.get_nowait()))
    return out


async def test_publishes_once_when_the_list_changes_and_never_when_unchanged() -> None:
    hub, local = LiveHub(), FakeLocal([_wire_device()])
    project = uuid.uuid4()
    queue = hub.subscribe(project)
    watcher = DeviceWatcher(hub, local)

    await watcher._tick()
    await watcher._tick()
    await watcher._tick()

    assert len(_frames(queue)) == 1
    local.devices = []
    await watcher._tick()
    frames = _frames(queue)
    assert len(frames) == 1 and frames[0]["devices"] == []


async def test_a_serial_less_device_does_not_raise_and_still_diffs() -> None:
    hub, local = LiveHub(), FakeLocal([_wire_device(None), _wire_device()])
    project = uuid.uuid4()
    queue = hub.subscribe(project)
    watcher = DeviceWatcher(hub, local)

    await watcher._tick()
    await watcher._tick()
    assert len(_frames(queue)) == 1

    local.devices = [_wire_device(None)]
    await watcher._tick()
    frames = _frames(queue)
    assert len(frames) == 1
    assert [d["device_ref"] for d in frames[0]["devices"]] == [None]


async def test_no_enumeration_while_nobody_is_subscribed() -> None:
    hub, local = LiveHub(), FakeLocal([_wire_device()])
    watcher = DeviceWatcher(hub, local)

    await watcher._tick()
    await watcher._tick()

    assert local.calls == 0


async def test_the_frame_reaches_every_subscribed_project_with_the_full_list() -> None:
    hub, local = LiveHub(), FakeLocal([_wire_device()])
    a, b = uuid.uuid4(), uuid.uuid4()
    qa, qb = hub.subscribe(a), hub.subscribe(b)

    await DeviceWatcher(hub, local)._tick()

    for project, queue in ((a, qa), (b, qb)):
        (frame,) = _frames(queue)
        assert frame["type"] == "hardware.devices_changed"
        assert frame["project_id"] == str(project)
        assert frame["at"]
        assert [d["device_ref"] for d in frame["devices"]] == [_wire_device()["device_ref"]]


async def test_delivery_is_local_only_never_through_redis_or_publish() -> None:
    hub, local = RedisMustNotBeUsed(), FakeLocal([_wire_device()])
    queue = hub.subscribe(uuid.uuid4())

    await DeviceWatcher(hub, local)._tick()

    assert len(_frames(queue)) == 1


async def test_a_detector_that_raises_once_does_not_kill_the_loop() -> None:
    hub, local = LiveHub(), FakeLocal([_wire_device()])
    queue = hub.subscribe(uuid.uuid4())
    local.fail_next = True
    watcher = DeviceWatcher(hub, local)

    await watcher._tick()
    assert _frames(queue) == []
    await watcher._tick()

    assert len(_frames(queue)) == 1


async def test_detector_failure_logs_type_without_private_exception_text(caplog: Any) -> None:
    class PrivateFailure(FakeLocal):
        def detect_devices(self) -> list[dict[str, Any]]:
            raise RuntimeError("private-device-state-sentinel")

    hub = LiveHub()
    hub.subscribe(uuid.uuid4())
    watcher = DeviceWatcher(hub, PrivateFailure([]))
    await watcher._tick()
    assert "RuntimeError" in caplog.text
    assert "private-device-state-sentinel" not in caplog.text


async def test_stop_cancels_a_running_task_and_start_twice_creates_one_task() -> None:
    hub, local = LiveHub(), FakeLocal([_wire_device()])
    queue = hub.subscribe(uuid.uuid4())
    watcher = DeviceWatcher(hub, local, interval_s=0.01)

    await watcher.start()
    first = watcher._task
    await watcher.start()
    assert watcher._task is first

    await asyncio.wait_for(queue.get(), timeout=1.0)
    await watcher.stop()

    assert first is not None and first.cancelled()
    assert watcher._task is None
    await watcher.stop()  # idempotent


async def test_a_tick_that_raises_outside_enumeration_does_not_end_the_loop() -> None:
    """Enumeration failures were already guarded; a bug in frame building or delivery must be
    logged and retried too (review of Phase 1, SOLUSDEV-250)."""
    hub = LiveHub()
    project = uuid.uuid4()
    queue = hub.subscribe(project)
    watcher = DeviceWatcher(hub, FakeLocal([_wire_device()]), interval_s=0.01)
    calls = 0
    original = watcher._tick

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("frame build exploded")
        await original()

    watcher._tick = flaky  # type: ignore[method-assign]
    await watcher.start()
    payload = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert "hardware.devices_changed" in payload and calls >= 2
    assert watcher._task is not None and not watcher._task.done()
    await watcher.stop()


def test_the_watcher_is_never_built_for_a_production_api() -> None:
    """Local-only delivery must not rest on livebench being absent from a server image: a
    production API never enumerates its host's ports for its tenants."""
    local = FakeLocal()

    assert watcher_wanted("dev", local) is True
    assert watcher_wanted("staging", local) is True
    assert watcher_wanted("production", local) is False
    assert watcher_wanted("dev", None) is False


async def test_a_project_that_subscribes_later_gets_the_list_at_its_next_tick() -> None:
    """Each project is told the list once per change (SOLUSDEV-326): one that subscribes between
    changes hears it at its next tick, and one that left and came back hears it again."""
    hub, local = LiveHub(), FakeLocal([_wire_device()])
    early, late = uuid.uuid4(), uuid.uuid4()
    early_queue = hub.subscribe(early)
    watcher = DeviceWatcher(hub, local)
    await watcher._tick()
    late_queue = hub.subscribe(late)

    await watcher._tick()

    assert len(_frames(early_queue)) == 1 and len(_frames(late_queue)) == 1
    hub.unsubscribe(late, late_queue)
    await watcher._tick()
    again = hub.subscribe(late)
    await watcher._tick()
    assert len(_frames(again)) == 1 and _frames(early_queue) == []


# ── SOLUSDEV-326 P1-T5: the machine remembers what it saw ───────────────────────────────────────


def _clock(monkeypatch: pytest.MonkeyPatch, *stamps: str) -> None:
    """The watcher's clock: one stamp per enumerating tick."""
    times = iter(datetime.fromisoformat(stamp) for stamp in stamps)
    monkeypatch.setattr(device_watch, "utcnow", lambda: next(times))


def _drained(subscription: Subscription) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    while not subscription.queue.empty():
        item = subscription.queue.get_nowait()
        assert isinstance(item, tuple), item
        frames.append(json.loads(item[1]))
    return frames


def _reader(hub: LiveHub, project: str, user: str) -> Subscription:
    """One member's project stream, as `GET /projects/{id}/events` subscribes it."""
    return hub.subscribe_channels(
        [Channel.project(uuid.UUID(project)), Channel.user(uuid.UUID(user))]
    )


T1, T2, T3, T4 = (f"2026-11-15T10:00:0{second}+00:00" for second in range(1, 5))


async def test_the_machine_remembers_what_it_saw_on_change_only_and_publishes_no_graph_change(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plug-in is not a graph change: a `graph.changed` fan-out reruns every checker."""
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    await _machine(db, project, alice)
    hub, changed = LiveHub(), list[uuid.UUID]()

    async def graph_changed(project_id: uuid.UUID) -> None:
        changed.append(project_id)

    hub.on_graph_changed = graph_changed
    reader = _reader(hub, project, alice)
    writes: list[str] = []
    remember = remember_devices

    async def counted(*args: Any, **kwargs: Any) -> Any:
        writes.append(kwargs["at"])
        return await remember(*args, **kwargs)

    monkeypatch.setattr(device_watch, "remember_devices", counted)
    _clock(monkeypatch, T1, T2)
    watcher = DeviceWatcher(hub, FakeLocal([_wire_device()]), sessions=app.state.sessionmaker)

    await watcher._tick()
    await watcher._tick()
    await watcher.settled()

    assert writes == [T1]
    # P2-T6: the arrival was owed an inspection this runner could not make (it cannot say
    # whether listening would restart the board): recorded, and the list sent again.
    assert (await _fresh_machine(app, project))["devices"] == [
        {
            "device_ref": DEVICE_REF,
            "identity_basis": "serial",
            "headline": "",
            "last_seen": T1,
            "present": True,
            "state": "unknown",
        }
    ]
    assert [frame["type"] for frame in _drained(reader)] == ["hardware.devices_changed"] * 2
    assert changed == []


async def test_a_device_that_leaves_keeps_its_row_and_when_it_was_last_seen(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    await _machine(db, project, alice)
    hub, local = LiveHub(), FakeLocal([_wire_device(), _usb_device("B")])
    _reader(hub, project, alice)
    _clock(monkeypatch, T1, T2, T3, T4)
    watcher = DeviceWatcher(hub, local, sessions=app.state.sessionmaker)

    async def seen() -> dict[str, str]:
        rows = (await _fresh_machine(app, project))["devices"]
        return {row["device_ref"]: row["last_seen"] for row in rows}

    await watcher._tick()
    local.devices = [_wire_device()]  # B unplugged
    await watcher._tick()
    assert await seen() == {DEVICE_REF: T2, "usb:B": T2}
    await watcher._tick()  # nothing changed: nothing written
    assert await seen() == {DEVICE_REF: T2, "usb:B": T2}
    local.devices = []
    await watcher._tick()
    await watcher.settled()  # P2-T6: the arrivals' inspections wrote no time
    assert await seen() == {DEVICE_REF: T4, "usb:B": T2}


async def test_each_reader_hears_only_what_is_theirs(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The frame names a member's own dismissals and, for the machine's owner, when a device was
    last seen: every local reader is sent their own (a reader naming no one, nobody's)."""
    project, alice, bob = await _team(client, alice_headers, bob_headers)
    machine = await _machine(db, project, alice)
    machine.attrs = {**machine.attrs, "dismissed": {alice: [DEVICE_REF]}}
    await db.commit()
    hub = LiveHub()
    mine, theirs = _reader(hub, project, alice), _reader(hub, project, bob)
    nobody = hub.subscribe(uuid.UUID(project))
    _clock(monkeypatch, T1)

    await DeviceWatcher(hub, FakeLocal([_wire_device()]), sessions=app.state.sessionmaker)._tick()

    def annotated(frame: dict[str, Any]) -> dict[str, Any]:
        (device,) = frame["devices"]
        return {key: device[key] for key in ("bound_to", "dismissed", "last_seen")}

    (alices,) = _drained(mine)
    (bobs,) = _drained(theirs)
    (anonymous,) = _frames(nobody)
    assert annotated(alices) == {"bound_to": None, "dismissed": True, "last_seen": T1}
    assert annotated(bobs) == {"bound_to": None, "dismissed": False, "last_seen": None}
    assert annotated(anonymous) == {"bound_to": None, "dismissed": False, "last_seen": None}


async def test_the_frame_names_the_robot_whose_stored_brain_binds_a_device(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A backfilled config binds its robot's device with no binding edge, as `GET /detected`
    says: the frame agrees with the bind rule too."""
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    robot = await _backfilled_robot(db, project)
    hub = LiveHub()
    reader = _reader(hub, project, alice)
    _clock(monkeypatch, T1)

    await DeviceWatcher(
        hub, FakeLocal([_usb_device("BBB")]), sessions=app.state.sessionmaker
    )._tick()

    (frame,) = _drained(reader)
    (device,) = frame["devices"]
    assert device["bound_to"] == str(robot.id)


async def test_a_machine_the_project_does_not_know_remembers_nothing_but_still_streams(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    host: list[str | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    await _machine(db, project, alice)
    host[0] = None  # this host has no companion identity: which machine is it?
    hub = LiveHub()
    reader = _reader(hub, project, alice)
    _clock(monkeypatch, T1)

    await DeviceWatcher(hub, FakeLocal([_wire_device()]), sessions=app.state.sessionmaker)._tick()

    assert len(_drained(reader)) == 1
    assert (await _fresh_machine(app, project))["devices"] == []
