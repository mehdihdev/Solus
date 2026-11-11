"""SOLUSDEV-322 P2-T1 — the simulator session ownership ledger (table `sim_session`).

A session is owned only when Solus itself started it: the wrapper that started it writes the
row (`record_owned_start`) in the same breath, and the per-call gate (`agent/dynamic_gate.py`)
asks `is_owned` before letting an action inside it through without a card. A session Solus only
attached to (`record_attached`), an id nobody recorded, an ended session or another project's
row is never owned: where ownership cannot be proven, the answer is a card.

Shared code: `provider` is a string the wrappers pass; this module names no simulator. One owned
session per `(project, provider)`: `record_owned_start` refuses a second while one is live.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, select, update

from solus_api.core.errors import APIError
from solus_api.models import SimSession, SimSessionOwner, utcnow
from solus_api.services.solus_graph import lock_project

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class OwnedSessionRunningError(APIError):
    """A Solus-owned session of this provider is already live in the project."""

    def __init__(self, provider: str) -> None:
        super().__init__(
            409, "sim_session_running", f"A {provider} session Solus started is still running"
        )


class SimSessionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    provider: str
    session_id: str
    owner: Literal["sol", "user"]
    started_by_call_id: str | None
    scene_ref: str | None
    scene_name: str | None = None
    started_at: datetime
    ended_at: datetime | None

    @classmethod
    def of(cls, row: SimSession) -> Self:
        return cls.model_validate(
            {
                "project_id": row.project_id,
                "provider": row.provider,
                "session_id": row.session_id,
                "owner": row.owner.value,
                "started_by_call_id": row.started_by_call_id,
                "scene_ref": row.scene_ref,
                "scene_name": row.scene_name,
                "started_at": row.started_at,
                "ended_at": row.ended_at,
            }
        )


def _live_sessions(project_id: UUID, provider: str | None = None) -> Select[tuple[SimSession]]:
    stmt = select(SimSession).where(
        SimSession.project_id == project_id, SimSession.ended_at.is_(None)
    )
    return stmt.where(SimSession.provider == provider) if provider is not None else stmt


class SessionsLedger:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record_owned_start(
        self,
        *,
        project_id: UUID,
        provider: str,
        session_id: str,
        call_id: str | None,
        scene_ref: str | None,
        created_by: UUID | None,
        scene_name: str | None = None,
    ) -> SimSessionRecord:
        async with self._sessions() as session, session.begin():
            await lock_project(session, project_id)
            live = _live_sessions(project_id, provider).where(
                (SimSession.owner == SimSessionOwner.SOL) | (SimSession.session_id == session_id)
            )
            if await session.scalar(live.limit(1)) is not None:
                raise OwnedSessionRunningError(provider)
            row = SimSession(
                project_id=project_id,
                provider=provider,
                session_id=session_id,
                owner=SimSessionOwner.SOL,
                started_by_call_id=call_id,
                scene_ref=scene_ref,
                scene_name=scene_name,
                created_by=created_by,
            )
            session.add(row)
            await session.flush()
            return SimSessionRecord.of(row)

    async def record_attached(
        self,
        *,
        project_id: UUID,
        provider: str,
        session_id: str,
        scene_ref: str | None,
        created_by: UUID | None,
        scene_name: str | None = None,
    ) -> SimSessionRecord:
        """Attaching to an id already live returns its row as it is: an attach never changes
        who owns a session."""
        async with self._sessions() as session, session.begin():
            await lock_project(session, project_id)
            existing = await session.scalar(
                _live_sessions(project_id, provider).where(SimSession.session_id == session_id)
            )
            if existing is not None:
                return SimSessionRecord.of(existing)
            row = SimSession(
                project_id=project_id,
                provider=provider,
                session_id=session_id,
                owner=SimSessionOwner.USER,
                scene_ref=scene_ref,
                scene_name=scene_name,
                created_by=created_by,
            )
            session.add(row)
            await session.flush()
            return SimSessionRecord.of(row)

    async def is_owned(self, *, project_id: UUID, provider: str, session_id: str) -> bool:
        async with self._sessions() as session:
            found = await session.scalar(
                _live_sessions(project_id, provider).where(
                    SimSession.session_id == session_id, SimSession.owner == SimSessionOwner.SOL
                )
            )
            return found is not None

    async def end_session(self, *, project_id: UUID, provider: str, session_id: str) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(SimSession)
                .where(
                    SimSession.project_id == project_id,
                    SimSession.provider == provider,
                    SimSession.session_id == session_id,
                    SimSession.ended_at.is_(None),
                )
                .values(ended_at=utcnow())
            )

    async def running(
        self, *, project_id: UUID, provider: str | None = None
    ) -> list[SimSessionRecord]:
        async with self._sessions() as session:
            rows = await session.scalars(
                _live_sessions(project_id, provider).order_by(SimSession.started_at, SimSession.id)
            )
            return [SimSessionRecord.of(row) for row in rows]

    async def owned_running_count(self, *, project_id: UUID, provider: str) -> int:
        async with self._sessions() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(SimSession)
                .where(
                    SimSession.project_id == project_id,
                    SimSession.provider == provider,
                    SimSession.ended_at.is_(None),
                    SimSession.owner == SimSessionOwner.SOL,
                )
            )
            return int(count or 0)
