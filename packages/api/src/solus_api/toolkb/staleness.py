"""SOLUS-TU-07 (SOLUSDEV-210) — versioning + staleness / re-verification.

Version scoping itself lives in `schema.py` (every entry carries a version
window; a query for a version the KB has no entry for simply returns nothing,
so a NEW tool release surfaces as "unavailable" in Guide — an honest gap, not
a stale answer). This module adds the FRESHNESS half:

- `is_stale` — an entry not re-verified within `STALE_AFTER_DAYS` (falling back
  to its creation time when never verified).
- `effective_confidence` — confidence decays with age so a long-unverified
  entry reads as tentative in Guide instead of confident. Stale-but-served is
  worse than absent: a confident pointer at a control that moved is precisely
  the failure this lane must not produce.
- `find_stale` / `sweep_stale` — detect stale published entries and re-queue
  them for acquisition (emit a data event; the actual re-probe belongs to the
  acquisition ladder / a future ARQ task, and needs the tools this host lacks).
"""

import logging
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import User, ensure_utc
from solus_api.services.events import emit_event
from solus_api.toolkb.schema import KnowledgeStatus, ToolKnowledgeEntry

logger = logging.getLogger("solus.toolkb.staleness")

#: Re-verify roughly twice a year — tool UIs drift on ~annual release cycles.
STALE_AFTER_DAYS: Final = 180
#: Recently-verified entries keep full confidence (no penalty for freshness).
_DECAY_GRACE_DAYS: Final = 30
#: Age at which decayed confidence reaches zero (a long-abandoned entry).
_DECAY_ZERO_DAYS: Final = STALE_AFTER_DAYS * 4


def _reference_time(entry: ToolKnowledgeEntry) -> datetime:
    """When the entry was last known-good: its verification, else its creation."""
    return ensure_utc(entry.last_verified_at or entry.created_at)


def age_days(entry: ToolKnowledgeEntry, *, now: datetime) -> float:
    return (now - _reference_time(entry)).total_seconds() / 86400.0


def is_stale(entry: ToolKnowledgeEntry, *, now: datetime) -> bool:
    return age_days(entry, now=now) > STALE_AFTER_DAYS


def effective_confidence(entry: ToolKnowledgeEntry, *, now: datetime) -> float:
    """Stored confidence scaled by a freshness factor that reaches 0 at
    `_DECAY_ZERO_DAYS`. Fresh entries are unchanged; stale ones fall below the
    Guide tentative threshold and so never render as confident."""
    age = age_days(entry, now=now)
    if age <= _DECAY_GRACE_DAYS:
        return entry.confidence  # recently verified — full confidence
    span = _DECAY_ZERO_DAYS - _DECAY_GRACE_DAYS
    freshness = max(0.0, 1.0 - (age - _DECAY_GRACE_DAYS) / span)
    return entry.confidence * freshness


async def find_stale(
    session: AsyncSession, *, now: datetime, limit: int = 500
) -> list[ToolKnowledgeEntry]:
    """Published, live entries whose last-known-good time is older than the cap."""
    cutoff = now - timedelta(days=STALE_AFTER_DAYS)
    stmt = (
        select(ToolKnowledgeEntry)
        .where(
            ToolKnowledgeEntry.deleted_at.is_(None),
            ToolKnowledgeEntry.status == KnowledgeStatus.PUBLISHED,
        )
        .order_by(ToolKnowledgeEntry.created_at.asc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    # last_verified_at ?? created_at compared in Python (COALESCE across two
    # timestamptz columns is awkward to keep driver-portable; the set is bounded).
    return [e for e in rows if _reference_time(e) < cutoff]


async def sweep_stale(session: AsyncSession, *, user: User, now: datetime) -> int:
    """Flag every stale published entry for re-acquisition. Returns the count.

    Emits `tool_knowledge.staleness_flagged` per entry (the re-queue signal;
    real re-probing is the acquisition ladder's job). Does NOT delete or mutate
    the entry — it stays served but reads as tentative via `effective_confidence`
    until re-verification refreshes `last_verified_at`.
    """
    stale = await find_stale(session, now=now)
    for entry in stale:
        emit_event(
            session,
            user=user,
            event_type="tool_knowledge.staleness_flagged",
            payload={
                "tool": entry.tool.value,
                "control_id": entry.control_id,
                "version_range": entry.version_range,
                "age_days": round(age_days(entry, now=now)),
            },
        )
    logger.info("toolkb staleness sweep flagged %d entries for re-acquisition", len(stale))
    return len(stale)
