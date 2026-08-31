"""The bridge session registry (contract §3).

One live session per (user, team, project) scope. The routing invariant is
structural: lookups are keyed by the server-derived scope triple, so a call for
team A can only ever reach a session bound to exactly that scope — there is no
fallback and no widening. Mirrors graph/buffer.py: a narrow Protocol with an
in-memory backend chosen at app assembly.

ponytail: in-memory, single API instance; a Redis-backed registry (presence +
pub/sub routing) replaces this when multi-instance Fargate lands — the Protocol
is the seam.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from solus_api.agent.tools.shapes import ToolResult
from solus_api.bridge.allowlist import BridgeToolSpec
from solus_api.bridge.frames import ArtifactChunkData, StatusData

ScopeKey = tuple[uuid.UUID, uuid.UUID, uuid.UUID]  # (user_id, team_id, project_id)


@dataclass
class BridgeSession:
    """One authenticated companion socket. Scope fields are SERVER-derived at
    bind (contract §3); `companion_instance_id` is client-supplied and used for
    routing/telemetry only — never authorization."""

    session_id: str
    user_id: uuid.UUID
    team_id: uuid.UUID
    project_id: uuid.UUID
    companion_instance_id: str
    companion_version: str
    protocol_version: int
    connected_at: datetime
    token_exp: datetime
    inventory: tuple[BridgeToolSpec, ...]
    send: Callable[[str], Awaitable[None]]
    close: Callable[[int], Awaitable[None]]
    max_inflight: int
    #: SOLUSDEV-167: may this socket's principal trigger a graph WRITE? Resolved
    #: from membership at bind (MEMBER or above), server-derived like every other
    #: scope field — never inferred from a frame.
    may_write: bool = False
    inflight: dict[str, asyncio.Future[ToolResult]] = field(default_factory=dict)
    # BRG-03: the last status snapshot (advisory, UI-facing; dies with the session).
    last_status: StatusData | None = None
    status_updated_at: datetime | None = None
    # SOLUS-CAD-00c: in-flight artifact pulls, keyed by fetch_id. Separate id
    # space from `inflight` (tool calls) so a chunk can never resolve a call.
    artifact_fetches: dict[str, "asyncio.Queue[ArtifactChunkData]"] = field(default_factory=dict)
    entered: int = 0  # dispatchers inside dispatch() (running + queued)
    slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))

    def __post_init__(self) -> None:
        self.slots = asyncio.Semaphore(self.max_inflight)

    @property
    def scope(self) -> ScopeKey:
        return (self.user_id, self.team_id, self.project_id)


class BridgeSessionRegistry(Protocol):
    """Lookup is exact-scope only — the §3 routing invariant."""

    def get(
        self, user_id: uuid.UUID, team_id: uuid.UUID, project_id: uuid.UUID
    ) -> BridgeSession | None: ...

    def bind(self, session: BridgeSession) -> BridgeSession | None:
        """Register; returns the superseded prior session for the same scope,
        if any (caller runs the §3 supersede sequence)."""
        ...

    def remove(self, session: BridgeSession) -> None:
        """Unregister, only if this exact session is still the current one —
        a superseded session's late cleanup must not evict its successor."""
        ...

    def count_for_team(self, team_id: uuid.UUID) -> int: ...


class InMemoryBridgeSessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[ScopeKey, BridgeSession] = {}

    def get(
        self, user_id: uuid.UUID, team_id: uuid.UUID, project_id: uuid.UUID
    ) -> BridgeSession | None:
        return self._sessions.get((user_id, team_id, project_id))

    def bind(self, session: BridgeSession) -> BridgeSession | None:
        old = self._sessions.get(session.scope)
        self._sessions[session.scope] = session
        return old

    def remove(self, session: BridgeSession) -> None:
        if self._sessions.get(session.scope) is session:
            del self._sessions[session.scope]

    def count_for_team(self, team_id: uuid.UUID) -> int:
        return sum(1 for s in self._sessions.values() if s.team_id == team_id)
