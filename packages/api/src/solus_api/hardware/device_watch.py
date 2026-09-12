"""Hot-detect (SOLUSDEV-250 Phase 1): the local API's device-enumeration stream.

A background loop diffs `local.detect_devices()` (no port is opened) at ~1 Hz and, when the
list changes, hands the FULL current list to every project subscribed to this process's
event stream as `hardware.devices_changed`.

**Local-only delivery is the invariant.** The list describes THIS machine, so it goes through
`LiveHub.publish_local` — never `publish`, which would ride Redis to every process serving the
project and put one engineer's USB devices on a teammate's screen. A cloud API with no local
runtime (`bench_local is None`) never constructs a watcher at all.

Ticks are strictly sequential (the next sleep starts after the last enumeration returns), an
idle server with no subscriber enumerates nothing, and an enumeration failure is logged and
retried on the next tick rather than ending the loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from solus_api.graph.live import LiveHub, hardware_devices_frame
from solus_api.hardware.detect import detected_devices_wire
from solus_api.models import utcnow

logger = logging.getLogger("solus.hardware.device_watch")


def _fingerprint(devices: list[dict[str, Any]]) -> str:
    # ponytail: the sorted list's JSON is the fingerprint; hash it if a machine ever shows
    # more than a few dozen devices.
    # device_ref is None for devices without a binding identity: key on that first so sorting
    # never compares None with str.
    ordered = sorted(
        devices,
        key=lambda d: (
            d.get("device_ref") is None,
            d.get("device_ref") or "",
            d.get("last_seen_path") or "",
        ),
    )
    return json.dumps(ordered, sort_keys=True)


def watcher_wanted(app_env: str, local: Any) -> bool:
    """Only a LOCAL runtime watches ports: no local runtime → nothing to watch; a production
    API never enumerates its host's ports for tenants, even if an image someday ships one."""
    return local is not None and app_env != "production"


class DeviceWatcher:
    def __init__(self, hub: LiveHub, local: Any, *, interval_s: float = 1.0) -> None:
        self._hub = hub
        self._local = local
        self._interval_s = interval_s
        self._task: asyncio.Task[None] | None = None
        self._last: str | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        # An in-flight to_thread enumeration simply finishes; nothing awaits its result.
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — a bug in one tick must not end the stream
                logger.warning("device watch tick failed: %s", type(exc).__name__)
            await asyncio.sleep(self._interval_s)

    async def _tick(self) -> None:
        if not self._hub.subscribed_project_ids():
            return
        try:
            devices = detected_devices_wire(await asyncio.to_thread(self._local.detect_devices))
        except Exception as exc:  # noqa: BLE001 — a bad enumeration must not end the loop
            logger.warning("device enumeration failed: %s", type(exc).__name__)
            return
        fingerprint = _fingerprint(devices)
        if fingerprint == self._last:
            return
        self._last = fingerprint
        at = utcnow().isoformat()
        for project_id in self._hub.subscribed_project_ids():
            self._hub.publish_local(
                project_id, hardware_devices_frame(project_id=project_id, devices=devices, at=at)
            )


__all__ = ["DeviceWatcher", "watcher_wanted"]
