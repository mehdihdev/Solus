"""CORPUS C3 — acceptance: the eval passes (test_corpus_eval), the two named
questions resolve to SOURCED chunks, and nothing ships without a licence
(test_corpus_licenses). Runs on the keyless full-text path like CI."""

from __future__ import annotations

from solus_api.corpus.chunking import content_root
from solus_api.corpus.domains import route_domains
from solus_api.corpus.enums import SourceClass
from solus_api.corpus.ingest import ingest_corpus
from solus_api.corpus.retrieval import corpus_hits
from sqlalchemy.ext.asyncio import AsyncSession

from corpus.corpus_helpers import RELEASE_TOML  # noqa: F401  (package import side effect)

TRACE_Q = "what trace width for 3 A on 1 oz copper"
CLEARANCE_Q = "clearance for a 48 V bus"


async def _ingested(db: AsyncSession) -> AsyncSession:
    await ingest_corpus(db, root=content_root(), embed=None)
    await db.commit()
    return db


def _domains(question: str) -> list[str] | None:
    routed = route_domains(question)
    return None if routed is None else [d.value for d in routed]


async def test_trace_width_question_cites_an_application_note(clean_corpus: AsyncSession) -> None:
    db = await _ingested(clean_corpus)
    hits = await corpus_hits(db, text=TRACE_Q, k=5, domains=_domains(TRACE_Q))
    app_notes = [
        h for h in hits
        if h.chunk_id.startswith("corpus:electrical/trace_width_current/ti-slua366")
    ]  # fmt: skip
    assert app_notes, [h.chunk_id for h in hits]
    top = app_notes[0]
    assert "SLUA366" in top.attribution and "Texas Instruments" in top.attribution
    assert "3.2 A" in top.chunk and "0.050 in" in top.chunk
    assert top.low_confidence is False


async def test_48v_clearance_question_answers_with_a_source(clean_corpus: AsyncSession) -> None:
    db = await _ingested(clean_corpus)
    hits = await corpus_hits(db, text=CLEARANCE_Q, k=5, domains=_domains(CLEARANCE_Q))
    assert hits and all(h.domain == "electrical" for h in hits)
    sourced = [h for h in hits if h.attribution]
    assert sourced, [h.chunk_id for h in hits]
    assert any("SLUP419" in h.attribution or "SLUAAR5" in h.attribution for h in sourced)
    assert any("60 V" in h.chunk and "48 V" in h.chunk for h in sourced)


async def test_every_sourced_chunk_served_carries_its_attribution(
    clean_corpus: AsyncSession,
) -> None:
    db = await _ingested(clean_corpus)
    for question in (TRACE_Q, CLEARANCE_Q, "torque coefficient K for steel bolts",
                     "contact conductance of a bolted aluminium joint"):  # fmt: skip
        for hit in await corpus_hits(db, text=question, k=5, domains=_domains(question)):
            if hit.chunk_id.split("/")[-1].startswith(("ti-", "nasa-", "microchip-", "infineon-",
                                                        "espressif-", "feetech-")):  # fmt: skip
                assert hit.attribution, hit.chunk_id


def test_source_classes_present_match_the_ticket() -> None:
    from solus_api.corpus.chunking import load_content_tree

    classes = {c.provenance.source_class for c in load_content_tree(content_root())}
    assert {
        SourceClass.SOLUS_AUTHORED,
        SourceClass.VENDOR_DOCUMENTATION,
        SourceClass.US_GOVERNMENT_WORK,
        SourceClass.DATASHEET,
    } <= classes
