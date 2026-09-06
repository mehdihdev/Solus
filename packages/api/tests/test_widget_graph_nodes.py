"""SOLUSDEV-246 (STORE ST2) — widgets in the graph, the service half.

The workspace layer: a per-project `solus:workspace` root, a `solus:live_bench`
singleton and one `solus:widget` node per installed extension (peers under the
root, `contains` edges from it), all `domain=workspace`, `origin=system`.
Registration is idempotent, uninstall leaves no node and no dangling edge, and
`reconcile_workspace_graph` heals installs that predate ST2. The SOL graph feed
never sees the layer. Route behaviour lives in `test_widget_graph_routes.py`.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from conftest import API_DIR
from fixtures.extensions.routes import seed_extension
from solus_api.agent.feeds import DbSolSystems
from solus_api.agent.interfaces import GraphScope
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.resolver import DbEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.models import (
    Domain,
    ExtensionInstall,
    GraphEdge,
    GraphEntity,
    Project,
    Team,
    TeamKind,
    User,
)
from solus_api.widgets.graph_nodes import (
    LIVE_BENCH_KIND,
    NON_WORKSPACE_DOMAINS,
    SYSTEM_ORIGIN,
    WIDGET_KIND,
    WORKSPACE_KIND,
    WidgetNodeFacts,
    ensure_live_bench,
    ensure_workspace_root,
    find_widget_node,
    reconcile_workspace_graph,
    register_widget_node,
    unregister_widget_node,
    update_widget_node,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

FIXTURES = API_DIR.parent / "shared-types" / "fixtures" / "extension-manifest"
V2: dict[str, Any] = json.loads(Path(FIXTURES / "manifest-v2-first-party.json").read_text())


async def _seed_project(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    user = User(supabase_user_id=uuid.uuid4().hex, email=f"{uuid.uuid4().hex}@x.io")
    team = Team(name="T", kind=TeamKind.COLLABORATIVE)
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name="Rover", created_by=user.id)
    db.add(project)
    await db.commit()
    return project.id, user.id, team.id


def _facts(slug: str = "bom", **over: Any) -> WidgetNodeFacts:
    base: dict[str, Any] = {
        "slug": slug,
        "name": slug.upper(),
        "version": "1.2.0",
        "enabled": True,
        "publisher": "Solus",
        "views": ("widget", "page"),
    }
    base.update(over)
    return WidgetNodeFacts(**base)


async def _live_edges(db: AsyncSession, project_id: uuid.UUID) -> list[GraphEdge]:
    rows = await db.scalars(
        select(GraphEdge).where(GraphEdge.project_id == project_id, GraphEdge.deleted_at.is_(None))
    )
    return list(rows.all())


async def _dangling(db: AsyncSession, project_id: uuid.UUID) -> int:
    """Live edges whose endpoint is missing or soft-deleted — must always be zero."""
    live_ids = set(
        await db.scalars(
            select(GraphEntity.id).where(
                GraphEntity.project_id == project_id, GraphEntity.deleted_at.is_(None)
            )
        )
    )
    return sum(
        1
        for edge in await _live_edges(db, project_id)
        if edge.src_id not in live_ids or edge.dst_id not in live_ids
    )


# ------------------------------------------------------------- root + bench


async def test_root_and_live_bench_are_singletons_with_one_edge(db: AsyncSession) -> None:
    project_id, _, _ = await _seed_project(db)
    root = await ensure_workspace_root(db, project_id)
    bench = await ensure_live_bench(db, project_id, root)
    await db.commit()
    again_root = await ensure_workspace_root(db, project_id)
    again_bench = await ensure_live_bench(db, project_id, again_root)
    await db.commit()
    assert again_root.id == root.id and again_bench.id == bench.id
    for node in (root, bench):
        assert node.domain is Domain.WORKSPACE
        assert node.origin == SYSTEM_ORIGIN
        assert node.source_id is None and node.external_ref is None
    assert root.kind == WORKSPACE_KIND and bench.kind == LIVE_BENCH_KIND
    edges = await _live_edges(db, project_id)
    assert [(e.src_id, e.dst_id, e.relation_type, e.domain_pair, e.origin) for e in edges] == [
        (root.id, bench.id, "contains", "workspace<->workspace", SYSTEM_ORIGIN)
    ]


async def test_root_is_per_project(db: AsyncSession) -> None:
    project_a, _, _ = await _seed_project(db)
    project_b, _, _ = await _seed_project(db)
    root_a = await ensure_workspace_root(db, project_a)
    root_b = await ensure_workspace_root(db, project_b)
    await db.commit()
    assert root_a.id != root_b.id
    assert root_a.project_id == project_a and root_b.project_id == project_b


# ----------------------------------------------------------------- widgets


async def test_register_is_idempotent_and_hangs_the_widget_under_the_root(
    db: AsyncSession,
) -> None:
    project_id, _, _ = await _seed_project(db)
    first = await register_widget_node(db, project_id, _facts())
    await db.commit()
    second = await register_widget_node(db, project_id, _facts(name="BOM v2", version="1.3.0"))
    await db.commit()
    assert first.id == second.id
    assert second.kind == WIDGET_KIND and second.domain is Domain.WORKSPACE
    assert second.origin == SYSTEM_ORIGIN and second.source_id is None
    assert second.name == "BOM v2"
    assert second.attrs == {
        "slug": "bom",
        "version": "1.3.0",
        "enabled": True,
        "publisher": "Solus",
        "views": ["widget", "page"],
    }
    root = await ensure_workspace_root(db, project_id)
    edges = await _live_edges(db, project_id)
    widget_edges = [e for e in edges if e.dst_id == first.id]
    assert len(widget_edges) == 1
    assert widget_edges[0].src_id == root.id and widget_edges[0].relation_type == "contains"
    # The Live Bench peer exists too: registering a widget implies the layer.
    assert await db.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id, GraphEntity.kind == LIVE_BENCH_KIND
        )
    )
    assert await find_widget_node(db, project_id, "bom") is not None
    assert await find_widget_node(db, project_id, "other") is None


async def test_update_changes_attrs_immutably_and_bumps_version(db: AsyncSession) -> None:
    project_id, _, _ = await _seed_project(db)
    node = await register_widget_node(db, project_id, _facts())
    await db.commit()
    before = dict(node.attrs)
    updated = await update_widget_node(db, project_id, "bom", enabled=False, version="2.0.0")
    await db.commit()
    assert updated is not None and updated.id == node.id
    assert updated.attrs["enabled"] is False and updated.attrs["version"] == "2.0.0"
    assert updated.attrs["publisher"] == "Solus"
    assert updated.version == 2  # optimistic-concurrency counter moved
    assert before["enabled"] is True  # the old dict was not mutated
    assert await update_widget_node(db, project_id, "ghost", enabled=False) is None


async def test_unregister_removes_the_node_and_every_edge_leaving_none_dangling(
    db: AsyncSession,
) -> None:
    project_id, _, _ = await _seed_project(db)
    node = await register_widget_node(db, project_id, _facts())
    # A foreign edge INTO the widget node (as W5 or a future link might add).
    other = await register_widget_node(db, project_id, _facts("planner"))
    db.add(
        GraphEdge(
            project_id=project_id,
            src_id=other.id,
            dst_id=node.id,
            relation_type="related_to",
            domain_pair="workspace<->workspace",
            origin=SYSTEM_ORIGIN,
        )
    )
    await db.commit()
    assert await _dangling(db, project_id) == 0

    removed = await unregister_widget_node(db, project_id, "bom")
    await db.commit()
    assert removed == 2  # root→bom and planner→bom
    await db.refresh(node)
    assert node.deleted_at is not None
    assert await find_widget_node(db, project_id, "bom") is None
    assert await _dangling(db, project_id) == 0
    live = await _live_edges(db, project_id)
    assert all(node.id not in (e.src_id, e.dst_id) for e in live)
    # Peers and the root survive.
    assert await find_widget_node(db, project_id, "planner") is not None
    assert await unregister_widget_node(db, project_id, "bom") == 0  # idempotent


async def test_unregister_is_project_scoped(db: AsyncSession) -> None:
    project_a, _, _ = await _seed_project(db)
    project_b, _, _ = await _seed_project(db)
    await register_widget_node(db, project_a, _facts())
    await register_widget_node(db, project_b, _facts())
    await db.commit()
    await unregister_widget_node(db, project_a, "bom")
    await db.commit()
    assert await find_widget_node(db, project_a, "bom") is None
    assert await find_widget_node(db, project_b, "bom") is not None


# --------------------------------------------------------------- reconcile


async def test_reconcile_backfills_installs_and_prunes_orphans(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, user_id, team_id = await _seed_project(db)
    catalog = await seed_extension(db, "bom")
    db.add(
        ExtensionInstall(
            project_id=project_id,
            extension_id=catalog.extension_id,
            version_id=catalog.versions["1.2.0"],
            enabled=False,
            installed_by=user_id,
        )
    )
    # An orphan node for a bundle that is NOT installed here.
    await register_widget_node(db, project_id, _facts("ghost"))
    await db.commit()

    graph = await reconcile_workspace_graph(db, project_id, team_id)
    await db.commit()
    assert graph.root.kind == WORKSPACE_KIND
    assert graph.live_bench.kind == LIVE_BENCH_KIND
    assert [w.attrs["slug"] for w in graph.widgets] == ["bom"]
    bom = graph.widgets[0]
    assert bom.name == "BOM" and bom.attrs["version"] == "1.2.0"
    assert bom.attrs["enabled"] is False
    assert bom.attrs["views"] == ["widget", "page", "window"]
    assert await find_widget_node(db, project_id, "ghost") is None
    assert {(e.src_id, e.dst_id) for e in graph.edges} == {
        (graph.root.id, graph.live_bench.id),
        (graph.root.id, bom.id),
    }
    assert await _dangling(db, project_id) == 0

    again = await reconcile_workspace_graph(db, project_id, team_id)
    await db.commit()
    assert [w.id for w in again.widgets] == [bom.id]  # idempotent, no duplicates


# ---------------------------------------------------------- SOL never sees it


async def test_the_sol_graph_feed_excludes_the_workspace_layer(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, _, _ = await _seed_project(db)
    motor = GraphEntity(
        project_id=project_id, kind="component", domain=Domain.ELECTRICAL, name="M1"
    )
    db.add(motor)
    await db.flush()
    widget = await register_widget_node(db, project_id, _facts())
    # Even a direct edge from a robot entity into the layer must not pull it in.
    db.add(
        GraphEdge(
            project_id=project_id,
            src_id=motor.id,
            dst_id=widget.id,
            relation_type="shown_in",
            domain_pair="electrical<->workspace",
            origin="manual",
        )
    )
    await db.commit()

    assert Domain.WORKSPACE not in NON_WORKSPACE_DOMAINS
    assert set(NON_WORKSPACE_DOMAINS) | {Domain.WORKSPACE} == set(Domain)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    systems = DbSolSystems(
        maker, TelemetryPlumbing(InMemoryTelemetryBuffer(), DbEntityResolver(maker))
    )
    ctx = await systems.get_graph_context(
        project_id, GraphScope(anchor_entity_ids=[motor.id], degree=2)
    )
    kinds = {e.kind for e in ctx.entities}
    assert "component" in kinds
    assert not any(k.startswith("solus:") for k in kinds)
    # An explicit ask for the layer still works — the default is the exclusion.
    explicit = await systems.get_graph_context(
        project_id,
        GraphScope(anchor_entity_ids=[widget.id], degree=1, domains=[Domain.WORKSPACE.value]),
    )
    assert {e.kind for e in explicit.entities} >= {WIDGET_KIND}
