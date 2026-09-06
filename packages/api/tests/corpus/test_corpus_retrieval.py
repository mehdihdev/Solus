"""CORPUS C2 — retrieval: filters are WHERE clauses, drafts never serve, the
global corpus needs no tenant and accepts none."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from solus_api.agent.interfaces import RetrievalFilter
from solus_api.corpus.chunking import build_manifest, load_content_tree, load_release
from solus_api.corpus.ingest import ingest_corpus
from solus_api.corpus.retrieval import CorpusHit, corpus_hits
from solus_api.models import EMBEDDING_DIM
from solus_api.rag import rag_query
from sqlalchemy.ext.asyncio import AsyncSession

from corpus.corpus_helpers import authored, write_tree

TRACE = "corpus:electrical/trace_width_current/width-sets-current"
FIT = "corpus:mechanical/fits_tolerances/reading-h7-g6"
LOW = "corpus:electrical/wire_gauge/voltage-drop-rule"
SPI = "corpus:electrical/signal_integrity/spi-clock-length"
DRAFT = "corpus:electrical/decoupling/draft-idea"


def _vec(lead: float, second: float = 0.0) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[0], vector[1] = lead, second
    return vector


#: Deterministic "embeddings": electrical chunks point along axis 0, mechanical along 1.
VECTORS = {TRACE: _vec(1.0), LOW: _vec(0.9, 0.1), SPI: _vec(0.8, 0.2), FIT: _vec(0.0, 1.0)}


async def fake_embed(text: str) -> list[float] | None:
    for chunk_id, vector in VECTORS.items():
        if text.startswith(TITLES[chunk_id]):
            return vector
    return _vec(1.0)  # a query: electrical-shaped


TITLES = {
    TRACE: "Trace width sets current capacity",
    FIT: "Reading an H7/g6 fit",
    LOW: "Voltage drop, not ampacity, sizes robot wiring",
    SPI: "SPI clock versus trace length",
    DRAFT: "Draft decoupling idea",
}


@pytest.fixture
async def seeded(clean_corpus: AsyncSession, tmp_path: Path) -> AsyncSession:
    root = write_tree(
        tmp_path,
        {
            "electrical/trace_width_current/width-sets-current.md": authored(
                "Copper trace width, copper weight and allowed temperature rise set how much "
                "current a PCB trace carries; external layers cool better than internal ones.",
                title=f'"{TITLES[TRACE]}"',
            ),
            "mechanical/fits_tolerances/reading-h7-g6.md": authored(
                "H7 is a hole tolerance grade and g6 a shaft grade; together they give a "
                "sliding clearance fit for a machined bore.",
                title=f'"{TITLES[FIT]}"',
                audience='"reference"',
                kind='"reference_value"',
            ),
            "electrical/wire_gauge/voltage-drop-rule.md": authored(
                "In a robot the wire gauge is usually set by voltage drop over the run, not by "
                "the ampacity table; check the drop at stall current.",
                title=f'"{TITLES[LOW]}"',
                confidence="0.5",
                confidence_basis='"rule_of_thumb"',
                kind='"rule_of_thumb"',
                audience='"reference"',
            ),
            "electrical/signal_integrity/spi-clock-length.md": authored(
                "SPI has no clock stretching, so trace length and clock rate trade off; keep "
                "the clock trace short at tens of MHz.",
                title=f'"{TITLES[SPI]}"',
                applicability='[{ key = "bus", value = "spi" }]',
            ),
            "electrical/decoupling/draft-idea.md": authored(
                "An unreviewed thought about decoupling capacitor placement.",
                title=f'"{TITLES[DRAFT]}"',
                status='"draft"',
            ),
        },
    )
    manifest = build_manifest(load_content_tree(root), load_release(root))
    (root / "manifest.json").write_text(json.dumps(manifest) + "\n")
    await ingest_corpus(clean_corpus, root=root, embed=fake_embed)
    await clean_corpus.commit()
    return clean_corpus


async def test_a_domain_filter_is_pure_on_the_full_text_path(seeded: AsyncSession) -> None:
    hits = await corpus_hits(
        seeded, text="how wide should a trace be for this current tolerance", k=10,
        domains=["electrical"],
    )  # fmt: skip
    assert hits and all(h.domain == "electrical" for h in hits)
    assert TRACE in {h.chunk_id for h in hits}
    assert FIT not in {h.chunk_id for h in hits}


async def test_a_domain_filter_is_pure_on_the_ann_path(seeded: AsyncSession) -> None:
    hits = await corpus_hits(
        seeded, text="anything", k=10, domains=["mechanical"], vector=_vec(1.0)
    )
    assert [h.chunk_id for h in hits] == [FIT]  # nearest overall is electrical; filtered out


async def test_ann_ranks_by_cosine_similarity(seeded: AsyncSession) -> None:
    hits = await corpus_hits(seeded, text="q", k=10, vector=_vec(1.0))
    assert [h.chunk_id for h in hits][:3] == [TRACE, LOW, SPI]
    assert hits[0].score > hits[1].score > hits[2].score


async def test_drafts_never_serve_on_either_path(seeded: AsyncSession) -> None:
    text_hits = await corpus_hits(seeded, text="decoupling capacitor placement", k=10)
    ann_hits = await corpus_hits(seeded, text="q", k=10, vector=_vec(1.0))
    assert DRAFT not in {h.chunk_id for h in text_hits + ann_hits}


async def test_an_unknown_domain_yields_nothing_not_everything(seeded: AsyncSession) -> None:
    assert await corpus_hits(seeded, text="trace current", k=5, domains=["chemistry"]) == []
    assert await corpus_hits(seeded, text="q", k=5, domains=["chemistry"], vector=_vec(1.0)) == []


async def test_topic_filter_and_or_semantics_on_natural_questions(seeded: AsyncSession) -> None:
    hits = await corpus_hits(
        seeded, text="does copper weight change how much current I can push?", k=5,
        topics=["trace_width_current"],
    )  # fmt: skip
    assert [h.chunk_id for h in hits] == [TRACE]


async def test_applicability_excludes_only_chunks_tagged_with_another_value(
    seeded: AsyncSession,
) -> None:
    all_hits = await corpus_hits(seeded, text="q", k=10, vector=_vec(1.0))
    i2c_hits = await corpus_hits(
        seeded, text="q", k=10, vector=_vec(1.0), applicability={"bus": "i2c"}
    )
    spi_hits = await corpus_hits(
        seeded, text="q", k=10, vector=_vec(1.0), applicability={"bus": "spi"}
    )
    assert SPI in {h.chunk_id for h in all_hits}
    assert SPI not in {h.chunk_id for h in i2c_hits}  # tagged spi ≠ i2c
    assert TRACE in {h.chunk_id for h in i2c_hits}  # untagged applies regardless
    assert SPI in {h.chunk_id for h in spi_hits}


async def test_low_confidence_is_flagged_never_dropped(seeded: AsyncSession) -> None:
    hits = {h.chunk_id: h for h in await corpus_hits(seeded, text="q", k=10, vector=_vec(1.0))}
    assert hits[LOW].low_confidence is True and hits[LOW].confidence == 0.5
    assert hits[TRACE].low_confidence is False


async def test_hits_carry_a_corpus_citation_and_rendered_text(seeded: AsyncSession) -> None:
    (hit,) = await corpus_hits(seeded, text="q", k=1, vector=_vec(1.0))
    assert isinstance(hit, CorpusHit)
    assert hit.source_ref.source_connector == "corpus"
    assert hit.source_ref.external_ref == "electrical/trace_width_current/width-sets-current"
    assert hit.chunk.startswith(TITLES[TRACE] + "\n\n")
    assert hit.audience == "fundamentals" and hit.topic == "trace_width_current"


async def test_k_is_bounded_and_empty_queries_return_nothing(seeded: AsyncSession) -> None:
    assert len(await corpus_hits(seeded, text="q", k=500, vector=_vec(1.0))) <= 20
    assert await corpus_hits(seeded, text="???", k=5) == []


# ------------------------------------------------- through the SYS-02 rag_query seam


async def test_rag_query_serves_the_corpus_without_a_tenant(seeded: AsyncSession) -> None:
    hits = await rag_query(
        seeded,
        text="trace width for current",
        k=5,
        filter=RetrievalFilter(source_types=["corpus"], domains=["electrical"]),
    )
    assert hits and all(isinstance(h, CorpusHit) for h in hits)
    assert all(h.domain == "electrical" for h in hits)  # type: ignore[attr-defined]


async def test_rag_query_still_refuses_unscoped_tenant_types(seeded: AsyncSession) -> None:
    with pytest.raises(ValueError, match="project_id"):
        await rag_query(
            seeded, text="trace", k=5, filter=RetrievalFilter(source_types=["corpus", "entity"])
        )
    with pytest.raises(ValueError, match="project_id"):
        await rag_query(seeded, text="trace", k=5, filter=None)


async def test_rag_query_default_types_exclude_the_corpus(seeded: AsyncSession) -> None:
    import uuid

    hits = await rag_query(
        seeded, text="trace width current", k=5, filter=RetrievalFilter(project_id=uuid.uuid4())
    )
    assert all(not isinstance(h, CorpusHit) for h in hits)
