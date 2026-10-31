"""Bounded per-session capture; artifact I/O runs in owned checkpoint tasks."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import get_args
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.graph.findings import MAX_LIMIT, FindingStatus, list_findings
from solus_api.graph.packet import TelemetryPacket
from solus_api.livebench.runs import store
from solus_api.livebench.runs.models import (
    MAX_BYTES,
    MAX_PACKETS,
    MAX_RUN_FINDINGS,
    RunFinding,
    RunManifest,
    RunSummary,
)
from solus_api.livebench.sessions import SessionManager, SessionNotFoundError
from solus_api.models import GraphEntity, utcnow
from solus_api.storage import ArtifactStore

logger = logging.getLogger(__name__)

#: Bytes the packet budget keeps back for the run's findings (`RunManifest.findings`): about 64
#: typical findings. ponytail: findings that outgrow what is left keep the most recently seen
#: that fit (logged); raise it if long robot sessions need more.
FINDINGS_RESERVE = 32 * 1024
_PACKET_BUDGET = MAX_BYTES - 1024 - FINDINGS_RESERVE


async def findings_during(
    session: AsyncSession, project_id: UUID, info: RunSummary
) -> list[RunFinding]:
    """The graph findings the run's bench session raised while it ran (SOLUSDEV-321 P2-T7):
    `evidence.session_id` is the run's session, `last_seen >= started_at` and
    `first_seen <= ended_at` (now, while it runs). Read through `list_findings` on the run's
    robot for every status (one dismissed or resolved since was still raised), newest first; a
    status stops at the page whose last row was touched before the run began, since a finding's
    `last_seen` never runs ahead of its `updated_at`. An imported run has no session: none."""
    if info.session_id is None:
        return []
    end = info.ended_at or utcnow()
    found: list[RunFinding] = []
    for status in get_args(FindingStatus):
        found += await _raised_with_status(session, project_id, info, status, end)
    return found


async def _raised_with_status(
    session: AsyncSession, project_id: UUID, info: RunSummary, status: FindingStatus, end: datetime
) -> list[RunFinding]:
    found: list[RunFinding] = []
    cursor: str | None = None
    while True:
        rows, meta = await list_findings(
            session, project_id, status=status, robot=info.robot_id, cursor=cursor, limit=MAX_LIMIT
        )
        found += [item for row in rows if (item := _run_finding(row, info, end)) is not None]
        cursor = meta["next_cursor"]
        if cursor is None or rows[-1].updated_at < info.started_at:
            return found


def _run_finding(row: GraphEntity, info: RunSummary, end: datetime) -> RunFinding | None:
    attrs = row.attrs or {}
    evidence = attrs.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("session_id") != str(info.session_id):
        return None
    keys = ("rule_id", "subjects", "severity", "count", "first_seen", "last_seen")
    try:
        item = RunFinding.model_validate({"finding_id": row.id, **{k: attrs.get(k) for k in keys}})
    except ValidationError:
        logger.warning("run finding skipped: run=%s finding=%s malformed", info.id, row.id)
        return None
    return item if item.last_seen >= info.started_at and item.first_seen <= end else None


def _fitting(found: list[RunFinding], room: int) -> list[RunFinding]:
    """The most recently seen findings whose JSON fits in `room` bytes, `MAX_RUN_FINDINGS` at
    most, so a manifest with its findings never outgrows `MAX_BYTES`."""
    kept: list[RunFinding] = []
    for item in sorted(found, key=lambda f: f.last_seen, reverse=True)[:MAX_RUN_FINDINGS]:
        room -= len(item.model_dump_json()) + 1
        if room < 0:
            break
        kept.append(item)
    return kept


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
                or capture.byte_count + cost > _PACKET_BUDGET
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
                found = await findings_during(session, capture.project_id, info)
                manifest.findings = _fitting(found, MAX_BYTES - 1024 - capture.byte_count)
                if len(manifest.findings) < len(found):
                    logger.warning(
                        "run findings trimmed: run=%s kept=%s of=%s",
                        info.id,
                        len(manifest.findings),
                        len(found),
                    )
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
