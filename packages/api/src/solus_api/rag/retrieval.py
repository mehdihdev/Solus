"""RAG retrieval over the pgvector store (SYS-02, W0-07 rag primitive).

Implements the retrieval half of `SolSystems.rag_query` / `get_error_history`
plus the flywheel write-back `record_error_solution` (sol-interface.md §5) as
pure query functions — the future real-systems class delegates to these with
the request's session and embedder.

TENANT SCOPING IS ENFORCED IN THE QUERY (CLAUDE.md §7, the highest-severity
invariant): `project_id` lands in the WHERE clause of every statement, so
isolation holds under ANY plan the database picks — an ANN scan that retrieved
across projects and filtered afterwards would be a cross-tenant leak with a
latency problem attached. Both tenant source types (`entity`, `error`) REQUIRE
`filter.project_id`; an unscoped tenant query is rejected loudly, never served.
# ponytail: no global corpora exist yet — when shared datasheets land, relax
# unscoped calls to global-only scope per sol-interface §5.

Keyless degradation: no embedder (or an embedder that fails / returns the wrong
dimension — FP-02's exact tolerance) downgrades to project-scoped Postgres
full-text search over the same rows, same result shapes. Scores are comparable
WITHIN one result list only (ANN: 1 - cosine distance; degraded: ts_rank).
# ponytail: on-the-fly to_tsvector, no GIN — add a generated tsvector column +
# GIN index when per-project row counts make this measurable.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import InstrumentedAttribute

from solus_api.agent.interfaces import ErrorHit, RagHit, RetrievalFilter
from solus_api.fingerprint.contract import SourceRef
from solus_api.models import EMBEDDING_DIM, Domain, ErrorSolution, GraphEntity

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    # Structurally identical to fingerprint.EmbedFn (the one seam); the alias is
    # re-declared rather than imported to keep this module's import graph lean.
    EmbedFn = Callable[[str], Awaitable[list[float] | None]]

logger = logging.getLogger("solus.rag")

_ERROR_CONNECTOR = "error_solution"  # SourceRef provenance for error_solution rows
MAX_K = 100  # ponytail: memory bound on LIMIT; raise when a real consumer needs more
# Cap the flywheel texts AND the on-the-fly tsvector input: PostgreSQL raises
# above ~1MB of tsvector, so one oversized recorded error must never brick a
# project's degraded retrieval (sec review M2).
MAX_ERROR_TEXT_CHARS = 100_000


async def _safe_embed(embed: EmbedFn | None, text: str) -> list[float] | None:
    """FP-02's embedding tolerance: None / raise / wrong dimension / non-finite
    values → no-signal (pgvector rejects NaN/Inf at bind time, which would abort
    the caller's transaction)."""
    if embed is None:
        return None
    try:
        vector = await embed(text)
    except Exception:  # noqa: BLE001 — embedding is best-effort; degrade instead
        logger.warning("query embedding failed; degrading to full-text search", exc_info=True)
        return None
    if vector is None:
        return None
    if len(vector) != EMBEDDING_DIM or not all(math.isfinite(value) for value in vector):
        logger.warning("query embedding malformed — degrading to full-text search")
        return None
    return vector


def _require_project_id(filter: RetrievalFilter | None) -> UUID:
    """SECURITY (§7): `project_id` must be the AUTHENTICATED request's project —
    derived via the centralized authorization layer (`deps.get_project_context` /
    the SOL loop's construction-bound scope), NEVER from user or model input.
    Authorization is deliberately not re-checked here (ad-hoc per-path auth is
    forbidden); this function only refuses unscoped tenant queries."""
    if filter is None or filter.project_id is None:
        raise ValueError(
            "tenant retrieval requires filter.project_id — an unscoped tenant query "
            "is rejected, never served cross-tenant (sol-interface.md §5)"
        )
    return filter.project_id


def _domain_values(filter: RetrievalFilter | None) -> list[Domain] | None:
    if filter is None or filter.domains is None:
        return None
    values: list[Domain] = []
    for raw in filter.domains:
        try:
            values.append(Domain(raw))
        except ValueError:
            logger.debug("ignoring unknown retrieval domain %.32r", raw)
    return values


def _entity_scope(project_id: UUID, domains: list[Domain] | None) -> list[ColumnElement[bool]]:
    scope: list[ColumnElement[bool]] = [
        GraphEntity.project_id == project_id,  # IN-QUERY tenant scoping — the invariant
        GraphEntity.deleted_at.is_(None),
    ]
    if domains is not None:
        scope.append(GraphEntity.domain.in_(domains))
    return scope


def _error_scope(project_id: UUID, domains: list[Domain] | None) -> list[ColumnElement[bool]]:
    scope: list[ColumnElement[bool]] = [
        ErrorSolution.project_id == project_id,
        ErrorSolution.deleted_at.is_(None),
    ]
    if domains is not None:
        scope.append(ErrorSolution.domain.in_(domains))
    return scope


def _text_match(column: InstrumentedAttribute[str], text: str) -> tuple[Any, ColumnElement[float]]:
    """Project-scoped full-text predicate + rank for the degraded path.
    `plainto_tsquery` treats the query as plain words — safe for arbitrary input.
    `left()` bounds the tsvector input so one oversized pre-existing row can never
    abort the whole query (PostgreSQL rejects >~1MB tsvectors)."""
    document = func.to_tsvector("simple", func.left(column, MAX_ERROR_TEXT_CHARS))
    query = func.plainto_tsquery("simple", text)
    return document.op("@@")(query), func.ts_rank(document, query)


async def _entity_hits(
    session: AsyncSession,
    *,
    text: str,
    k: int,
    project_id: UUID,
    domains: list[Domain] | None,
    vector: list[float] | None,
) -> list[RagHit]:
    # Column selection, not entities: nothing downstream reads the 1536-float
    # embedding column, so it never leaves the database.
    scope = _entity_scope(project_id, domains)
    if vector is not None:
        distance = GraphEntity.embedding.cosine_distance(vector)
        stmt = (
            select(GraphEntity.id, GraphEntity.name, distance.label("distance"))
            .where(*scope, GraphEntity.embedding.is_not(None))
            .order_by(distance)
            .limit(k)
        )
        return [
            RagHit(
                chunk=name,
                source_ref=SourceRef(graph_entity_id=entity_id),
                score=1.0 - float(dist),
            )
            for entity_id, name, dist in (await session.execute(stmt)).all()
        ]
    predicate, rank = _text_match(GraphEntity.name, text)
    stmt = (
        select(GraphEntity.id, GraphEntity.name, rank.label("score"))
        .where(*scope, predicate)
        .order_by(rank.desc())
        .limit(k)
    )
    return [
        RagHit(chunk=name, source_ref=SourceRef(graph_entity_id=entity_id), score=float(score))
        for entity_id, name, score in (await session.execute(stmt)).all()
    ]


async def _error_hits(
    session: AsyncSession,
    *,
    text: str,
    k: int,
    project_id: UUID,
    domains: list[Domain] | None,
    vector: list[float] | None,
) -> list[ErrorHit]:
    scope = _error_scope(project_id, domains)
    columns = (ErrorSolution.id, ErrorSolution.error_text, ErrorSolution.solution_text)
    if vector is not None:
        distance = ErrorSolution.embedding.cosine_distance(vector)
        stmt = (
            select(*columns, distance.label("distance"))
            .where(*scope, ErrorSolution.embedding.is_not(None))
            .order_by(distance)
            .limit(k)
        )
        return [
            ErrorHit(
                chunk=error_text,
                solution_text=solution_text,
                source_ref=SourceRef(source_connector=_ERROR_CONNECTOR, external_ref=str(row_id)),
                score=1.0 - float(dist),
            )
            for row_id, error_text, solution_text, dist in (await session.execute(stmt)).all()
        ]
    predicate, rank = _text_match(ErrorSolution.error_text, text)
    stmt = (
        select(*columns, rank.label("score"))
        .where(*scope, predicate)
        .order_by(rank.desc())
        .limit(k)
    )
    return [
        ErrorHit(
            chunk=error_text,
            solution_text=solution_text,
            source_ref=SourceRef(source_connector=_ERROR_CONNECTOR, external_ref=str(row_id)),
            score=float(score),
        )
        for row_id, error_text, solution_text, score in (await session.execute(stmt)).all()
    ]


async def rag_query(
    session: AsyncSession,
    *,
    text: str,
    k: int,
    filter: RetrievalFilter | None = None,
    embed: EmbedFn | None = None,
) -> list[RagHit]:
    """Semantic retrieval over the pgvector store — top-`k`, project-scoped in-query.

    `filter.source_types` selects the corpora (`entity` → graph_entity, `error` →
    error_solution; None → both, merged by score); unknown types are ignored with
    a debug log. ANN when a query embedding is available, project-scoped
    full-text otherwise (keyless degradation — same shapes, never an exception).
    """
    project_id = _require_project_id(filter)
    k = max(1, min(k, MAX_K))  # LIMIT is caller-influenced: bound it (sec review M4)
    domains = _domain_values(filter)
    requested = filter.source_types if filter is not None and filter.source_types else None
    vector = await _safe_embed(embed, text)

    hits: list[RagHit] = []
    known = {"entity", "error"}
    types = requested if requested is not None else sorted(known)
    for unknown in set(types) - known:
        logger.debug("ignoring unknown retrieval source_type %.32r", unknown)
    if "entity" in types:
        hits.extend(
            await _entity_hits(
                session, text=text, k=k, project_id=project_id, domains=domains, vector=vector
            )
        )
    if "error" in types:
        hits.extend(
            await _error_hits(
                session, text=text, k=k, project_id=project_id, domains=domains, vector=vector
            )
        )
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:k]


async def get_error_history(
    session: AsyncSession,
    *,
    query: str,
    k: int,
    filter: RetrievalFilter | None = None,
    embed: EmbedFn | None = None,
) -> list[ErrorHit]:
    """Error-scoped retrieval ("recall how we fixed this before") — top-`k`,
    project-scoped in-query, with the same ANN/full-text degradation as
    `rag_query`."""
    project_id = _require_project_id(filter)
    k = max(1, min(k, MAX_K))  # LIMIT is caller-influenced: bound it (sec review M4)
    domains = _domain_values(filter)
    vector = await _safe_embed(embed, query)
    return await _error_hits(
        session, text=query, k=k, project_id=project_id, domains=domains, vector=vector
    )


async def record_error_solution(
    session: AsyncSession,
    *,
    project_id: UUID,
    error_text: str,
    solution_text: str,
    domain: str,
    attrs: dict[str, Any] | None = None,
    embed: EmbedFn | None = None,
) -> UUID:
    """THE FLYWHEEL WRITE-BACK (W0-07): persist a solved error so future retrieval
    recalls it. Embedding is best-effort (keyless → NULL, nothing raises); the
    row is flushed, not committed — the caller owns the transaction. Texts are
    truncated to `MAX_ERROR_TEXT_CHARS` — model-generated blobs are untrusted
    input and an oversized row must never poison the retrieval path (§7).
    SECURITY: `project_id` must come from the authenticated request's authorized
    context (see `_require_project_id`), never from user or model input."""
    error_text = error_text[:MAX_ERROR_TEXT_CHARS]
    solution_text = solution_text[:MAX_ERROR_TEXT_CHARS]
    row = ErrorSolution(
        project_id=project_id,
        error_text=error_text,
        solution_text=solution_text,
        domain=Domain(domain),  # boundary validation: unknown domain raises ValueError
        attrs=attrs or {},
        embedding=await _safe_embed(embed, f"{error_text}\n{solution_text}"),
    )
    session.add(row)
    await session.flush()
    return row.id
