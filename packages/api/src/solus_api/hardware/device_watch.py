"""Hot-detect (SOLUSDEV-250 Phase 1): the local API's device-enumeration stream.

A background loop diffs `local.detect_devices()` (no port is opened) at ~1 Hz and, when the
list changes, hands the FULL current list to every project subscribed to this process's
event stream as `hardware.devices_changed` — each project once per change, so one that
subscribes between changes hears the list at its next tick.

SOLUSDEV-326: given a database, each change is also written into this machine's device memory
(`hardware/device_memory.py`) — never announced as a `graph.changed`, whose fan-out reruns every
checker on every plug — and each reader's frame says what that reader may know of each device
(`device_memory.annotate`: what binds it, their "Not now", the owner's last-seen).

P2-T6, the plug-in path (`hardware/plug_in.py`): a device that arrives unbound and not dismissed
by this machine's owner is inspected at once for that owner, while they read the project here — no
model is called. Its row says `inspecting`, then `inspected`, `busy` or `unknown`, and the readers
are sent the list again when it settles. Inspections run one at a time, outside the tick.

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
import json
import logging
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.graph.live import LiveHub, hardware_devices_frame
from solus_api.hardware.detect import detected_devices_wire
from solus_api.hardware.device_memory import (
    DeviceContext,
    annotate,
    device_context,
    record_state,
    remember_devices,
    stamp_state,
    this_machine,
)
from solus_api.hardware.plug_in import INSPECTING, arrivals, inspect_arrival, machine_owner
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


def _has_state(machine: Mapping[str, Any], ref: str, state: str | None) -> bool:
    return any(
        isinstance(row, Mapping) and row.get("device_ref") == ref and row.get("state") == state
        for row in machine.get("devices") or []
    )


def watcher_wanted(app_env: str, local: Any) -> bool:
    """Only a LOCAL runtime watches ports: no local runtime → nothing to watch; a production
    API never enumerates its host's ports for tenants, even if an image someday ships one."""
    return local is not None and app_env != "production"


class DeviceWatcher:
    def __init__(
        self,
        hub: LiveHub,
        local: Any,
        *,
        interval_s: float = 1.0,
        sessions: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._hub = hub
        self._local = local
        self._interval_s = interval_s
        self._sessions = sessions
        self._task: asyncio.Task[None] | None = None
        #: per subscribed project: the fingerprint and device refs of the list it was last told
        self._told: dict[uuid.UUID, tuple[str, frozenset[str]]] = {}
        #: the last enumeration, for the frame sent when an inspection settles
        self._devices: list[dict[str, Any]] = []
        #: plug-in inspections in flight, per (project, device ref); one listens at a time
        self._inspections: dict[tuple[uuid.UUID, str], asyncio.Task[None]] = {}
        self._listening = asyncio.Lock()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        # An in-flight to_thread enumeration or listen simply finishes; nothing awaits its
        # result. An inspection cut short stays `inspecting` and is run again by the next watcher.
        tasks = [*self._inspections.values(), *([self._task] if self._task is not None else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._task = None

    async def settled(self) -> None:
        """Wait for every plug-in inspection in flight."""
        while self._inspections:
            await asyncio.gather(*self._inspections.values(), return_exceptions=True)

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
        projects = self._hub.subscribed_project_ids()
        self._told = {project: told for project, told in self._told.items() if project in projects}
        if not projects:
            return
        try:
            devices = detected_devices_wire(await asyncio.to_thread(self._local.detect_devices))
        except Exception as exc:  # noqa: BLE001 — a bad enumeration must not end the loop
            logger.warning("device enumeration failed: %s", type(exc).__name__)
            return
        self._devices = devices
        fingerprint = _fingerprint(devices)
        refs = frozenset(device["device_ref"] for device in devices if device["device_ref"])
        at = utcnow().isoformat()
        for project_id in projects:
            told = self._told.get(project_id)
            if told is not None and told[0] == fingerprint:
                continue
            gone = told[1] - refs if told is not None else frozenset()
            try:
                await self._tell(project_id, devices, gone, at)
            except Exception as exc:  # noqa: BLE001 — retried next tick; the others are told
                logger.warning(
                    "device list not delivered project=%s error=%s", project_id, type(exc).__name__
                )
                continue
            self._told[project_id] = (fingerprint, refs)

    async def _tell(
        self, project_id: uuid.UUID, devices: list[dict[str, Any]], gone: frozenset[str], at: str
    ) -> None:
        """Remember the change on this machine, then send each local reader their own frame."""
        if self._sessions is None:
            frame = hardware_devices_frame(project_id=project_id, devices=devices, at=at)
            self._hub.publish_local(project_id, frame)
            return
        from solus_api.hardware.host_topology import LocalHostProvider  # imports the route stack

        host = await LocalHostProvider(self._local).identity()
        owner, owed = None, list[str]()
        async with self._sessions() as session:
            machine = await remember_devices(session, project_id, host, devices, gone=gone, at=at)
            context = await device_context(session, project_id, devices, machine)
            if machine is not None:
                owner = machine_owner(machine.attrs)
                owed = self._owed(project_id, owner, machine.attrs, context)
                if owed:
                    stamp_state(machine, owed, INSPECTING)
                    context = DeviceContext(machine.attrs, context.holders)
            await session.commit()
        self._publish(project_id, devices, context, at)
        for ref in owed:
            assert owner is not None  # `_owed` is empty without one
            self._inspections[project_id, ref] = asyncio.create_task(
                self._inspect(project_id, host, owner, ref, at)
            )

    def _owed(
        self,
        project_id: uuid.UUID,
        owner: uuid.UUID | None,
        machine: dict[str, Any],
        context: DeviceContext,
    ) -> list[str]:
        """The arrivals to inspect now: none unless the machine's owner reads the project here."""
        if owner is None or owner not in self._hub.local_viewers(project_id):
            return []
        running = {ref for project, ref in self._inspections if project == project_id}
        return arrivals(machine, context, running)

    async def _inspect(
        self, project_id: uuid.UUID, host: str | None, owner: uuid.UUID, ref: str, at: str
    ) -> None:
        """Inspect one arrival for the machine's owner, record how it went, and send the readers
        the list again. Runs outside the tick: a listen can outlast many."""
        assert self._sessions is not None
        recorded = False
        try:
            async with self._listening:
                # This waited its turn behind every earlier arrival's listen: a "Not now" said
                # meanwhile holds. Nothing is opened; the `inspecting` it waited under is cleared
                # (no state), so the row never reads as still being identified.
                dismissed = await self._dismissed(project_id, host, owner, ref)
                state = (
                    None
                    if dismissed
                    else await inspect_arrival(
                        self._sessions,
                        self._local,
                        project_id=project_id,
                        user_id=owner,
                        device_ref=ref,
                    )
                )
            async with self._sessions() as session:
                machine = await record_state(session, project_id, host, ref, state, only=INSPECTING)
                context = await device_context(session, project_id, self._devices, machine)
                await session.commit()
            # A dismissed arrival settled nothing: the next tick tells this project again.
            recorded = not dismissed and (machine is None or _has_state(machine.attrs, ref, state))
            self._publish(project_id, self._devices, context, at)
        except Exception as exc:  # noqa: BLE001 — one device's inspection must not end the others
            logger.warning(
                "plug-in inspection not recorded project=%s error=%s",
                project_id,
                type(exc).__name__,
            )
        finally:
            self._inspections.pop((project_id, ref), None)
            if not recorded:
                # The device left and came back meanwhile (a new arrival), or the write failed:
                # the next tick tells this project again, and what is still owed is inspected.
                self._told.pop(project_id, None)

    async def _dismissed(
        self, project_id: uuid.UUID, host: str | None, owner: uuid.UUID, ref: str
    ) -> bool:
        """Whether the machine's owner has said "Not now" to `ref`, as stored now."""
        assert self._sessions is not None
        async with self._sessions() as session:
            machine = await this_machine(session, project_id, host)
        said = (machine.attrs.get("dismissed") or {}) if machine is not None else {}
        return ref in said.get(str(owner), [])

    def _publish(
        self, project_id: uuid.UUID, devices: list[dict[str, Any]], context: DeviceContext, at: str
    ) -> None:
        self._hub.publish_local_each(
            project_id,
            {
                viewer: hardware_devices_frame(
                    project_id=project_id, devices=annotate(devices, context, viewer), at=at
                )
                for viewer in self._hub.local_viewers(project_id)
            },
        )


__all__ = ["DeviceWatcher", "watcher_wanted"]
