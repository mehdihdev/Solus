"""SOL setpoint state and routes (SOLUSDEV-319, ADR-014 amendment 2026-10-31).

docs/api/bench-view.md §5 (`GET /setpoint`, `POST /setpoint/stop`) and §6.2 (refusals);
docs/architecture/bench-view.md §6. The move itself runs in livebench, reached through the
optional `livebench.local` import. This module owns what is around it: single-use 30 s previews
(the user's confirmation is of exactly what a preview showed), one move in flight per physical
robot, and every refusal decided atomically against teleoperation under the `TeleopManager`'s
start lock. A move is only ever STARTED by the SOL `bench.setpoint` tool after its confirmation
card is approved; these routes only show and stop it.

The exceptions live here so `livebench.local` can raise them along the legal dependency
direction (the same arrangement as `teleop.NotActuatedError`).
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, require_role
from solus_api.livebench.sessions import (
    SessionManager,
    SessionNotFoundError,
    SessionStillStartingError,
)
from solus_api.livebench.teleop import (
    NotActuatedError,
    PreviewExpiredError,
    TeleopManager,
    _device_key,
)
from solus_api.models import Role, User, utcnow
from solus_api.services.events import emit_event

logger = logging.getLogger(__name__)

PREVIEW_TTL_SECONDS: Final = 30.0
MAX_PREVIEWS_PER_PROJECT: Final = 32

#: §6.2 frozen codes → the fixed sentence after "setpoint refused (<code>): ".
REFUSALS: Final[dict[str, str]] = {
    "unavailable": "local hardware is not available on this server.",
    "not_connected": "the robot is not connected right now.",
    "teleop_active": "a teleoperation is running in this project.",
    "follower": "the robot is being driven by a teleoperation.",
    "uncalibrated": "the joint has no calibrated range, or this robot cannot be driven.",
    "torque_off": "the joint's torque is off; SOL never turns torque on.",
    "in_flight": "a setpoint move is already running on this robot.",
}

SetpointEventKind = Literal["requested", "applied", "refused"]


class SetpointRefusedError(Exception):
    """A §6.2 refusal. `unit`/`clamped` are known only once the joint was resolved."""

    def __init__(self, code: str, *, unit: str | None = None, clamped: bool | None = None) -> None:
        if code not in REFUSALS:
            raise ValueError(f"unknown setpoint refusal code {code!r}")
        super().__init__(f"setpoint refused ({code}): {REFUSALS[code]}")
        self.code, self.unit, self.clamped = code, unit, clamped


class SetpointNotFoundError(LookupError):
    """Unknown session (in this project) or joint."""


@dataclass
class _Preview:
    session_id: UUID
    joint: str
    requested: float
    expires: float


@dataclass
class _Move:
    id: UUID
    session_id: UUID
    robot: str
    joint: str
    unit: str
    target: float
    clamped: bool
    key: str
    handle: Any = None
    started_at: datetime = field(default_factory=utcnow)
    ended_at: datetime | None = None

    @property
    def state(self) -> str:
        return "moving" if self.handle is None else str(self.handle.state)

    def out(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "session_id": str(self.session_id),
            "robot": self.robot,
            "joint": self.joint,
            "unit": self.unit,
            "target": self.target,
            "state": self.state,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }


class SetpointManager:
    """One per API process, beside `TeleopManager`, sharing its session manager, physical device
    keys and start lock."""

    def __init__(
        self, sessions: SessionManager, teleop: TeleopManager, local: Callable[[], Any]
    ) -> None:
        self._sessions, self._teleop, self._local = sessions, teleop, local
        self.clock: Callable[[], float] = time.monotonic
        #: Test seam: the move's tick rate (None = the livebench default, 30 Hz).
        self.rate_hz: float | None = None
        self._previews: dict[UUID, dict[UUID, _Preview]] = {}
        self._moves: dict[UUID, _Move] = {}  # the project's most recent move
        self._reserved: set[str] = set()  # robots whose move is being started
        sessions.add_end_listener(self._session_ended)

    # ── refusals ────────────────────────────────────────────────────────────────

    def _require_local(self) -> Any:
        local = self._local()
        if local is None:
            raise SetpointRefusedError("unavailable")
        return local

    def _resolve(self, project_id: UUID, session_id: UUID) -> tuple[Any, Any]:
        try:
            self._sessions.get(project_id, session_id)
        except SessionNotFoundError:
            raise SetpointNotFoundError("session") from None
        try:
            return self._sessions.connection(project_id, session_id)
        except (SessionNotFoundError, SessionStillStartingError):
            raise SetpointRefusedError("not_connected") from None

    def _teleop_reason(self, project_id: UUID, key: str) -> str | None:
        """Why teleoperation forbids moving this robot now, as a §6.2 code, or None.
        Reads the TeleopManager's state (same process, same lock) — see the module doc."""
        teleop = self._teleop
        live = [t for t in teleop._teleops.values() if t.running]
        live += list(teleop._starting.values())
        if teleop._running(project_id) is not None or project_id in teleop._starting:
            return "teleop_active"
        if key in {t.keys[1] for t in live}:
            return "follower"
        if key in {t.keys[0] for t in live}:
            return "teleop_active"  # a leader in another project: moving it would steer
        if key in teleop._releasing:
            return "torque_off"
        return None

    def _in_flight(self, key: str) -> bool:
        return key in self._reserved or any(
            m.key == key and m.state == "moving" for m in self._moves.values()
        )

    def _check(self, project_id: UUID, key: str) -> None:
        code = self._teleop_reason(project_id, key)
        if code is not None:
            raise SetpointRefusedError(code)
        if self._in_flight(key):
            raise SetpointRefusedError("in_flight")

    def _guard(self, project_id: UUID, key: str) -> Callable[[], str | None]:
        def guard() -> str | None:
            code = self._teleop_reason(project_id, key)
            return {"torque_off": "release"}.get(code, "teleop") if code else None

        return guard

    # ── preview / start ─────────────────────────────────────────────────────────

    async def preview(
        self, project_id: UUID, session_id: UUID, joint: str, target: float
    ) -> dict[str, Any]:
        """The card's facts. Raises SetpointRefusedError, SetpointNotFoundError or ValueError."""
        if not math.isfinite(target):
            raise ValueError("target must be a finite number")
        local = self._require_local()
        out, conn = self._resolve(project_id, session_id)
        self._check(project_id, _device_key(out))
        try:
            wire: dict[str, Any] = await asyncio.to_thread(
                local.setpoint_preview, conn, joint, target
            )
        except NotActuatedError:
            raise SetpointRefusedError("uncalibrated") from None
        previews = self._previews.setdefault(project_id, {})
        now = self.clock()
        for stale in [k for k, p in previews.items() if p.expires < now]:
            del previews[stale]
        while len(previews) >= MAX_PREVIEWS_PER_PROJECT:
            del previews[next(iter(previews))]
        preview_id = uuid.uuid4()
        previews[preview_id] = _Preview(session_id, joint, target, now + PREVIEW_TTL_SECONDS)
        return {
            "preview_id": str(preview_id),
            "expires_at": (utcnow() + timedelta(seconds=PREVIEW_TTL_SECONDS)).isoformat(),
            "session_id": str(session_id),
            "robot": out.label,
            "joint": wire["joint"],
            "unit": wire["unit"],
            "current": wire["current"],
            "target": wire["target"],
            "requested": wire["requested"],
            "clamped": wire["clamped"],
            "max_step": wire["max_step"],
            "max_step_ticks": wire["max_step_ticks"],
        }

    async def start(self, project_id: UUID, preview_id: UUID) -> dict[str, Any]:
        """Consume a fresh preview and start its move. Returns the move record plus `clamped`.
        Raises PreviewExpiredError, SetpointRefusedError or SetpointNotFoundError."""
        local = self._require_local()
        async with self._teleop._start_lock:  # decided atomically against teleop starts
            preview = self._previews.get(project_id, {}).pop(preview_id, None)
            if preview is None or preview.expires < self.clock():
                raise PreviewExpiredError(str(preview_id))
            out, conn = self._resolve(project_id, preview.session_id)
            key = _device_key(out)
            self._check(project_id, key)
            self._reserved.add(key)
            try:
                move = await self._launch(local, project_id, out, conn, key, preview)
            finally:
                self._reserved.discard(key)
        return {**move.out(), "clamped": move.clamped}

    async def _launch(
        self, local: Any, project_id: UUID, out: Any, conn: Any, key: str, preview: _Preview
    ) -> _Move:
        move = _Move(
            id=uuid.uuid4(),
            session_id=preview.session_id,
            robot=out.label,
            joint=preview.joint,
            unit="",
            target=preview.requested,
            clamped=False,
            key=key,
        )

        def ended(state: str) -> None:
            move.ended_at = utcnow()
            logger.info(
                "setpoint ended: project=%s move=%s session=%s state=%s",
                project_id,
                move.id,
                move.session_id,
                state,
            )

        try:
            move.handle = await local.setpoint_apply(
                conn,
                preview.joint,
                preview.requested,
                on_ended=ended,
                guard=self._guard(project_id, key),
                rate_hz=self.rate_hz,
            )
        except NotActuatedError:
            raise SetpointRefusedError("uncalibrated") from None
        move.unit, move.target, move.clamped = (
            move.handle.unit,
            move.handle.target,
            move.handle.clamped,
        )
        self._moves[project_id] = move
        logger.info(
            "setpoint started: project=%s move=%s session=%s", project_id, move.id, move.session_id
        )
        return move

    # ── state / stop ────────────────────────────────────────────────────────────

    def current(self, project_id: UUID) -> dict[str, Any] | None:
        move = self._moves.get(project_id)
        return move.out() if move is not None else None

    async def stop(self, project_id: UUID, reason: str = "user") -> dict[str, Any] | None:
        """Stop and HOLD (torque stays on). Idempotent; None when the project has no move."""
        move = self._moves.get(project_id)
        if move is None:
            return None
        if move.state == "moving":
            await self._local().setpoint_stop(move.handle, reason)
        return move.out()

    async def stop_robots(self, keys: Iterable[str], reason: str) -> None:
        """Stop any move on these physical robots (teleop start / release call this first)."""
        wanted = set(keys)
        for project_id, move in list(self._moves.items()):
            if move.key in wanted and move.state == "moving":
                await self.stop(project_id, reason)

    async def _session_ended(self, project_id: UUID, session_id: UUID) -> None:
        move = self._moves.get(project_id)
        if move is not None and move.session_id == session_id and move.state == "moving":
            await self.stop(project_id, "session_ended")

    async def aclose(self) -> None:
        for project_id, move in list(self._moves.items()):
            if move.state == "moving":
                try:
                    await self.stop(project_id, "shutdown")
                except Exception:
                    logger.exception("setpoint shutdown stop failed: %s", move.id)


def emit_setpoint_event(
    db: AsyncSession,
    *,
    user: User,
    team_id: UUID,
    project_id: UUID,
    kind: SetpointEventKind,
    unit: str | None,
    clamped: bool | None,
    code: str | None = None,
) -> None:
    """`bench.setpoint_requested/_applied/_refused {unit, clamped, code}` (route doc §8). Never
    carries names, values or targets. The caller commits."""
    emit_event(
        db,
        user=user,
        event_type=f"bench.setpoint_{kind}",
        team_id=team_id,
        project_id=project_id,
        payload={"unit": unit, "clamped": clamped, "code": code},
    )


def setpoint_manager(app: FastAPI) -> SetpointManager:
    """The app's manager; built on first use when `main.py` did not construct one."""
    manager: SetpointManager | None = getattr(app.state, "bench_setpoint", None)
    if manager is None:
        manager = app.state.bench_setpoint = SetpointManager(
            app.state.bench_sessions, app.state.bench_teleop, lambda: app.state.bench_local
        )
    return manager


# ── routes (docs/api/bench-view.md §5) ──────────────────────────────────────────

router = APIRouter(prefix="/api/v1/projects/{project_id}/bench")


def _local_manager(request: Request) -> SetpointManager:
    if request.app.state.bench_local is None:
        raise APIError(503, "source_unavailable", "Local hardware is not available on this server")
    return setpoint_manager(request.app)


@router.get("/setpoint")
async def current_setpoint(ctx: ProjectCtx, request: Request) -> dict[str, Any]:
    return envelope(_local_manager(request).current(ctx.project.id))


@router.post("/setpoint/stop")
async def stop_setpoint(ctx: ProjectCtx, request: Request) -> dict[str, Any]:
    """The safety control: member role, never rate-limited, idempotent."""
    require_role(ctx, Role.MEMBER)
    return envelope(await _local_manager(request).stop(ctx.project.id))
