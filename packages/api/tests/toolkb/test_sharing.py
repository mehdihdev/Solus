"""SOLUS-TU-05 (SOLUSDEV-208) — sharing / compounding.

A learning acquired on one install becomes available to others for the same
tool + version, but ONLY when it is corroborated: a candidate auto-promotes to
published (shared) when it clears a confidence threshold AND has been confirmed
by ≥ MIN_DISTINCT_VOTERS *distinct* voters. Distinctness is enforced by a
server-only observation table keyed on a salted per-voter hash — no user/team/
project FK, never exposed on any read route — so a single actor can never
ballot-stuff an entry into the shared store (the red-team invariant that also
closes the TU-08 flag). Everything project- or customer-specific is already
structurally excluded by TU-06.
"""

import uuid
from collections.abc import Callable

import pytest
from solus_api.contracts.tool_knowledge import ToolFamily
from solus_api.models import User
from solus_api.toolkb.feedback import apply_feedback
from solus_api.toolkb.schema import (
    AcquisitionMethod,
    KnowledgeStatus,
    ToolKnowledgeEntry,
    ToolKnowledgeObservation,
    Verdict,
    version_keys,
)
from solus_api.toolkb.sharing import (
    MIN_DISTINCT_VOTERS,
    PROMOTE_CONFIDENCE,
    promote_eligible,
    record_observation,
    tally,
    voter_key,
)
from solus_api.toolkb.storage import query_entries
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

type EntryFactory = Callable[..., ToolKnowledgeEntry]


def _candidate(make_entry: EntryFactory, **over: object) -> ToolKnowledgeEntry:
    low, high = version_keys(">=9.0 <10.0")
    fields: dict[str, object] = {
        "status": KnowledgeStatus.CANDIDATE,
        "acquired_via": AcquisitionMethod.API_GEOMETRY,
        "provenance": "observed_ui",
        "confidence": 0.9,
        "version_range": ">=9.0 <10.0",
        "version_min_key": low,
        "version_max_key": high,
    }
    fields.update(over)
    return make_entry(**fields)


async def _mk_user(db: AsyncSession, n: int) -> User:
    user = User(supabase_user_id=f"voter-{n}", email=f"voter{n}@example.com")
    db.add(user)
    await db.flush()
    return user


# ------------------------------------------------------------------ voter key
class TestVoterKey:
    def test_deterministic_per_user(self) -> None:
        uid = uuid.uuid4()
        assert voter_key(uid) == voter_key(uid)

    def test_distinct_users_distinct_keys(self) -> None:
        assert voter_key(uuid.uuid4()) != voter_key(uuid.uuid4())

    def test_is_opaque_not_the_raw_id(self) -> None:
        uid = uuid.uuid4()
        assert str(uid) not in voter_key(uid)  # salted hash, not the id

    def test_configured_salt_is_honored_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regression: the salt MUST be read from configuration (env / .env),
        not silently fall back to the ephemeral salt — otherwise a deployment's
        configured salt is ignored and vote de-dup breaks across restarts."""
        from solus_api.toolkb import sharing

        monkeypatch.setenv("SOLUS_TOOLKB_VOTE_SALT", "a-configured-salt-value")
        assert sharing._load_vote_salt() == "a-configured-salt-value"

    def test_unset_salt_falls_back_to_ephemeral(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from solus_api.toolkb import sharing

        monkeypatch.delenv("SOLUS_TOOLKB_VOTE_SALT", raising=False)
        # pydantic would still read packages/api/.env if the key were there; the
        # test asserts the shape of the fallback, not that .env is absent — a
        # 64-hex ephemeral salt distinct from any short configured value.
        salt = sharing._load_vote_salt()
        assert isinstance(salt, str) and len(salt) >= 32


# ------------------------------------------------------------- observations
async def test_record_observation_dedups_per_voter(
    db: AsyncSession, make_entry: EntryFactory
) -> None:
    entry = _candidate(make_entry)
    db.add(entry)
    await db.flush()
    key = voter_key(uuid.uuid4())

    await record_observation(db, knowledge_id=entry.id, voter_hash=key, verdict=Verdict.CONFIRM)
    await record_observation(db, knowledge_id=entry.id, voter_hash=key, verdict=Verdict.CONFIRM)
    # a voter may change their mind — latest verdict wins, still one row
    await record_observation(db, knowledge_id=entry.id, voter_hash=key, verdict=Verdict.REJECT)
    await db.flush()

    rows = await db.scalar(select(func.count()).select_from(ToolKnowledgeObservation))
    assert rows == 1
    confirms, rejects = await tally(db, entry.id)
    assert (confirms, rejects) == (0, 1)


async def test_tally_counts_distinct_voters(db: AsyncSession, make_entry: EntryFactory) -> None:
    entry = _candidate(make_entry)
    db.add(entry)
    await db.flush()
    for _ in range(3):
        await record_observation(
            db, knowledge_id=entry.id, voter_hash=voter_key(uuid.uuid4()), verdict=Verdict.CONFIRM
        )
    await record_observation(
        db, knowledge_id=entry.id, voter_hash=voter_key(uuid.uuid4()), verdict=Verdict.REJECT
    )
    await db.flush()
    assert await tally(db, entry.id) == (3, 1)


# --------------------------------------------------------------- promotion
async def test_single_voter_can_never_auto_promote(
    db: AsyncSession, make_entry: EntryFactory
) -> None:
    """The red-team invariant: one actor voting confirm any number of times
    stays one distinct voter, so the entry is never shared."""
    entry = _candidate(make_entry)
    db.add(entry)
    await db.flush()
    user = await _mk_user(db, 1)

    for _ in range(10):
        await apply_feedback(db, entry_id=entry.id, verdict=Verdict.CONFIRM, user=user)
    await db.refresh(entry)
    assert entry.status is KnowledgeStatus.CANDIDATE
    assert entry.confirm_count == 1  # one DISTINCT voter, not ten

    served, _ = await query_entries(db, tool=ToolFamily.KICAD, version="9.0.4")
    assert entry.id not in {r.id for r in served}


async def test_distinct_voters_promote_a_candidate_to_shared(
    db: AsyncSession, make_entry: EntryFactory
) -> None:
    entry = _candidate(make_entry)
    db.add(entry)
    await db.flush()

    # two distinct users confirm an api_geometry candidate (base 0.9)
    for i in range(MIN_DISTINCT_VOTERS):
        user = await _mk_user(db, i)
        result = await apply_feedback(db, entry_id=entry.id, verdict=Verdict.CONFIRM, user=user)

    await db.refresh(entry)
    assert entry.status is KnowledgeStatus.PUBLISHED
    assert entry.confidence >= PROMOTE_CONFIDENCE
    assert result.last_verified_at is not None  # promotion re-verifies

    # now shared: served to any tenant querying the tool + version
    served, _ = await query_entries(db, tool=ToolFamily.KICAD, version="9.0.4")
    assert entry.id in {r.id for r in served}


async def test_low_confidence_blocks_promotion_even_with_corroboration(
    db: AsyncSession, make_entry: EntryFactory
) -> None:
    # a visual candidate (base 0.5) confirmed by exactly MIN_DISTINCT_VOTERS is
    # corroborated but still below the confidence gate → stays a candidate
    entry = _candidate(make_entry, acquired_via=AcquisitionMethod.VISUAL, confidence=0.5)
    db.add(entry)
    await db.flush()
    for i in range(MIN_DISTINCT_VOTERS):
        user = await _mk_user(db, i)
        await apply_feedback(db, entry_id=entry.id, verdict=Verdict.CONFIRM, user=user)
    await db.refresh(entry)
    # concrete, not a conditional guard: visual base 0.5 + 2 confirms settles at
    # 0.7, which is corroborated (≥ MIN voters) yet below the 0.85 gate → not shared
    assert entry.confirm_count == MIN_DISTINCT_VOTERS
    assert entry.confidence == pytest.approx(0.7)
    assert entry.confidence < PROMOTE_CONFIDENCE
    assert entry.status is KnowledgeStatus.CANDIDATE


async def test_rejects_keep_a_corroborated_entry_out_of_the_store(
    db: AsyncSession, make_entry: EntryFactory
) -> None:
    entry = _candidate(make_entry)
    db.add(entry)
    await db.flush()
    # two confirms would promote; two rejects alongside them drag confidence down
    for i in range(MIN_DISTINCT_VOTERS):
        await apply_feedback(
            db, entry_id=entry.id, verdict=Verdict.CONFIRM, user=await _mk_user(db, i)
        )
    for i in range(4):
        await apply_feedback(
            db, entry_id=entry.id, verdict=Verdict.REJECT, user=await _mk_user(db, 100 + i)
        )
    await db.refresh(entry)
    assert entry.status is KnowledgeStatus.CANDIDATE  # confidence gate held


@pytest.mark.parametrize(
    "order",
    [
        [Verdict.CONFIRM, Verdict.CONFIRM, Verdict.CONFIRM, Verdict.REJECT],  # confirms front-run
        [Verdict.CONFIRM, Verdict.REJECT, Verdict.CONFIRM, Verdict.CONFIRM],  # reject interleaved
    ],
)
async def test_status_is_order_independent(
    db: AsyncSession, make_entry: EntryFactory, order: list[Verdict]
) -> None:
    """The security-review counterexample: {3 confirms, 1 reject} on a 0.9-base
    candidate must reach the SAME final status regardless of arrival order — it
    must NOT stay published below the promote gate just because confirms landed
    first (confidence settles at ~0.63 < 0.85)."""
    entry = _candidate(make_entry)
    db.add(entry)
    await db.flush()
    for i, verdict in enumerate(order):
        await apply_feedback(db, entry_id=entry.id, verdict=verdict, user=await _mk_user(db, i))
    await db.refresh(entry)
    assert entry.confidence < PROMOTE_CONFIDENCE
    assert entry.status is KnowledgeStatus.CANDIDATE


async def test_promote_eligible_sweep(db: AsyncSession, make_entry: EntryFactory) -> None:
    # observations accrued out-of-band; a batch sweep promotes what now qualifies
    entry = _candidate(make_entry)
    db.add(entry)
    await db.flush()
    for _ in range(MIN_DISTINCT_VOTERS):
        await record_observation(
            db, knowledge_id=entry.id, voter_hash=voter_key(uuid.uuid4()), verdict=Verdict.CONFIRM
        )
    await db.flush()

    promoted = await promote_eligible(db)
    assert promoted == 1
    await db.refresh(entry)
    assert entry.status is KnowledgeStatus.PUBLISHED


async def test_already_published_is_not_reprocessed(
    db: AsyncSession, make_entry: EntryFactory
) -> None:
    entry = _candidate(make_entry, status=KnowledgeStatus.PUBLISHED)
    db.add(entry)
    await db.flush()
    for _ in range(MIN_DISTINCT_VOTERS):
        await record_observation(
            db, knowledge_id=entry.id, voter_hash=voter_key(uuid.uuid4()), verdict=Verdict.CONFIRM
        )
    await db.flush()
    assert await promote_eligible(db) == 0
