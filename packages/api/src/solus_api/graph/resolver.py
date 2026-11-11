"""Resolve a telemetry device/topic id to a graph entity (SOLUS-LNK-06).

Ingestion attaches a packet to "the corresponding graph entity" by matching the packet's
`device_id` against the entity's `external_ref` — the identity linchpin (`graph_entity`
docstring). Resolution is PROJECT-SCOPED: a device id known in one team's project never
resolves under another's (§7 tenant isolation) — the query filters by `project_id`, which is
derived from the authenticated request, never from the (untrusted) packet.

SOLUSDEV-322 P5-T2 — the session-level `source` tag. A simulated joint and the real one must
land on the SAME part node. A sim session's packets resolve with `source=<provider>` (the
session's provider, set server-side, never by a packet): besides `external_ref`, a part answers
when its `attrs.sim_aliases` (rows `{provider, device_id}`, written only by the gated mapping
tool) holds `{provider: source, device_id}`. ONE query, an `external_ref` hit winning — no second
round trip per unresolved 50 Hz packet. Without a source nothing changes: the query is the
pre-322 one.
"""

import time
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from sqlalchemy import Select, and_, case, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.graph.read_scope import current_scope
from solus_api.models import GraphEntity

ALIASES = "sim_aliases"


class EntityResolver(Protocol):
    """Maps a project-scoped device/topic id to a graph entity id, or None if unknown.
    `source` is the session's provider tag; None resolves by `external_ref` alone."""

    async def resolve(
        self, project_id: UUID, device_id: str, *, source: str | None = None
    ) -> UUID | None: ...


class DictEntityResolver:
    """In-memory resolver for tests/dev: an explicit `(project_id, device_id) → entity_id` map.
    Ignores `source`."""

    def __init__(self, mapping: dict[tuple[UUID, str], UUID]) -> None:
        self._mapping = dict(mapping)

    async def resolve(
        self, project_id: UUID, device_id: str, *, source: str | None = None
    ) -> UUID | None:
        return self._mapping.get((project_id, device_id))


class CachingEntityResolver:
    """TTL cache over another resolver for hot streaming paths (SOLUSDEV-72).

    A 50 Hz physics-simulator run emits one packet per joint per tick — resolving each
    against the DB is hundreds of queries per second for identical answers.
    POSITIVE results are cached for `ttl_seconds`; negative results are never
    cached, so a device that gets linked to an entity mid-stream attaches on
    the very next packet. Bounded: at `max_entries` the cache is cleared rather
    than grown (ponytail: full reset, LRU if churn ever matters — a reset costs
    one TTL's worth of re-queries, not correctness). Keyed on the source too: the
    same device id under a real and a sim session are two entries."""

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
        self._cache: dict[tuple[UUID, str | None, str], tuple[float, UUID]] = {}

    async def resolve(
        self, project_id: UUID, device_id: str, *, source: str | None = None
    ) -> UUID | None:
        key = (project_id, source, device_id)
        hit = self._cache.get(key)
        now = self._clock()
        if hit is not None and now - hit[0] < self._ttl:
            return hit[1]
        # `source=` only when set: pre-322 resolvers (and test fakes) take two positionals.
        if source is None:
            entity_id = await self._inner.resolve(project_id, device_id)
        else:
            entity_id = await self._inner.resolve(project_id, device_id, source=source)
        if entity_id is not None:
            if len(self._cache) >= self._max:
                self._cache.clear()
            self._cache[key] = (now, entity_id)
        else:
            self._cache.pop(key, None)
        return entity_id


class DbEntityResolver:
    """Resolves against `graph_entity` by `external_ref` — and, under a `source`, by a matching
    `attrs.sim_aliases` row — scoped to the given project and to live (non-soft-deleted) rows.
    Returns the matching entity id, or None."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def resolve(
        self, project_id: UUID, device_id: str, *, source: str | None = None
    ) -> UUID | None:
        stmt = select(GraphEntity.id).where(
            GraphEntity.project_id == project_id,
            current_scope(project_id).entity_predicate(),
            GraphEntity.deleted_at.is_(None),
        )
        if source is None:
            stmt = stmt.where(GraphEntity.external_ref == device_id)
        else:
            stmt = _with_alias(stmt, device_id, source)
        async with self._sessionmaker() as session:
            entity_id: UUID | None = await session.scalar(stmt.limit(1))
            return entity_id


def _with_alias(stmt: Select[tuple[UUID]], device_id: str, source: str) -> Select[tuple[UUID]]:
    """`external_ref = :d OR attrs -> 'sim_aliases' @> [{provider: :s, device_id: :d}]`, the
    `external_ref` hit first. `->` (not subscripting) so the partial GIN index on that expression
    (`a32200000002`) serves the containment; `attrs ? 'sim_aliases'` is the index's predicate."""
    by_ref = GraphEntity.external_ref == device_id
    aliases = GraphEntity.attrs.op("->", return_type=JSONB)(ALIASES)
    by_alias = and_(
        GraphEntity.attrs.has_key(ALIASES),
        aliases.contains([{"provider": source, "device_id": device_id}]),
    )
    return stmt.where(or_(by_ref, by_alias)).order_by(case((by_ref, 0), else_=1))
