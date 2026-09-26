"""Bounded per-session capture; artifact I/O runs in owned checkpoint tasks."""

import asyncio
import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.graph.packet import TelemetryPacket
from solus_api.livebench.runs import store
from solus_api.livebench.runs.models import MAX_BYTES, MAX_PACKETS, RunManifest, RunSummary
from solus_api.livebench.sessions import SessionManager, SessionNotFoundError
from solus_api.models import utcnow
from solus_api.storage import ArtifactStore

logger = logging.getLogger(__name__)


@dataclass
class Capture:
    project_id: UUID
    user_id: UUID
    info: RunSummary
    manifest: RunManifest
    byte_count: int
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task[None] | None = None
    signals: set[tuple[str, str]] = field(default_factory=set)


class RunCaptureManager:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        artifacts: ArtifactStore,
        bench_sessions: SessionManager,
        *,
        checkpoint_seconds: float = 2,
    ) -> None:
        self.sessions = sessions
        self.artifacts = artifacts
        self.bench_sessions = bench_sessions
        self.interval = checkpoint_seconds
        self.active: dict[UUID, Capture] = {}

    def contains(self, run_id: UUID) -> bool:
        return run_id in self.active

    def add(self, capture: Capture) -> None:
        self.active[capture.info.id] = capture
        capture.task = asyncio.create_task(self._checkpoint_loop(capture))

    def ingest(self, project_id: UUID, session_id: UUID | None, packet: TelemetryPacket) -> None:
        if session_id is None:
            return
        for capture in tuple(self.active.values()):
            if (
                capture.project_id != project_id
                or capture.info.session_id != session_id
                or capture.info.status != "running"
            ):
                continue
            # Conservative JSON upper bound (including escaped names). Avoid
            # serialization, disk I/O and unbounded task creation on ingestion.
            keys = {(packet.device_id, name) for name in packet.values}
            cost = (
                256
                + len(packet.device_id) * 6
                + sum(
                    64 + len(name) * 12 + len(packet.units.get(name, "")) * 6
                    for name in packet.values
                )
            )
            if (
                len(capture.signals | keys) > 4096
                or len(capture.manifest.packets) >= MAX_PACKETS
                or capture.byte_count + cost > MAX_BYTES - 1024
            ):
                capture.info.status = "truncated"
                capture.info.drop_count += 1
                continue
            capture.signals.update(keys)
            capture.manifest.packets.append(packet.model_copy(deep=True))
            capture.byte_count += cost

    async def _checkpoint_loop(self, capture: Capture) -> None:
        try:
            while capture.info.id in self.active:
                await asyncio.sleep(self.interval)
                if capture.info.status == "running":
                    try:
                        bench = (
                            self.bench_sessions.get(capture.project_id, capture.info.session_id)
                            if capture.info.session_id
                            else None
                        )
                        if bench is None or bench.status == "ended":
                            capture.info.status = "interrupted"
                    except SessionNotFoundError:
                        capture.info.status = "interrupted"
                await self.persist(capture, final=capture.info.status != "running")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "run checkpoint failed: run=%s error=%s", capture.info.id, type(exc).__name__
            )
            self.active.pop(capture.info.id, None)

    async def persist(self, capture: Capture, *, final: bool) -> RunSummary:
        async with capture.lock:
            if final:
                self.active.pop(capture.info.id, None)
                capture.info.ended_at = utcnow()
            info = capture.info.model_copy(deep=True)
            manifest = capture.manifest.model_copy(deep=True)
            async with self.sessions() as session:
                entity = await store.record(session, capture.project_id, info.id, lock=True)
                persisted = store.summary(entity)
                if persisted.status != "running":
                    self.active.pop(info.id, None)
                    capture.info = persisted
                    return persisted
                await store.save(
                    session, self.artifacts, entity, info, manifest, capture.user_id, final=final
                )
            if final:
                capture.info = info
            else:
                # Packets can arrive while artifact I/O awaits. Keep a newly
                # observed truncation instead of replacing it with stale state.
                capture.info.packet_count = info.packet_count
            return info

    async def stop(self, run_id: UUID) -> RunSummary | None:
        capture = self.active.get(run_id)
        if capture is None:
            return None
        if capture.info.status == "running":
            capture.info.status = "completed"
        if capture.task:
            capture.task.cancel()
            await asyncio.gather(capture.task, return_exceptions=True)
        return await self.persist(capture, final=True)

    async def aclose(self) -> None:
        for capture in tuple(self.active.values()):
            if capture.info.status == "running":
                capture.info.status = "interrupted"
            await self.stop(capture.info.id)
