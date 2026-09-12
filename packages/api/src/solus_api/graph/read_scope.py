"""Immutable personal graph scope, frozen once for a request or SOL turn."""

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from solus_api.models import (
    GraphEdge,
    GraphEntity,
    Source,
    SourceRevision,
    SourceStatus,
    SourceViewSelection,
)


@dataclass(frozen=True)
class GraphReadScope:
    project_id: UUID
    replacements: tuple[tuple[UUID, UUID], ...] = ()
    root_replacements: tuple[tuple[UUID, UUID], ...] = ()
    source_branches: tuple[tuple[UUID, str], ...] = ()

    def branch_for_source(self, source_id: UUID) -> str | None:
        return dict(self.source_branches).get(source_id)

    def entity_predicate(self) -> ColumnElement[bool]:
        ordinary = select(Source.id).where(
            Source.project_id == self.project_id, Source.revision_base_source_id.is_(None)
        )
        bases = [base for base, _ in self.replacements]
        snapshots = [snapshot for _, snapshot in self.replacements]
        return and_(
            GraphEntity.project_id == self.project_id,
            or_(
                GraphEntity.source_id.is_(None),
                and_(GraphEntity.source_id.in_(ordinary), GraphEntity.source_id.not_in(bases)),
                GraphEntity.source_id.in_(snapshots),
            ),
        )

    def edge_predicate(self) -> ColumnElement[bool]:
        ids = select(GraphEntity.id).where(
            self.entity_predicate(), GraphEntity.deleted_at.is_(None)
        )
        return and_(
            GraphEdge.project_id == self.project_id,
            or_(
                GraphEdge.src_id.in_(ids),
                GraphEdge.src_id.in_([old for old, _ in self.root_replacements]),
            ),
            or_(
                GraphEdge.dst_id.in_(ids),
                GraphEdge.dst_id.in_([old for old, _ in self.root_replacements]),
            ),
        )

    def aliases(self, ids: list[UUID]) -> list[UUID]:
        wanted = set(ids)
        return ids + [old for old, new in self.root_replacements if new in wanted]

    def project_id_for_entity(self, entity_id: UUID) -> UUID:
        return dict(self.root_replacements).get(entity_id, entity_id)

    def project_edge(self, edge: GraphEdge) -> GraphEdge:
        if not self.root_replacements:
            return edge
        values = {column.key: getattr(edge, column.key) for column in GraphEdge.__table__.columns}
        values["src_id"] = self.project_id_for_entity(edge.src_id)
        values["dst_id"] = self.project_id_for_entity(edge.dst_id)
        return GraphEdge(**values)


_CURRENT: ContextVar[GraphReadScope | None] = ContextVar("graph_read_scope", default=None)


def current_scope(project_id: UUID) -> GraphReadScope:
    scope = _CURRENT.get()
    return (
        scope
        if scope is not None and scope.project_id == project_id
        else GraphReadScope(project_id)
    )


@contextmanager
def bind_scope(scope: GraphReadScope) -> Iterator[None]:
    token = _CURRENT.set(scope)
    try:
        yield
    finally:
        _CURRENT.reset(token)


async def resolve_scopes(
    session: AsyncSession, project_ids: list[UUID], user_id: UUID
) -> dict[UUID, GraphReadScope]:
    rows = await session.execute(
        select(
            SourceRevision.project_id,
            SourceRevision.base_source_id,
            SourceRevision.materialized_source_id,
            func.coalesce(SourceViewSelection.active_branch, SourceRevision.branch),
        )
        .join(SourceViewSelection, SourceViewSelection.active_revision_id == SourceRevision.id)
        .join(Source, Source.id == SourceRevision.base_source_id)
        .where(
            SourceViewSelection.user_id == user_id,
            SourceViewSelection.project_id == SourceRevision.project_id,
            SourceRevision.project_id.in_(project_ids),
            SourceViewSelection.base_source_id == SourceRevision.base_source_id,
            Source.project_id == SourceRevision.project_id,
            Source.status != SourceStatus.DISCONNECTED,
            Source.revision_base_source_id.is_(None),
        )
    )
    replacements: dict[UUID, list[tuple[UUID, UUID]]] = {pid: [] for pid in project_ids}
    branches: dict[UUID, list[tuple[UUID, str]]] = {pid: [] for pid in project_ids}
    for pid, base, snapshot, branch in rows:
        replacements[pid].append((base, snapshot))
        branches[pid].append((snapshot, branch))
    source_ids = {sid for values in replacements.values() for pair in values for sid in pair}
    roots: dict[UUID, UUID] = {}
    if source_ids:
        root_rows = await session.execute(
            select(GraphEntity.source_id, GraphEntity.id).where(
                GraphEntity.source_id.in_(source_ids),
                GraphEntity.project_id.in_(project_ids),
                GraphEntity.external_ref == ":repo",
                GraphEntity.deleted_at.is_(None),
            )
        )
        roots = {
            source_id: entity_id for source_id, entity_id in root_rows if source_id is not None
        }
    return {
        pid: GraphReadScope(
            pid,
            tuple(values),
            tuple(
                (roots[base], roots[snapshot])
                for base, snapshot in values
                if base in roots and snapshot in roots
            ),
            tuple(branches[pid]),
        )
        for pid, values in replacements.items()
    }


async def resolve_scope(session: AsyncSession, project_id: UUID, user_id: UUID) -> GraphReadScope:
    return (await resolve_scopes(session, [project_id], user_id))[project_id]


async def scoped_stream[T](scope: GraphReadScope, stream: AsyncIterator[T]) -> AsyncIterator[T]:
    with bind_scope(scope):
        async for item in stream:
            yield item
