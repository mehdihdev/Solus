"""Resolve a telemetry device/topic id to a graph entity (SOLUS-LNK-06).

Ingestion attaches a packet to "the corresponding graph entity" by matching the packet's
`device_id` against the entity's `external_ref` — the identity linchpin (`graph_entity`
docstring). Resolution is PROJECT-SCOPED: a device id known in one team's project never
resolves under another's (§7 tenant isolation) — the query filters by `project_id`, which is
derived from the authenticated request, never from the (untrusted) packet.
"""

from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
                GraphEntity.external_ref == device_id,
                GraphEntity.deleted_at.is_(None),
            )
            .limit(1)
        )
        async with self._sessionmaker() as session:
            entity_id: UUID | None = await session.scalar(stmt)
            return entity_id
