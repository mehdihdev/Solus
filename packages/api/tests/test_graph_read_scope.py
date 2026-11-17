"""Default and personal graph scope cannot expose hidden branch snapshots — nor (SOLUSDEV-326)
hardware its onboarder has not added to the graph to anyone else."""

import uuid
from collections.abc import AsyncIterator

import pytest
from solus_api.graph.read_scope import (
    GraphReadScope,
    bind_scope,
    current_scope,
    resolve_scope,
    system_view,
)
from solus_api.models import Domain, GraphEntity, Project, Team
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def test_scope_is_request_bound_and_restored() -> None:
    project, base, snapshot = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scope = GraphReadScope(project, ((base, snapshot),))
    assert current_scope(project).replacements == ()
    with bind_scope(scope):
        assert current_scope(project) == scope
        assert current_scope(uuid.uuid4()).replacements == ()
    assert current_scope(project).replacements == ()


def test_default_scope_excludes_internal_sources_in_sql() -> None:
    predicate = str(GraphReadScope(uuid.uuid4()).entity_predicate())
    assert "revision_base_source_id IS NULL" in predicate
    assert "source_id IS NULL" in predicate


async def test_stream_keeps_admitted_scope_after_request_scope_ends() -> None:
    from solus_api.graph.read_scope import scoped_stream

    project, base, snapshot = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scope = GraphReadScope(project, ((base, snapshot),))

    async def stream() -> AsyncIterator[tuple[tuple[uuid.UUID, uuid.UUID], ...]]:
        yield current_scope(project).replacements

    with bind_scope(scope):
        frozen = scoped_stream(current_scope(project), stream())
    assert [item async for item in frozen] == [scope.replacements]
    assert current_scope(project).replacements == ()


def test_clone_edge_projection_is_read_only() -> None:
    from solus_api.models import GraphEdge

    project, base_source, snapshot_source = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    base_root, snapshot_root, local = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scope = GraphReadScope(
        project, ((base_source, snapshot_source),), ((base_root, snapshot_root),)
    )
    edge = GraphEdge(project_id=project, src_id=local, dst_id=base_root, relation_type="clone_of")
    projected = scope.project_edge(edge)
    assert projected.src_id == local and projected.dst_id == snapshot_root
    assert edge.dst_id == base_root
    assert scope.aliases([snapshot_root]) == [snapshot_root, base_root]


def test_shared_snapshot_keeps_each_users_selected_branch() -> None:
    project, base, snapshot = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    first = GraphReadScope(project, ((base, snapshot),), source_branches=((snapshot, "main"),))
    second = GraphReadScope(project, ((base, snapshot),), source_branches=((snapshot, "release"),))
    assert first.branch_for_source(snapshot) == "main"
    assert second.branch_for_source(snapshot) == "release"
    assert second.branch_for_source(base) is None


# --- SOLUSDEV-326: hardware not in the graph is visible only to its onboarder ---------------

ONBOARDER, TEAMMATE = uuid.uuid4(), uuid.uuid4()


def test_a_viewer_adds_the_onboarder_clause_and_the_system_view_none() -> None:
    project = uuid.uuid4()
    system = str(GraphReadScope(project).entity_predicate())
    viewer = GraphReadScope(project, viewer_id=ONBOARDER)
    assert str(viewer.entity_predicate()) != system
    assert "@>" in str(viewer.entity_predicate()) and "->>" in str(viewer.entity_predicate())
    assert str(viewer.entity_predicate(include_hidden=True)) == system


def test_hides_is_the_viewer_clause_for_a_row_already_read() -> None:
    project = uuid.uuid4()
    hidden = {"in_graph": False, "onboarded_by": str(ONBOARDER)}
    assert GraphReadScope(project, viewer_id=TEAMMATE).hides(hidden)
    assert not GraphReadScope(project, viewer_id=ONBOARDER).hides(hidden)
    assert not GraphReadScope(project).hides(hidden)  # the system view hides nothing
    for shown in ({}, {"in_graph": True, "onboarded_by": str(ONBOARDER)}):
        assert not GraphReadScope(project, viewer_id=TEAMMATE).hides(shown)
    # Nobody onboarded it: hidden from every viewer, never `str(None)`-matched.
    assert GraphReadScope(project, viewer_id=TEAMMATE).hides({"in_graph": False})


def test_system_view_drops_only_the_viewer_and_restores_the_request_scope() -> None:
    project, base, snapshot = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scope = GraphReadScope(project, ((base, snapshot),), viewer_id=ONBOARDER)
    with system_view():  # nothing bound: nothing to drop
        assert current_scope(project).viewer_id is None
    with bind_scope(scope):
        with system_view():
            inner = current_scope(project)
            assert inner.viewer_id is None and inner.replacements == scope.replacements
        assert current_scope(project) == scope


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _hardware(db: AsyncSession) -> tuple[uuid.UUID, GraphEntity, GraphEntity]:
    """A project with one robot its onboarder has not added to the graph and one shared part."""
    team = Team(name="visibility")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="Rover")
    db.add(project)
    await db.flush()

    def part(name: str, **attrs: object) -> GraphEntity:
        return GraphEntity(
            project_id=project.id,
            kind="part",
            domain=Domain.ELECTRICAL,
            origin="manual",
            name=name,
            external_ref=f"usb:FAKE-0001/{name}",
            attrs=attrs,
        )

    hidden = part("hidden", in_graph=False, onboarded_by=str(ONBOARDER))
    shared = part("shared")
    db.add_all([hidden, shared])
    await db.commit()
    return project.id, hidden, shared


async def test_the_onboarder_sees_hidden_hardware_and_a_teammate_does_not(
    db: AsyncSession,
) -> None:
    project, hidden, shared = await _hardware(db)

    async def ids(scope: GraphReadScope, **kw: bool) -> set[uuid.UUID]:
        rows = await db.scalars(select(GraphEntity.id).where(scope.entity_predicate(**kw)))
        return set(rows)

    assert await ids(GraphReadScope(project)) == {hidden.id, shared.id}
    assert await ids(GraphReadScope(project, viewer_id=ONBOARDER)) == {hidden.id, shared.id}
    assert await ids(GraphReadScope(project, viewer_id=TEAMMATE)) == {shared.id}
    opted = await ids(GraphReadScope(project, viewer_id=TEAMMATE), include_hidden=True)
    assert opted == {hidden.id, shared.id}
    assert (await resolve_scope(db, project, TEAMMATE)).viewer_id == TEAMMATE


async def test_the_resolver_resolves_hidden_hardware_for_every_viewer(
    db: AsyncSession, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Telemetry ingest never filters by viewer, and its cache is not viewer-keyed."""
    from solus_api.graph.resolver import CachingEntityResolver, DbEntityResolver

    project, hidden, _ = await _hardware(db)
    resolver = CachingEntityResolver(DbEntityResolver(maker))
    for viewer in (TEAMMATE, ONBOARDER, None):
        with bind_scope(GraphReadScope(project, viewer_id=viewer)):
            assert await DbEntityResolver(maker).resolve(project, hidden.external_ref or "") == (
                hidden.id
            )
            assert await resolver.resolve(project, hidden.external_ref or "") == hidden.id


async def test_sol_anchors_admit_hidden_hardware_for_its_onboarder_only(db: AsyncSession) -> None:
    from solus_api.agent.sol_anchors import visible_entity_ids

    project, hidden, shared = await _hardware(db)
    both = [hidden.id, shared.id]
    with bind_scope(GraphReadScope(project, viewer_id=ONBOARDER)):
        assert await visible_entity_ids(db, project, both) == set(both)
    with bind_scope(GraphReadScope(project, viewer_id=TEAMMATE)):
        assert await visible_entity_ids(db, project, both) == {shared.id}


async def test_sol_telemetry_leaves_out_hidden_hardware_for_a_teammate(
    db: AsyncSession, maker: async_sessionmaker[AsyncSession]
) -> None:
    """SOL's `get_telemetry` tool and its context's telemetry section read one seam: a hidden
    part's packets resolve for everyone, yet only its onboarder's turn carries its signals."""
    from datetime import UTC, datetime

    from solus_api.agent.context import build_context
    from solus_api.agent.feeds import DbSolSystems
    from solus_api.agent.interfaces import GraphScope, TelemetryWindow
    from solus_api.agent.runtime import build_dispatch, build_sol_registry
    from solus_api.agent.tools.shapes import ToolCall
    from solus_api.graph.buffer import InMemoryTelemetryBuffer
    from solus_api.graph.packet import TelemetryPacket
    from solus_api.graph.resolver import DbEntityResolver
    from solus_api.graph.telemetry import TelemetryPlumbing

    project, hidden, shared = await _hardware(db)
    assert await GraphReadScope(project, viewer_id=TEAMMATE).hidden_ids(db) == {hidden.id}
    assert await GraphReadScope(project, viewer_id=ONBOARDER).hidden_ids(db) == set()
    assert await GraphReadScope(project).hidden_ids(db) == set()
    plumbing = TelemetryPlumbing(InMemoryTelemetryBuffer(), DbEntityResolver(maker))
    systems = DbSolSystems(maker, plumbing)
    now = datetime.now(UTC)
    for part in (hidden, shared):
        values = {f"{part.name}.position": 1.0}
        packet = TelemetryPacket(device_id=part.external_ref or "", timestamp=now, values=values)
        assert (await plumbing.ingest(project, packet)).entity_id == part.id
    dispatch = build_dispatch(build_sol_registry(maker, project, systems=systems), None)
    anchors = GraphScope(anchor_entity_ids=[shared.id], degree=0)
    window = TelemetryWindow(duration_seconds=60)
    both = {"hidden.position", "shared.position"}
    for viewer, signals in ((ONBOARDER, both), (TEAMMATE, {"shared.position"})):
        with bind_scope(GraphReadScope(project, viewer_id=viewer)):
            tool = await dispatch(ToolCall(tool="get_telemetry", args={"duration_seconds": 60}))
            context = await build_context(
                systems, "how is the arm", project_id=project, scope=anchors, window=window
            )
        assert tool.ok and tool.value is not None, tool.error
        assert {name for found in tool.value["windows"] for name in found["signals"]} == signals
        text = " ".join(s.text for s in context.sections if s.kind == "telemetry")
        assert f"{len(signals)} signal(s)" in text, text
