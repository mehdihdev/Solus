"""`/api/v1/corpus` — the served view of the shipped corpus (docs/api/corpus.md).

Read-only by design: the only write path is `corpus.ingest`. Search is full-text
only here — embedding a caller-supplied string per request would expose the
unmetered embed seam to every authenticated user. Cross-tenant on
purpose — every authenticated user reads the same chunks; the boundary is what
a row cannot contain. Only `status = active` rows exist over HTTP (a draft is a
404, not a leak of unreviewed text); a `withdrawn` chunk resolves with an empty
body so a past SOL citation lands somewhere honest. `reviewer`, `reviewed_at`,
`drafting`, `content_hash`, and `embedding` never leave the database.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.corpus.enums import Status
from solus_api.corpus.retrieval import corpus_hits
from solus_api.corpus.schema import (
    CitationRole,
    CorpusChunkRow,
    CorpusCitationRow,
    CorpusRelease,
)
from solus_api.deps import CurrentUser, SessionDep

router = APIRouter(prefix="/api/v1/corpus", tags=["corpus"])

MAX_QUERY_CHARS = 500
MAX_LIMIT = 20
EXCERPT_CHARS = 280


@router.get("/manifest")
async def get_manifest(_: CurrentUser, session: SessionDep) -> dict[str, Any]:
    release = (
        (await session.execute(select(CorpusRelease).order_by(CorpusRelease.applied_at.desc())))
        .scalars()
        .first()
    )
    if release is None:
        raise APIError(404, "corpus_not_ingested", "No corpus release has been applied")
    return envelope(
        {
            "corpus_version": release.corpus_version,
            "released_at": release.released_at.isoformat(),
            "policy_revision": release.policy_revision,
            "applied_at": release.applied_at.isoformat(),
            "chunk_count": release.chunk_count,
            "manifest_hash": release.manifest_hash,
        }
    )


@router.get("/search")
async def search(
    _: CurrentUser,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=MAX_QUERY_CHARS)],
    domain: Annotated[list[str] | None, Query()] = None,
    topic: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 5,
) -> dict[str, Any]:
    # Full-text only over HTTP (§7 cost control): the embed seam is unmetered and
    # Solus-paid, so it serves SOL turns — which are admission-capped — and never
    # an arbitrary authenticated request. 100-odd curated chunks rank well on text.
    hits = await corpus_hits(session, text=q, k=limit, domains=domain, topics=topic)
    return envelope(
        [
            {
                "id": hit.chunk_id,
                "title": hit.title,
                "domain": hit.domain,
                "topic": hit.topic,
                "kind": hit.kind,
                "audience": hit.audience,
                "score": round(hit.score, 4),
                "confidence": hit.confidence,
                "low_confidence": hit.low_confidence,
                "excerpt": _excerpt(hit.chunk, hit.title),
            }
            for hit in hits
        ]
    )


def _excerpt(chunk: str, title: str) -> str:
    body = chunk.removeprefix(title).lstrip("\n")
    return body if len(body) <= EXCERPT_CHARS else body[:EXCERPT_CHARS] + "…"


async def _citations(session: AsyncSession, chunk_id: str) -> list[CorpusCitationRow]:
    stmt = (
        select(CorpusCitationRow)
        .where(CorpusCitationRow.chunk_id == chunk_id)
        .order_by(CorpusCitationRow.role, CorpusCitationRow.position)
    )
    return list((await session.execute(stmt)).scalars())


@router.get("/chunks/{chunk_id:path}")
async def get_chunk(_: CurrentUser, session: SessionDep, chunk_id: str) -> dict[str, Any]:
    row = await session.get(CorpusChunkRow, chunk_id)
    if row is None or row.status is Status.DRAFT:
        raise APIError(404, "chunk_not_found", "Chunk not found")
    reading = [
        {"title": c.title, "author": c.author, "identifier": c.identifier, "url": c.url}
        for c in await _citations(session, row.id)
        if c.role is CitationRole.FURTHER_READING
    ]
    applicability = [
        {"key": key, "value": value}
        for key, value in (tag.split("=", 1) for tag in row.applicability)
    ]
    return envelope(
        {
            "id": row.id,
            "domain": row.domain.value,
            "topic": row.topic.value,
            "title": row.title,
            "body": row.body,
            "kind": row.kind.value,
            "audience": row.audience.value,
            "status": row.status.value,
            "confidence": row.confidence,
            "confidence_basis": row.confidence_basis.value,
            "applicability": applicability,
            "source": {
                "class": row.source_class.value,
                "title": row.source_title,
                "publisher": row.source_publisher,
                "url": row.source_url,
                "license": row.source_license.value,
                "attribution": row.attribution,
            },
            "further_reading": reading,
            "related": list(row.related),
            "supersedes": row.supersedes,
            "corpus_version": row.corpus_version,
            "revised_in": row.revised_in,
        }
    )
