"""CORPUS C3 — nothing in the corpus lacks a licence, and the sourced classes
carry the provenance the policy demands."""

from __future__ import annotations

from collections import Counter

from solus_api.corpus.chunking import chunks_from_source, content_root, load_content_tree
from solus_api.corpus.enums import CorpusDomain, SourceClass, SourceLicense, Status, Topic
from solus_api.corpus.licenses import license_findings, license_report

from corpus.corpus_helpers import authored


def test_every_active_shipped_chunk_has_a_usable_licence_record() -> None:
    chunks = load_content_tree(content_root())
    assert license_findings(chunks) == []
    active = [c for c in chunks if c.status is Status.ACTIVE]
    assert all(c.provenance.source_license is not SourceLicense.UNKNOWN for c in active)


def test_the_shipped_corpus_carries_the_c3_source_classes() -> None:
    classes = Counter(
        c.provenance.source_class for c in load_content_tree(content_root())
        if c.status is Status.ACTIVE
    )  # fmt: skip
    assert classes[SourceClass.SOLUS_AUTHORED] >= 100
    assert classes[SourceClass.VENDOR_DOCUMENTATION] >= 8, "curated vendor notes (C3 item 2)"
    assert classes[SourceClass.US_GOVERNMENT_WORK] >= 5, "NASA references (C3 item 3)"
    assert classes[SourceClass.DATASHEET] >= 3, "datasheets for named R4 parts (C3 item 4)"


def test_sourced_chunks_point_at_the_rights_holder_with_a_locator() -> None:
    for chunk in load_content_tree(content_root()):
        prov = chunk.provenance
        if prov.source_class is SourceClass.SOLUS_AUTHORED:
            continue
        assert prov.source_url and prov.source_url.startswith("https://"), chunk.id
        assert prov.source_locator, chunk.id
        assert prov.attribution, chunk.id  # every sourced chunk renders a citation


def test_findings_name_the_gaps_and_the_report_lists_classes() -> None:
    text = authored("Body.").replace(
        'confidence_basis = "consensus"', 'confidence_basis = "consensus"'
    )
    (clean,) = chunks_from_source(
        text, domain=CorpusDomain.ELECTRICAL, topic=Topic.DECOUPLING, slug="x"
    )
    assert license_findings([clean]) == []
    draft = clean.model_copy(update={"status": Status.DRAFT})
    assert license_findings([draft]) == []  # drafts never ship, so never count
    report = license_report([clean])
    assert "solus_authored | solus-proprietary | Solus | solus_original | 1" in report
    assert "Findings: none" in report
