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
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

from solus_api.livebench.sessions import SessionManager
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
    started_at: datetime = field(default_factory=utcnow)
    stopped_at: datetime | None = None
    stop_reason: str | None = None

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


class TeleopManager:
    def __init__(self, sessions: SessionManager, local: Callable[[], Any]) -> None:
        self._sessions = sessions
        self._local = local
        self.clock: Callable[[], float] = time.monotonic
        self._previews: dict[UUID, dict[UUID, _Preview]] = {}
        self._teleops: dict[UUID, _Teleop] = {}
        self._recording: set[asyncio.Task[None]] = set()  # keep stop-event tasks referenced
        sessions.add_end_listener(self._session_ended)

    def _running(self, project_id: UUID) -> _Teleop | None:
        teleop = self._teleops.get(project_id)
        return teleop if teleop is not None and teleop.running else None

    @staticmethod
    def _end(session_id: UUID, label: str) -> dict[str, str]:
        return {"session_id": str(session_id), "label": label}

    async def preview(self, project_id: UUID, leader: UUID, follower: UUID) -> dict[str, Any]:
        """Raises SessionNotFoundError for a session that is not active in THIS project."""
        leader_out, leader_conn = self._sessions.connection(project_id, leader)
        follower_out, follower_conn = self._sessions.connection(project_id, follower)
        if leader == follower:
            wire = _not_ready("same_session", "Pick two different robots.")
        else:
            try:
                wire = await asyncio.to_thread(
                    self._local().teleop_preview, leader_conn, follower_conn
                )
            except NotActuatedError as exc:
                wire = _not_ready("not_actuated", str(exc))
        if self._running(project_id) is not None:
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
        if self._running(project_id) is not None:
            raise TeleopRunningError("a teleoperation is already running in this project")
        preview = self._previews.get(project_id, {}).pop(preview_id, None)
        if preview is None or preview.expires < self.clock():
            raise PreviewExpiredError(str(preview_id))
        if not preview.wire["ready"]:
            raise TeleopNotReadyError(preview.wire)
        leader_out, leader_conn = self._sessions.connection(project_id, preview.leader)
        follower_out, follower_conn = self._sessions.connection(project_id, preview.follower)
        teleop = _Teleop(
            id=uuid.uuid4(),
            leader=self._end(preview.leader, leader_out.label),
            follower=self._end(preview.follower, follower_out.label),
            loop=None,
        )

        def stopped(reason: str) -> None:
            if not teleop.running:
                return
            teleop.stop_reason, teleop.stopped_at = reason, utcnow()
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
        return teleop.out()

    def current(self, project_id: UUID) -> dict[str, Any] | None:
        teleop = self._teleops.get(project_id)
        return teleop.out() if teleop is not None else None

    async def stop(self, project_id: UUID, reason: str = "user") -> dict[str, Any] | None:
        """Stop and HOLD: the follower keeps its last goal with torque on."""
        teleop = self._teleops.get(project_id)
        if teleop is None:
            return None
        if teleop.running:
            await teleop.loop.stop(reason)
        return teleop.out()

    async def release(self, project_id: UUID, session_id: UUID) -> None:
        _, conn = self._sessions.connection(project_id, session_id)
        teleop = self._running(project_id)
        if teleop is not None and teleop.follower["session_id"] == str(session_id):
            raise TeleopRunningError("stop teleoperation before releasing its follower")
        await asyncio.to_thread(self._local().robot_release, conn)

    async def _session_ended(self, project_id: UUID, session_id: UUID) -> None:
        teleop = self._running(project_id)
        ends = (teleop.leader["session_id"], teleop.follower["session_id"]) if teleop else ()
        if teleop is not None and str(session_id) in ends:
            await teleop.loop.stop("session_ended")

    async def aclose(self) -> None:
        for teleop in list(self._teleops.values()):
            if teleop.running:
                try:
                    await teleop.loop.stop("shutdown")
                except Exception:
                    logger.exception("teleop shutdown stop failed: %s", teleop.id)
