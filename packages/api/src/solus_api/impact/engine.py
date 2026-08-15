"""Impact traversal engine — SOLUS-IMP-01 (SOLUSDEV-197).

Given a focused entity and the change made to it, compute the CTR-04
`ImpactResult`: which entities the change reaches, through which path, and what
goes wrong there. Traversal is `load_neighborhood` — the ONE traversal in Solus
(its docstring forbids a second) — so the impact engine, the focus view, and the
SOL agent can never disagree about the graph. Canonical identity participates
two ways: real `same_as` edges (LNK-01/02) are walked like any edge, and
FK-only canonical siblings (FP-02 stamped, not yet edged) enter as a synthetic
`same_as` hop at distance 1 — the same physical part in another domain is one
identity hop away, whether or not the linker has materialized the edge yet.

Consequences come from a pluggable async provider. IMP-01 keeps the engine
free of rule knowledge; IMP-02 supplies the checker-backed provider that maps
CHK `Warning`s (and their narration) onto entities. The engine only assembles:
node severity = worst consequence (a contract invariant), `distance ==
len(path)` (ditto), nodes sorted worst-first then nearest, truncation reported
honestly from the traversal.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.checkers.interface import severity_rank
from solus_api.contracts.action_gate import DiffRow
from solus_api.contracts.impact import (
    Consequence,
    ImpactEntity,
    ImpactFocus,
    ImpactNode,
    ImpactPathStep,
    ImpactResult,
    worst_severity,
)
from solus_api.graph.neighborhood import DEFAULT_MAX_ENTITIES, Neighborhood, load_neighborhood
from solus_api.models import GraphEntity

#: The synthetic relation for an FK-only canonical hop (matches the linker's
#: materialized edge type, so a path reads the same either way).
SAME_AS = "same_as"

#: FP-02 bookkeeping rows (`origin="fingerprint"`) are internal identity
#: anchors, not user-facing surfaces — they never become impact nodes.
_FINGERPRINT_ORIGIN = "fingerprint"

ConsequenceProvider = Callable[
    [Neighborhood, UUID], Awaitable[Mapping[UUID, Sequence[Consequence]]]
]


async def _load_focus(session: AsyncSession, project_id: UUID, focus_id: UUID) -> GraphEntity:
    row = (
        await session.execute(
            select(GraphEntity).where(
                GraphEntity.id == focus_id,
                GraphEntity.project_id == project_id,
                GraphEntity.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError(f"focus entity {focus_id} not found in project")
    return row


async def _canonical_siblings(
    session: AsyncSession, project_id: UUID, focus: GraphEntity
) -> list[UUID]:
    """Live same-project entities that are the same physical part as `focus`
    via the FP-02 FK (the canonical row itself included as a traversal root,
    though it is never surfaced as a node)."""
    canonical_id = focus.canonical_part_id
    if canonical_id is None and focus.origin == _FINGERPRINT_ORIGIN:
        canonical_id = focus.id
    if canonical_id is None:
        return []
    rows = (
        await session.scalars(
            select(GraphEntity.id)
            .where(
                GraphEntity.project_id == project_id,
                GraphEntity.deleted_at.is_(None),
                GraphEntity.id != focus.id,
                or_(
                    GraphEntity.canonical_part_id == canonical_id,
                    GraphEntity.id == canonical_id,
                ),
            )
            # The traversal's stable-order convention: sibling SEED order is a
            # BFS tie-breaker, and an unordered query would make equal-length
            # paths flip between identical requests.
            .order_by(GraphEntity.created_at, GraphEntity.id)
        )
    ).all()
    return list(rows)


def _bfs(
    neighborhood: Neighborhood, focus_id: UUID, siblings: Sequence[UUID]
) -> tuple[dict[UUID, int], dict[UUID, tuple[UUID, str]]]:
    """Multi-source shortest paths over the induced subgraph, parent-tracked.

    The focus is distance 0; FK siblings seed at distance 1 behind a synthetic
    `same_as` hop. Edges are undirected (focus asks what relates, not which way
    an edge points); iteration order is the traversal's stable edge order, so
    tie paths are deterministic.
    """
    adjacency: dict[UUID, list[tuple[UUID, str]]] = {}
    for edge in neighborhood.edges:
        adjacency.setdefault(edge.src_id, []).append((edge.dst_id, edge.relation_type))
        adjacency.setdefault(edge.dst_id, []).append((edge.src_id, edge.relation_type))

    present = {entity.id for entity in neighborhood.entities}
    distance: dict[UUID, int] = {focus_id: 0}
    parent: dict[UUID, tuple[UUID, str]] = {}
    queue: list[UUID] = [focus_id]
    for sibling in siblings:
        if sibling in present and sibling not in distance:
            distance[sibling] = 1
            parent[sibling] = (focus_id, SAME_AS)
            queue.append(sibling)

    while queue:
        current = queue.pop(0)
        for neighbor, relation in adjacency.get(current, []):
            if neighbor in distance or neighbor not in present:
                continue
            distance[neighbor] = distance[current] + 1
            parent[neighbor] = (current, relation)
            queue.append(neighbor)
    return distance, parent


def _path_to(
    entity_id: UUID,
    parent: dict[UUID, tuple[UUID, str]],
    entities: Mapping[UUID, GraphEntity],
) -> list[ImpactPathStep]:
    steps: list[ImpactPathStep] = []
    current = entity_id
    while current in parent:
        step_from, relation = parent[current]
        row = entities[step_from]
        steps.append(
            ImpactPathStep(
                entity=ImpactEntity(project_id=str(row.project_id), entity_id=str(row.id)),
                domain=row.domain,
                label=row.name,
                relation=relation,
            )
        )
        current = step_from
    steps.reverse()
    return steps


async def compute_impact(
    session: AsyncSession,
    project_id: UUID,
    *,
    focus_id: UUID,
    change: list[DiffRow],
    provider: ConsequenceProvider,
    depth: int = 2,
    max_entities: int = DEFAULT_MAX_ENTITIES,
    computed_at: str | None = None,
) -> ImpactResult:
    """One impact analysis, ready for the CTR-04 widget. Read-only; never commits."""
    focus = await _load_focus(session, project_id, focus_id)
    siblings = await _canonical_siblings(session, project_id, focus)
    neighborhood = await load_neighborhood(
        session,
        project_id,
        roots=[focus.id, *siblings],
        depth=depth,
        max_entities=max_entities,
    )
    entities = {row.id: row for row in neighborhood.entities}
    # The roots load is capped and ordered by (created_at, id); with more
    # canonical siblings than max_entities the FOCUS itself can be truncated
    # out — but it anchors every path, and the engine already holds its row.
    entities.setdefault(focus.id, focus)
    distance, parent = _bfs(neighborhood, focus.id, siblings)
    consequences = await provider(neighborhood, focus.id)

    nodes: list[ImpactNode] = []
    for entity_id, found in consequences.items():
        row = entities.get(entity_id)
        # Unreached, cross-project (the traversal never loads those), internal
        # fingerprint rows, and the focus row itself are not impact nodes.
        if (
            row is None
            or not found
            or entity_id not in distance
            or entity_id == focus.id
            or row.origin == _FINGERPRINT_ORIGIN
        ):
            continue
        nodes.append(
            ImpactNode(
                entity=ImpactEntity(project_id=str(row.project_id), entity_id=str(row.id)),
                label=row.name,
                domain=row.domain,
                severity=worst_severity([c.severity for c in found]),
                distance=distance[entity_id],
                path=_path_to(entity_id, parent, entities),
                consequences=list(found),
            )
        )
    nodes.sort(key=lambda n: (-severity_rank(n.severity), n.distance, n.label))

    return ImpactResult(
        focus=ImpactFocus(
            entity=ImpactEntity(project_id=str(focus.project_id), entity_id=str(focus.id)),
            domain=focus.domain,
            label=focus.name,
        ),
        change=change,
        computed_at=computed_at or datetime.now(UTC).isoformat(),
        truncated=neighborhood.truncated,
        nodes=nodes,
    )
