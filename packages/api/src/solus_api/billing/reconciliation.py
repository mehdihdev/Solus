"""Dead-letter reconciliation for credit debits (SOLUSDEV-83 / ADR-024 W0-03).

A paid model call must never fail the user's request on the accounting write. If
the inline debit fails (DB race/outage), the post-call hook records a
`PendingCreditDebit` here; an ARQ worker sweeps and retries it idempotently until
reconciled — so credits converge without ever blocking a served result.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.billing import credits
from solus_api.models import DebitReconcileStatus, PendingCreditDebit

logger = logging.getLogger("solus.billing.reconciliation")

MAX_ATTEMPTS = 5
SWEEP_LIMIT = 200


async def record_failed_debit(
    session: AsyncSession,
    user_id: uuid.UUID,
    credits_amount: int,
    *,
    idempotency_key: str,
    attrs: dict[str, Any] | None = None,
) -> None:
    """Record a debit that could not be applied inline. Idempotent by the
    operation key — a repeat (or a retry that also failed) never duplicates."""
    await session.execute(
        pg_insert(PendingCreditDebit)
        .values(
            user_id=user_id,
            credits=abs(credits_amount),
            idempotency_key=idempotency_key,
            attrs=attrs or {},
            status=DebitReconcileStatus.PENDING,
            attempts=0,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    await session.commit()


async def reconcile_pending_debits(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    max_attempts: int = MAX_ATTEMPTS,
    limit: int = SWEEP_LIMIT,
) -> int:
    """Retry every pending debit idempotently. Success (incl. a duplicate the
    ledger already recorded) → RECONCILED; a failure bumps `attempts` and, past
    `max_attempts`, marks FAILED for human follow-up. Returns the count reconciled."""
    async with sessionmaker() as session:
        rows = (
            await session.scalars(
                select(PendingCreditDebit)
                .where(PendingCreditDebit.status == DebitReconcileStatus.PENDING)
                .limit(limit)
            )
        ).all()
        work = [
            (r.id, r.user_id, r.credits, r.idempotency_key, dict(r.attrs), r.attempts) for r in rows
        ]

    reconciled = 0
    for pid, user_id, amount, key, attrs, attempts in work:
        try:
            async with sessionmaker() as s:
                # The ledger idempotency key dedupes against an inline debit that
                # may have already applied — never double-debits.
                await credits.debit_credits(s, user_id, amount, idempotency_key=key, attrs=attrs)
            async with sessionmaker() as s:
                row = await s.get(PendingCreditDebit, pid)
                if row is not None:
                    row.status = DebitReconcileStatus.RECONCILED
                    await s.commit()
            reconciled += 1
        except Exception as exc:  # noqa: BLE001 — a retry failure must not stall the sweep
            logger.exception("credit reconcile failed pending=%s", pid)
            async with sessionmaker() as s:
                row = await s.get(PendingCreditDebit, pid)
                if row is not None:
                    row.attempts = attempts + 1
                    row.last_error = str(exc)[:1024]
                    if row.attempts >= max_attempts:
                        row.status = DebitReconcileStatus.FAILED
                    await s.commit()
    return reconciled


async def reconcile_credit_debits(ctx: dict[str, Any]) -> int:
    """ARQ task/cron entrypoint — sweep the dead-letter queue."""
    return await reconcile_pending_debits(ctx["sessionmaker"])
