"""SOLUSDEV-250 Phase 1 — hot-detect: the local API diffs `detect_devices()` at ~1 Hz and
delivers a FULL current device list to every subscribed project's stream, on this machine only.

The frame goes through `publish_local` (never Redis): one machine's device list must never fan
out to another machine's session. Nothing here opens a port.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from solus_api.graph.live import LiveHub
from solus_api.hardware.device_watch import DeviceWatcher, watcher_wanted
from test_hardware_detect import _wire_device


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
