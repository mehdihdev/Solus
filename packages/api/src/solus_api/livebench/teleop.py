"""Leader → follower teleoperation state (SOLUSDEV-319, ADR-014 amendment 2026-10-30).

The loop itself lives in livebench and is reached through the optional `livebench.local` import
(the package arrow points livebench → solus-api), like every other local hardware call. This
module owns what the routes need around it: single-use previews with a short life (the user's
confirmation is of exactly what a preview showed), one teleop per project, stopping it before
either robot's link closes, and refusing to release a follower that is being driven.

The exceptions are defined here so `livebench.local` can raise them along the legal dependency
direction (the same arrangement as `sessions.DeviceNotFoundError`).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Literal, Protocol
from uuid import UUID

from solus_api.livebench.sessions import BenchSessionOut, SessionManager, SessionNotFoundError
from solus_api.models import utcnow

logger = logging.getLogger(__name__)

PREVIEW_TTL_SECONDS: Final = 30.0
#: Previews are requested ~2x a second while a dialog is open; keep a bounded few per project.
MAX_PREVIEWS_PER_PROJECT: Final = 32


class NotActuatedError(Exception):
    """The robot's driver exposes no actuator (it can be read, never driven)."""


class TeleopNotReadyError(Exception):
    def __init__(self, preview: dict[str, Any]) -> None:
        super().__init__("teleoperation is not ready to start")
        self.preview = preview


class TeleopRunningError(Exception):
    """The project already runs a teleop, or the robot is its follower."""


class PreviewExpiredError(Exception):
    """Unknown, used or expired preview — preview again."""


def _not_ready(code: str, message: str) -> dict[str, Any]:
    return {
        "ready": False,
        "blockers": [{"code": code, "message": message}],
        "pairs": [],
        "tolerance": {},
    }


def _device_key(out: BenchSessionOut) -> str:
    """The physical robot behind a session: two sessions (any project) on one arm share it."""
    device = out.device or {}
    ref = device.get("device_ref")
    if not ref and device.get("serial_number"):
        ref = f"usb:{device['serial_number']}"
    return str(ref) if ref else f"session:{out.id}"


@dataclass
class _Preview:
    leader: UUID
    follower: UUID
    expires: float
    wire: dict[str, Any]


@dataclass
class _Teleop:
    id: UUID
    leader: dict[str, str]
    follower: dict[str, str]
    loop: Any
    keys: tuple[str, str] = ("", "")  # physical (leader, follower)
    started_at: datetime = field(default_factory=utcnow)
    stopped_at: datetime | None = None
    stop_reason: str | None = None
    pending_stop: str | None = None  # asked to stop while its loop was still starting

    @property
    def running(self) -> bool:
        return self.stop_reason is None

    def out(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "state": "running" if self.running else "stopped",
            "leader": self.leader,
            "follower": self.follower,
            "rate_hz": self.loop.rate_hz,
            "started_at": self.started_at.isoformat(),
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
            "stop_reason": self.stop_reason,
            "pairs": [
                {k: pair[k] for k in ("address", "leader_signal", "follower_signal")}
                for pair in self.loop.pairs
            ],
        }


StopRecorder = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
RobotRole = Literal["leader", "follower", "releasing"]


class SetpointStopper(Protocol):
    """What teleop needs of the setpoint manager (wired by its owner, not imported: the setpoint
    module imports this one). A teleop start or a release ends any move on its robots first."""

    async def stop_robots(self, keys: Iterable[str], reason: str) -> None: ...


class TeleopManager:
    def __init__(self, sessions: SessionManager, local: Callable[[], Any]) -> None:
        self._sessions = sessions
        self._local = local
        self.clock: Callable[[], float] = time.monotonic
        self._previews: dict[UUID, dict[UUID, _Preview]] = {}
        self._teleops: dict[UUID, _Teleop] = {}
        #: Starts in flight, so stop / session end / shutdown can reach them before they run.
        self._starting: dict[UUID, _Teleop] = {}
        #: Robots whose torque-off is on the bus right now: never started or paired meanwhile.
        self._releasing: set[str] = set()
        self._start_lock = asyncio.Lock()
        self._recording: set[asyncio.Task[None]] = set()  # keep stop-event tasks referenced
        #: Optional; None leaves start / release exactly as before (no setpoint to stop).
        self.setpoints: SetpointStopper | None = None
        sessions.add_end_listener(self._session_ended)

    def _running(self, project_id: UUID) -> _Teleop | None:
        teleop = self._teleops.get(project_id)
        return teleop if teleop is not None and teleop.running else None

    def _busy(self) -> set[str]:
        """Physical robots in any running or starting teleop, across every project."""
        live = [t for t in self._teleops.values() if t.running] + list(self._starting.values())
        return {key for teleop in live for key in teleop.keys} | self._releasing

    # ── read accessors (for the setpoint manager's refusals) ──────────────────────

    @property
    def start_lock(self) -> asyncio.Lock:
        """Held while a start or release is checked and claimed; decide against it under it."""
        return self._start_lock

    def project_active(self, project_id: UUID) -> bool:
        """A teleop is running or starting in this project."""
        return self._running(project_id) is not None or project_id in self._starting

    def robot_role(self, key: str) -> RobotRole | None:
        """This physical robot's part in any running or starting teleop, or its torque-off."""
        live = [t for t in self._teleops.values() if t.running] + list(self._starting.values())
        if key in {t.keys[1] for t in live}:
            return "follower"
        if key in {t.keys[0] for t in live}:
            return "leader"
        return "releasing" if key in self._releasing else None

    async def _stop_setpoints(self, keys: Iterable[str], reason: str) -> None:
        if self.setpoints is not None:
            await self.setpoints.stop_robots(set(keys), reason)

    @staticmethod
    def _end(session_id: UUID, label: str) -> dict[str, str]:
        return {"session_id": str(session_id), "label": label}

    async def preview(self, project_id: UUID, leader: UUID, follower: UUID) -> dict[str, Any]:
        """Raises SessionNotFoundError for a session that is not active in THIS project."""
        leader_out, leader_conn = self._sessions.connection(project_id, leader)
        follower_out, follower_conn = self._sessions.connection(project_id, follower)
        if leader == follower or _device_key(leader_out) == _device_key(follower_out):
            wire = _not_ready("same_session", "Pick two different robots.")
        else:
            try:
                wire = await asyncio.to_thread(
                    self._local().teleop_preview, leader_conn, follower_conn
                )
            except NotActuatedError as exc:
                wire = _not_ready("not_actuated", str(exc))
        busy = self._busy()
        if (
            self._running(project_id) is not None
            or project_id in self._starting
            or {_device_key(leader_out), _device_key(follower_out)} & busy
        ):
            running = {"code": "teleop_running", "message": "A teleoperation is already running."}
            wire = {**wire, "ready": False, "blockers": [*wire["blockers"], running]}
        previews = self._previews.setdefault(project_id, {})
        now = self.clock()
        for stale in [k for k, p in previews.items() if p.expires < now]:
            del previews[stale]
        while len(previews) >= MAX_PREVIEWS_PER_PROJECT:
            del previews[next(iter(previews))]
        preview_id = uuid.uuid4()
        previews[preview_id] = _Preview(leader, follower, now + PREVIEW_TTL_SECONDS, wire)
        return {
            "preview_id": str(preview_id),
            "expires_at": (utcnow() + timedelta(seconds=PREVIEW_TTL_SECONDS)).isoformat(),
            "leader": self._end(leader, leader_out.label),
            "follower": self._end(follower, follower_out.label),
            **wire,
        }

    async def start(
        self, project_id: UUID, preview_id: UUID, *, record_stop: StopRecorder | None = None
    ) -> dict[str, Any]:
        async with self._start_lock:  # one check-and-reserve at a time (no double start)
            teleop = self._reserve(project_id, preview_id)
        try:
            return await self._launch(project_id, teleop, record_stop)
        finally:
            self._starting.pop(project_id, None)

    def _reserve(self, project_id: UUID, preview_id: UUID) -> _Teleop:
        if self._running(project_id) is not None or project_id in self._starting:
            raise TeleopRunningError("a teleoperation is already running in this project")
        preview = self._previews.get(project_id, {}).pop(preview_id, None)
        if preview is None or preview.expires < self.clock():
            raise PreviewExpiredError(str(preview_id))
        if not preview.wire["ready"]:
            raise TeleopNotReadyError(preview.wire)
        leader_out, _ = self._sessions.connection(project_id, preview.leader)
        follower_out, _ = self._sessions.connection(project_id, preview.follower)
        keys = (_device_key(leader_out), _device_key(follower_out))
        if set(keys) & self._busy():
            raise TeleopRunningError("one of these robots is already in a teleoperation")
        teleop = _Teleop(
            id=uuid.uuid4(),
            leader=self._end(preview.leader, leader_out.label),
            follower=self._end(preview.follower, follower_out.label),
            loop=None,
            keys=keys,
        )
        self._starting[project_id] = teleop
        return teleop

    async def _launch(
        self, project_id: UUID, teleop: _Teleop, record_stop: StopRecorder | None
    ) -> dict[str, Any]:
        leader_id = UUID(teleop.leader["session_id"])
        follower_id = UUID(teleop.follower["session_id"])
        _, leader_conn = self._sessions.connection(project_id, leader_id)
        _, follower_conn = self._sessions.connection(project_id, follower_id)
        # Reserved (so no new move can start on these robots); end any in flight before hold.
        await self._stop_setpoints(teleop.keys, "teleop")

        def stopped(reason: str) -> None:
            if not teleop.running:
                return
            teleop.stop_reason, teleop.stopped_at = reason, utcnow()
            logger.info(
                "teleop stopped: project=%s teleop=%s leader=%s follower=%s reason=%s",
                project_id,
                teleop.id,
                teleop.leader["session_id"],
                teleop.follower["session_id"],
                reason,
            )
            if record_stop is not None:
                task = asyncio.get_running_loop().create_task(record_stop(teleop.out()))
                self._recording.add(task)
                task.add_done_callback(self._recording.discard)

        try:
            teleop.loop = await self._local().teleop_start(
                leader_conn, follower_conn, on_stopped=stopped
            )
        except NotActuatedError as exc:
            raise TeleopNotReadyError(_not_ready("not_actuated", str(exc))) from exc
        self._teleops[project_id] = teleop
        try:  # either robot's session may have ended while the loop was starting
            self._sessions.connection(project_id, leader_id)
            self._sessions.connection(project_id, follower_id)
        except SessionNotFoundError:
            await teleop.loop.stop("session_ended")
            raise
        if teleop.pending_stop is not None:
            await teleop.loop.stop(teleop.pending_stop)
        return teleop.out()

    def current(self, project_id: UUID) -> dict[str, Any] | None:
        teleop = self._teleops.get(project_id)
        return teleop.out() if teleop is not None else None

    async def stop(self, project_id: UUID, reason: str = "user") -> dict[str, Any] | None:
        """Stop and HOLD: the follower keeps its last goal with torque on."""
        starting = self._starting.get(project_id)
        if starting is not None:
            starting.pending_stop = starting.pending_stop or reason
        teleop = self._teleops.get(project_id)
        if teleop is None:
            return None
        if teleop.running:
            await teleop.loop.stop(reason)
        return teleop.out()

    async def release(self, project_id: UUID, session_id: UUID) -> None:
        out, conn = self._sessions.connection(project_id, session_id)
        key = _device_key(out)
        async with self._start_lock:  # checked and claimed atomically against starts
            live = [t for t in self._teleops.values() if t.running]
            live += list(self._starting.values())
            if key in {teleop.keys[1] for teleop in live} or key in self._releasing:
                raise TeleopRunningError("stop teleoperation before releasing its follower")
            self._releasing.add(key)
        try:
            await self._stop_setpoints({key}, "release")  # never torque off under a move
            await asyncio.to_thread(self._local().robot_release, conn)
        finally:
            self._releasing.discard(key)

    async def _session_ended(self, project_id: UUID, session_id: UUID) -> None:
        starting = self._starting.get(project_id)
        if starting is not None and str(session_id) in (
            starting.leader["session_id"],
            starting.follower["session_id"],
        ):
            starting.pending_stop = starting.pending_stop or "session_ended"
        teleop = self._running(project_id)
        ends = (teleop.leader["session_id"], teleop.follower["session_id"]) if teleop else ()
        if teleop is not None and str(session_id) in ends:
            await teleop.loop.stop("session_ended")

    async def aclose(self) -> None:
        for starting in self._starting.values():
            starting.pending_stop = starting.pending_stop or "shutdown"
        for teleop in list(self._teleops.values()):
            if teleop.running:
                try:
                    await teleop.loop.stop("shutdown")
                except Exception:
                    logger.exception("teleop shutdown stop failed: %s", teleop.id)
