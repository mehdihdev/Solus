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
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import (
    Domain,
    Extension,
    ExtensionInstall,
    ExtensionPublisher,
    ExtensionVersion,
    GraphEdge,
    GraphEntity,
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
    """What the install row says about a bundle, rendered into node attrs."""

    slug: str
    name: str
    version: str
    enabled: bool
    publisher: str
    views: tuple[str, ...]

    def attrs(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "version": self.version,
            "enabled": self.enabled,
            "publisher": self.publisher,
            "views": list(self.views),
        }


@dataclass(frozen=True)
class WorkspaceGraph:
    root: GraphEntity
    live_bench: GraphEntity
    widgets: list[GraphEntity]
    edges: list[GraphEdge]


def _live(project_id: uuid.UUID, kind: str) -> Any:
    return (
        GraphEntity.project_id == project_id,
        GraphEntity.kind == kind,
        GraphEntity.deleted_at.is_(None),
    )


async def _singleton(
    session: AsyncSession, project_id: uuid.UUID, kind: str, name: str
) -> GraphEntity:
    node = await session.scalar(
        select(GraphEntity)
        .where(*_live(project_id, kind))
        .order_by(GraphEntity.created_at)
        .limit(1)
    )
    if node is None:
        node = GraphEntity(
            project_id=project_id,
            kind=kind,
            domain=Domain.WORKSPACE,
            name=name,
            origin=SYSTEM_ORIGIN,
            attrs={},
        )
        session.add(node)
        await session.flush()
    return node


async def _ensure_edge(
    session: AsyncSession, project_id: uuid.UUID, src: GraphEntity, dst: GraphEntity
) -> GraphEdge:
    edge = await session.scalar(
        select(GraphEdge).where(
            GraphEdge.project_id == project_id,
            GraphEdge.src_id == src.id,
            GraphEdge.dst_id == dst.id,
            GraphEdge.relation_type == CONTAINS,
            GraphEdge.deleted_at.is_(None),
        )
    )
    if edge is None:
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
    return edge


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
        .order_by(GraphEntity.created_at)
        .limit(1)
    )
    return node


async def register_widget_node(
    session: AsyncSession, project_id: uuid.UUID, facts: WidgetNodeFacts
) -> GraphEntity:
    """Idempotent per (project, slug): creates the node under the root (ensuring
    the root and Live Bench exist) or refreshes name/attrs on the existing one."""
    root = await ensure_workspace_root(session, project_id)
    await ensure_live_bench(session, project_id, root)
    node = await find_widget_node(session, project_id, facts.slug)
    if node is None:
        node = GraphEntity(
            project_id=project_id,
            kind=WIDGET_KIND,
            domain=Domain.WORKSPACE,
            name=facts.name,
            origin=SYSTEM_ORIGIN,
            attrs=facts.attrs(),
        )
        session.add(node)
        await session.flush()
    elif node.name != facts.name or node.attrs != facts.attrs():
        node.name = facts.name
        node.attrs = facts.attrs()
        node.version = node.version + 1
    await _ensure_edge(session, project_id, root, node)
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


async def unregister_widget_node(session: AsyncSession, project_id: uuid.UUID, slug: str) -> int:
    """Soft-delete the bundle's node and EVERY live edge touching it (both
    directions, any origin) so no edge dangles. Returns edges removed."""
    node = await find_widget_node(session, project_id, slug)
    if node is None:
        return 0
    removed = await _soft_delete_edges_touching(session, project_id, node.id)
    node.deleted_at = utcnow()
    await session.flush()
    return removed


def facts_from_install(
    extension: Extension,
    install: ExtensionInstall,
    pinned: ExtensionVersion,
    publisher: ExtensionPublisher | None,
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
    )


async def _installed_facts(session: AsyncSession, project_id: uuid.UUID) -> list[WidgetNodeFacts]:
    rows = (
        await session.execute(
            select(Extension, ExtensionInstall, ExtensionVersion, ExtensionPublisher)
            .join(ExtensionInstall, ExtensionInstall.extension_id == Extension.id)
            .join(ExtensionVersion, ExtensionVersion.id == ExtensionInstall.version_id)
            .outerjoin(ExtensionPublisher, ExtensionPublisher.id == Extension.publisher_id)
            .where(ExtensionInstall.project_id == project_id)
            .order_by(ExtensionInstall.created_at)
        )
    ).all()
    facts = (facts_from_install(ext, install, pinned, pub) for ext, install, pinned, pub in rows)
    return [f for f in facts if f is not None]


async def _live_edges(
    session: AsyncSession, project_id: uuid.UUID, root: GraphEntity
) -> list[GraphEdge]:
    rows = await session.scalars(
        select(GraphEdge)
        .where(
            GraphEdge.project_id == project_id,
            GraphEdge.src_id == root.id,
            GraphEdge.deleted_at.is_(None),
        )
        .order_by(GraphEdge.created_at)
    )
    return list(rows.all())


async def reconcile_workspace_graph(
    session: AsyncSession, project_id: uuid.UUID, team_id: uuid.UUID
) -> WorkspaceGraph:
    """The layer as it SHOULD be given the install rows: ensures the root and Live
    Bench, registers/refreshes one node per install, unregisters nodes whose
    install is gone. Idempotent; the read route calls it on every request."""
    del team_id  # team policy (block) does not change the layer's shape — enabled does
    root = await ensure_workspace_root(session, project_id)
    live_bench = await ensure_live_bench(session, project_id, root)
    wanted = await _installed_facts(session, project_id)
    widgets = [await register_widget_node(session, project_id, facts) for facts in wanted]
    wanted_slugs = {facts.slug for facts in wanted}
    stray = await session.scalars(select(GraphEntity).where(*_live(project_id, WIDGET_KIND)))
    for node in stray.all():
        if node.attrs.get("slug") not in wanted_slugs:
            await unregister_widget_node(session, project_id, str(node.attrs.get("slug")))
    await session.flush()
    return WorkspaceGraph(
        root=root,
        live_bench=live_bench,
        widgets=widgets,
        edges=await _live_edges(session, project_id, root),
    )
