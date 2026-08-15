"""SOLUS-TU-07 (SOLUSDEV-210) — versioning + staleness / re-verification.

Tool UIs change between releases, so knowledge is version-scoped (TU-04) and
carries a freshness signal. Stale-but-served is WORSE than absent: a confident
pointer at a control that moved is exactly the failure this lane must not
produce. So staleness (a) is detected from age since last verification, (b)
decays effective confidence so a stale entry renders tentative in Guide rather
than confident, and (c) is re-queued for acquisition rather than served as-is.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from solus_api.toolkb.schema import ToolKnowledgeEntry
from solus_api.toolkb.staleness import (
    STALE_AFTER_DAYS,
    effective_confidence,
    find_stale,
    is_stale,
    sweep_stale,
)
from sqlalchemy.ext.asyncio import AsyncSession

type EntryFactory = Callable[..., ToolKnowledgeEntry]

NOW = datetime(2026, 8, 8, tzinfo=UTC)


def _aged(
    make_entry: EntryFactory, *, days: float, verified: bool, **over: object
) -> ToolKnowledgeEntry:
    ts = NOW - timedelta(days=days)
    return make_entry(
        created_at=ts,
        last_verified_at=ts if verified else None,
        **over,
    )


# ------------------------------------------------------------------ detection
class TestIsStale:
    def test_fresh_entry_is_not_stale(self, make_entry: EntryFactory) -> None:
        assert not is_stale(_aged(make_entry, days=10, verified=True), now=NOW)

    def test_old_verified_entry_is_stale(self, make_entry: EntryFactory) -> None:
        assert is_stale(_aged(make_entry, days=STALE_AFTER_DAYS + 1, verified=True), now=NOW)

    def test_never_verified_falls_back_to_created_at(self, make_entry: EntryFactory) -> None:
        # an entry never re-verified but old since creation is stale
        assert is_stale(_aged(make_entry, days=STALE_AFTER_DAYS + 1, verified=False), now=NOW)
        assert not is_stale(_aged(make_entry, days=1, verified=False), now=NOW)


class TestEffectiveConfidence:
    def test_fresh_confidence_is_unchanged(self, make_entry: EntryFactory) -> None:
        e = _aged(make_entry, days=1, verified=True, confidence=0.9)
        assert effective_confidence(e, now=NOW) == pytest.approx(0.9)

    def test_stale_confidence_decays_below_tentative(self, make_entry: EntryFactory) -> None:
        # a high-confidence but long-unverified entry must not read as confident
        from solus_api.toolkb.guides import TENTATIVE_BELOW

        e = _aged(make_entry, days=STALE_AFTER_DAYS * 2, verified=True, confidence=0.9)
        assert effective_confidence(e, now=NOW) < TENTATIVE_BELOW

    def test_decay_is_monotonic(self, make_entry: EntryFactory) -> None:
        younger = _aged(make_entry, days=200, verified=True, confidence=0.9)
        older = _aged(make_entry, days=400, verified=True, confidence=0.9)
        assert effective_confidence(older, now=NOW) < effective_confidence(younger, now=NOW)


# -------------------------------------------------------------------- queries
async def test_find_stale_returns_only_stale_published(
    db: AsyncSession, make_entry: EntryFactory
) -> None:
    db.add(_aged(make_entry, days=1, verified=True, control_id="kicad.a.fresh"))
    db.add(_aged(make_entry, days=STALE_AFTER_DAYS + 5, verified=True, control_id="kicad.a.stale"))
    await db.flush()

    stale = await find_stale(db, now=NOW)
    assert [e.control_id for e in stale] == ["kicad.a.stale"]


async def test_sweep_requeues_stale_and_stamps_them(
    db: AsyncSession, make_entry: EntryFactory
) -> None:
    from solus_api.models import User, utcnow

    user = User(supabase_user_id="op", email="op@example.com", data_collection_consent=True)
    db.add(user)
    db.add(_aged(make_entry, days=STALE_AFTER_DAYS + 5, verified=True, control_id="kicad.a.stale"))
    await db.flush()

    count = await sweep_stale(db, user=user, now=utcnow())
    assert count == 1
    # the sweep emitted a re-verification event (queued for re-acquisition)
    from solus_api.models import DataEvent
    from sqlalchemy import select

    events = (await db.execute(select(DataEvent))).scalars().all()
    assert any(e.event_type == "tool_knowledge.staleness_flagged" for e in events)
