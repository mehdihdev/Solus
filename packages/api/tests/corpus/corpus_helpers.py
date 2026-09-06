"""Shared by the corpus suites: an authored-file factory, a content-tree writer,
and the `clean_corpus` fixture that empties the global corpus tables around a
test (they are tenant-free, so the per-project truncation elsewhere never
touches them). Imported explicitly by each suite — NOT a conftest, because a
second `conftest.py` basename shadows the top-level one that older suites
import helpers from."""

from __future__ import annotations

from pathlib import Path

RELEASE_TOML = (
    'corpus_version = "0.1.0"\npolicy_revision = "docs/corpus/LICENSING.md@43e8a06"\n'
    "released_at = 2026-09-06\n"
)


def front_matter(**overrides: str) -> str:
    fields = {
        "title": '"Decoupling is about loop area"',
        "kind": '"principle"',
        "audience": '"fundamentals"',
        "applicability": "[]",
        "derivation": '"solus_original"',
        "confidence": "0.9",
        "confidence_basis": '"consensus"',
        "drafting": '"llm_assisted"',
        "reviewer": '"mhussain"',
        "reviewed_at": "2026-09-06",
        "status": '"active"',
        "related": "[]",
        "further_reading": "[]",
        "corpus_version": '"0.1.0"',
        "revised_in": '"0.1.0"',
    }
    fields.update(overrides)
    body = "\n".join(f"{k} = {v}" for k, v in fields.items())
    return (
        "+++\n"
        f"{body}\n\n"
        "[provenance]\n"
        'source_class = "solus_authored"\n'
        'source_title = "Solus engineering corpus"\n'
        'source_publisher = "Solus"\n'
        'source_license = "solus-proprietary"\n'
        "accessed_at = 2026-09-06\n"
        "checked_against = [\n"
        '  { title = "I2C-bus specification", author = "NXP", url = "https://www.nxp.com/" },\n'
        "]\n"
        "+++\n"
    )


def authored(body: str, **overrides: str) -> str:
    return front_matter(**overrides) + "\n" + body + "\n"


def write_tree(root: Path, files: dict[str, str], *, release: str = RELEASE_TOML) -> Path:
    (root / "corpus.toml").write_text(release)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root
