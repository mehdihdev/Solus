"""The one canonical bounded graph traversal (SOLUSDEV-191 / WS-01).

This is the traversal the shared-focus engine scopes widgets with, and the one a real
`SolSystems.get_graph_context` will adapt rather than reimplement — so "bounded", "project-scoped"
and "no dangling edges" are all load-bearing, not incidental.

The graph these tests build (all within one project unless stated):

    root ── drives ──▶ hop1a ── reads_from ──▶ hop2 ── depends_on ──▶ hop3
      │                  ▲
      └── mates_with ──▶ hop1b  (edge hop1a◀──▶hop1b closes the ring)
"""

import uuid
from dataclasses import dataclass

import pytest
from solus_api.agent.interfaces import GraphContext
from solus_api.graph.neighborhood import (
    EDGES_PER_ENTITY,
    MAX_DEPTH,
    Neighborhood,
    load_neighborhood,
    to_graph_context,
)
from solus_api.models import Domain, GraphEdge, GraphEntity, Membership, Project, Role, Team, User
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession


async def _project(db: AsyncSession, slug: str) -> Project:
    user = User(supabase_user_id=f"sub-{slug}-{uuid.uuid4().hex[:8]}", email=f"{slug}@ex.com")
    team = Team(name=slug)
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name=slug, created_by=user.id)
    db.add(project)
    await db.flush()
    return project


async def _entity(
    db: AsyncSession, project: Project, name: str, *, kind: str = "part", deleted: bool = False
) -> GraphEntity:
    entity = GraphEntity(
        project_id=project.id, kind=kind, domain=Domain.ELECTRICAL, name=name, attrs={}
    )
    db.add(entity)
    await db.flush()
    if deleted:
        from datetime import UTC, datetime

        entity.deleted_at = datetime.now(UTC)
        await db.flush()
    return entity


async def _edge(
    db: AsyncSession,
    project: Project,
    src: GraphEntity,
    dst: GraphEntity,
    *,
    relation_type: str = "drives",
    deleted: bool = False,
) -> GraphEdge:
    edge = GraphEdge(
        project_id=project.id,
        src_id=src.id,
        dst_id=dst.id,
        relation_type=relation_type,
        domain_pair="electrical<->electrical",
        attrs={},
    )
    db.add(edge)
    await db.flush()
    if deleted:
        from datetime import UTC, datetime

        edge.deleted_at = datetime.now(UTC)
        await db.flush()
    return edge


@dataclass(frozen=True)
class _Chain:
    """The fixture graph above, named so tests read like the diagram."""

    project: Project
    root: GraphEntity
    hop1a: GraphEntity
    hop1b: GraphEntity
    hop2: GraphEntity
    hop3: GraphEntity


async def _chain(db: AsyncSession, slug: str) -> _Chain:
    project = await _project(db, slug)
    root = await _entity(db, project, "root", kind="motor")
    hop1a = await _entity(db, project, "hop1a", kind="ic")
    hop1b = await _entity(db, project, "hop1b", kind="bracket")
    hop2 = await _entity(db, project, "hop2", kind="ic")
    hop3 = await _entity(db, project, "hop3", kind="ic")
    await _edge(db, project, root, hop1a, relation_type="drives")
    await _edge(db, project, root, hop1b, relation_type="mates_with")
    await _edge(db, project, hop1a, hop1b, relation_type="mates_with")
    await _edge(db, project, hop1a, hop2, relation_type="reads_from")
    await _edge(db, project, hop2, hop3, relation_type="depends_on")
    await db.commit()
    return _Chain(project, root=root, hop1a=hop1a, hop1b=hop1b, hop2=hop2, hop3=hop3)


def _names(nb: Neighborhood) -> set[str]:
    return {e.name for e in nb.entities}


# ------------------------------------------------------------------------------ depth


async def test_depth_zero_returns_only_the_focused_entity(db: AsyncSession) -> None:
    g = await _chain(db, "depth0")
    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=0)
    assert _names(nb) == {"root"}
    assert nb.edges == []


async def test_depth_one_returns_direct_neighbours(db: AsyncSession) -> None:
    g = await _chain(db, "depth1")
    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=1)
    assert _names(nb) == {"root", "hop1a", "hop1b"}


async def test_depth_two_reaches_two_hops_and_no_further(db: AsyncSession) -> None:
    """The bound is the point — an unbounded traversal would drag in the whole project."""
    g = await _chain(db, "depth2")
    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=2)
    assert _names(nb) == {"root", "hop1a", "hop1b", "hop2"}
    assert "hop3" not in _names(nb)


async def test_traversal_follows_edges_in_both_directions(db: AsyncSession) -> None:
    """Focus is undirected: selecting the IC must reveal the motor that drives it."""
    g = await _chain(db, "bidir")
    nb = await load_neighborhood(db, g.project.id, roots=[g.hop2.id], depth=1)
    assert _names(nb) == {"hop2", "hop1a", "hop3"}


async def test_depth_beyond_the_cap_is_rejected(db: AsyncSession) -> None:
    g = await _chain(db, "depthcap")
    with pytest.raises(ValueError):
        await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=MAX_DEPTH + 1)


# ------------------------------------------------------------------- the induced subgraph


async def test_edges_between_neighbours_are_included(db: AsyncSession) -> None:
    """The result is the INDUCED subgraph: hop1a↔hop1b closes the ring and must be present,
    or the widget renders two nodes that look unrelated when they are wired together."""
    g = await _chain(db, "induced")
    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=1)
    pairs = {(e.src_id, e.dst_id) for e in nb.edges}
    assert (g.hop1a.id, g.hop1b.id) in pairs


async def test_no_edge_dangles_outside_the_returned_entities(db: AsyncSession) -> None:
    """Every returned edge must have BOTH endpoints in the returned entity set — a dangling edge
    is a rendering crash waiting to happen."""
    g = await _chain(db, "nodangle")
    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=2)
    ids = {e.id for e in nb.entities}
    assert all(edge.src_id in ids and edge.dst_id in ids for edge in nb.edges)


async def test_edges_are_not_duplicated(db: AsyncSession) -> None:
    g = await _chain(db, "nodupe")
    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=2)
    assert len({e.id for e in nb.edges}) == len(nb.edges)


async def test_a_cycle_terminates(db: AsyncSession) -> None:
    g = await _chain(db, "cycle")
    await _edge(db, g.project, g.hop2, g.root, relation_type="depends_on")
    await db.commit()
    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=MAX_DEPTH)
    assert "root" in _names(nb)


# ------------------------------------------------------------------- scoping and filters


async def test_traversal_is_project_scoped(db: AsyncSession) -> None:
    """Tenant isolation, the highest-severity invariant: an edge crossing into another project's
    entity must not drag that entity back."""
    g = await _chain(db, "tenantx")
    other = await _project(db, "tenanty")
    intruder = await _entity(db, other, "intruder")
    # A deliberately malformed cross-project edge, stored under the FIRST project.
    await _edge(db, g.project, g.root, intruder)
    await db.commit()

    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=MAX_DEPTH)
    assert "intruder" not in _names(nb)
    assert all(e.project_id == g.project.id for e in nb.entities)


async def test_a_root_from_another_project_yields_nothing(db: AsyncSession) -> None:
    g = await _chain(db, "foreignroot")
    other = await _project(db, "foreignroot2")
    outsider = await _entity(db, other, "outsider")
    await db.commit()
    nb = await load_neighborhood(db, g.project.id, roots=[outsider.id], depth=1)
    assert nb.entities == []


async def test_unknown_root_yields_nothing(db: AsyncSession) -> None:
    g = await _chain(db, "unknownroot")
    nb = await load_neighborhood(db, g.project.id, roots=[uuid.uuid4()], depth=1)
    assert nb.entities == []


async def test_soft_deleted_entities_and_edges_are_excluded(db: AsyncSession) -> None:
    g = await _chain(db, "softdel")
    ghost = await _entity(db, g.project, "ghost", deleted=True)
    await _edge(db, g.project, g.root, ghost)
    await db.commit()
    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=1)
    assert "ghost" not in _names(nb)


async def test_entity_types_filter_narrows_the_neighbourhood(db: AsyncSession) -> None:
    g = await _chain(db, "kindfilter")
    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=1, entity_types=["ic"])
    assert _names(nb) == {"root", "hop1a"}  # the root is always kept; hop1b is a bracket


async def test_a_filtered_out_node_is_not_a_stepping_stone(db: AsyncSession) -> None:
    """The documented `entity_types` semantics, at the only depth where they mean anything: a node
    excluded by the filter is not traversed THROUGH, so anything reachable only via it is out too.
    At depth 1 this is untestable — an excluded node cannot be an intermediate hop."""
    project = await _project(db, "steppingstone")
    root = await _entity(db, project, "root", kind="ic")
    gate = await _entity(db, project, "gate", kind="bracket")  # excluded by the filter
    beyond = await _entity(db, project, "beyond", kind="ic")  # wanted kind, but only via `gate`
    await _edge(db, project, root, gate)
    await _edge(db, project, gate, beyond)
    await db.commit()

    unfiltered = await load_neighborhood(db, project.id, roots=[root.id], depth=2)
    assert _names(unfiltered) == {"root", "gate", "beyond"}

    filtered = await load_neighborhood(
        db, project.id, roots=[root.id], depth=2, entity_types=["ic"]
    )
    assert _names(filtered) == {"root"}


async def test_relation_types_filter_narrows_the_neighbourhood(db: AsyncSession) -> None:
    g = await _chain(db, "reltypefilter")
    nb = await load_neighborhood(
        db, g.project.id, roots=[g.root.id], depth=1, relation_types=["drives"]
    )
    assert _names(nb) == {"root", "hop1a"}


async def test_multiple_roots_are_supported(db: AsyncSession) -> None:
    g = await _chain(db, "multiroot")
    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id, g.hop3.id], depth=0)
    assert _names(nb) == {"root", "hop3"}


# ----------------------------------------------------------------------------- bounds


async def test_max_entities_truncates_and_says_so(db: AsyncSession) -> None:
    """Bounded output, and honest about it — a silent cap reads as 'this is the whole picture'."""
    g = await _chain(db, "truncate")
    nb = await load_neighborhood(
        db, g.project.id, roots=[g.root.id], depth=MAX_DEPTH, max_entities=2
    )
    assert nb.truncated is True
    assert len(nb.entities) <= 2


async def test_truncation_is_deterministic(db: AsyncSession) -> None:
    """A capped view must not shuffle between identical requests — refreshing would silently
    swap which neighbours you can see."""
    g = await _chain(db, "stabletrunc")
    runs = [
        [
            e.id
            for e in (
                await load_neighborhood(
                    db, g.project.id, roots=[g.root.id], depth=MAX_DEPTH, max_entities=3
                )
            ).entities
        ]
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]


async def test_an_untruncated_result_says_so(db: AsyncSession) -> None:
    g = await _chain(db, "nottruncated")
    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=1)
    assert nb.truncated is False


async def _hub(db: AsyncSession, slug: str, spokes: int) -> tuple[Project, GraphEntity]:
    """A hub with `spokes` neighbours — the shape a 20k-file monorepo's `:repo` entity has, which
    is what makes these bounds a customer-reachable concern rather than a theoretical one."""
    project = await _project(db, slug)
    hub = await _entity(db, project, "hub")
    spokes_rows = [
        GraphEntity(
            project_id=project.id,
            kind="part",
            domain=Domain.ELECTRICAL,
            name=f"spoke{i}",
            attrs={},
        )
        for i in range(spokes)
    ]
    db.add_all(spokes_rows)
    await db.flush()
    db.add_all(
        [
            GraphEdge(
                project_id=project.id,
                src_id=hub.id,
                dst_id=s.id,
                relation_type="contains",
                domain_pair="electrical<->electrical",
                attrs={},
            )
            for s in spokes_rows
        ]
    )
    await db.commit()
    return project, hub


async def test_a_hub_node_stays_a_bounded_read(db: AsyncSession) -> None:
    """Security C1/C2: a node with a very high degree must return a bounded result, not hydrate
    every neighbour (measured 1.3 GiB for 20k rows before `defer(embedding)` + a SQL LIMIT) and
    not blow asyncpg's 32,767 bind-parameter ceiling with an unbounded `IN (...)`."""
    project, hub = await _hub(db, "hubnode", spokes=1_200)
    nb = await load_neighborhood(db, project.id, roots=[hub.id], depth=1, max_entities=50)
    assert len(nb.entities) <= 50
    assert nb.truncated is True


async def test_the_embedding_column_is_never_hydrated(db: AsyncSession) -> None:
    """Security C1: `graph_entity.embedding` is a 1536-float vector that NEITHER consumer wants —
    `serialize_entity` omits it and `EntityRead` drops it. `raiseload` makes an accidental future
    access loud instead of silently costing a gigabyte per request."""
    g = await _chain(db, "noembed")
    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=1)
    with pytest.raises(InvalidRequestError):
        _ = nb.entities[0].embedding


async def test_a_dense_neighbourhood_caps_edges_and_says_so(db: AsyncSession) -> None:
    """Security C3: entity caps do not bound edges. 500 mutually-connected entities induce ~125k
    edges (43 MB of JSON) — and the pre-fix code reported `truncated=False` while doing it."""
    project = await _project(db, "clique")
    members = [
        GraphEntity(
            project_id=project.id, kind="part", domain=Domain.ELECTRICAL, name=f"m{i}", attrs={}
        )
        for i in range(30)
    ]
    db.add_all(members)
    await db.flush()
    db.add_all(
        [
            GraphEdge(
                project_id=project.id,
                src_id=a.id,
                dst_id=b.id,
                relation_type="connected_to",
                domain_pair="electrical<->electrical",
                attrs={},
            )
            for a in members
            for b in members
            if a.id != b.id
        ]
    )
    await db.commit()

    max_entities = 10
    nb = await load_neighborhood(
        db, project.id, roots=[members[0].id], depth=1, max_entities=max_entities
    )
    assert len(nb.edges) <= max_entities * EDGES_PER_ENTITY
    assert nb.truncated is True


async def test_max_entities_must_be_positive(db: AsyncSession) -> None:
    g = await _chain(db, "badmax")
    with pytest.raises(ValueError):
        await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=1, max_entities=0)


# ------------------------------------------------------- the W0-07 adapter (one traversal)


async def test_adapts_to_the_w0_07_graph_context_shape(db: AsyncSession) -> None:
    """The reuse claim, made concrete: SOL's `get_graph_context` returns THIS traversal through a
    thin adapter, so the focus engine and the agent can never disagree about the graph."""
    g = await _chain(db, "adapter")
    nb = await load_neighborhood(db, g.project.id, roots=[g.root.id], depth=1)
    context = to_graph_context(nb)

    assert isinstance(context, GraphContext)
    assert {e.name for e in context.entities} == _names(nb)
    assert len(context.edges) == len(nb.edges)
    assert context.truncated is False
    # EntityRead deliberately omits the embedding — a 1536-float vector is noise in a prompt.
    assert not hasattr(context.entities[0], "embedding")
