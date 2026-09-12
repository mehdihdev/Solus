"""Bounded graph traversal — the ONE traversal in Solus (SOLUSDEV-191 / WS-01).

Two consumers, one implementation, deliberately:

* the **shared-focus engine** — `GET /projects/{id}/graph?root=&depth=`, which re-scopes every
  mounted widget when the user selects an entity;
* the **SOL agent** — a real `SolSystems.get_graph_context` adapts this via `to_graph_context`
  rather than growing a second traversal that could disagree with what the user is looking at.

It returns ORM rows, not a serialized shape, precisely so those two can serialize differently
(the HTTP surface uses `serialize_entity`'s public keys; the agent uses W0-07's `EntityRead`)
without either mapping being duplicated.

**Iterated frontier, not a recursive CTE.** ADR-027 deferred a graph database because the
traversal we need is shallow; `graph_edge.src_id`/`dst_id` are each indexed, so `depth` bounded
queries of `WHERE src_id IN (…) OR dst_id IN (…)` is both sufficient and obvious. Depth is capped
at `MAX_DEPTH` — SYS-05's 2-degree sub-sampling is the perf lever this leaves room for.

**Every result is bounded and honest about it.** `max_entities` caps the output and sets
`truncated`, because a silently capped subgraph reads as "this is the whole picture".

**Project scoping is enforced on every query**, never inferred from an edge. A malformed edge
pointing at another project's entity resolves to nothing rather than dragging that entity back
(CLAUDE.md §7 — tenant isolation is the highest-severity invariant).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.graph.read_scope import current_scope
from solus_api.models import Domain, GraphEdge, GraphEntity

#: Hard ceiling on traversal depth. Anything deeper is a query, not a neighbourhood — and ADR-027
#: explicitly defers deep multi-hop traversal until it is a MEASURED bottleneck.
MAX_DEPTH: Final = 2

#: Default cap on returned entities. Generous for a focus view, small enough to stay a bounded read.
DEFAULT_MAX_ENTITIES: Final = 500

#: Edge rows examined per hop while DISCOVERING neighbours. A hub node (the `:repo` entity of a
#: 20k-file monorepo has an edge to every file) would otherwise make one click scan the project.
MAX_EDGE_SCAN: Final = 10_000

#: Candidate ids bound into a single `IN (...)`. asyncpg caps a statement at 32,767 bind
#: parameters, and exceeding it raises `InterfaceError` — a 500 that would repeat forever for that
#: node. Kept far below the limit; generous enough that a `kind` filter still has candidates to
#: match after the cap.
MAX_BIND_IDS: Final = 2_048

#: Cap on RETURNED edges. Entities alone do not bound a response: 500 mutually-connected entities
#: induce ~125k edges, which serialized to 43 MB in review. Scales with the entity cap so a dense
#: but legitimate neighbourhood survives whole.
EDGES_PER_ENTITY: Final = 8


@dataclass(frozen=True)
class Neighborhood:
    """The induced subgraph around one or more anchors: every returned edge has BOTH endpoints in
    `entities`, so a consumer can render it without checking for dangling references."""

    entities: list[GraphEntity]
    edges: list[GraphEdge]
    truncated: bool


async def _load_entities(
    session: AsyncSession,
    project_id: UUID,
    ids: Sequence[UUID],
    entity_types: Sequence[str] | None,
    domains: Sequence[Domain] | None = None,
    *,
    limit: int,
) -> list[GraphEntity]:
    """Hydrate at most `limit` entities from `ids`, project-scoped and live.

    `defer(embedding)` is load-bearing, not tidiness: `graph_entity.embedding` is a 1536-float
    vector, and selecting it for a hub node's neighbours measured **1.3 GiB** of RSS for 20k rows
    (3.0s vs 0.3s deferred). Neither consumer wants it — `serialize_entity` omits it and
    `EntityRead` drops it deliberately — so the traversal was paying a gigabyte to discard the
    data. `raiseload` turns any future access into a loud error rather than a silent lazy load.

    The `limit` is applied in SQL, not in Python afterwards, so the cap bounds the WORK.
    """
    if not ids:
        return []
    stmt = (
        select(GraphEntity)
        .options(defer(GraphEntity.embedding, raiseload=True))
        .where(
            GraphEntity.project_id == project_id,
            current_scope(project_id).entity_predicate(),
            GraphEntity.deleted_at.is_(None),
            GraphEntity.id.in_(ids),
        )
    )
    if entity_types:
        stmt = stmt.where(GraphEntity.kind.in_(entity_types))
    if domains is not None:
        # May be empty after sanitizing unknown names — `IN ()` matches nothing,
        # which is the correct reading of "restrict to these domains".
        stmt = stmt.where(GraphEntity.domain.in_(domains))
    # Stable order so TRUNCATION is deterministic: without it, two identical requests could keep
    # different neighbours, and a user refreshing a capped view would see it shuffle.
    stmt = stmt.order_by(GraphEntity.created_at, GraphEntity.id).limit(limit)
    return list((await session.scalars(stmt)).all())


async def _adjacent_ids(
    session: AsyncSession,
    project_id: UUID,
    frontier: Sequence[UUID],
    relation_types: Sequence[str] | None,
) -> tuple[list[UUID], bool]:
    """Endpoint ids one hop from `frontier`, in a stable order, plus whether the scan hit its cap.

    Selects only the two id columns — discovery does not need whole rows. Bounded at
    `MAX_EDGE_SCAN`: a hub node with an edge to every file in a monorepo would otherwise make one
    click scan the entire project, and feed an unbounded id list into the next query's `IN (...)`.
    """
    frontier = current_scope(project_id).aliases(list(frontier))
    stmt = select(GraphEdge.src_id, GraphEdge.dst_id).where(
        GraphEdge.project_id == project_id,
        current_scope(project_id).edge_predicate(),
        GraphEdge.deleted_at.is_(None),
        or_(GraphEdge.src_id.in_(frontier), GraphEdge.dst_id.in_(frontier)),
    )
    if relation_types:
        stmt = stmt.where(GraphEdge.relation_type.in_(relation_types))
    # Confidence-first (SYS-05 relevance pruning): discovery order decides which
    # neighbours survive a binding budget, so rank by edge confidence, with the
    # old created_at/id order as the deterministic tiebreak.
    stmt = stmt.order_by(GraphEdge.confidence.desc(), GraphEdge.created_at, GraphEdge.id).limit(
        MAX_EDGE_SCAN + 1
    )

    rows = (await session.execute(stmt)).all()
    capped = len(rows) > MAX_EDGE_SCAN
    # A list, not a set: iteration order of a set of UUIDs is not stable, and this list gets
    # sliced below — an unstable order would make truncation non-deterministic again.
    touched: list[UUID] = []
    seen: set[UUID] = set()
    for src_id, dst_id in rows[:MAX_EDGE_SCAN]:
        for endpoint in (
            current_scope(project_id).project_id_for_entity(src_id),
            current_scope(project_id).project_id_for_entity(dst_id),
        ):
            if endpoint not in seen:
                seen.add(endpoint)
                touched.append(endpoint)
    return touched, capped


async def _induced_edges(
    session: AsyncSession,
    project_id: UUID,
    entity_ids: Sequence[UUID],
    relation_types: Sequence[str] | None,
    *,
    limit: int,
) -> tuple[list[GraphEdge], bool]:
    """Edges with BOTH endpoints among `entity_ids`, plus whether the cap bit.

    One query at the end rather than accumulating per hop, which is what guarantees no edge
    dangles and picks up edges *between* neighbours — without it, two parts wired to each other
    render as unrelated.

    Capped because bounding entities does NOT bound edges: 500 mutually-connected entities induce
    ~125k edges, which serialized to 43 MB in review while still reporting `truncated=False`.
    """
    if not entity_ids:
        return [], False
    entity_ids = current_scope(project_id).aliases(list(entity_ids))
    stmt = select(GraphEdge).where(
        GraphEdge.project_id == project_id,
        current_scope(project_id).edge_predicate(),
        GraphEdge.deleted_at.is_(None),
        GraphEdge.src_id.in_(entity_ids),
        GraphEdge.dst_id.in_(entity_ids),
    )
    if relation_types:
        stmt = stmt.where(GraphEdge.relation_type.in_(relation_types))
    stmt = stmt.order_by(GraphEdge.created_at, GraphEdge.id).limit(limit + 1)
    rows = list((await session.scalars(stmt)).all())
    return [current_scope(project_id).project_edge(row) for row in rows[:limit]], len(rows) > limit


async def load_neighborhood(
    session: AsyncSession,
    project_id: UUID,
    *,
    roots: Sequence[UUID],
    depth: int = 1,
    entity_types: Sequence[str] | None = None,
    relation_types: Sequence[str] | None = None,
    domains: Sequence[str] | None = None,
    max_entities: int = DEFAULT_MAX_ENTITIES,
) -> Neighborhood:
    """The induced subgraph within `depth` hops of `roots`, project-scoped and bounded.

    Traversal is UNDIRECTED — focus is a question about what an entity relates to, not about
    which way an edge happens to point, so selecting an IC must reveal the motor driving it.

    `entity_types` and `domains` narrow which entities are reached AND traversed through (a
    filtered-out node is not a stepping stone); roots are always kept so a focused entity never
    vanishes from its own neighbourhood. Unknown or out-of-project roots simply yield nothing —
    the caller decides whether that is a 404, and there is no existence oracle here. Unknown
    `domains` values match nothing (they are filtered in-query, never post-hoc).
    """
    if not 0 <= depth <= MAX_DEPTH:
        raise ValueError(f"depth must be between 0 and {MAX_DEPTH}")
    if max_entities <= 0:
        raise ValueError("max_entities must be positive")
    # Sanitize to enum members BEFORE the query: the VARCHAR+CHECK enum column's bind
    # processor raises LookupError on values outside the vocabulary, and an unknown
    # domain must mean "matches nothing", not a 500.
    domain_filter = [Domain(d) for d in domains if d in Domain] if domains is not None else None

    # Roots are loaded WITHOUT the kind filter: the entity you focused is always part of its own
    # neighbourhood, even when you are filtering the view down to other kinds.
    found = await _load_entities(
        session, project_id, list(roots)[:MAX_BIND_IDS], entity_types=None, limit=max_entities + 1
    )
    truncated = len(found) > max_entities
    seen: dict[UUID, GraphEntity] = {e.id: e for e in found[:max_entities]}

    frontier = list(seen)
    for _ in range(depth):
        room = max_entities - len(seen)
        # Deliberately NOT breaking when `room == 0`: the `limit=room + 1` probe below is how we
        # learn that more neighbours existed. Stopping early here would leave `truncated=False` on
        # a view that is demonstrably partial — the flag would lie exactly when it matters most.
        if not frontier or truncated:
            break

        discovered, scan_capped = await _adjacent_ids(session, project_id, frontier, relation_types)
        truncated = truncated or scan_capped

        fresh = [eid for eid in discovered if eid not in seen]
        if len(fresh) > MAX_BIND_IDS:
            # Bind-parameter ceiling, not a display cap: exceeding asyncpg's limit raises rather
            # than returning less, so this slice is what keeps a hub node a bounded read.
            fresh, truncated = fresh[:MAX_BIND_IDS], True
        if not entity_types and domain_filter is None and len(fresh) > room:
            # SYS-05 relevance pruning: when the budget binds within a hop, keep the
            # candidates discovered through the highest-confidence edges (discovery
            # order is confidence-ranked above) instead of letting the hydrate
            # query's created_at LIMIT pick arbitrarily. Skipped under kind/domain
            # filters, where the filter needs the full candidate pool to fill the
            # room. ponytail: sliced-away ids that were soft-deleted over-report
            # `truncated`; harmless and conservative.
            fresh, truncated = fresh[:room], True

        # `_load_entities` re-applies the project scope, so an edge pointing at another project's
        # entity silently resolves to nothing rather than leaking it. `limit=room + 1` bounds the
        # rows the DB hydrates, so the cap is on work done, not on work discarded.
        rows = await _load_entities(
            session, project_id, fresh, entity_types, domain_filter, limit=room + 1
        )
        if len(rows) > room:
            rows, truncated = rows[:room], True
        for row in rows:
            seen[row.id] = row
        frontier = [row.id for row in rows]

    edges, edges_capped = await _induced_edges(
        session, project_id, list(seen), relation_types, limit=max_entities * EDGES_PER_ENTITY
    )
    return Neighborhood(
        entities=list(seen.values()), edges=edges, truncated=truncated or edges_capped
    )


def to_graph_context(neighborhood: Neighborhood) -> GraphContext:
    """Adapt to the W0-07 shape a real `SolSystems.get_graph_context` returns. Model-consumable:
    `EntityRead` drops the embedding, since a 1536-float vector is noise in a reasoning context."""
    return GraphContext(
        entities=[EntityRead.model_validate(e) for e in neighborhood.entities],
        edges=[EdgeRead.model_validate(e) for e in neighborhood.edges],
        truncated=neighborhood.truncated,
    )
