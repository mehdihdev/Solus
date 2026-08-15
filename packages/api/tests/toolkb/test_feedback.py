"""SOLUS-TU-08 (SOLUSDEV-211) — human confirm/reject loop.

Precision beats recall: a wrongly-learned meaning propagates to EVERY user, so
a reject must pull confidence down HARD and fast, while a single confirm nudges
it up. Low confidence then surfaces as tentative guidance (via TU-07's
effective_confidence), never a confident wrong instruction. The recompute is
deterministic from the acquisition base + the confirm/reject counts, so it is
auditable and order-independent.
"""

import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient
from solus_api.toolkb.feedback import Verdict, recompute_confidence
from solus_api.toolkb.schema import AcquisitionMethod, ToolKnowledgeEntry
from sqlalchemy.ext.asyncio import AsyncSession

type EntryFactory = Callable[..., ToolKnowledgeEntry]


# --------------------------------------------------------- pure recompute
class TestRecompute:
    def test_no_votes_is_the_acquisition_base(self) -> None:
        base = 0.8  # docs tier
        assert recompute_confidence(AcquisitionMethod.DOCS, confirms=0, rejects=0) == pytest.approx(
            base
        )

    def test_confirms_raise_confidence(self) -> None:
        c0 = recompute_confidence(AcquisitionMethod.OPERATOR, confirms=0, rejects=0)
        c5 = recompute_confidence(AcquisitionMethod.OPERATOR, confirms=5, rejects=0)
        assert c5 > c0

    def test_rejects_drop_confidence_hard(self) -> None:
        # two rejects on a docs-tier entry must push it well below the tentative
        # threshold — precision over recall
        from solus_api.toolkb.guides import TENTATIVE_BELOW

        c = recompute_confidence(AcquisitionMethod.DOCS, confirms=0, rejects=2)
        assert c < TENTATIVE_BELOW

    def test_a_reject_outweighs_a_confirm(self) -> None:
        balanced = recompute_confidence(AcquisitionMethod.DOCS, confirms=1, rejects=1)
        base = recompute_confidence(AcquisitionMethod.DOCS, confirms=0, rejects=0)
        assert balanced < base

    def test_stays_in_unit_interval(self) -> None:
        assert recompute_confidence(AcquisitionMethod.VISUAL, confirms=1000, rejects=0) <= 1.0
        assert recompute_confidence(AcquisitionMethod.VISUAL, confirms=0, rejects=1000) >= 0.0


# ------------------------------------------------------------- endpoint
async def _entry(db: AsyncSession, make_entry: EntryFactory, **over: object) -> ToolKnowledgeEntry:
    row = make_entry(**over)
    db.add(row)
    await db.flush()
    return row


async def test_confirm_raises_and_stamps_verification(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    make_entry: EntryFactory,
) -> None:
    row = await _entry(db, make_entry, confidence=0.8)
    await db.commit()

    resp = await client.post(
        f"/api/v1/toolkb/entries/{row.id}/feedback",
        json={"verdict": "confirm"},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["confirm_count"] == 1
    assert data["confidence"] >= 0.8

    await db.refresh(row)
    assert row.confirm_count == 1
    assert row.last_verified_at is not None


async def test_no_toolkb_route_leaks_voter_identity(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    make_entry: EntryFactory,
) -> None:
    """The §7.3 boundary: the observation table is server-only. No /toolkb
    response — the feedback ack or the served entry — may carry a voter_hash,
    a voter/observation field, or any per-vote record (only aggregate counts)."""
    from solus_api.toolkb.sharing import voter_key

    row = await _entry(db, make_entry, confidence=0.8)
    await db.commit()
    resp = await client.post(
        f"/api/v1/toolkb/entries/{row.id}/feedback",
        json={"verdict": "confirm"},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    # the ack is aggregate-only — exact key set, no voter dimension
    assert set(resp.json()["data"]) == {"id", "confidence", "confirm_count", "reject_count"}

    listed = await client.get(
        "/api/v1/toolkb/entries", params={"tool": "kicad"}, headers=alice_headers
    )
    # neither the alice voter hash nor any voter/observation field appears anywhere
    assert voter_key(uuid.UUID(int=0)) not in listed.text
    for banned in ("voter_hash", "voter", "observation"):
        assert banned not in listed.text
        assert banned not in resp.text


async def test_reject_lowers_confidence_and_renders_tentative(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    make_entry: EntryFactory,
) -> None:
    from solus_api.toolkb.guides import TENTATIVE_BELOW

    row = await _entry(db, make_entry, confidence=0.8)
    await db.commit()

    for _ in range(2):
        resp = await client.post(
            f"/api/v1/toolkb/entries/{row.id}/feedback",
            json={"verdict": "reject"},
            headers=alice_headers,
        )
        assert resp.status_code == 200
    assert resp.json()["data"]["confidence"] < TENTATIVE_BELOW


async def test_feedback_requires_auth_and_valid_verdict(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    make_entry: EntryFactory,
) -> None:
    row = await _entry(db, make_entry)
    await db.commit()
    assert (
        await client.post(f"/api/v1/toolkb/entries/{row.id}/feedback", json={"verdict": "confirm"})
    ).status_code == 401
    bad = await client.post(
        f"/api/v1/toolkb/entries/{row.id}/feedback",
        json={"verdict": "maybe"},
        headers=alice_headers,
    )
    assert bad.status_code == 422


async def test_feedback_on_missing_entry_is_404(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.post(
        f"/api/v1/toolkb/entries/{uuid.uuid4()}/feedback",
        json={"verdict": "confirm"},
        headers=alice_headers,
    )
    assert resp.status_code == 404


def test_verdict_enum() -> None:
    assert {v.value for v in Verdict} == {"confirm", "reject"}
