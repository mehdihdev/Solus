"""Widgets in the graph (SOLUSDEV-246 / STORE ST2, ADR-027 as amended 2026-09-06).

The workspace layer of a project's graph: one `solus:workspace` root, one
`solus:live_bench` node and one `solus:widget` node per installed extension,
all `domain=workspace`, `origin=system`, joined by `contains` edges from the
root. Solus writes these rows itself inside the install lifecycle — a bundle
never registers its own node (ADR-035) — and removes them on uninstall together
with every edge that touches them, so nothing dangles. `reconcile_workspace_graph`
is the self-healing read: it backfills installs that predate this layer and prunes
nodes whose install is gone. SOL never sees the layer (`NON_WORKSPACE_DOMAINS`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from solus_contracts.extension_manifest import parse_extension_manifest
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import (
    Domain,
    Extension,
    ExtensionInstall,
    ExtensionPublisher,
    ExtensionVersion,
    GraphEdge,
    GraphEntity,
    TeamExtensionPolicy,
    utcnow,
)

WORKSPACE_KIND = "solus:workspace"
LIVE_BENCH_KIND = "solus:live_bench"
WIDGET_KIND = "solus:widget"
SYSTEM_ORIGIN = "system"
CONTAINS = "contains"
WORKSPACE_PAIR = "workspace<->workspace"
#: What SOL's graph feed reads by default: everything the robot is made of, and
#: never the layer describing the workspace (widget-bundles.md §10).
NON_WORKSPACE_DOMAINS: tuple[Domain, ...] = tuple(d for d in Domain if d is not Domain.WORKSPACE)


@dataclass(frozen=True)
class WidgetNodeFacts:
    """What the install row says about a bundle, rendered into node attrs.
    `enabled` is the EFFECTIVE state: the install's flag AND not team-blocked."""

    slug: str
    name: str
    version: str
    enabled: bool
    publisher: str
    views: tuple[str, ...]
    blocked: bool = False

    def attrs(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "version": self.version,
            "enabled": self.enabled and not self.blocked,
            "blocked": self.blocked,
            "publisher": self.publisher,
            "views": list(self.views),
        }


@dataclass(frozen=True)
class WorkspaceGraph:
    """The layer as read. `root`/`live_bench` are None until the layer exists
    (first install or an explicit reconcile) — empty beats invented."""

    root: GraphEntity | None
    live_bench: GraphEntity | None
    widgets: list[GraphEntity]
    edges: list[GraphEdge]


@dataclass(frozen=True)
class ReconcileOutcome:
    graph: WorkspaceGraph
    created: int
    refreshed: int
    pruned: int

    @property
    def changed(self) -> bool:
        return bool(self.created or self.refreshed or self.pruned)


def _live(project_id: uuid.UUID, kind: str) -> Any:
    """Only rows THIS module wrote: kind AND domain AND origin. A connector or
    fingerprint row that happens to carry a `solus:` kind is never ours to
    read, adopt or retire."""
    return (
        GraphEntity.project_id == project_id,
        GraphEntity.kind == kind,
        GraphEntity.domain == Domain.WORKSPACE,
        GraphEntity.origin == SYSTEM_ORIGIN,
        GraphEntity.deleted_at.is_(None),
    )


async def _find_singleton(
    session: AsyncSession, project_id: uuid.UUID, kind: str
) -> GraphEntity | None:
    node: GraphEntity | None = await session.scalar(
        select(GraphEntity)
        .where(*_live(project_id, kind))
        .order_by(GraphEntity.created_at, GraphEntity.id)
        .limit(1)
    )
    return node


async def _insert_or_reselect(
    session: AsyncSession, row: GraphEntity, reselect: Any
) -> GraphEntity:
    """INSERT under a savepoint; on the partial unique index firing (a
    concurrent writer won the race) roll the savepoint back and adopt theirs."""
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        winner: GraphEntity | None = await reselect()
        if winner is None:  # pragma: no cover — the index just proved it exists
            raise
        return winner
    return row


async def _singleton(
    session: AsyncSession, project_id: uuid.UUID, kind: str, name: str
) -> GraphEntity:
    node = await _find_singleton(session, project_id, kind)
    if node is not None:
        return node
    fresh = GraphEntity(
        project_id=project_id,
        kind=kind,
        domain=Domain.WORKSPACE,
        name=name,
        origin=SYSTEM_ORIGIN,
        attrs={},
    )
    return await _insert_or_reselect(
        session, fresh, lambda: _find_singleton(session, project_id, kind)
    )


def _contains_edges(project_id: uuid.UUID) -> Any:
    return (
        GraphEdge.project_id == project_id,
        GraphEdge.relation_type == CONTAINS,
        GraphEdge.origin == SYSTEM_ORIGIN,
        GraphEdge.deleted_at.is_(None),
    )


async def _ensure_edge(
    session: AsyncSession, project_id: uuid.UUID, src: GraphEntity, dst: GraphEntity
) -> tuple[GraphEdge, bool]:
    """The `contains` edge, and whether this call created it."""
    edge = await session.scalar(
        select(GraphEdge).where(
            *_contains_edges(project_id), GraphEdge.src_id == src.id, GraphEdge.dst_id == dst.id
        )
    )
    if edge is not None:
        return edge, False
    edge = GraphEdge(
        project_id=project_id,
        src_id=src.id,
        dst_id=dst.id,
        relation_type=CONTAINS,
        domain_pair=WORKSPACE_PAIR,
        origin=SYSTEM_ORIGIN,
        attrs={},
    )
    session.add(edge)
    await session.flush()
    return edge, True


async def ensure_workspace_root(session: AsyncSession, project_id: uuid.UUID) -> GraphEntity:
    return await _singleton(session, project_id, WORKSPACE_KIND, "Workspace")


async def ensure_live_bench(
    session: AsyncSession, project_id: uuid.UUID, root: GraphEntity
) -> GraphEntity:
    bench = await _singleton(session, project_id, LIVE_BENCH_KIND, "Live Bench")
    await _ensure_edge(session, project_id, root, bench)
    return bench


async def find_widget_node(
    session: AsyncSession, project_id: uuid.UUID, slug: str
) -> GraphEntity | None:
    node: GraphEntity | None = await session.scalar(
        select(GraphEntity)
        .where(*_live(project_id, WIDGET_KIND), GraphEntity.attrs["slug"].astext == slug)
        .order_by(GraphEntity.created_at, GraphEntity.id)
        .limit(1)
    )
    return node


async def _register(
    session: AsyncSession, project_id: uuid.UUID, facts: WidgetNodeFacts
) -> tuple[GraphEntity, bool, bool]:
    """(node, created, refreshed)."""
    root = await ensure_workspace_root(session, project_id)
    await ensure_live_bench(session, project_id, root)
    node = await find_widget_node(session, project_id, facts.slug)
    created = refreshed = False
    if node is None:
        fresh = GraphEntity(
            project_id=project_id,
            kind=WIDGET_KIND,
            domain=Domain.WORKSPACE,
            name=facts.name,
            origin=SYSTEM_ORIGIN,
            attrs=facts.attrs(),
        )
        node = await _insert_or_reselect(
            session, fresh, lambda: find_widget_node(session, project_id, facts.slug)
        )
        created = node is fresh
    if node.name != facts.name or node.attrs != facts.attrs():
        node.name = facts.name
        node.attrs = facts.attrs()
        node.version = node.version + 1
        refreshed = not created
    _, edge_created = await _ensure_edge(session, project_id, root, node)
    return node, created or edge_created, refreshed


async def register_widget_node(
    session: AsyncSession, project_id: uuid.UUID, facts: WidgetNodeFacts
) -> GraphEntity:
    """Idempotent per (project, slug): creates the node under the root (ensuring
    the root and Live Bench exist) or refreshes name/attrs on the existing one."""
    node, _, _ = await _register(session, project_id, facts)
    return node


async def update_widget_node(
    session: AsyncSession, project_id: uuid.UUID, slug: str, **changes: Any
) -> GraphEntity | None:
    """Merge attr changes (a NEW dict — the old one is never mutated); None when
    the bundle has no node here."""
    node = await find_widget_node(session, project_id, slug)
    if node is None:
        return None
    merged = {**node.attrs, **changes}
    if merged != node.attrs:
        node.attrs = merged
        node.version = node.version + 1
    return node


async def _soft_delete_edges_touching(
    session: AsyncSession, project_id: uuid.UUID, entity_id: uuid.UUID
) -> int:
    result = await session.execute(
        update(GraphEdge)
        .where(
            GraphEdge.project_id == project_id,
            or_(GraphEdge.src_id == entity_id, GraphEdge.dst_id == entity_id),
            GraphEdge.deleted_at.is_(None),
        )
        .values(deleted_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def _retire(session: AsyncSession, node: GraphEntity) -> int:
    """Soft-delete THIS row and every live edge touching it, both directions,
    any origin — by row, never by a re-lookup that could miss or mis-hit."""
    removed = await _soft_delete_edges_touching(session, node.project_id, node.id)
    node.deleted_at = utcnow()
    await session.flush()
    return removed


async def unregister_widget_node(session: AsyncSession, project_id: uuid.UUID, slug: str) -> int:
    """Soft-delete the bundle's node and EVERY live edge touching it so no edge
    dangles. Returns edges removed; 0 when there is no node."""
    node = await find_widget_node(session, project_id, slug)
    return 0 if node is None else await _retire(session, node)


def facts_from_install(
    extension: Extension,
    install: ExtensionInstall,
    pinned: ExtensionVersion,
    publisher: ExtensionPublisher | None,
    *,
    blocked: bool = False,
) -> WidgetNodeFacts | None:
    """The node facts for one install row; None when the pinned manifest no
    longer parses (a stale row must never break registration)."""
    try:
        manifest = parse_extension_manifest(pinned.manifest)
    except ValueError:
        return None
    views = tuple(
        kind for kind in ("widget", "page", "window") if getattr(manifest.views, kind) is not None
    )
    return WidgetNodeFacts(
        slug=extension.slug,
        name=manifest.extension.name,
        version=pinned.version,
        enabled=install.enabled,
        publisher=publisher.display_name if publisher is not None else manifest.extension.publisher,
        views=views,
        blocked=blocked,
    )


@dataclass(frozen=True)
class _Installed:
    """Every install's slug is WANTED even when its facts cannot be built (a
    stale manifest must never prune a live install's node)."""

    facts: list[WidgetNodeFacts]
    slugs: set[str]


async def _installed(
    session: AsyncSession, project_id: uuid.UUID, team_id: uuid.UUID
) -> _Installed:
    rows = (
        await session.execute(
            select(
                Extension,
                ExtensionInstall,
                ExtensionVersion,
                ExtensionPublisher,
                TeamExtensionPolicy,
            )
            .join(ExtensionInstall, ExtensionInstall.extension_id == Extension.id)
            .join(ExtensionVersion, ExtensionVersion.id == ExtensionInstall.version_id)
            .outerjoin(ExtensionPublisher, ExtensionPublisher.id == Extension.publisher_id)
            .outerjoin(
                TeamExtensionPolicy,
                (TeamExtensionPolicy.extension_id == Extension.id)
                & (TeamExtensionPolicy.team_id == team_id),
            )
            .where(ExtensionInstall.project_id == project_id)
            .order_by(ExtensionInstall.created_at)
        )
    ).all()
    facts = [
        facts_from_install(ext, inst, pinned, pub, blocked=bool(policy and policy.blocked))
        for ext, inst, pinned, pub, policy in rows
    ]
    return _Installed(
        facts=[f for f in facts if f is not None], slugs={ext.slug for ext, *_ in rows}
    )


async def _child_edges(
    session: AsyncSession, project_id: uuid.UUID, root: GraphEntity
) -> list[GraphEdge]:
    rows = await session.scalars(
        select(GraphEdge)
        .where(*_contains_edges(project_id), GraphEdge.src_id == root.id)
        .order_by(GraphEdge.created_at, GraphEdge.id)
    )
    return list(rows.all())


async def _widgets_under(session: AsyncSession, project_id: uuid.UUID) -> list[GraphEntity]:
    rows = await session.scalars(
        select(GraphEntity)
        .where(*_live(project_id, WIDGET_KIND))
        .order_by(GraphEntity.created_at, GraphEntity.id)
    )
    return list(rows.all())


async def load_workspace_graph(session: AsyncSession, project_id: uuid.UUID) -> WorkspaceGraph:
    """Pure READ of the layer. No row is created, refreshed or retired here —
    a viewer may call this. Absent layer → `root`/`live_bench` None, nothing
    invented."""
    root = await _find_singleton(session, project_id, WORKSPACE_KIND)
    if root is None:
        return WorkspaceGraph(None, None, [], [])
    return WorkspaceGraph(
        root=root,
        live_bench=await _find_singleton(session, project_id, LIVE_BENCH_KIND),
        widgets=await _widgets_under(session, project_id),
        edges=await _child_edges(session, project_id, root),
    )


async def _prune_strays(session: AsyncSession, project_id: uuid.UUID, wanted: set[str]) -> int:
    """Retire every system-origin widget node whose slug is not installed —
    including nodes with a missing or non-string slug, which nothing can own."""
    pruned = 0
    for node in await _widgets_under(session, project_id):
        slug = node.attrs.get("slug")
        if not isinstance(slug, str) or slug not in wanted:
            await _retire(session, node)
            pruned += 1
    return pruned


async def reconcile_workspace_graph(
    session: AsyncSession, project_id: uuid.UUID, team_id: uuid.UUID
) -> ReconcileOutcome:
    """The layer as it SHOULD be given the install rows: ensures the root and Live
    Bench, registers/refreshes one node per install (blocked state included),
    retires nodes whose install is gone. Idempotent. A WRITE: callers gate it
    behind the member floor and the install-write budget."""
    created = refreshed = 0
    root = await ensure_workspace_root(session, project_id)
    live_bench = await ensure_live_bench(session, project_id, root)
    installed = await _installed(session, project_id, team_id)
    for facts in installed.facts:
        _, was_created, was_refreshed = await _register(session, project_id, facts)
        created += int(was_created)
        refreshed += int(was_refreshed)
    pruned = await _prune_strays(session, project_id, installed.slugs)
    await session.flush()
    graph = WorkspaceGraph(
        root=root,
        live_bench=live_bench,
        widgets=await _widgets_under(session, project_id),
        edges=await _child_edges(session, project_id, root),
    )
    return ReconcileOutcome(graph=graph, created=created, refreshed=refreshed, pruned=pruned)
