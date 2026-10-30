"""One index for ⌘K, `@` and SOL (SOLUSDEV-320 T7; docs/api/search.md §2).

One SQL statement per group over the generated `search_text` / `search_tsv` columns:
trigram `%` on the name (threshold 0.3, set per transaction so the GIN trigram index applies)
or a `simple` full-text match or an exact `external_ref`. Ranking is the §2 order — name
matches, then text matches, then exact ref matches — and inside a tier score =
greatest(similarity, ts_rank), 1.0 for an exact ref/name match. Project-scoped through the
caller's graph read scope. Zero external calls by construction.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Float, and_, case, cast, func, literal, or_, select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.graph.read_scope import current_scope
from solus_api.models import Domain, GraphEntity, SolusEntry, SolusSection

#: pg_trgm's own default; typed MPNs against hyphenated names land around 0.5.
NAME_SIMILARITY: float = 0.3
#: Per group, for the route; a caller may ask for one more row to learn `truncated`.
MAX_LIMIT: int = 50
SNIPPET_CHARS: int = 160
CODE_KINDS: frozenset[str] = frozenset({"code_file", "code_module"})

Why = Literal["name_match", "text_match", "ref_match"]


class EntityHit(BaseModel):
    id: uuid.UUID
    kind: str
    domain: str
    name: str
    snippet: str
    score: float
    why: Why


class SolusHit(BaseModel):
    id: uuid.UUID
    entity_id: uuid.UUID | None
    section: str
    subsection: str | None
    kind: str
    name: str
    snippet: str
    score: float
    why: Why


class SearchResponse(BaseModel):
    entities: list[EntityHit] = Field(default_factory=list)
    solus: list[SolusHit] = Field(default_factory=list)
    truncated: bool = False


async def _set_similarity_threshold(session: AsyncSession) -> None:
    """Transaction-local, so `column % q` (the indexable form) means `similarity >= 0.3`."""
    await session.execute(sql_text(f"SET LOCAL pg_trgm.similarity_threshold = {NAME_SIMILARITY}"))


def _window(search_text: str | None, q: str) -> str:
    """A ≤160-char window of the indexed text around the first query word."""
    text = search_text or ""
    word = q.split()[0] if q.split() else q
    at = text.lower().find(word.lower())
    start = max(0, at - SNIPPET_CHARS // 4) if at >= 0 else 0
    return text[start : start + SNIPPET_CHARS]


async def search_entities(
    session: AsyncSession,
    project_id: uuid.UUID,
    q: str,
    *,
    kinds: list[str] | None = None,
    domains: list[Domain] | None = None,
    limit: int = 20,
) -> list[EntityHit]:
    limit = max(1, min(limit, MAX_LIMIT + 1))
    await _set_similarity_threshold(session)
    query = func.plainto_tsquery("simple", q)
    similarity = func.similarity(GraphEntity.name, q)
    name_match = or_(GraphEntity.name.op("%")(q), GraphEntity.name == q)
    rank = cast(func.ts_rank(GraphEntity.search_tsv, query), Float)
    ref_match = GraphEntity.external_ref == q
    exact = or_(ref_match, GraphEntity.name == q)
    score = case((exact, literal(1.0)), else_=func.greatest(similarity, rank)).label("score")
    why = case(
        (ref_match, literal("ref_match")),
        (name_match, literal("name_match")),
        else_=literal("text_match"),
    ).label("why")
    tier = case((ref_match, 2), (name_match, 0), else_=1)
    where = [
        current_scope(project_id).entity_predicate(),
        GraphEntity.deleted_at.is_(None),
        GraphEntity.domain != Domain.WORKSPACE,
        or_(name_match, GraphEntity.search_tsv.op("@@")(query), ref_match),
    ]
    if kinds:
        where.append(GraphEntity.kind.in_(kinds))
    if domains:
        where.append(GraphEntity.domain.in_(domains))
    stmt = (
        select(
            GraphEntity.id,
            GraphEntity.kind,
            GraphEntity.domain,
            GraphEntity.name,
            GraphEntity.external_ref,
            GraphEntity.attrs["path"].astext,
            GraphEntity.search_text,
            score,
            why,
        )
        .where(and_(*where))
        .order_by(tier, score.desc(), GraphEntity.name)
        .limit(limit)
    )
    hits: list[EntityHit] = []
    for id_, kind, domain, name, ref, path, text, score_, why_ in await session.execute(stmt):
        if kind in CODE_KINDS and path:
            snippet = path
        elif why_ == "name_match":
            snippet = name
        elif why_ == "ref_match":
            snippet = ref or name
        else:
            snippet = _window(text, q)
        hits.append(
            EntityHit(
                id=id_,
                kind=kind,
                domain=domain.value,
                name=name,
                snippet=snippet,
                score=float(score_),
                why=why_,
            )
        )
    return hits


async def search_solus(
    session: AsyncSession,
    project_id: uuid.UUID,
    q: str,
    *,
    sections: list[SolusSection] | None = None,
    subsections: list[str] | None = None,
    limit: int = 20,
) -> list[SolusHit]:
    limit = max(1, min(limit, MAX_LIMIT + 1))
    await _set_similarity_threshold(session)
    query = func.plainto_tsquery("simple", q)
    # The trigram index is on search_text (text + flattened payload); `text` alone is
    # what a payload-less note indexes to, so a note still name-matches.
    similarity = func.similarity(SolusEntry.search_text, q)
    exact = SolusEntry.text == q
    name_match = or_(SolusEntry.search_text.op("%")(q), exact)
    rank = cast(func.ts_rank(SolusEntry.search_tsv, query), Float)
    score = case((exact, literal(1.0)), else_=func.greatest(similarity, rank)).label("score")
    why = case((name_match, literal("name_match")), else_=literal("text_match")).label("why")
    tier = case((name_match, 0), else_=1)
    where: list[Any] = [
        SolusEntry.project_id == project_id,
        SolusEntry.deleted_at.is_(None),
        or_(name_match, SolusEntry.search_tsv.op("@@")(query)),
    ]
    if sections:
        where.append(SolusEntry.section.in_(sections))
    if subsections:
        where.append(SolusEntry.subsection.in_(subsections))
    stmt = (
        select(
            SolusEntry.id,
            SolusEntry.entity_id,
            SolusEntry.section,
            SolusEntry.subsection,
            SolusEntry.kind,
            SolusEntry.text,
            SolusEntry.search_text,
            score,
            why,
        )
        .where(and_(*where))
        .order_by(tier, score.desc(), SolusEntry.text)
        .limit(limit)
    )
    return [
        SolusHit(
            id=id_,
            entity_id=entity_id,
            section=section.value,
            subsection=subsection,
            kind=kind.value,
            name=text or "",
            snippet=(text or "") if why_ == "name_match" else _window(search_text, q),
            score=float(score_),
            why=why_,
        )
        for id_, entity_id, section, subsection, kind, text, search_text, score_, why_ in (
            await session.execute(stmt)
        )
    ]
