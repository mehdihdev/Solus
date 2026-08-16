"""Real `SolSystems` (SOLUS-SYS-04) — conformance, scoping, and honesty.

The adapter (`agent/feeds.py`) assembles the real graph traversal, telemetry
plumbing, and SYS-02 retrieval behind the W0-07 Protocol. These tests prove:
the shared core contract holds against a real database; every feed is
project-scoped IN the query (the highest-severity invariant); `degree`/`window`
and `budget` are honored; and empty is honest — a feed with no data returns
nothing rather than inventing content.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fixtures.sol_contract import assert_core_contract
from solus_api.agent.feeds import DbSolSystems
from solus_api.agent.interfaces import (
    ContextBudget,
    GraphScope,
    RetrievalFilter,
    SolSystems,
    TelemetryWindow,
)
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.resolver import DbEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.models import (
    Domain,
    ErrorSolution,
    GraphEdge,
    GraphEntity,
    Membership,
    Project,
    Role,
    Team,
    User,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def test_fake_sol_systems_is_banished_from_production() -> None:
    """Ratchet (SYS-04): the canned double must never re-enter production wiring.
    Zero references — code, comments, or docstrings — anywhere under src/solus_api;
    the fake lives in tests/fixtures and only tests may construct it."""
    src = Path(__file__).resolve().parents[1] / "src" / "solus_api"
    offenders = [
        str(path)
        for path in sorted(src.rglob("*.py"))
        if "FakeSolSystems" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def buffer() -> InMemoryTelemetryBuffer:
    return InMemoryTelemetryBuffer()


@pytest.fixture
def systems(
    maker: async_sessionmaker[AsyncSession], buffer: InMemoryTelemetryBuffer
) -> DbSolSystems:
    # embed=None exercises the deterministic keyless (full-text) retrieval path.
    plumbing = TelemetryPlumbing(buffer, DbEntityResolver(maker))
    built: SolSystems = DbSolSystems(maker, plumbing)  # mypy: structural conformance
    assert isinstance(built, DbSolSystems)
    return built


async def _seed_feed_project(db: AsyncSession, tag: str) -> Project:
    user = User(supabase_user_id=f"sub-{tag}-{uuid.uuid4().hex[:8]}", email=f"{tag}@ex.com")
    team = Team(name=tag)
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name=tag, created_by=user.id)
    db.add(project)
    await db.flush()
    return project


def _seed_part(
    project_id: uuid.UUID, name: str, *, domain: Domain = Domain.ELECTRICAL
) -> GraphEntity:
    return GraphEntity(
        project_id=project_id,
        kind="part",
        domain=domain,
        name=name,
        external_ref=f"ref-{name}",
        attrs={},
    )


def _link(project_id: uuid.UUID, src: GraphEntity, dst: GraphEntity) -> GraphEdge:
    return GraphEdge(
        project_id=project_id,
        src_id=src.id,
        dst_id=dst.id,
        relation_type="connected_to",
        domain_pair="electrical<->electrical",
        confidence=1.0,
        attrs={},
    )


# --- core contract against the real database ----------------------------------


async def test_real_systems_satisfies_core_contract(
    db: AsyncSession, systems: DbSolSystems, buffer: InMemoryTelemetryBuffer
) -> None:
    project = await _seed_feed_project(db, "core")
    root = _seed_part(project.id, "actuator-base")
    peer = _seed_part(project.id, "servo-horn")
    db.add_all([root, peer])
    await db.flush()
    db.add(_link(project.id, root, peer))
    db.add(
        ErrorSolution(
            project_id=project.id,
            error_text="brownout at motor start",
            solution_text="add bulk cap",
            domain=Domain.ELECTRICAL,
            attrs={},
        )
    )
    await db.commit()
    await buffer.append(project.id, root.id, "motor_current_a", _NOW, 1.2)

    await assert_core_contract(systems, project.id, anchors=[root.id])


# --- graph feed ----------------------------------------------------------------


async def test_get_graph_context_returns_the_seeded_neighborhood(
    db: AsyncSession, systems: DbSolSystems
) -> None:
    project = await _seed_feed_project(db, "graph")
    root = _seed_part(project.id, "kinova-shoulder")
    peer = _seed_part(project.id, "kinova-elbow")
    db.add_all([root, peer])
    await db.flush()
    db.add(_link(project.id, root, peer))
    await db.commit()

    ctx = await systems.get_graph_context(
        project.id, GraphScope(anchor_entity_ids=[root.id], degree=1)
    )
    assert {e.name for e in ctx.entities} == {"kinova-shoulder", "kinova-elbow"}
    assert len(ctx.edges) == 1 and ctx.truncated is False


async def test_degree_beyond_the_traversal_cap_is_clamped_not_an_error(
    db: AsyncSession, systems: DbSolSystems
) -> None:
    """`GraphScope.degree` is only `ge=0`; `load_neighborhood` raises above MAX_DEPTH=2.
    The adapter clamps — a deep request must degrade to bounded context, never to a
    masked 500 — and reports `truncated=True` because context beyond the clamp MAY
    have been dropped (conservative honesty)."""
    project = await _seed_feed_project(db, "deep")
    a, b, c, d = (_seed_part(project.id, n) for n in ("a", "b", "c", "d"))
    db.add_all([a, b, c, d])
    await db.flush()
    db.add_all([_link(project.id, a, b), _link(project.id, b, c), _link(project.id, c, d)])
    await db.commit()

    ctx = await systems.get_graph_context(
        project.id, GraphScope(anchor_entity_ids=[a.id], degree=5)
    )
    names = {e.name for e in ctx.entities}
    assert names == {"a", "b", "c"}  # two hops, not five
    assert ctx.truncated is True


async def test_domains_narrow_the_neighborhood_in_query(
    db: AsyncSession, systems: DbSolSystems
) -> None:
    project = await _seed_feed_project(db, "domains")
    root = _seed_part(project.id, "pcb", domain=Domain.ELECTRICAL)
    elec = _seed_part(project.id, "regulator", domain=Domain.ELECTRICAL)
    mech = _seed_part(project.id, "bracket", domain=Domain.MECHANICAL)
    db.add_all([root, elec, mech])
    await db.flush()
    db.add_all([_link(project.id, root, elec), _link(project.id, root, mech)])
    await db.commit()

    scope = GraphScope(anchor_entity_ids=[root.id], degree=1, domains=["electrical"])
    ctx = await systems.get_graph_context(project.id, scope)
    assert {e.name for e in ctx.entities} == {"pcb", "regulator"}  # root always kept

    bogus = GraphScope(anchor_entity_ids=[root.id], degree=1, domains=["no-such-domain"])
    ctx = await systems.get_graph_context(project.id, bogus)
    assert {e.name for e in ctx.entities} == {"pcb"}  # unknown domain matches nothing


async def test_budget_max_entities_subsamples_and_flags(
    db: AsyncSession, systems: DbSolSystems
) -> None:
    project = await _seed_feed_project(db, "budget")
    root = _seed_part(project.id, "hub")
    spokes = [_seed_part(project.id, f"spoke-{i}") for i in range(3)]
    db.add_all([root, *spokes])
    await db.flush()
    db.add_all([_link(project.id, root, s) for s in spokes])
    await db.commit()

    ctx = await systems.get_graph_context(
        project.id,
        GraphScope(anchor_entity_ids=[root.id], degree=1),
        ContextBudget(max_entities=2),
    )
    assert len(ctx.entities) <= 2 and ctx.truncated is True
    kept = {e.id for e in ctx.entities}
    assert all(e.src_id in kept and e.dst_id in kept for e in ctx.edges)


# --- tenant isolation (the highest-severity invariant) --------------------------


async def test_no_feed_crosses_tenants(
    db: AsyncSession, systems: DbSolSystems, buffer: InMemoryTelemetryBuffer
) -> None:
    """Write under project A, read under project B — every feed returns none of A's data,
    scoped in the query (roots from another project resolve to nothing)."""
    a = await _seed_feed_project(db, "tenant-a")
    b = await _seed_feed_project(db, "tenant-b")
    a_root = _seed_part(a.id, "a-secret-part")
    db.add(a_root)
    db.add(
        ErrorSolution(
            project_id=a.id,
            error_text="a-only brownout",
            solution_text="a fix",
            domain=Domain.ELECTRICAL,
            attrs={},
        )
    )
    await db.commit()
    await buffer.append(a.id, a_root.id, "motor_current_a", _NOW, 3.1)

    ctx = await systems.get_graph_context(b.id, GraphScope(anchor_entity_ids=[a_root.id], degree=2))
    assert ctx.entities == [] and ctx.edges == []

    telemetry = await systems.get_telemetry(b.id, TelemetryWindow(duration_seconds=60))
    assert telemetry.windows == []

    b_filter = RetrievalFilter(project_id=b.id)
    assert await systems.get_error_history("brownout", k=10, filter=b_filter) == []
    assert await systems.rag_query("secret", k=10, filter=b_filter) == []


async def test_unfiltered_tenant_retrieval_is_refused(systems: DbSolSystems) -> None:
    """sol-interface §5: tenant corpora are never served unscoped. The refusal IS the
    guarantee — a real impl raising here is correct behavior, not a failure."""
    with pytest.raises(ValueError, match="project_id"):
        await systems.rag_query("anything", k=3)
    with pytest.raises(ValueError, match="project_id"):
        await systems.rag_query("anything", k=3, filter=RetrievalFilter())
    with pytest.raises(ValueError, match="project_id"):
        await systems.get_error_history("anything", k=3)


# --- honesty: empty beats invented ---------------------------------------------


async def test_empty_project_is_honestly_empty(db: AsyncSession, systems: DbSolSystems) -> None:
    project = await _seed_feed_project(db, "empty")
    await db.commit()

    ctx = await systems.get_graph_context(
        project.id, GraphScope(anchor_entity_ids=[uuid.uuid4()], degree=2)
    )
    assert ctx.entities == [] and ctx.edges == [] and ctx.truncated is False

    telemetry = await systems.get_telemetry(project.id, TelemetryWindow(duration_seconds=60))
    assert telemetry.windows == []

    scoped = RetrievalFilter(project_id=project.id)
    assert await systems.get_error_history("lm358", k=5, filter=scoped) == []
    assert await systems.rag_query("camera_node", k=5, filter=scoped) == []


# --- the flywheel ---------------------------------------------------------------


async def test_record_error_solution_commits_and_round_trips(
    db: AsyncSession,
    systems: DbSolSystems,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project = await _seed_feed_project(db, "record")
    await db.commit()

    recorded = await systems.record_error_solution(
        project.id, "i2c conflict", "re-strap AD0", "electrical", attrs={"bus": "i2c1"}
    )
    async with maker() as fresh:  # a second session proves the adapter COMMITTED
        row = await fresh.get(ErrorSolution, recorded)
        assert row is not None
        assert row.project_id == project.id and row.solution_text == "re-strap AD0"

    hits = await systems.get_error_history(
        "i2c conflict", k=5, filter=RetrievalFilter(project_id=project.id)
    )
    assert [h.chunk for h in hits] == ["i2c conflict"]


# --- embed forwarding -----------------------------------------------------------


async def test_embed_fn_is_forwarded_to_every_retrieval(
    db: AsyncSession,
    maker: async_sessionmaker[AsyncSession],
    buffer: InMemoryTelemetryBuffer,
) -> None:
    project = await _seed_feed_project(db, "embed")
    await db.commit()

    calls: list[str] = []

    async def recording_embed(text: str) -> list[float] | None:
        calls.append(text)
        return None  # no-signal: retrieval degrades to full-text, adapter must not care

    plumbing = TelemetryPlumbing(buffer, DbEntityResolver(maker))
    systems = DbSolSystems(maker, plumbing, embed=recording_embed)
    scoped = RetrievalFilter(project_id=project.id)
    await systems.rag_query("q1", k=1, filter=scoped)
    await systems.get_error_history("q2", k=1, filter=scoped)
    await systems.record_error_solution(project.id, "q3-err", "q3-fix", "electrical")
    assert calls == ["q1", "q2", "q3-err\nq3-fix"]
