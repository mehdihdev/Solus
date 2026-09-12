"""Resolve a telemetry device/topic id to a graph entity (SOLUS-LNK-06).

Ingestion attaches a packet to "the corresponding graph entity" by matching the packet's
`device_id` against the entity's `external_ref` — the identity linchpin (`graph_entity`
docstring). Resolution is PROJECT-SCOPED: a device id known in one team's project never
resolves under another's (§7 tenant isolation) — the query filters by `project_id`, which is
derived from the authenticated request, never from the (untrusted) packet.
"""

import time
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.graph.read_scope import current_scope
from solus_api.models import GraphEntity


class EntityResolver(Protocol):
    """Maps a project-scoped device/topic id to a graph entity id, or None if unknown."""

    async def resolve(self, project_id: UUID, device_id: str) -> UUID | None: ...


class DictEntityResolver:
    """In-memory resolver for tests/dev: an explicit `(project_id, device_id) → entity_id` map."""

    def __init__(self, mapping: dict[tuple[UUID, str], UUID]) -> None:
        self._mapping = dict(mapping)

    async def resolve(self, project_id: UUID, device_id: str) -> UUID | None:
        return self._mapping.get((project_id, device_id))


class CachingEntityResolver:
    """TTL cache over another resolver for hot streaming paths (SOLUSDEV-72).

    A 50 Hz MuJoCo run emits one packet per joint per tick — resolving each
    against the DB is hundreds of queries per second for identical answers.
    POSITIVE results are cached for `ttl_seconds`; negative results are never
    cached, so a device that gets linked to an entity mid-stream attaches on
    the very next packet. Bounded: at `max_entries` the cache is cleared rather
    than grown (ponytail: full reset, LRU if churn ever matters — a reset costs
    one TTL's worth of re-queries, not correctness)."""

    def __init__(
        self,
        inner: EntityResolver,
        *,
        ttl_seconds: float = 30.0,
        max_entries: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._cache: dict[tuple[UUID, str], tuple[float, UUID]] = {}

    async def resolve(self, project_id: UUID, device_id: str) -> UUID | None:
        key = (project_id, device_id)
        hit = self._cache.get(key)
        now = self._clock()
        if hit is not None and now - hit[0] < self._ttl:
            return hit[1]
        entity_id = await self._inner.resolve(project_id, device_id)
        if entity_id is not None:
            if len(self._cache) >= self._max:
                self._cache.clear()
            self._cache[key] = (now, entity_id)
        else:
            self._cache.pop(key, None)
        return entity_id


class DbEntityResolver:
    """Resolves against `graph_entity` by `external_ref`, scoped to the given project and to
    live (non-soft-deleted) rows. Returns the matching entity id, or None."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def resolve(self, project_id: UUID, device_id: str) -> UUID | None:
        stmt = (
            select(GraphEntity.id)
            .where(
                GraphEntity.project_id == project_id,
                current_scope(project_id).entity_predicate(),
                GraphEntity.external_ref == device_id,
                GraphEntity.deleted_at.is_(None),
            )
            .limit(1)
        )
        async with self._sessionmaker() as session:
            entity_id: UUID | None = await session.scalar(stmt)
            return entity_id
