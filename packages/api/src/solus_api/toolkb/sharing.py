"""SOLUS-TU-05 (SOLUSDEV-208) — sharing / compounding.

A learning acquired on one install becomes available to others for the same
tool + version — but only when *corroborated*. A candidate is promoted to
`published` (the shared, every-tenant store) when it clears a confidence gate
AND has been confirmed by ≥ ``MIN_DISTINCT_VOTERS`` DISTINCT voters. Distinctness
is enforced by the server-only ``tool_knowledge_observation`` table keyed on a
salted per-voter hash (``voter_key``) with a UNIQUE (knowledge_id, voter_hash):
one voter, one vote per entry. So a single actor can never ballot-stuff an entry
into the shared store — the red-team invariant that also closes the TU-08 flag.

Promotion is order-independent: it always evaluates the FULL current tally, and
it is bidirectional — a promoted entry that later falls below the demote gate is
retracted from the shared store (docs-published entries are vendor-authoritative
and exempt; hysteresis between the promote and demote gates prevents flapping).

Everything project- or customer-specific is already structurally excluded from
the store by TU-06 — this layer only decides WHICH tool-knowledge entries are
shared, never widens WHAT they may contain.
"""

import hashlib
import logging
import secrets
import uuid
from typing import Final

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.config import REPO_ROOT
from solus_api.models import utcnow
from solus_api.toolkb.schema import (
    INITIAL_CONFIDENCE,
    AcquisitionMethod,
    KnowledgeStatus,
    ToolKnowledgeEntry,
    ToolKnowledgeObservation,
    Verdict,
)

logger = logging.getLogger("solus.toolkb.sharing")

# --- confidence model (lives here so sharing has no import cycle with feedback)
#: Smoothing prior: how many "base-confidence votes" the acquisition method is
#: worth before human votes move it. Higher = steadier; one stray vote matters less.
_PRIOR: Final = 3.0
#: A reject weighs this many times a confirm — precision over recall.
_REJECT_WEIGHT: Final = 3.0

# --- promotion gate -----------------------------------------------------------
#: A candidate needs confidence ≥ this AND ≥ MIN_DISTINCT_VOTERS confirms to share.
#: A published non-docs entry that no longer meets this is retracted — status is
#: a PURE function of the current tally (no hysteresis), so it is order-independent.
PROMOTE_CONFIDENCE: Final = 0.85
#: Corroboration floor. ≥ 2 guarantees a single voter can never auto-promote.
MIN_DISTINCT_VOTERS: Final = 2


class _ToolkbSettings(BaseSettings):
    """Reads the vote salt the SAME way the app reads every other secret — through
    pydantic, so a value in the root `.env` OR a real exported env var both work.
    Raw `os.environ` would miss `.env` entirely (nothing bridges it into the
    process env; the app runs uvicorn with no load_dotenv).

    `env_file` is ANCHORED to the repo root, exactly like `core.config.Settings`:
    a bare ".env" resolves against the process CWD, and every launcher cd's into a
    subdirectory first, so a relative path silently reads nothing. There is one
    env file, at the root.

    A local settings class rather than a field on `Settings` because this is read
    at import time, and `Settings` has a required `supabase_jwt_secret` — a bare
    `Settings()` here would raise before the app could report anything useful.
    """

    model_config = SettingsConfigDict(
        env_prefix="SOLUS_", env_file=REPO_ROOT / ".env", extra="ignore"
    )

    toolkb_vote_salt: str | None = None


def _load_vote_salt() -> str:
    """Salt for the one-way voter hash — a per-deployment secret so the
    server-only observation rows cannot be correlated back to a user even with
    DB read access (the §7.3 anonymity promise).

    NO secret is embedded in source (CLAUDE.md §7). A configured value (`.env` or
    env var) wins; when unset we use an ephemeral per-process random salt and warn
    loudly (the same degrade-with-warning posture as the connectors secret store).
    That keeps de-anonymization impossible in every configuration — the
    unconfigured cost is only that distinct-voter de-dup does not survive a
    restart, which is dev-only and must never be the prod path.
    """
    configured = _ToolkbSettings().toolkb_vote_salt
    if configured:
        return configured
    logger.warning(
        "SOLUS_TOOLKB_VOTE_SALT unset — using an ephemeral per-process salt; "
        "tool-knowledge vote de-dup will not survive a restart. Set it (Secrets "
        "Manager, or the root .env locally) in any shared or production environment."
    )
    return secrets.token_hex(32)


#: Rotating this resets de-dup: prior rows are hashed under the old salt, so a
#: returning voter re-hashes to a new key. Rotate only when that reset is intended.
_VOTE_SALT: Final = _load_vote_salt()


def recompute_confidence(acquired_via: AcquisitionMethod, *, confirms: int, rejects: int) -> float:
    """Deterministic confidence from the acquisition base and the vote counts.

    Beta-style smoothing: the acquisition base acts as ``_PRIOR`` pseudo-votes of
    agreement; confirms add agreement, rejects (weighted) add disagreement. Pure
    and order-independent — the same counts always yield the same value.
    """
    base = INITIAL_CONFIDENCE[acquired_via]
    agree = _PRIOR * base + confirms
    total = _PRIOR + confirms + _REJECT_WEIGHT * rejects
    return max(0.0, min(1.0, agree / total))


def voter_key(user_id: uuid.UUID) -> str:
    """A salted, one-way hash identifying a voter — never the raw id, no FK."""
    return hashlib.sha256(f"{_VOTE_SALT}:{user_id}".encode()).hexdigest()


async def record_observation(
    session: AsyncSession, *, knowledge_id: uuid.UUID, voter_hash: str, verdict: Verdict
) -> None:
    """Upsert one voter's verdict on one entry — a voter may change their mind,
    but never counts twice (the UNIQUE constraint is the dedup)."""
    stmt = (
        pg_insert(ToolKnowledgeObservation)
        .values(knowledge_id=knowledge_id, voter_hash=voter_hash, verdict=verdict)
        .on_conflict_do_update(
            constraint="uq_tk_observation_voter",
            set_={"verdict": verdict, "updated_at": utcnow()},
        )
    )
    await session.execute(stmt)


async def tally(session: AsyncSession, knowledge_id: uuid.UUID) -> tuple[int, int]:
    """(distinct confirms, distinct rejects) for an entry — each row is one voter."""
    rows = await session.execute(
        select(ToolKnowledgeObservation.verdict, func.count())
        .where(ToolKnowledgeObservation.knowledge_id == knowledge_id)
        .group_by(ToolKnowledgeObservation.verdict)
    )
    counts = {verdict: n for verdict, n in rows.all()}
    return counts.get(Verdict.CONFIRM, 0), counts.get(Verdict.REJECT, 0)


async def reconcile_entry(session: AsyncSession, entry: ToolKnowledgeEntry) -> bool:
    """Recount from the observation table, recompute confidence, and set the
    shared-store status. Returns True iff this call promoted a candidate.

    Status is a PURE function of the current tally (no hysteresis band), so it is
    genuinely order-independent: the same set of votes yields the same status
    regardless of arrival order, and an entry can never sit `published` while
    below the promote gate. `shareable` is exactly the promote condition; a
    non-docs entry is `published` iff shareable, else `candidate`.

    Docs-published entries are vendor-authoritative: votes move their confidence
    (so Guide can render them tentative) but never change their status.
    """
    confirms, rejects = await tally(session, entry.id)
    entry.confirm_count = confirms
    entry.reject_count = rejects
    entry.confidence = recompute_confidence(entry.acquired_via, confirms=confirms, rejects=rejects)

    if entry.acquired_via is AcquisitionMethod.DOCS:
        return False

    shareable = confirms >= MIN_DISTINCT_VOTERS and entry.confidence >= PROMOTE_CONFIDENCE
    if shareable and entry.status is KnowledgeStatus.CANDIDATE:
        entry.status = KnowledgeStatus.PUBLISHED
        entry.last_verified_at = utcnow()  # promotion re-verifies
        logger.info(
            "toolkb promoted to shared store: id=%s control=%s conf=%.3f confirms=%d",
            entry.id,
            entry.control_id,
            entry.confidence,
            confirms,
        )
        return True
    if not shareable and entry.status is KnowledgeStatus.PUBLISHED:
        # A promoted entry no longer meeting the gate is retracted — a confident
        # wrong entry served to every tenant is exactly the failure this lane
        # must not produce.
        entry.status = KnowledgeStatus.CANDIDATE
        logger.info(
            "toolkb retracted from shared store: id=%s control=%s conf=%.3f",
            entry.id,
            entry.control_id,
            entry.confidence,
        )
    return False


async def promote_eligible(session: AsyncSession) -> int:
    """Batch sweep: reconcile every live candidate against its observations and
    promote those that now qualify. The compounding pipeline — safe to run on a
    schedule; order-independent and idempotent."""
    candidates = (
        (
            await session.execute(
                select(ToolKnowledgeEntry).where(
                    ToolKnowledgeEntry.deleted_at.is_(None),
                    ToolKnowledgeEntry.status == KnowledgeStatus.CANDIDATE,
                )
            )
        )
        .scalars()
        .all()
    )
    promoted = 0
    for entry in candidates:
        if await reconcile_entry(session, entry):
            promoted += 1
    await session.flush()
    if promoted:
        logger.info(
            "toolkb promotion sweep: promoted %d candidate(s) to the shared store", promoted
        )
    return promoted
