"""SOLUS-TU-08 (SOLUSDEV-211) — human confirm/reject loop.

Precision beats recall: a wrongly-learned meaning propagates to EVERY user, so
a reject pulls confidence down hard while a single confirm nudges it up. As of
TU-05 each vote is recorded per DISTINCT voter in the server-only observation
table, so counts reflect distinct people (not repeat clicks) and confidence is
a deterministic function of those counts — order-independent and auditable.

Low confidence then surfaces as tentative guidance via TU-07's
``effective_confidence``, never a confident wrong instruction. A confirm is also
a re-verification, so it refreshes ``last_verified_at``. Recording a vote may
also promote a corroborated candidate into the shared store, or retract one that
has fallen — see ``toolkb.sharing``.

`Verdict` and `recompute_confidence` live in `schema`/`sharing` now (so the
observation model and the promotion logic can share them without an import
cycle); they are re-exported here for existing callers.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import User, utcnow
from solus_api.services.events import emit_event
from solus_api.toolkb.schema import ToolKnowledgeEntry, Verdict
from solus_api.toolkb.sharing import (
    recompute_confidence,
    reconcile_entry,
    record_observation,
    voter_key,
)

__all__ = ["Verdict", "apply_feedback", "recompute_confidence"]

logger = logging.getLogger("solus.toolkb.feedback")


async def apply_feedback(
    session: AsyncSession,
    *,
    entry_id: uuid.UUID,
    verdict: Verdict,
    user: User,
    team_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> ToolKnowledgeEntry:
    """Record one voter's confirm/reject, recompute confidence, reconcile the
    entry's shared-store status, and emit the event.

    Idempotent per voter: the same user voting again updates their single vote,
    never inflates the count. Raises ``LookupError`` if there is no live entry.
    """
    # FOR UPDATE serializes concurrent votes on the SAME entry: without it two
    # voters race the read-recompute-write, each tallies only its own vote, and
    # the last write wins with a stale count/status (a missed promotion — review
    # finding). Locking the entry row makes the recompute atomic per entry.
    entry = await session.get(ToolKnowledgeEntry, entry_id, with_for_update=True)
    if entry is None or entry.deleted_at is not None:
        raise LookupError(f"no live tool_knowledge entry {entry_id}")

    await record_observation(
        session, knowledge_id=entry.id, voter_hash=voter_key(user.id), verdict=verdict
    )
    if verdict is Verdict.CONFIRM:
        entry.last_verified_at = utcnow()  # a confirmation IS a re-verification
    promoted = await reconcile_entry(session, entry)
    await session.flush()

    emit_event(
        session,
        user=user,
        event_type=f"tool_knowledge.{verdict.value}ed",
        team_id=team_id,
        project_id=project_id,
        payload={
            "tool": entry.tool.value,
            "control_id": entry.control_id,
            "confidence": round(entry.confidence, 3),
            "confirm_count": entry.confirm_count,
            "reject_count": entry.reject_count,
            "promoted": promoted,
            "status": entry.status.value,
        },
    )
    logger.info(
        "toolkb feedback %s: id=%s control=%s -> conf=%.3f (c=%d r=%d) status=%s",
        verdict.value,
        entry.id,
        entry.control_id,
        entry.confidence,
        entry.confirm_count,
        entry.reject_count,
        entry.status.value,
    )
    return entry
