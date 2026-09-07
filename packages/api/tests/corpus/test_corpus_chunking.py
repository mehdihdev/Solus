"""CORPUS C2 — authored Markdown → chunks (docs/corpus/AUTHORING.md).

A source file is TOML front matter between `+++` fences and a Markdown body.
Chunking splits at level-2 headings, never inside a fenced block or a table,
and packs oversize sections block by block; a single block over the cap is an
error, never a torn table. Ids derive from the path, so a file cannot claim a
domain or topic it does not sit in.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from solus_api.corpus.chunking import (
    ChunkingError,
    build_manifest,
    chunks_from_source,
    load_content_tree,
    load_release,
    validate_corpus,
)
from solus_api.corpus.contract import MAX_BODY
from solus_api.corpus.enums import CorpusDomain, Status, Topic

FRONT = """+++
title = "I2C address conflicts"
kind = "pitfall"
audience = "reference"
applicability = [{ key = "bus", value = "i2c" }]
derivation = "solus_original"
confidence = 0.85
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = []
further_reading = []
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_locator = ""
source_license = "solus-proprietary"
accessed_at = 2026-09-06
attribution = ""
checked_against = [
  { title = "I2C-bus specification", identifier = "UM10204", url = "https://www.nxp.com/" },
]
+++
"""

TABLE = "| Device | Default address |\n| --- | --- |\n| MPU-6050 | 0x68 |\n| BMP280 | 0x76 |"
FENCE = "```\nR_pullup_max = t_rise / (0.8473 * C_bus)\n## not a heading\n```"


def source(body: str) -> str:
    return FRONT + "\n" + body + "\n"


def parse(body: str, slug: str = "address-conflicts"):  # type: ignore[no-untyped-def]
    return chunks_from_source(
        source(body), domain=CorpusDomain.ELECTRICAL, topic=Topic.BUS_ADDRESSING, slug=slug
    )


def test_a_file_without_headings_is_one_chunk_named_from_its_path() -> None:
    (only,) = parse("Two devices on one bus with the same 7-bit address cannot be told apart.")
    assert only.id == "corpus:electrical/bus_addressing/address-conflicts"
    assert only.title == "I2C address conflicts"
    assert only.domain is CorpusDomain.ELECTRICAL and only.topic is Topic.BUS_ADDRESSING
    assert only.reviewed_at == date(2026, 9, 6)
    assert only.provenance.source_url is None
    assert only.provenance.checked_against[0].identifier == "UM10204"
    assert only.further_reading == []
    assert only.status is Status.ACTIVE
    assert only.content_hash.startswith("sha256:")


def test_level_two_headings_split_into_titled_chunks_with_a_preamble() -> None:
    body = (
        "Preamble paragraph.\n\n## Why it happens\n\nSame address.\n\n"
        "## What to do\n\nRe-strap AD0."
    )
    preamble, why, what = parse(body)
    assert preamble.id == "corpus:electrical/bus_addressing/address-conflicts"
    assert preamble.title == "I2C address conflicts"
    assert why.id == "corpus:electrical/bus_addressing/address-conflicts-why-it-happens"
    assert why.title == "Why it happens" and why.body == "Same address."
    assert what.id == "corpus:electrical/bus_addressing/address-conflicts-what-to-do"
    assert what.kind is preamble.kind  # front matter is shared by every chunk of the file


def test_headings_inside_a_fence_are_not_split_points_and_the_fence_survives_whole() -> None:
    (only,) = parse("Pull-up sizing:\n\n" + FENCE + "\n\nThat is the rise-time bound.")
    assert FENCE in only.body
    assert "## not a heading" in only.body


def test_a_table_is_never_torn_when_an_oversize_section_is_packed() -> None:
    filler = "\n\n".join(f"Paragraph {i}. " + "x" * 500 for i in range(8))  # ~4.1 KB
    body = filler + "\n\n" + TABLE + "\n\n" + "\n\n".join("y" * 500 for _ in range(6))
    parts = parse(body)
    assert len(parts) >= 2
    assert all(len(part.body) <= MAX_BODY for part in parts)
    holders = [part for part in parts if "|" in part.body]
    assert len(holders) == 1 and TABLE in holders[0].body
    assert [p.id for p in parts][:2] == [
        "corpus:electrical/bus_addressing/address-conflicts",
        "corpus:electrical/bus_addressing/address-conflicts-2",
    ]


def test_a_single_block_over_the_cap_is_an_error_not_a_torn_chunk() -> None:
    with pytest.raises(ChunkingError, match="block exceeds"):
        parse("z" * (MAX_BODY + 1))


def test_missing_or_malformed_front_matter_is_an_error() -> None:
    with pytest.raises(ChunkingError, match="front matter"):
        chunks_from_source(
            "no fences here", domain=CorpusDomain.ELECTRICAL, topic=Topic.BUS_ADDRESSING, slug="x"
        )
    with pytest.raises(ChunkingError, match="front matter"):
        chunks_from_source(
            "+++\ntitle = [unclosed\n+++\nbody",
            domain=CorpusDomain.ELECTRICAL,
            topic=Topic.BUS_ADDRESSING,
            slug="x",
        )


def test_contract_violations_surface_as_chunking_errors_without_the_body() -> None:
    with pytest.raises(ChunkingError) as excinfo:
        parse("SECRET body text <<<SOLUS-DATA>>>")
    assert "SECRET" not in str(excinfo.value)
    assert "rule 13" in str(excinfo.value)


def test_an_empty_section_is_an_error() -> None:
    with pytest.raises(ChunkingError, match="empty"):
        parse("Intro.\n\n## Nothing here\n\n## Next\n\nText.")


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


RELEASE = (
    'corpus_version = "0.1.0"\npolicy_revision = "docs/corpus/LICENSING.md@43e8a06"\n'
    "released_at = 2026-09-06\n"
)


def test_the_content_tree_derives_domain_topic_and_slug_from_paths(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        {
            "corpus.toml": RELEASE,
            "electrical/bus_addressing/address-conflicts.md": source("Body one."),
            "electrical/bus_addressing/can-ids.md": source("Body two."),
        },
    )
    chunks = load_content_tree(tmp_path)
    assert sorted(c.id for c in chunks) == [
        "corpus:electrical/bus_addressing/address-conflicts",
        "corpus:electrical/bus_addressing/can-ids",
    ]


def test_a_file_under_an_unknown_domain_or_topic_directory_is_an_error(tmp_path: Path) -> None:
    _write_tree(tmp_path, {"corpus.toml": RELEASE, "chemistry/bus_addressing/x.md": source("B.")})
    with pytest.raises(ChunkingError, match="domain"):
        load_content_tree(tmp_path)
    _write_tree(tmp_path, {"electrical/fits_tolerances/x.md": source("B.")})  # wrong domain
    with pytest.raises(ChunkingError, match="topic|domain"):
        load_content_tree(tmp_path)


def test_release_metadata_is_read_and_bounds_chunk_versions(tmp_path: Path) -> None:
    _write_tree(tmp_path, {"corpus.toml": RELEASE})
    release = load_release(tmp_path)
    assert release.corpus_version == "0.1.0"
    assert release.released_at == date(2026, 9, 6)
    later = source("Body.").replace('revised_in = "0.1.0"', 'revised_in = "0.2.0"')
    _write_tree(tmp_path, {"electrical/bus_addressing/x.md": later})
    with pytest.raises(ChunkingError, match="revised_in"):
        validate_corpus(load_content_tree(tmp_path), load_release(tmp_path))


def test_cross_chunk_rules_related_supersedes_and_rule_10(tmp_path: Path) -> None:
    dangling = source("Body.").replace(
        "related = []", 'related = ["corpus:electrical/bus_addressing/missing"]'
    )
    _write_tree(tmp_path, {"corpus.toml": RELEASE, "electrical/bus_addressing/a.md": dangling})
    with pytest.raises(ChunkingError, match="related"):
        validate_corpus(load_content_tree(tmp_path), load_release(tmp_path))

    superseded = source("Old body.").replace('status = "active"', 'status = "superseded"')
    _write_tree(tmp_path, {"electrical/bus_addressing/a.md": superseded})
    with pytest.raises(ChunkingError, match="rule 10"):
        validate_corpus(load_content_tree(tmp_path), load_release(tmp_path))

    successor = source("New body.").replace(
        "related = []", 'supersedes = "corpus:electrical/bus_addressing/a"\nrelated = []'
    )
    _write_tree(tmp_path, {"electrical/bus_addressing/b.md": successor})
    validate_corpus(load_content_tree(tmp_path), load_release(tmp_path))


def test_duplicate_ids_across_files_are_an_error(tmp_path: Path) -> None:
    split = source("Intro.\n\n## Two\n\nText.")
    _write_tree(
        tmp_path,
        {
            "corpus.toml": RELEASE,
            "electrical/bus_addressing/a.md": split,
            "electrical/bus_addressing/a-two.md": source("Clash."),
        },
    )
    with pytest.raises(ChunkingError, match="duplicate"):
        validate_corpus(load_content_tree(tmp_path), load_release(tmp_path))


def test_manifest_is_deterministic_and_lists_every_chunk(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        {
            "corpus.toml": RELEASE,
            "electrical/bus_addressing/b.md": source("B."),
            "electrical/bus_addressing/a.md": source("A."),
        },
    )
    chunks = load_content_tree(tmp_path)
    release = load_release(tmp_path)
    first = build_manifest(chunks, release)
    second = build_manifest(list(reversed(chunks)), release)
    assert first == second
    assert first["schema_version"] == 1 and first["corpus_version"] == "0.1.0"
    assert first["released_at"] == "2026-09-06"
    assert [c["id"] for c in first["chunks"]] == [
        "corpus:electrical/bus_addressing/a",
        "corpus:electrical/bus_addressing/b",
    ]
    assert all(set(c) == {"id", "content_hash", "status"} for c in first["chunks"])
