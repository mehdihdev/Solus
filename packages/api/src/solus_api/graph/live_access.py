"""Access re-verification and stream limits for the live SSE routes (ADR-037 §5).

A live stream outlives the request that authorised it, so authorisation is re-checked while
it is open: on every `access.revoked` / `membership.changed` hint, and at least every
`REVERIFY_SECONDS`. Each check opens a SHORT session — a streaming response must never hold
a DB connection (see routers/live.py) — and re-decodes the bearer token, so an expired or
invalidated credential ends the stream too.

Nothing here provisions: an unknown user is "revoked", never created.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.core.security import TokenClaims, decode_token
from solus_api.graph.live import Channel
from solus_api.models import Membership, Project, ProjectMembership, Team, User

logger = logging.getLogger("solus.graph.live_access")

#: Open live streams allowed per user, per process, across both stream routes.
MAX_STREAMS_PER_USER = 8


def account_channels(user_id: uuid.UUID, team_ids: list[uuid.UUID]) -> list[Channel]:
    """The account stream's subscription: the user's own channel plus one per live team."""
    return [Channel.user(user_id), *(Channel.team(team_id) for team_id in team_ids)]


async def live_team_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Teams the user belongs to right now: live membership in a team that is not deleted."""
    rows = await session.scalars(
        select(Membership.team_id)
        .join(Team, Team.id == Membership.team_id)
        .where(
            Membership.user_id == user_id,
            Membership.deleted_at.is_(None),
            Team.deleted_at.is_(None),
        )
    )
    return sorted(set(rows.all()), key=str)


@dataclass(frozen=True)
class LiveAccessVerifier:
    """Re-checks one open stream's credential and scope. Built per request by
    `deps.get_live_verifier`, which supplies the raw bearer token."""

    sessionmaker: async_sessionmaker[AsyncSession]
    settings: Settings
    jwks_client: Any
    token: str

    def _claims(self) -> TokenClaims | None:
        try:
            return decode_token(self.token, self.settings, self.jwks_client)
        except APIError:
            return None  # expired, tampered, wrong audience: the credential is dead

    async def _user(self, session: AsyncSession, user_id: uuid.UUID) -> User | None:
        """The still-live user this token belongs to, or None."""
        claims = self._claims()
        if claims is None:
            return None
        user = await session.scalar(select(User).where(User.supabase_user_id == claims.sub))
        if user is None or user.id != user_id or user.deleted_at is not None:
            return None
        return user

    async def account_teams(self, user_id: uuid.UUID) -> list[uuid.UUID] | None:
        """The user's current team ids, or None when the account stream must end."""
        async with self.sessionmaker() as session:
            if await self._user(session, user_id) is None:
                return None
            return await live_team_ids(session, user_id)

    async def project_access(self, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Same rule as `deps.get_project_context` (team member OR direct share), plus: a
        deleted project or team grants nothing."""
        # Function-local: `deps` imports this module for its dependency provider.
        from solus_api.deps import live_membership

        async with self.sessionmaker() as session:
            if await self._user(session, user_id) is None:
                return False
            project = await session.get(Project, project_id)
            if project is None or project.deleted_at is not None:
                return False
            team = await session.get(Team, project.team_id)
            if team is None or team.deleted_at is not None:
                return False
            if await live_membership(session, project.team_id, user_id) is not None:
                return True
            share = await session.scalar(
                select(ProjectMembership).where(
                    ProjectMembership.project_id == project_id,
                    ProjectMembership.user_id == user_id,
                    ProjectMembership.deleted_at.is_(None),
                )
            )
            return share is not None


class StreamPermit:
    """One held stream slot. `release` is idempotent, so the generator's `finally` and the
    response's background hook can both call it."""

    __slots__ = ("_limiter", "_released", "_user_id")

    def __init__(self, limiter: StreamLimiter, user_id: uuid.UUID) -> None:
        self._limiter = limiter
        self._user_id = user_id
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._limiter._release(self._user_id)


class StreamLimiter:
    """Caps concurrent live streams per user within this process (ADR-037, CLAUDE.md §7).

    Per process by design: a hard global cap would need shared state on the hot path, and
    this exists to stop one runaway client exhausting a worker's connections.
    """

    def __init__(self, max_per_user: int = MAX_STREAMS_PER_USER) -> None:
        self._max = max_per_user
        self._open: Counter[uuid.UUID] = Counter()

    def acquire(self, user_id: uuid.UUID) -> StreamPermit | None:
        if self._open[user_id] >= self._max:
            return None
        self._open[user_id] += 1
        return StreamPermit(self, user_id)

    def open_count(self, user_id: uuid.UUID) -> int:
        return self._open[user_id]

    def _release(self, user_id: uuid.UUID) -> None:
        self._open[user_id] -= 1
        if self._open[user_id] <= 0:
            del self._open[user_id]
