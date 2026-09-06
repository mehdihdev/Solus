"""CORPUS C2 — the ONLY write path (ADR-036 rule 3) and the tables' containment."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from solus_api.corpus.chunking import (
    ChunkingError,
    build_manifest,
    load_content_tree,
    load_release,
)
from solus_api.corpus.enums import Status
from solus_api.corpus.ingest import ingest_corpus
from solus_api.corpus.schema import CorpusChunkRow, CorpusCitationRow, CorpusRelease
from solus_api.models import EMBEDDING_DIM, Base
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from corpus.corpus_helpers import authored, write_tree

SRC = Path(__file__).resolve().parents[2] / "src" / "solus_api"

A = "electrical/decoupling/loop-area.md"
B = "mechanical/fits_tolerances/h7-g6.md"


def tree(tmp_path: Path, **files: str) -> Path:
    root = write_tree(
        tmp_path,
        {
            A: authored("Loop area sets inductance."),
            B: authored("H7/g6 is a sliding clearance fit.", title='"Reading H7/g6"'),
            **files,
        },
    )
    write_manifest(root)
    return root


def write_manifest(root: Path) -> None:
    manifest = build_manifest(load_content_tree(root), load_release(root))
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


async def rows(db: AsyncSession) -> dict[str, CorpusChunkRow]:
    return {r.id: r for r in (await db.execute(select(CorpusChunkRow))).scalars()}


async def _vec(_text: str) -> list[float] | None:
    return [0.0] * (EMBEDDING_DIM - 1) + [1.0]


async def test_ingest_inserts_rows_citations_and_a_release(
    clean_corpus: AsyncSession, tmp_path: Path
) -> None:
    report = await ingest_corpus(clean_corpus, root=tree(tmp_path), embed=_vec)
    await clean_corpus.commit()
    assert (report.inserted, report.updated, report.withdrawn, report.embedded) == (2, 0, 0, 2)
    stored = await rows(clean_corpus)
    assert set(stored) == {
        "corpus:electrical/decoupling/loop-area",
        "corpus:mechanical/fits_tolerances/h7-g6",
    }
    loop = stored["corpus:electrical/decoupling/loop-area"]
    assert loop.status is Status.ACTIVE and loop.embedding is not None
    citations = list((await clean_corpus.execute(select(CorpusCitationRow))).scalars())
    assert {(c.chunk_id, c.role.value, c.title) for c in citations} == {
        ("corpus:electrical/decoupling/loop-area", "checked_against", "I2C-bus specification"),
        ("corpus:mechanical/fits_tolerances/h7-g6", "checked_against", "I2C-bus specification"),
    }
    release = (await clean_corpus.execute(select(CorpusRelease))).scalar_one()
    assert release.corpus_version == "0.1.0" and release.chunk_count == 2
    assert release.manifest_hash.startswith("sha256:")


async def test_ingest_is_idempotent(clean_corpus: AsyncSession, tmp_path: Path) -> None:
    root = tree(tmp_path)
    await ingest_corpus(clean_corpus, root=root)
    await clean_corpus.commit()
    again = await ingest_corpus(clean_corpus, root=root)
    await clean_corpus.commit()
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, 2)
    assert len(list((await clean_corpus.execute(select(CorpusRelease))).scalars())) == 1


async def test_keyless_ingest_stores_text_and_a_later_run_backfills_vectors(
    clean_corpus: AsyncSession, tmp_path: Path
) -> None:
    root = tree(tmp_path)
    first = await ingest_corpus(clean_corpus, root=root, embed=None)
    await clean_corpus.commit()
    assert first.embedded == 0
    assert all(r.embedding is None for r in (await rows(clean_corpus)).values())
    second = await ingest_corpus(clean_corpus, root=root, embed=_vec)
    await clean_corpus.commit()
    assert second.unchanged == 2 and second.embedded == 2


async def test_a_failing_embedder_never_blocks_ingest(
    clean_corpus: AsyncSession, tmp_path: Path
) -> None:
    async def boom(_text: str) -> list[float] | None:
        raise RuntimeError("provider down")

    report = await ingest_corpus(clean_corpus, root=tree(tmp_path), embed=boom)
    assert report.inserted == 2 and report.embedded == 0


async def test_a_changed_chunk_updates_in_place_and_replaces_citations(
    clean_corpus: AsyncSession, tmp_path: Path
) -> None:
    root = tree(tmp_path)
    await ingest_corpus(clean_corpus, root=root, embed=_vec)
    await clean_corpus.commit()
    before = (await rows(clean_corpus))["corpus:electrical/decoupling/loop-area"].content_hash
    (root / A).write_text(
        authored(
            "Loop area sets inductance. Keep the capacitor on the same layer.",
            further_reading='[{ title = "High-Speed Digital Design", author = "Johnson" }]',
        )
    )
    write_manifest(root)
    report = await ingest_corpus(clean_corpus, root=root, embed=_vec)
    await clean_corpus.commit()
    assert (report.updated, report.unchanged) == (1, 1)
    row = (await rows(clean_corpus))["corpus:electrical/decoupling/loop-area"]
    assert row.content_hash != before and "same layer" in row.body
    reading = [
        c.title
        for c in (await clean_corpus.execute(select(CorpusCitationRow))).scalars()
        if c.chunk_id == row.id and c.role.value == "further_reading"
    ]
    assert reading == ["High-Speed Digital Design"]


async def test_a_chunk_dropped_from_the_manifest_is_withdrawn_not_deleted(
    clean_corpus: AsyncSession, tmp_path: Path
) -> None:
    root = tree(tmp_path)
    await ingest_corpus(clean_corpus, root=root, embed=_vec)
    await clean_corpus.commit()
    (root / B).unlink()
    write_manifest(root)
    report = await ingest_corpus(clean_corpus, root=root, embed=_vec)
    await clean_corpus.commit()
    assert report.withdrawn == 1
    gone = (await rows(clean_corpus))["corpus:mechanical/fits_tolerances/h7-g6"]
    assert gone.status is Status.WITHDRAWN
    assert gone.body == "" and gone.related == [] and gone.applicability == []
    assert gone.embedding is None and gone.revised_in == "0.1.0"
    assert gone.title == "Reading H7/g6"  # id and title survive so citations resolve
    citations = list((await clean_corpus.execute(select(CorpusCitationRow))).scalars())
    assert all(c.chunk_id != gone.id for c in citations)


async def test_a_stale_or_missing_manifest_writes_nothing(
    clean_corpus: AsyncSession, tmp_path: Path
) -> None:
    root = tree(tmp_path)
    (root / "manifest.json").unlink()
    with pytest.raises(ChunkingError, match="manifest"):
        await ingest_corpus(clean_corpus, root=root)
    write_manifest(root)
    (root / A).write_text(authored("Edited after the manifest was built."))
    with pytest.raises(ChunkingError, match="stale"):
        await ingest_corpus(clean_corpus, root=root)
    assert await rows(clean_corpus) == {}


# ------------------------------------------------------------- containment proofs


def test_tripwire_only_ingest_constructs_chunk_rows() -> None:
    offenders = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if re.search(r"(?<!class )\bCorpusChunkRow\(", p.read_text()) and p.name != "ingest.py"
    ]
    assert offenders == [], offenders


@pytest.mark.parametrize("table", ["corpus_chunk", "corpus_citation", "corpus_release"])
def test_tables_have_no_tenant_column_no_tenant_fk_and_no_blob(table: str) -> None:
    meta = Base.metadata.tables[table]
    names = {c.name for c in meta.columns}
    forbidden = {
        "project_id",
        "team_id",
        "user_id",
        "entity_id",
        "source_id",
        "document_id",
        "conversation_id",
        "file_path",
        "metadata",
        "attrs",
        "extra",
        "payload",
        "notes",
        "tags",
    }
    assert not names & forbidden, names & forbidden
    for fk in meta.foreign_keys:
        assert fk.column.table.name.startswith("corpus_"), fk
    assert all("JSON" not in type(c.type).__name__.upper() for c in meta.columns)


def test_chunk_row_columns_mirror_the_contract() -> None:
    columns = {c.key for c in inspect(CorpusChunkRow).mapper.column_attrs}
    assert {"id", "domain", "topic", "title", "body", "status", "content_hash"} <= columns
    assert "embedding" in columns
