"""THE ONLY WRITE PATH into `corpus_chunk` (ADR-036 rule 3; ADR-033 rule 3 verbatim).

Reads the Solus-committed content tree, re-runs every contract and cross-chunk
rule, checks the tree against its committed manifest (a chunk not in the
manifest is not served — schema §8), and upserts by chunk id:

- new id → insert; changed `content_hash` or status → update in place, citations
  replaced; unchanged → untouched (an embedding is backfilled if missing);
- an id the manifest no longer lists → `withdrawn`: body and links cleared,
  embedding dropped, citations deleted, id kept so past SOL citations resolve;
- one `corpus_release` row per applied version.

Embedding is best-effort and unmetered (Solus's own cost, ADR-036): a keyless
environment ingests text and serves the full-text path. Nothing here takes a
request, a `SyncContext`, or anything customer-derived. A tripwire test fails
the suite if `CorpusChunkRow(` is constructed anywhere else in `src/`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.corpus.chunking import (
    MANIFEST_FILE,
    ChunkingError,
    CorpusReleaseInfo,
    build_manifest,
    load_content_tree,
    load_release,
    validate_corpus,
)
from solus_api.corpus.contract import Citation, CorpusChunk
from solus_api.corpus.enums import Status
from solus_api.corpus.schema import (
    CitationRole,
    CorpusChunkRow,
    CorpusCitationRow,
    CorpusRelease,
)
from solus_api.models import utcnow

logger = logging.getLogger("solus.corpus.ingest")

type EmbedFn = Callable[[str], Awaitable[list[float] | None]]


class IngestReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    corpus_version: str
    total: int
    inserted: int
    updated: int
    unchanged: int
    withdrawn: int
    embedded: int


def embedding_text(chunk: CorpusChunk) -> str:
    """What a chunk's vector represents: title and body, nothing about review."""
    return f"{chunk.title}\n\n{chunk.body}"


def _tags(chunk: CorpusChunk) -> list[str]:
    return [f"{entry.key.value}={entry.value}" for entry in chunk.applicability]


def _apply(row: CorpusChunkRow, chunk: CorpusChunk) -> None:
    prov = chunk.provenance
    row.domain = chunk.domain
    row.topic = chunk.topic
    row.title = chunk.title
    row.body = chunk.body
    row.kind = chunk.kind
    row.audience = chunk.audience
    row.applicability = _tags(chunk)
    row.derivation = chunk.derivation
    row.source_class = prov.source_class
    row.source_title = prov.source_title
    row.source_publisher = prov.source_publisher
    row.source_url = prov.source_url
    row.source_locator = prov.source_locator
    row.source_license = prov.source_license
    row.accessed_at = prov.accessed_at
    row.attribution = prov.attribution
    row.license = chunk.license
    row.confidence = chunk.confidence
    row.confidence_basis = chunk.confidence_basis
    row.drafting = chunk.drafting
    row.reviewer = chunk.reviewer
    row.reviewed_at = chunk.reviewed_at
    row.status = chunk.status
    row.supersedes = chunk.supersedes
    row.related = list(chunk.related)
    row.corpus_version = chunk.corpus_version
    row.revised_in = chunk.revised_in
    row.content_hash = chunk.content_hash


def _new_row(chunk: CorpusChunk) -> CorpusChunkRow:
    row = CorpusChunkRow(id=chunk.id)
    _apply(row, chunk)
    return row


def _citation_rows(chunk: CorpusChunk) -> list[CorpusCitationRow]:
    def rows(role: CitationRole, citations: Sequence[Citation]) -> list[CorpusCitationRow]:
        return [
            CorpusCitationRow(
                chunk_id=chunk.id,
                role=role,
                position=index,
                title=c.title,
                author=c.author,
                identifier=c.identifier,
                url=c.url,
            )
            for index, c in enumerate(citations)
        ]

    return rows(CitationRole.FURTHER_READING, chunk.further_reading) + rows(
        CitationRole.CHECKED_AGAINST, chunk.provenance.checked_against
    )


async def _replace_citations(session: AsyncSession, chunk: CorpusChunk) -> None:
    await session.execute(delete(CorpusCitationRow).where(CorpusCitationRow.chunk_id == chunk.id))
    session.add_all(_citation_rows(chunk))


async def _embed_or_none(embed: EmbedFn | None, chunk: CorpusChunk) -> list[float] | None:
    if embed is None or chunk.status is not Status.ACTIVE:
        return None
    try:
        return await embed(embedding_text(chunk))
    except Exception:  # noqa: BLE001 — embedding is best-effort by design
        logger.warning("corpus embed failed for %s; storing without vector", chunk.id)
        return None


def _withdrawn_form(row: CorpusChunkRow, release: CorpusReleaseInfo) -> CorpusChunk:
    """The rule-10 shape of a chunk the manifest dropped: id and provenance
    kept, every served field cleared, revised in the release that withdrew it."""
    return CorpusChunk.create(
        id=row.id,
        domain=row.domain,
        topic=row.topic,
        title=row.title,
        body="",
        kind=row.kind,
        audience=row.audience,
        applicability=[],
        derivation=row.derivation,
        provenance={
            "source_class": row.source_class,
            "source_title": row.source_title,
            "source_publisher": row.source_publisher,
            "source_url": row.source_url,
            "source_locator": row.source_locator,
            "source_license": row.source_license,
            "accessed_at": row.accessed_at,
            "attribution": row.attribution,
            "checked_against": [],
        },
        further_reading=[],
        license=row.license,
        confidence=row.confidence,
        confidence_basis=row.confidence_basis,
        drafting=row.drafting,
        reviewer=row.reviewer,
        reviewed_at=row.reviewed_at,
        status=Status.WITHDRAWN,
        supersedes=row.supersedes,
        related=[],
        corpus_version=row.corpus_version,
        revised_in=release.corpus_version,
    )


def _check_manifest(root: Path, built: dict[str, object]) -> str:
    path = root / MANIFEST_FILE
    try:
        on_disk = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        raise ChunkingError(
            str(path), "manifest.json missing or unreadable; run manifest"
        ) from None
    if on_disk != built:
        raise ChunkingError(str(path), "manifest.json is stale; run manifest and commit it")
    canonical = json.dumps(built, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


async def ingest_corpus(
    session: AsyncSession, *, root: Path, embed: EmbedFn | None = None
) -> IngestReport:
    """Apply the content tree at `root` to the store. Flushes; the caller commits."""
    release = load_release(root)
    chunks = load_content_tree(root)
    validate_corpus(chunks, release)
    manifest = build_manifest(chunks, release)
    manifest_hash = _check_manifest(root, manifest)

    existing = {row.id: row for row in (await session.execute(select(CorpusChunkRow))).scalars()}
    inserted = updated = unchanged = embedded = 0
    for chunk in chunks:
        row = existing.get(chunk.id)
        if row is None:
            row = _new_row(chunk)
            session.add(row)
            session.add_all(_citation_rows(chunk))
            inserted += 1
        elif row.content_hash != chunk.content_hash or row.status is not chunk.status:
            _apply(row, chunk)
            await _replace_citations(session, chunk)
            updated += 1
        else:
            unchanged += 1
            if row.embedding is not None or embed is None:
                continue
        vector = await _embed_or_none(embed, chunk)
        if vector is not None:
            embedded += 1
        row.embedding = vector

    listed = {chunk.id for chunk in chunks}
    withdrawn = 0
    for row in existing.values():
        if row.id in listed or row.status is Status.WITHDRAWN:
            continue
        _apply(row, _withdrawn_form(row, release))
        row.embedding = None
        await session.execute(delete(CorpusCitationRow).where(CorpusCitationRow.chunk_id == row.id))
        withdrawn += 1

    record = (
        await session.execute(
            select(CorpusRelease).where(CorpusRelease.corpus_version == release.corpus_version)
        )
    ).scalar_one_or_none()
    if record is None:
        record = CorpusRelease(
            corpus_version=release.corpus_version,
            policy_revision=release.policy_revision,
            released_at=release.released_at,
            chunk_count=len(chunks),
            manifest_hash=manifest_hash,
        )
        session.add(record)
    else:
        record.applied_at = utcnow()
        record.chunk_count = len(chunks)
        record.manifest_hash = manifest_hash
        record.policy_revision = release.policy_revision
    await session.flush()
    report = IngestReport(
        corpus_version=release.corpus_version,
        total=len(chunks),
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        withdrawn=withdrawn,
        embedded=embedded,
    )
    logger.info("corpus ingest applied: %s", report.model_dump())
    return report


async def run_ingest_cli(root: Path, *, database_url: str | None, embed: bool) -> int:
    """`python -m solus_api.corpus ingest` — deploy/admin entry point."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    url = database_url or os.environ.get("SOLUS_DATABASE_URL")
    if not url:
        print("set SOLUS_DATABASE_URL or pass --database-url", flush=True)
        return 2
    engine = create_async_engine(url)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    embed_fn: EmbedFn | None = None
    if embed:
        embed_fn = _cli_embed_fn(sessionmaker)
    try:
        async with sessionmaker() as session:
            report = await ingest_corpus(session, root=root, embed=embed_fn)
            await session.commit()
    finally:
        await engine.dispose()
    print(json.dumps(report.model_dump(), indent=2))
    return 0


def _cli_embed_fn(sessionmaker: object) -> EmbedFn | None:
    """The app's own embed seam, unmetered (ADR-036). Keyless → None → text only."""
    try:
        from solus_api.connectors.secrets import build_secret_store
        from solus_api.core.config import Settings
        from solus_api.orchestration.embeddings import build_embed_fn

        settings = Settings()  # type: ignore[call-arg]  # env-sourced; jwt secret unused here
        store = build_secret_store(settings, sessionmaker)  # type: ignore[arg-type]
        return build_embed_fn(store, allow_unmetered=True)
    except Exception as exc:  # noqa: BLE001 — a CLI degrades loudly, never crashes
        print(f"embedding unavailable ({type(exc).__name__}); ingesting text only", flush=True)
        return None
