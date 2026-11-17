"""Immutable personal graph scope, frozen once for a request or SOL turn.

SOLUSDEV-326: a scope may carry its viewer. Hardware not in the graph (`attrs.in_graph` false;
absent is in it) is visible only to its onboarder (`attrs.onboarded_by`), so a viewer's
`entity_predicate` admits it for that one person; the system view (no viewer) filters nothing.
"""

from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Final
from uuid import UUID

from sqlalchemy import and_, func, not_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from solus_api.graph.edges import projected_copy
from solus_api.models import (
    GraphEdge,
    GraphEntity,
    SolusEntry,
    SolusEntryKind,
    Source,
    SourceRevision,
    SourceStatus,
    SourceViewSelection,
)

IN_GRAPH: Final = "in_graph"
ONBOARDED_BY: Final = "onboarded_by"
#: A machine's attrs only its owner reads (M38, SOLUSDEV-326): its command history, the devices
#: it has seen and what each member dismissed. Every model-facing read drops them for everyone.
OWNER_ONLY_MACHINE_ATTRS: Final = frozenset({"recent_commands", "devices", "dismissed"})


def visible_to(viewer_id: UUID | None) -> ColumnElement[bool]:
    """What `viewer_id` may see of hardware: everything in the graph and what they onboarded and
    have not added yet. None is nobody's own view — what is in the graph only."""
    in_graph = not_(GraphEntity.attrs.contains({IN_GRAPH: False}))
    if viewer_id is None:
        return in_graph
    return or_(in_graph, GraphEntity.attrs[ONBOARDED_BY].astext == str(viewer_id))


def visibility_attrs(*, in_graph: bool, onboarded_by: UUID | None) -> dict[str, Any]:
    """The attrs a hardware writer stamps; in the graph with no onboarder is none at all."""
    if not in_graph and onboarded_by is None:
        raise ValueError("hardware kept out of the graph needs its onboarder")
    stamp: dict[str, Any] = {} if in_graph else {IN_GRAPH: False}
    return stamp | ({ONBOARDED_BY: str(onboarded_by)} if onboarded_by is not None else {})


def flags_of(attrs: Mapping[str, Any]) -> dict[str, Any]:
    """The visibility attrs a robot's own hardware copies from it."""
    return {key: attrs[key] for key in (IN_GRAPH, ONBOARDED_BY) if key in attrs}


def owns_machine(attrs: Mapping[str, Any], user_id: UUID | None) -> bool:
    """Whether `user_id` is the member who registered the machine these `attrs` belong to
    (`attrs.owner_user_id`): the one definition of the owner rule (CLAUDE.md §7) that the
    serializer, `owned_commands`, the card's own-machine guard and the `get_machine` tool share.
    An asker with no id owns nothing — `str(None)` must never equal a stored owner."""
    return user_id is not None and attrs.get("owner_user_id") == str(user_id)


@dataclass(frozen=True)
class GraphReadScope:
    project_id: UUID
    replacements: tuple[tuple[UUID, UUID], ...] = ()
    root_replacements: tuple[tuple[UUID, UUID], ...] = ()
    source_branches: tuple[tuple[UUID, str], ...] = ()
    #: The person reading; None is the system view (ingest, background work), which sees all.
    viewer_id: UUID | None = None

    def branch_for_source(self, source_id: UUID) -> str | None:
        return dict(self.source_branches).get(source_id)

    def entity_predicate(self, *, include_hidden: bool = False) -> ColumnElement[bool]:
        """The project's entities in this view. `include_hidden` opts out of the viewer clause,
        for reads that must never be one person's (telemetry resolution)."""
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
            visible_to(self.viewer_id)
            if self.viewer_id is not None and not include_hidden
            else true(),
        )

    def hides(self, attrs: Mapping[str, Any]) -> bool:
        """The viewer clause for a row already read: True when this viewer may not see it."""
        return (
            self.viewer_id is not None
            and attrs.get(IN_GRAPH) is False
            and attrs.get(ONBOARDED_BY) != str(self.viewer_id)
        )

    async def hidden_ids(self, session: AsyncSession) -> frozenset[UUID]:
        """The viewer clause for reads that hold entity ids, not rows (buffered telemetry, bench
        sessions): what this viewer may not see. The system view hides nothing."""
        if self.viewer_id is None:
            return frozenset()
        hidden = await session.scalars(
            select(GraphEntity.id).where(
                GraphEntity.project_id == self.project_id, not_(visible_to(self.viewer_id))
            )
        )
        return frozenset(hidden)

    def entry_predicate(self, *, everyone: bool = False) -> ColumnElement[bool]:
        """`.solus` entries in this view: a CONFIG entry whose configured entity the viewer may
        not see is left out, and so is a filed document the viewer may not see (a hidden robot's
        bench run). `everyone` is what every member may see (a cache shared by all of them); the
        system view sees every entry."""
        if self.viewer_id is None and not everyone:
            return true()
        hidden = select(GraphEntity.id).where(
            GraphEntity.project_id == self.project_id,
            not_(visible_to(None if everyone else self.viewer_id)),
        )
        return and_(
            or_(
                SolusEntry.kind != SolusEntryKind.CONFIG,
                SolusEntry.configured_entity_id.is_(None),
                SolusEntry.configured_entity_id.not_in(hidden),
            ),
            or_(
                SolusEntry.kind != SolusEntryKind.ARTIFACT,
                SolusEntry.entity_id.is_(None),
                SolusEntry.entity_id.not_in(hidden),
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
        return projected_copy(
            edge,
            src_id=self.project_id_for_entity(edge.src_id),
            dst_id=self.project_id_for_entity(edge.dst_id),
        )


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


@contextmanager
def system_view() -> Iterator[None]:
    """Work that outlives the request — a bench session's pump, tap and evaluator — reads as the
    system: a task copies the request's ContextVars, and no one person's view may filter what
    is ingested or judged. The bound source view (replacements, branches) is kept."""
    scope = _CURRENT.get()
    if scope is None:
        yield
        return
    with bind_scope(replace(scope, viewer_id=None)):
        yield


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
            viewer_id=user_id,
        )
        for pid, values in replacements.items()
    }


async def resolve_scope(session: AsyncSession, project_id: UUID, user_id: UUID) -> GraphReadScope:
    return (await resolve_scopes(session, [project_id], user_id))[project_id]


async def scoped_stream[T](scope: GraphReadScope, stream: AsyncIterator[T]) -> AsyncIterator[T]:
    with bind_scope(scope):
        async for item in stream:
            yield item
