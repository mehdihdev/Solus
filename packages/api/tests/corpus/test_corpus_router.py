"""CORPUS C2 — `/api/v1/corpus` (docs/api/corpus.md): read-only, authenticated,
cross-tenant by design, drafts invisible, review metadata never on the wire."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from solus_api.corpus.chunking import build_manifest, load_content_tree, load_release
from solus_api.corpus.ingest import ingest_corpus
from sqlalchemy.ext.asyncio import AsyncSession

from corpus.corpus_helpers import authored, write_tree

LOOP = "corpus:electrical/decoupling/loop-area"
FIT = "corpus:mechanical/fits_tolerances/reading-h7-g6"
DRAFT = "corpus:electrical/decoupling/draft-idea"


@pytest.fixture
async def seeded(clean_corpus: AsyncSession, tmp_path: Path) -> AsyncSession:
    root = write_tree(
        tmp_path,
        {
            "electrical/decoupling/loop-area.md": authored(
                "Loop inductance through the capacitor and the IC pins sets decoupling.",
                applicability='[{ key = "fabrication_class", value = "prototype" }]',
                further_reading='[{ title = "High-Speed Digital Design", author = "Johnson" }]',
            ),
            "mechanical/fits_tolerances/reading-h7-g6.md": authored(
                "H7/g6 is a sliding clearance fit for a machined bore.",
                title='"Reading H7/g6"',
                audience='"reference"',
                kind='"reference_value"',
            ),
            "electrical/decoupling/draft-idea.md": authored(
                "An unreviewed decoupling thought.", title='"Draft"', status='"draft"'
            ),
        },
    )
    manifest = build_manifest(load_content_tree(root), load_release(root))
    (root / "manifest.json").write_text(json.dumps(manifest) + "\n")
    await ingest_corpus(clean_corpus, root=root)
    await clean_corpus.commit()
    return clean_corpus


async def test_every_route_requires_authentication(client: AsyncClient) -> None:
    for path in (
        "/api/v1/corpus/manifest",
        "/api/v1/corpus/search?q=x",
        f"/api/v1/corpus/chunks/{LOOP}",
    ):
        assert (await client.get(path)).status_code == 401, path


async def test_manifest_reports_the_applied_release(
    client: AsyncClient, alice_headers: dict[str, str], seeded: AsyncSession
) -> None:
    response = await client.get("/api/v1/corpus/manifest", headers=alice_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["corpus_version"] == "0.1.0" and data["chunk_count"] == 3
    assert data["manifest_hash"].startswith("sha256:")
    assert set(data) == {
        "corpus_version", "released_at", "policy_revision", "applied_at", "chunk_count",
        "manifest_hash",
    }  # fmt: skip


async def test_manifest_is_404_before_any_ingest(
    client: AsyncClient, alice_headers: dict[str, str], clean_corpus: AsyncSession
) -> None:
    response = await client.get("/api/v1/corpus/manifest", headers=alice_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "corpus_not_ingested"


async def test_search_is_domain_pure_and_hides_drafts(
    client: AsyncClient, alice_headers: dict[str, str], seeded: AsyncSession
) -> None:
    response = await client.get(
        "/api/v1/corpus/search",
        params={"q": "decoupling capacitor fit tolerance", "domain": "electrical", "limit": 5},
        headers=alice_headers,
    )
    assert response.status_code == 200
    ids = [hit["id"] for hit in response.json()["data"]]
    assert LOOP in ids and FIT not in ids and DRAFT not in ids
    hit = response.json()["data"][0]
    assert set(hit) == {
        "id", "title", "domain", "topic", "kind", "audience", "score", "confidence",
        "low_confidence", "excerpt",
    }  # fmt: skip
    assert "reviewer" not in json.dumps(response.json())


async def test_search_validates_its_inputs(
    client: AsyncClient, alice_headers: dict[str, str], seeded: AsyncSession
) -> None:
    assert (await client.get("/api/v1/corpus/search", headers=alice_headers)).status_code == 422
    too_long = await client.get(
        "/api/v1/corpus/search", params={"q": "x" * 501}, headers=alice_headers
    )
    assert too_long.status_code == 422
    big = await client.get(
        "/api/v1/corpus/search", params={"q": "x", "limit": 21}, headers=alice_headers
    )
    assert big.status_code == 422
    unknown = await client.get(
        "/api/v1/corpus/search",
        params={"q": "decoupling", "domain": "chemistry"},
        headers=alice_headers,
    )
    assert unknown.status_code == 200 and unknown.json()["data"] == []


async def test_chunk_view_carries_provenance_but_never_review_metadata(
    client: AsyncClient, alice_headers: dict[str, str], seeded: AsyncSession
) -> None:
    response = await client.get(f"/api/v1/corpus/chunks/{LOOP}", headers=alice_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == LOOP and data["status"] == "active"
    assert data["applicability"] == [{"key": "fabrication_class", "value": "prototype"}]
    assert data["further_reading"] == [
        {"title": "High-Speed Digital Design", "author": "Johnson", "identifier": "", "url": None}
    ]
    assert data["source"]["class"] == "solus_authored" and data["source"]["url"] is None
    for hidden in ("reviewer", "reviewed_at", "drafting", "content_hash", "embedding"):
        assert hidden not in data


async def test_drafts_and_unknown_ids_are_404(
    client: AsyncClient, alice_headers: dict[str, str], seeded: AsyncSession
) -> None:
    draft = await client.get(f"/api/v1/corpus/chunks/{DRAFT}", headers=alice_headers)
    missing = await client.get(
        "/api/v1/corpus/chunks/corpus:electrical/decoupling/nope", headers=alice_headers
    )
    assert draft.status_code == 404 and missing.status_code == 404
    assert draft.json()["error"]["code"] == "chunk_not_found"
    assert "unreviewed" not in draft.text


async def test_a_second_team_reads_the_same_corpus(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    seeded: AsyncSession,
) -> None:
    # Cross-tenant on purpose (ADR-036): the boundary is row content, not readership.
    a = await client.get(f"/api/v1/corpus/chunks/{FIT}", headers=alice_headers)
    b = await client.get(f"/api/v1/corpus/chunks/{FIT}", headers=bob_headers)
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
