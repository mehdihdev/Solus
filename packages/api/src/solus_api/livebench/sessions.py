"""Bench sessions (SOLUSDEV-72): the server-side lifecycle of a local connection.

The route that `stream_live.py` promised — a session owns one tappable
LiveConnection, tees every pumped packet into the project's `TelemetryPlumbing`
(the existing §2.13 ingest sink; there is no second telemetry path), and exposes
start/list/detail/stop. State is in-memory and project-keyed, like the bench
event ring: live ephemeral lifecycle, no durable history by decision.

Tenant binding (§7): the tap closes over the ctx-derived `project_id` — never
anything a packet claims — so a stream can only ever feed its own project. The
manager knows nothing about providers; the router hands it an `open_conn`
closure built from `livebench.local` (loaded via `load_local`, an OPTIONAL
runtime import: the package arrow points livebench → solus-api, so a server
without livebench simply reports local sources unavailable).

The device exceptions are defined HERE, not in livebench, for the same reason:
the router must catch them without importing livebench; `livebench.local`
imports and raises them along the legal dependency direction.
"""

import asyncio
import importlib
import importlib.util
import logging
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from types import ModuleType
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from solus_api.agent.interfaces import TelemetryWindow, TelemetryWindowSummary
from solus_api.connectors.live import BatchCallback, LiveStatus
from solus_api.graph.packet import TelemetryPacket
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.models import utcnow

logger = logging.getLogger(__name__)

DEFAULT_MAX_ACTIVE_PER_PROJECT = 4
DEFAULT_ENDED_KEPT = 32
DEFAULT_DEVICE_IDS_KEPT = 64
DEFAULT_WINDOW_SECONDS = 1.0


class TooManySessionsError(Exception):
    """The per-project active-session cap is hit — stop one first."""


class SessionNotFoundError(Exception):
    """No such session in this project (or not your project — same answer)."""


class SessionStillStartingError(Exception):
    """The session's connection is still opening; stop it once it lands."""


class DeviceNotFoundError(Exception):
    """No currently-enumerated device matches the requested identity."""


class AmbiguousDeviceError(Exception):
    """More than one device matches — refuse and show candidates, never guess."""

    def __init__(self, candidates: list[Any]) -> None:
        super().__init__(f"{len(candidates)} devices share this identity")
        self.candidates = candidates


def load_local() -> ModuleType | None:
    """The livebench local-source catalog, when installed on this server."""
    if importlib.util.find_spec("livebench") is None:
        return None
    return importlib.import_module("livebench.local")


class TappableConnection(Protocol):
    """The LiveConnection surface a session drives, plus the packet tap
    (structurally `PacketStreamLiveConnection` — no livebench import needed)."""

    tap: Callable[[TelemetryPacket], Awaitable[None]] | None

    async def subscribe(self, window: TelemetryWindow) -> str: ...

    def on_batch(self, handle: str, callback: BatchCallback) -> None: ...

    def status(self) -> LiveStatus: ...

    async def aclose(self) -> None: ...


async def drain_task(task: asyncio.Future[Any]) -> Any:
    """Finish owned resource cleanup even when its caller receives cancellation again."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    return task.result()


async def _acquire_connection(
    open_conn: Callable[[], Awaitable[TappableConnection]],
) -> TappableConnection:
    """Retain acquisition through cancellation, including non-cancellable worker threads."""
    opening = asyncio.ensure_future(open_conn())
    try:
        return await asyncio.shield(opening)
    except asyncio.CancelledError:
        try:
            connection = await drain_task(opening)
        except Exception as exc:
            logger.debug("cancelled connection acquisition failed: %s", type(exc).__name__)
        else:
            await drain_task(asyncio.ensure_future(connection.aclose()))
        raise


class BenchSessionOut(BaseModel):
    """Wire shape of one bench session (frozen contract with the desktop)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    mode: Literal["sim", "real"]
    provider: str
    status: Literal["starting", "active", "ended"]
    link: str
    label: str
    created_at: datetime
    ended_at: datetime | None
    device: dict[str, Any] | None
    device_ids: list[str]
    counts: dict[str, int]
    last_summary: dict[str, Any] | None


@dataclass
class _Session:
    id: UUID
    project_id: UUID
    mode: Literal["sim", "real"]
    provider: str
    label: str
    created_at: datetime
    device: dict[str, Any] | None = None
    conn: TappableConnection | None = None  # None while starting
    ended_at: datetime | None = None
    ingested: int = 0
    unresolved: int = 0
    device_ids: dict[str, None] = field(default_factory=dict)  # insertion-ordered set
    last_summary: TelemetryWindowSummary | None = None

    def out(self, *, device_ids_kept: int) -> BenchSessionOut:
        if self.ended_at is not None:
            status: Literal["starting", "active", "ended"] = "ended"
            link = LiveStatus.DISCONNECTED.value
        elif self.conn is None:
            status = "starting"
            link = LiveStatus.DISCONNECTED.value
        else:
            status = "active"
            link = self.conn.status().value
        return BenchSessionOut(
            id=self.id,
            mode=self.mode,
            provider=self.provider,
            status=status,
            link=link,
            label=self.label,
            created_at=self.created_at,
            ended_at=self.ended_at,
            device=self.device,
            device_ids=sorted(list(self.device_ids)[:device_ids_kept]),
            counts={"ingested": self.ingested, "unresolved": self.unresolved},
            last_summary=(self.last_summary.model_dump(mode="json") if self.last_summary else None),
        )


class SessionManager:
    """In-memory, project-keyed bench sessions over tappable LiveConnections."""

    def __init__(
        self,
        plumbing: TelemetryPlumbing,
        *,
        max_active_per_project: int = DEFAULT_MAX_ACTIVE_PER_PROJECT,
        ended_kept: int = DEFAULT_ENDED_KEPT,
        device_ids_kept: int = DEFAULT_DEVICE_IDS_KEPT,
    ) -> None:
        self._plumbing = plumbing
        self._cap = max_active_per_project
        self._device_ids_kept = device_ids_kept
        self._active: dict[UUID, dict[UUID, _Session]] = {}
        self._ended: dict[UUID, deque[_Session]] = {}
        self._ended_kept = ended_kept
        self._starting: set[asyncio.Task[Any]] = set()
        self._closing = False
        self.on_ended: Callable[[UUID, UUID], Awaitable[None]] | None = None
        self._ending: dict[UUID, asyncio.Task[None]] = {}

    async def start(
        self,
        project_id: UUID,
        *,
        mode: Literal["sim", "real"],
        provider: str,
        label: str,
        open_conn: Callable[[], Awaitable[TappableConnection]],
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        device: dict[str, Any] | None = None,
    ) -> BenchSessionOut:
        if self._closing:
            raise RuntimeError("Session manager is shutting down")
        await self._sweep_dead(project_id)
        if self._closing:
            raise RuntimeError("Session manager is shutting down")
        active = self._active.setdefault(project_id, {})
        if len(active) >= self._cap:
            raise TooManySessionsError(f"{self._cap} sessions already active in this project")
        # Reserve synchronously — no await between the cap check and the insert,
        # so two concurrent starts cannot both pass the cap on one event loop.
        session = _Session(
            id=uuid.uuid4(),
            project_id=project_id,
            mode=mode,
            provider=provider,
            label=label,
            created_at=utcnow(),
            device=device,
        )
        active[session.id] = session
        task = asyncio.current_task()
        assert task is not None
        self._starting.add(task)
        conn: TappableConnection | None = None
        try:
            conn = await _acquire_connection(open_conn)
            if self._closing or session.ended_at is not None or task.cancelling():
                raise asyncio.CancelledError
            conn.tap = self._tap_for(session)
            handle = await conn.subscribe(TelemetryWindow(duration_seconds=window_seconds))
            if self._closing or session.ended_at is not None or task.cancelling():
                raise asyncio.CancelledError
            conn.on_batch(handle, self._summary_sink(session))
        except BaseException:
            active.pop(session.id, None)  # a failed start never holds a slot
            if conn is not None:
                try:
                    await drain_task(asyncio.ensure_future(conn.aclose()))
                except Exception:
                    logger.warning("failed session connection cleanup: session=%s", session.id)
            raise
        finally:
            self._starting.discard(task)
        session.conn = conn
        logger.info(
            "bench session started: project=%s session=%s provider=%s",
            project_id,
            session.id,
            provider,
        )
        return session.out(device_ids_kept=self._device_ids_kept)

    def _tap_for(self, session: _Session) -> Callable[[TelemetryPacket], Awaitable[None]]:
        # Closes over the ctx-derived project id — never packet content (§7).
        project_id = session.project_id

        async def tap(packet: TelemetryPacket) -> None:
            if len(session.device_ids) < self._device_ids_kept:
                session.device_ids.setdefault(packet.device_id)
            result = await self._plumbing.ingest(project_id, packet)
            if result.entity_id is None:
                session.unresolved += 1
            else:
                session.ingested += 1

        return tap

    def _summary_sink(self, session: _Session) -> BatchCallback:
        async def sink(summary: TelemetryWindowSummary) -> None:
            session.last_summary = summary

        return sink

    def _find(self, project_id: UUID, session_id: UUID) -> _Session:
        session = self._active.get(project_id, {}).get(session_id)
        if session is None:
            for ended in self._ended.get(project_id, ()):
                if ended.id == session_id:
                    return ended
            raise SessionNotFoundError(str(session_id))
        return session

    def get(self, project_id: UUID, session_id: UUID) -> BenchSessionOut:
        return self._find(project_id, session_id).out(device_ids_kept=self._device_ids_kept)

    def list(
        self,
        project_id: UUID,
        *,
        status: Literal["active", "ended"] | None = None,
        mode: Literal["sim", "real"] | None = None,
    ) -> list[BenchSessionOut]:
        sessions: list[_Session] = [
            *self._active.get(project_id, {}).values(),
            *self._ended.get(project_id, ()),
        ]
        out = [s.out(device_ids_kept=self._device_ids_kept) for s in sessions]
        if status is not None:
            wanted = {"active": ("active", "starting"), "ended": ("ended",)}[status]
            out = [o for o in out if o.status in wanted]
        if mode is not None:
            out = [o for o in out if o.mode == mode]
        return sorted(out, key=lambda o: o.created_at)

    async def stop(self, project_id: UUID, session_id: UUID) -> BenchSessionOut:
        session = self._find(project_id, session_id)
        if session.ended_at is not None:  # concurrent callers also wait for teardown
            ending = self._ending.get(session.id)
            if ending is not None:
                await drain_task(ending)
            return session.out(device_ids_kept=self._device_ids_kept)
        if session.conn is None:
            raise SessionStillStartingError(str(session_id))
        await self._end(session)
        return session.out(device_ids_kept=self._device_ids_kept)

    async def _end(self, session: _Session) -> None:
        ending = self._ending.get(session.id)
        if ending is None:
            ending = asyncio.create_task(self._close_session(session))
            self._ending[session.id] = ending
        try:
            await drain_task(ending)
        finally:
            if ending.done():
                self._ending.pop(session.id, None)

    async def _close_session(self, session: _Session) -> None:
        # Bookkeeping FIRST, synchronously — no await between the ended_at check
        # in `stop` and these lines, so a concurrent second stop sees `ended_at`
        # set and returns idempotently instead of double-closing the connection
        # or appending the session to the ended ring twice.
        conn = session.conn
        session.ended_at = utcnow()
        self._active.get(session.project_id, {}).pop(session.id, None)
        self._ended.setdefault(session.project_id, deque(maxlen=self._ended_kept)).append(session)
        if conn is not None:
            try:
                # aclose only — it cancels the pump and flushes the pending partial
                # window (the contract's teardown); unsubscribe would KeyError.
                await conn.aclose()
            except Exception as exc:
                # The session IS ended; a teardown error must not 500 the stop.
                logger.warning(
                    "bench session close failed: project=%s session=%s error=%s",
                    session.project_id,
                    session.id,
                    type(exc).__name__,
                )
        if self.on_ended is not None:
            await self.on_ended(session.project_id, session.id)

    async def _sweep_dead(self, project_id: UUID) -> None:
        """End active sessions whose pump has finished (duration elapsed, replay
        exhausted, fatal link error) — they must not hold cap slots, ports, or
        subprocesses. A reconnecting serial link keeps its pump alive and is
        never swept."""
        for session in list(self._active.get(project_id, {}).values()):
            if session.conn is not None and session.conn.status() is LiveStatus.DISCONNECTED:
                await self._end(session)

    async def aclose_all(self) -> None:
        """Shutdown teardown: close every active session's pump/subprocesses/ports."""
        self._closing = True
        starting = list(self._starting)
        for task in starting:
            task.cancel()
        await asyncio.gather(*starting, return_exceptions=True)
        for project_sessions in list(self._active.values()):
            for session in list(project_sessions.values()):
                await self._end(session)

        for ending in list(self._ending.values()):
            await drain_task(ending)
