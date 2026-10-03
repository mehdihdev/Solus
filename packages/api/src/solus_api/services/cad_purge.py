"""Delete-on-revocation for the durable CAD store, built to never be lost (ADR-038 §1).

Revoking a grant promises that the derived copies of the customer's CAD are gone.
A best-effort inline delete cannot keep that promise (S3 can fail, a worker can die,
a sync can still be writing), so the promise is a DATABASE RECORD:

1. `schedule_cad_purge` runs inside the revoking transaction. It tombstones the account
   in Redis (so an in-flight sync cannot write after the purge), and inserts a
   `CadPurgeRequest` holding only the opaque account hash. The record commits or rolls
   back with the revocation.
2. After the commit the request path calls `run_cad_purges_after_commit`: it tries the
   purge inline, bounded by a timeout, and a failure is logged, never raised — the
   user's revoke has already succeeded.
3. Whatever is still due is retried with exponential backoff by the ARQ cron
   (`purge_cad_accounts`) and at API startup. Without a worker (inline mode) it is also
   retried by the next revoke / disconnect / account-deletion request on any account,
   and by the next API start.
4. Each record runs `PASSES` times: the second pass, `DELAYED_PASS_SECONDS` later, sweeps
   up any object a sync that was already running wrote after the first pass. The record
   is deleted only after the last pass found the prefix empty.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.models import CadPurgeRequest
from solus_api.storage.cad_store import CadStore, account_hash

logger = logging.getLogger("solus.services.cad_purge")

#: First pass right away, second after the delay (catches in-flight syncs).
PASSES = 2
#: Longer than the tombstone's reach is not needed: the tombstone blocks new writes for an
#: hour; this pass only has to run after any sync that started before the revoke has ended.
DELAYED_PASS_SECONDS = 15 * 60
BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 3600
#: Records processed per run, so one run (and its row locks) stays short.
BATCH = 10
#: The inline attempt after a commit must not hold the user's response hostage.
INLINE_TIMEOUT_SECONDS = 15.0


def scope_hash(provider: str, account_ref: str) -> str:
    return account_hash(f"{provider}:{account_ref}")


def _backoff_seconds(attempts: int) -> int:
    return int(min(BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0), BACKOFF_MAX_SECONDS))


async def enqueue_cad_purge(
    session: AsyncSession, hashes: Iterable[str], *, now: datetime | None = None
) -> None:
    """Record the duty (idempotent per account; re-enqueueing resets the passes).
    Joins the caller's transaction — it does not commit."""
    stamp = now or datetime.now(UTC)
    for digest in dict.fromkeys(hashes):
        insert = pg_insert(CadPurgeRequest).values(
            account_hash=digest,
            passes_remaining=PASSES,
            attempts=0,
            next_attempt_at=stamp,
            created_at=stamp,
        )
        await session.execute(
            insert.on_conflict_do_update(
                index_elements=[CadPurgeRequest.account_hash],
                set_={"passes_remaining": PASSES, "attempts": 0, "next_attempt_at": stamp},
            )
        )


async def schedule_cad_purge(
    session: AsyncSession, cache: IntegrationCache, provider: str, account_refs: Iterable[str]
) -> None:
    """Tombstone each account, then queue its purge in the caller's transaction.
    A no-op when this deployment has no durable store (nothing was ever written)."""
    if cache.durable_store is None:
        return
    refs = list(dict.fromkeys(account_refs))
    for ref in refs:
        await cache.tombstone_account(provider, ref)
    await enqueue_cad_purge(session, [scope_hash(provider, ref) for ref in refs])


async def run_due_cad_purges(
    session: AsyncSession,
    store: CadStore | None,
    *,
    now: datetime | None = None,
    limit: int = BATCH,
) -> int:
    """Run every due record once. Returns how many completed a pass.

    A failing record keeps its pass count, backs off and is retried; it is never
    dropped and never raises out of here. Safe under concurrent runners
    (`SKIP LOCKED`)."""
    if store is None:
        return 0
    stamp = now or datetime.now(UTC)
    rows = (
        await session.scalars(
            select(CadPurgeRequest)
            .where(CadPurgeRequest.next_attempt_at <= stamp)
            .order_by(CadPurgeRequest.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    completed = 0
    for row in rows:
        try:
            await store.delete_account_hash(row.account_hash)
        except Exception:  # noqa: BLE001 — retried with backoff; the record is the safety net
            row.attempts += 1
            row.next_attempt_at = stamp + timedelta(seconds=_backoff_seconds(row.attempts))
            logger.error(
                "durable CAD purge failed for account %s (attempt %d); will retry",
                row.account_hash[:12],
                row.attempts,
                exc_info=True,
            )
            continue
        completed += 1
        row.passes_remaining -= 1
        if row.passes_remaining <= 0:
            await session.delete(row)
        else:
            row.attempts = 0
            row.next_attempt_at = stamp + timedelta(seconds=DELAYED_PASS_SECONDS)
    await session.commit()
    return completed


async def run_cad_purges_after_commit(
    session: AsyncSession,
    store: CadStore | None,
    *,
    timeout_seconds: float = INLINE_TIMEOUT_SECONDS,
) -> None:
    """The inline attempt after a revoking commit: bounded, and never raises."""
    if store is None:
        return
    try:
        async with asyncio.timeout(timeout_seconds):
            await run_due_cad_purges(session, store)
    except Exception:  # noqa: BLE001 — the revoke already succeeded; the record retries
        logger.warning("inline durable CAD purge did not finish; it will be retried", exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("could not roll back after a failed inline CAD purge")


async def run_startup_cad_purges(
    sessionmaker: Callable[[], AsyncSession], store: CadStore | None
) -> None:
    """API start: drain whatever was due while no process was running. Never raises
    (a purge problem must not stop the API booting)."""
    if store is None:
        return
    try:
        async with sessionmaker() as session:
            await run_cad_purges_after_commit(session, store)
    except Exception:  # noqa: BLE001
        logger.warning("startup durable CAD purge could not run", exc_info=True)
