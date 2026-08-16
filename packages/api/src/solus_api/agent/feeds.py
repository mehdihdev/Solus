"""Real `SolSystems` (SOLUS-SYS-04) — the W0-07 feeds assembled from the real subsystems.

One adapter class, zero new query paths: graph context is `load_neighborhood` +
`to_graph_context` (the ONE traversal, shared with the focus engine), telemetry
is `TelemetryPlumbing` (already Protocol-shaped), retrieval and the error
flywheel are SYS-02's `rag/retrieval.py`. Tenant scoping therefore stays IN the
delegated queries — nothing here fetches broadly and filters afterwards, and
unscoped tenant retrieval is refused by the retrieval layer itself.

Empty is honest: a project with no graph rows, no buffered telemetry, or no
recorded errors yields empty results — never invented content. That is the
entire point of this module replacing the canned test double in production wiring.

Session discipline mirrors `DbEntityResolver`: hold a SESSIONMAKER and open a
short-lived session per call — the SOL SSE generator streams after the request
session closes, so a request-scoped session must never be captured here.
`__init__` does zero I/O (the app is constructible without a database).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from solus_api.agent.interfaces import (
    ContextBudget,
    ErrorHit,
    GraphContext,
    GraphScope,
    RagHit,
    RetrievalFilter,
    TelemetrySummaryView,
    TelemetryWindow,
)
from solus_api.agent.perf import SemanticCache
from solus_api.graph.neighborhood import (
    DEFAULT_MAX_ENTITIES,
    MAX_DEPTH,
    load_neighborhood,
    to_graph_context,
)
from solus_api.rag import retrieval

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.graph.telemetry import TelemetryPlumbing
    from solus_api.rag.retrieval import EmbedFn


class DbSolSystems:
    """The real `SolSystems` — structural conformance to the Protocol, like the
    fake it replaces (pinned by the typed assignment in the conformance tests).

    `embed` is optional and best-effort: keyless environments degrade to the
    retrieval layer's full-text path rather than failing (SYS-02 design)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        telemetry: TelemetryPlumbing,
        embed: EmbedFn | None = None,
        cache: SemanticCache | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._telemetry = telemetry
        self._embed = embed
        self._cache = cache

    async def get_graph_context(
        self,
        project_id: UUID,
        scope: GraphScope,
        budget: ContextBudget | None = None,
    ) -> GraphContext:
        # `GraphScope.degree` is only `ge=0`; the traversal hard-caps at MAX_DEPTH
        # and raises above it. Clamp instead — a deep request must degrade to
        # bounded context, never surface as a masked 500 mid-stream — and report
        # `truncated`, since context beyond the clamp may have been dropped.
        depth = min(scope.degree, MAX_DEPTH)
        clamped = depth < scope.degree
        max_entities = DEFAULT_MAX_ENTITIES
        if budget is not None and budget.max_entities is not None:
            max_entities = budget.max_entities
        # budget.max_tokens is deliberately not handled here: the context packer
        # (agent/context.py) owns token budgeting at pack time.
        async with self._sessionmaker() as session:
            neighborhood = await load_neighborhood(
                session,
                project_id,
                roots=scope.anchor_entity_ids,
                depth=depth,
                entity_types=scope.kinds,
                domains=scope.domains or None,
                max_entities=max_entities,
            )
        ctx = to_graph_context(neighborhood)
        if clamped and not ctx.truncated:
            ctx = ctx.model_copy(update={"truncated": True})
        return ctx

    async def get_telemetry(
        self,
        project_id: UUID,
        window: TelemetryWindow,
    ) -> TelemetrySummaryView:
        return await self._telemetry.get_telemetry(project_id, window)

    async def get_error_history(
        self,
        query: str,
        k: int,
        filter: RetrievalFilter | None = None,
    ) -> list[ErrorHit]:
        async def fetch(session: AsyncSession, embed: EmbedFn | None) -> list[ErrorHit]:
            return await retrieval.get_error_history(
                session, query=query, k=k, filter=filter, embed=embed
            )

        return await self._cached_retrieval("error", query, k, filter, fetch)

    async def rag_query(
        self,
        text: str,
        k: int,
        filter: RetrievalFilter | None = None,
    ) -> list[RagHit]:
        async def fetch(session: AsyncSession, embed: EmbedFn | None) -> list[RagHit]:
            return await retrieval.rag_query(session, text=text, k=k, filter=filter, embed=embed)

        return await self._cached_retrieval("rag", text, k, filter, fetch)

    def cache_stats(self) -> dict[str, float]:
        """Measured hit-rate (SYS-05 acceptance) — empty when no cache is wired."""
        return self._cache.stats() if self._cache is not None else {}

    async def _cached_retrieval[T](
        self,
        kind: str,
        query_text: str,
        k: int,
        filter: RetrievalFilter | None,
        fetch: Callable[[AsyncSession, EmbedFn | None], Awaitable[list[T]]],
    ) -> list[T]:
        """The SYS-05 semantic cache seam. Exact hits (normalized text) are checked
        FIRST and cost zero embed calls; only an exact miss embeds the query — once —
        and that same vector drives both the semantic lookup and (via a fixed-embed
        closure) the ANN retrieval. Unscoped or cacheless calls go straight through
        (the retrieval layer's own refusal of unscoped tenant reads stays the
        authority). Empty results are never cached: a just-recorded solution must be
        findable immediately. Cached lists are copied in AND out — no caller ever
        holds the cache's own object (SEC L1)."""
        if self._cache is None or filter is None or filter.project_id is None:
            async with self._sessionmaker() as session:
                return await fetch(session, self._embed)

        # One BUCKET per (kind, k, filter shape): a semantic near-duplicate may only
        # substitute for a query asking the same question the same way — a k=20
        # result must never serve a k=3 ask, nor an unfiltered result a domain-
        # filtered one (SEC H1). The bucket rides in the cache's kind dimension, so
        # both the exact AND the similarity path are bound by it.
        project_id = filter.project_id
        bucket = (
            f"{kind}|{k}|{','.join(sorted(filter.source_types or []))}"
            f"|{','.join(sorted(filter.domains or []))}"
        )
        cached = self._cache.lookup(project_id, bucket, query_text, None)
        if cached is not None:
            exact_hits: list[T] = list(cached)
            return exact_hits
        vector = await self._embed_once(query_text)
        if vector is not None:
            cached = self._cache.lookup(project_id, bucket, query_text, vector)
            if cached is not None:
                near_hits: list[T] = list(cached)
                return near_hits

        async def fixed_embed(_: str) -> list[float] | None:
            # Reuse the keying vector — a None (keyless/no-signal) rides through to
            # the retrieval layer's own full-text degradation rather than paying a
            # second embed call.
            return vector

        async with self._sessionmaker() as session:
            fetched = await fetch(session, fixed_embed)
        if fetched:
            self._cache.store(project_id, bucket, query_text, vector, list(fetched))
        return fetched

    async def _embed_once(self, text: str) -> list[float] | None:
        if self._embed is None:
            return None
        try:
            return await self._embed(text)
        except Exception:  # noqa: BLE001 — EmbedFn is best-effort no-signal by contract
            return None

    async def record_error_solution(
        self,
        project_id: UUID,
        error_text: str,
        solution_text: str,
        domain: str,
        attrs: dict[str, Any] | None = None,
    ) -> UUID:
        async with self._sessionmaker() as session:
            row_id = await retrieval.record_error_solution(
                session,
                project_id=project_id,
                error_text=error_text,
                solution_text=solution_text,
                domain=domain,
                attrs=attrs,
                embed=self._embed,
            )
            # The retrieval layer flushes and leaves the transaction to its
            # caller; here the transaction is OURS — the flywheel write must
            # survive this call, so commit before the session closes.
            await session.commit()
        return row_id
