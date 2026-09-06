"""Corpus retrieval (ADR-036 rule 4): filter in SQL, then rank.

Domain, topic, and applicability are WHERE clauses, never post-filters — a
trace-width question restricted to `electrical` cannot load a machining chunk
under any plan the database picks. Only `status = active` rows serve. Ranking
is ANN over the chunk embedding when a query vector exists and OR-semantics
English full-text otherwise (SYS-02's keyless degradation, same shapes).

Precision over recall: a low-confidence chunk is served with `low_confidence`
set so the prompt can say so — it is never dropped (a gap is honest) and never
promoted (a flag is not a score). The corpus is global: no `project_id` exists
to scope by, and none is accepted.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Final

from sqlalchemy import ColumnElement, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.interfaces import RagHit
from solus_api.corpus.enums import (
    APPLICABILITY_VALUES,
    ApplicabilityKey,
    CorpusDomain,
    Status,
    Topic,
)
from solus_api.corpus.schema import CorpusChunkRow
from solus_api.fingerprint.contract import SourceRef

logger = logging.getLogger("solus.corpus.retrieval")

type EmbedFn = Callable[[str], Awaitable[list[float] | None]]

CORPUS_CONNECTOR: Final = "corpus"
#: Below this the chunk is served WITH a flag (schema §6, C2 traps).
LOW_CONFIDENCE: Final = 0.6
MAX_K: Final = 20
_MAX_QUERY_TERMS: Final = 32
_TERM_RE: Final = re.compile(r"[a-z0-9]+")
_TS_CONFIG: Final = "english"


class CorpusHit(RagHit):
    """A `RagHit` that carries what the prompt renders and what SOL cites."""

    chunk_id: str
    title: str
    domain: str
    topic: str
    kind: str
    audience: str
    confidence: float
    attribution: str
    low_confidence: bool


def external_ref(chunk_id: str) -> str:
    """`corpus:electrical/decoupling/loop-area` → `electrical/decoupling/loop-area`,
    the `[corpus:<ref>]` citation SOL is asked to repeat."""
    return chunk_id.removeprefix("corpus:")


def _enum_values[E](kind: type[E], raw: Sequence[str] | None) -> list[E] | None:
    """None → no filter. A non-empty list with no valid member → [] (nothing),
    never everything: an unknown filter must not widen the search."""
    if raw is None:
        return None
    values: list[E] = []
    for item in raw:
        try:
            values.append(kind(item))  # type: ignore[call-arg]
        except ValueError:
            logger.debug("ignoring unknown corpus filter value %.32r", item)
    return values


def _scope(
    domains: list[CorpusDomain] | None,
    topics: list[Topic] | None,
    applicability: Mapping[str, str] | None,
) -> list[ColumnElement[bool]]:
    scope: list[ColumnElement[bool]] = [CorpusChunkRow.status == Status.ACTIVE]
    if domains is not None:
        scope.append(CorpusChunkRow.domain.in_(domains) if domains else literal(False))
    if topics is not None:
        scope.append(CorpusChunkRow.topic.in_(topics) if topics else literal(False))
    for raw_key, value in (applicability or {}).items():
        try:
            key = ApplicabilityKey(raw_key)
        except ValueError:
            continue  # an unknown key filters nothing (SCOPE §6: closed keys)
        others = [f"{key.value}={other}" for other in APPLICABILITY_VALUES[key] if other != value]
        # A chunk applies unless it is tagged with a DIFFERENT value for this key.
        scope.append(~CorpusChunkRow.applicability.overlap(others))
    return scope


def _or_query(text: str) -> str | None:
    terms = list(dict.fromkeys(_TERM_RE.findall(text.lower())))[:_MAX_QUERY_TERMS]
    return " | ".join(terms) if terms else None


_COLUMNS: Final = (
    CorpusChunkRow.id,
    CorpusChunkRow.title,
    CorpusChunkRow.body,
    CorpusChunkRow.domain,
    CorpusChunkRow.topic,
    CorpusChunkRow.kind,
    CorpusChunkRow.audience,
    CorpusChunkRow.confidence,
    CorpusChunkRow.attribution,
)


def _hit(row: Any, score: float) -> CorpusHit:
    return CorpusHit(
        chunk=f"{row.title}\n\n{row.body}",
        source_ref=SourceRef(source_connector=CORPUS_CONNECTOR, external_ref=external_ref(row.id)),
        score=score,
        chunk_id=row.id,
        title=row.title,
        domain=row.domain.value,
        topic=row.topic.value,
        kind=row.kind.value,
        audience=row.audience.value,
        confidence=float(row.confidence),
        attribution=row.attribution,
        low_confidence=float(row.confidence) < LOW_CONFIDENCE,
    )


async def corpus_hits(
    session: AsyncSession,
    *,
    text: str,
    k: int,
    domains: Sequence[str] | None = None,
    topics: Sequence[str] | None = None,
    applicability: Mapping[str, str] | None = None,
    vector: list[float] | None = None,
    embed: EmbedFn | None = None,
) -> list[CorpusHit]:
    """Top-`k` active chunks for `text` within the filters. `vector` is a
    precomputed query embedding (the SYS-05 cache keys on it); `embed` is used
    only when `vector` is None. Either absent → full-text path."""
    k = max(1, min(k, MAX_K))
    scope = _scope(_enum_values(CorpusDomain, domains), _enum_values(Topic, topics), applicability)
    if vector is None and embed is not None:
        try:
            vector = await embed(text)
        except Exception:  # noqa: BLE001 — best-effort by contract
            vector = None
    if vector is not None:
        distance = CorpusChunkRow.embedding.cosine_distance(vector)
        stmt = (
            select(*_COLUMNS, distance.label("distance"))
            .where(*scope, CorpusChunkRow.embedding.is_not(None))
            .order_by(distance, CorpusChunkRow.id)
            .limit(k)
        )
        return [_hit(row, 1.0 - float(row.distance)) for row in (await session.execute(stmt))]
    query = _or_query(text)
    if query is None:
        return []
    document = func.to_tsvector(
        _TS_CONFIG, CorpusChunkRow.title + literal(" ") + CorpusChunkRow.body
    )
    tsquery = func.to_tsquery(_TS_CONFIG, query)
    rank = func.ts_rank_cd(document, tsquery)
    stmt = (
        select(*_COLUMNS, rank.label("rank"))
        .where(*scope, document.op("@@")(tsquery))
        .order_by(rank.desc(), CorpusChunkRow.id)
        .limit(k)
    )
    return [_hit(row, float(row.rank)) for row in (await session.execute(stmt))]
