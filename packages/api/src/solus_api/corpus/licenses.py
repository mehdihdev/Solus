"""Licence accounting for the shipped corpus (CORPUS C3).

"Nothing in the corpus lacks a license" is a property the contract enforces per
chunk (rule 9) and this module makes visible per release: a report of every
active chunk grouped by source class, licence, and publisher, plus the checks a
release must pass before it ships. Pure functions over the content tree — no
database, no network.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from solus_api.corpus.contract import CorpusChunk
from solus_api.corpus.enums import (
    ATTRIBUTION_REQUIRED,
    Derivation,
    SourceClass,
    SourceLicense,
    Status,
)


@dataclass(frozen=True)
class LicenseFinding:
    chunk_id: str
    problem: str


def license_findings(chunks: Iterable[CorpusChunk]) -> list[LicenseFinding]:
    """Every way a chunk could ship without a usable licence record. Empty means
    the release is clean. Overlaps the contract on purpose: this is the report a
    human reads at the MR, not the validator."""
    findings: list[LicenseFinding] = []
    for chunk in chunks:
        if chunk.status is not Status.ACTIVE:
            continue
        prov = chunk.provenance
        if prov.source_license is SourceLicense.UNKNOWN:
            findings.append(LicenseFinding(chunk.id, "source_license is unknown"))
        if prov.source_class is not SourceClass.SOLUS_AUTHORED and not prov.source_url:
            findings.append(LicenseFinding(chunk.id, "sourced chunk has no source_url"))
        if prov.source_class is not SourceClass.SOLUS_AUTHORED and not prov.source_locator:
            findings.append(LicenseFinding(chunk.id, "sourced chunk has no locator"))
        if (
            chunk.derivation is Derivation.VERBATIM
            and prov.source_license in ATTRIBUTION_REQUIRED
            and not prov.attribution.strip()
        ):
            findings.append(LicenseFinding(chunk.id, "verbatim excerpt without attribution"))
        if (
            prov.source_class is SourceClass.SOLUS_AUTHORED
            and chunk.drafting.value == "llm_assisted"
            and not prov.checked_against
        ):
            findings.append(LicenseFinding(chunk.id, "llm-assisted chunk lists no sources"))
    return findings


def license_report(chunks: Sequence[CorpusChunk]) -> str:
    """A Markdown table: active chunks by source class × licence × publisher."""
    active = [c for c in chunks if c.status is Status.ACTIVE]
    rows = Counter(
        (
            c.provenance.source_class.value,
            c.provenance.source_license.value,
            c.provenance.source_publisher,
            c.derivation.value,
        )
        for c in active
    )
    lines = [
        f"Active chunks: {len(active)} · classes: "
        f"{len({c.provenance.source_class for c in active})} · "
        f"licences: {len({c.provenance.source_license for c in active})}",
        "",
        "| source_class | source_license | publisher | derivation | chunks |",
        "| --- | --- | --- | --- | --- |",
    ]
    for (cls, lic, publisher, derivation), n in sorted(rows.items()):
        lines.append(f"| {cls} | {lic} | {publisher} | {derivation} | {n} |")
    findings = license_findings(active)
    lines.append("")
    lines.append(
        "Findings: none"
        if not findings
        else "Findings:\n" + "\n".join(f"- {f.chunk_id}: {f.problem}" for f in findings)
    )
    return "\n".join(lines)
