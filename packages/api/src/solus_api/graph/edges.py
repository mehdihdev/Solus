"""The one `graph_edge` writer (SOLUSDEV-320, docs/api/relations.md §2).

Every non-connector edge is written through `write_edge`; `connectors/runtime.py` is the
only other constructor (`tests/test_edge_writer_ratchet.py`). `annotate_edge` sets the one
key a checker run caches on an existing edge (`checker_results`), or raises it to 1.0 on
evidence from outside the graph (`confirmed_by`), re-reading the row under a row lock first.
Flushes, never commits, takes no other lock: callers hold `lock_project` where they do today.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from solus_contracts.relations import (
    CANDIDATE_THRESHOLD,
    EdgeEvidence,
    EdgeOrigin,
    EvidenceKind,
    MatrixCell,
    RelationType,
    evidence_key,
    normalize_domain_pair,
)
from solus_contracts.relations import matrix_cell as _matrix_cell
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.models import GraphEdge, GraphEntity, utcnow

logger = logging.getLogger("solus.graph.edges")

MAX_EVIDENCE = 50


def is_candidate(edge: GraphEdge) -> bool:
    return edge.origin == EdgeOrigin.INFERRED and edge.confidence < CANDIDATE_THRESHOLD


def retire_edge(edge: GraphEdge) -> None:
    """Soft delete: live readers filter `deleted_at IS NULL`; the row stays as history."""
    edge.deleted_at = utcnow()


def projected_copy(edge: GraphEdge, **overrides: Any) -> GraphEdge:
    """A transient copy for read projection (never added to a session)."""
    values = {column.key: getattr(edge, column.key) for column in GraphEdge.__table__.columns}
    return GraphEdge(**{**values, **overrides})


def _merge_evidence(existing: list[Any], new: list[EdgeEvidence]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in [*existing, *(e.model_dump(mode="json") for e in new)]:
        key = (str(item["kind"]), str(item["ref"]))
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged[-MAX_EVIDENCE:]  # the newest survive the cap


async def _endpoint(session: AsyncSession, project_id: UUID, entity_id: UUID) -> GraphEntity:
    row = await session.get(GraphEntity, entity_id)
    if row is None or row.project_id != project_id or row.deleted_at is not None:
        raise APIError(404, "not_found", "Edge endpoint not found in this project")
    return row


async def _keyed_row(
    session: AsyncSession,
    project_id: UUID,
    src_id: UUID,
    dst_id: UUID,
    relation_type: str,
    source_id: UUID | None,
    *,
    declined: bool = False,
) -> GraphEdge | None:
    """The live row on the natural key, or (`declined=True`) its latest declined tombstone."""
    stmt = select(GraphEdge).where(
        GraphEdge.project_id == project_id,
        GraphEdge.src_id == src_id,
        GraphEdge.dst_id == dst_id,
        GraphEdge.relation_type == relation_type,
        GraphEdge.source_id.is_(None) if source_id is None else GraphEdge.source_id == source_id,
    )
    if declined:
        stmt = stmt.where(
            GraphEdge.deleted_at.is_not(None), GraphEdge.attrs.has_key("declined_by")
        ).order_by(GraphEdge.deleted_at.desc())
    else:
        stmt = stmt.where(GraphEdge.deleted_at.is_(None)).order_by(
            GraphEdge.created_at, GraphEdge.id
        )
    row: GraphEdge | None = await session.scalar(stmt.limit(1))
    return row


async def _existing(
    session: AsyncSession,
    project_id: UUID,
    src_id: UUID,
    dst_id: UUID,
    relation: str,
    source_id: UUID | None,
    edge_id: UUID | None,
    managed_by: str | None,
) -> GraphEdge | None:
    """The row an upsert lands on: by explicit identity (tombstones included) or live key."""
    if edge_id is None:
        return await _keyed_row(session, project_id, src_id, dst_id, relation, source_id)
    edge = await session.get(GraphEdge, edge_id)
    if edge is not None and (
        edge.project_id != project_id or edge.attrs.get("managed_by") != managed_by
    ):
        raise APIError(409, "topology_conflict", "Relation identity conflicts")
    return edge


async def write_edge(
    session: AsyncSession,
    *,
    project_id: UUID,
    src_id: UUID,
    dst_id: UUID,
    relation_type: str,
    origin: str,
    confidence: float,
    evidence: list[EdgeEvidence],
    created_by: UUID | None,
    matrix_cell: MatrixCell | None = None,
    attrs: dict[str, Any] | None = None,
    source_id: UUID | None = None,
    edge_id: UUID | None = None,
    managed_by: str | None = None,
) -> GraphEdge:
    """Upsert on the live `(project, src, dst, relation_type, source_id)` key, or on `edge_id`.

    Evidence merges deduped on `(kind, ref)`; `confidence = max(existing, new)` unless the
    write is manual; a manual edge is never downgraded; `domain_pair` is always derived from
    the endpoints. A declined tombstone with the same evidence is not re-proposed.

    An `edge_id` write is a managed identity (topology, host, bindings): the caller states
    the whole desired `attrs` and evidence, so both REPLACE instead of merging and stale
    provenance never outlives the config that produced it. Only `created_by` carries over.
    """
    try:
        relation = RelationType(relation_type)
        origin_value = EdgeOrigin(origin)
    except ValueError as exc:
        raise APIError(422, "validation_error", str(exc)) from exc
    if not 0.0 <= confidence <= 1.0:
        raise APIError(422, "validation_error", "confidence must be within 0..1")
    src = await _endpoint(session, project_id, src_id)
    dst = await _endpoint(session, project_id, dst_id)
    pair = normalize_domain_pair(src.domain.value, dst.domain.value)
    cell = matrix_cell or _matrix_cell(src.domain.value, dst.domain.value)

    edge = await _existing(
        session, project_id, src_id, dst_id, relation, source_id, edge_id, managed_by
    )
    if edge is None and edge_id is None and origin_value is EdgeOrigin.INFERRED:
        declined = await _keyed_row(
            session, project_id, src_id, dst_id, relation, source_id, declined=True
        )
        if declined is not None and evidence_key(
            declined.attrs.get("evidence", [])
        ) == evidence_key(e.model_dump() for e in evidence):
            logger.info(
                "edge declined, not re-proposed project=%s edge=%s", project_id, declined.id
            )
            return declined

    prior: dict[str, Any] = edge.attrs if edge is not None and edge_id is None else {}
    merged: dict[str, Any] = {**prior, **(attrs or {})}
    merged["evidence"] = _merge_evidence(prior.get("evidence", []), evidence)
    if cell is None:
        merged.pop("matrix_cell", None)
    else:
        merged["matrix_cell"] = cell.value
    if edge is None:
        merged["created_by"] = str(created_by) if created_by else None
        edge = GraphEdge(
            id=edge_id,
            project_id=project_id,
            source_id=source_id,
            src_id=src_id,
            dst_id=dst_id,
            relation_type=relation.value,
            domain_pair=pair,
            confidence=confidence,
            origin=origin_value.value,
            attrs=merged,
        )
        session.add(edge)
    else:
        merged.setdefault("created_by", edge.attrs.get("created_by"))
        if origin_value is EdgeOrigin.MANUAL:
            edge.confidence = confidence
        else:
            edge.confidence = max(edge.confidence, confidence)
        if edge.origin != EdgeOrigin.MANUAL:
            edge.origin = origin_value.value
        edge.domain_pair = pair
        edge.attrs = merged
        edge.deleted_at = None
    await session.flush()
    return edge


async def _live_edge(
    session: AsyncSession,
    project_id: UUID,
    edge_id: UUID,
    *,
    candidate: bool = False,
    fresh: bool = False,
) -> GraphEdge:
    """A live edge of this project; relations.md §5: foreign, deleted or (when the caller
    needs one) non-candidate edges are all 404, so a route can pass its path id straight in.
    `fresh` re-reads the row under a row lock, whatever copy the session already holds, and never
    waits for one: `SKIP LOCKED` reads a row another transaction holds as absent (R68)."""
    edge = await session.get(
        GraphEdge,
        edge_id,
        populate_existing=fresh,
        with_for_update={"skip_locked": True} if fresh else None,
    )
    if (
        edge is None
        or edge.project_id != project_id
        or edge.deleted_at is not None
        or (candidate and not is_candidate(edge))
    ):
        raise APIError(404, "not_found", "Edge not found")
    return edge


async def confirm_edge(
    session: AsyncSession, project_id: UUID, edge_id: UUID, user_id: UUID
) -> GraphEdge:
    edge = await _live_edge(session, project_id, edge_id, candidate=True)
    stamp = utcnow().isoformat()
    edge.origin = EdgeOrigin.MANUAL.value
    edge.confidence = 1.0
    edge.attrs = {
        **edge.attrs,
        "evidence": _merge_evidence(
            edge.attrs.get("evidence", []),
            [EdgeEvidence(kind=EvidenceKind.USER_CONFIRMED, ref=str(user_id))],
        ),
        "confirmed_by": str(user_id),
        "confirmed_at": stamp,
    }
    await session.flush()
    return edge


async def decline_edge(
    session: AsyncSession, project_id: UUID, edge_id: UUID, user_id: UUID, reason: str | None
) -> GraphEdge:
    edge = await _live_edge(session, project_id, edge_id, candidate=True)
    now = utcnow()
    edge.deleted_at = now
    edge.attrs = {
        **edge.attrs,
        "declined_by": str(user_id),
        "declined_reason": reason,
        "declined_at": now.isoformat(),
    }
    await session.flush()
    return edge


async def supersede_edge(
    session: AsyncSession, project_id: UUID, old_id: UUID, new_id: UUID
) -> None:
    edge = await _live_edge(session, project_id, old_id)
    replacement = await _live_edge(session, project_id, new_id)
    retire_edge(edge)
    edge.attrs = {**edge.attrs, "superseded_by": str(replacement.id)}
    await session.flush()


async def annotate_edge(
    session: AsyncSession,
    project_id: UUID,
    edge_id: UUID,
    *,
    checker_results: list[dict[str, Any]] | None = None,
    confirmed_by: EdgeEvidence | None = None,
) -> GraphEdge | None:
    """Cache a matrix run's results on a live edge of this project: `attrs.checker_results` is
    reassigned to the items, each validated as a `CheckerResult`, and nothing else on the row
    changes. `confirmed_by` (R131) is evidence from outside the graph that the edge holds (a live
    `ros2` listing): it raises the edge to 1.0 and merges into its evidence; origin stays.
    Callers hold `lock_project`; under it the row is re-read fresh, under a row lock, so
    attrs another writer committed since the caller read the edge (a sync's nets, an acceptance's
    `commanded` fact) are kept, never written back from the caller's stale copy.

    It never WAITS for that lock (R68): a sync locks edge rows before it takes the project lock,
    so a caller holding the project lock that waited could deadlock with it. A row another
    transaction holds is not written, and None says so; the caller judges it again later.
    Foreign, deleted and unknown edges are 404, so a run never revives a tombstone."""
    from solus_api.checkers.checker_results import CheckerResult  # checkers import this module

    updates: dict[str, Any] = {}
    if checker_results is not None:
        updates["checker_results"] = [
            CheckerResult.model_validate(item).model_dump(mode="json") for item in checker_results
        ]
    try:
        edge = await _live_edge(session, project_id, edge_id, fresh=True)
    except APIError:  # SKIP LOCKED reads a row another transaction holds as absent: is it live?
        held = await session.get(GraphEdge, edge_id, populate_existing=True)
        if held is None or held.project_id != project_id or held.deleted_at is not None:
            raise
        return None
    if confirmed_by is not None:
        updates["evidence"] = _merge_evidence(edge.attrs.get("evidence", []), [confirmed_by])
        edge.confidence = 1.0
    edge.attrs = {**edge.attrs, **updates}
    await session.flush()
    return edge


async def candidates(
    session: AsyncSession,
    project_id: UUID,
    *,
    relation_type: str | None = None,
    subject: UUID | None = None,
    limit: int = 200,
) -> list[GraphEdge]:
    """Live inferred edges below the candidate threshold, under the bound read scope."""
    from solus_api.graph.read_scope import current_scope  # read_scope imports projected_copy

    stmt = select(GraphEdge).where(
        current_scope(project_id).edge_predicate(),
        GraphEdge.deleted_at.is_(None),
        GraphEdge.origin == EdgeOrigin.INFERRED.value,
        GraphEdge.confidence < CANDIDATE_THRESHOLD,
    )
    if relation_type is not None:
        stmt = stmt.where(GraphEdge.relation_type == relation_type)
    if subject is not None:
        stmt = stmt.where(or_(GraphEdge.src_id == subject, GraphEdge.dst_id == subject))
    stmt = stmt.order_by(GraphEdge.confidence.desc(), GraphEdge.created_at, GraphEdge.id).limit(
        limit
    )
    return list((await session.scalars(stmt)).all())
