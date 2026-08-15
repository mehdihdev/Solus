"""Dead-letter reconciliation for failed credit debits (SOLUSDEV-83 / ADR-024 W0-03)."""

import uuid

from solus_api.billing import credits, reconciliation
from solus_api.models import (
    CreditBalance,
    DebitReconcileStatus,
    PendingCreditDebit,
    User,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


async def _make_user(session: AsyncSession, email: str = "recon@example.com") -> uuid.UUID:
    user = User(supabase_user_id=f"sub-{email}", email=email)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user.id


async def _balance(session: AsyncSession, user_id: uuid.UUID) -> int | None:
    bal: int | None = await session.scalar(
        select(CreditBalance.balance).where(CreditBalance.user_id == user_id)
    )
    return bal


async def test_record_failed_debit_creates_pending(db: AsyncSession) -> None:
    user_id = await _make_user(db)
    await reconciliation.record_failed_debit(db, user_id, 40, idempotency_key="call-x", attrs={})
    row = await db.scalar(
        select(PendingCreditDebit).where(PendingCreditDebit.idempotency_key == "call-x")
    )
    assert row is not None
    assert row.credits == 40
    assert row.status is DebitReconcileStatus.PENDING


async def test_record_failed_debit_is_idempotent(db: AsyncSession) -> None:
    user_id = await _make_user(db)
    await reconciliation.record_failed_debit(db, user_id, 40, idempotency_key="dup", attrs={})
    await reconciliation.record_failed_debit(db, user_id, 40, idempotency_key="dup", attrs={})
    rows = (
        await db.scalars(
            select(PendingCreditDebit).where(PendingCreditDebit.idempotency_key == "dup")
        )
    ).all()
    assert len(rows) == 1


async def test_reconcile_applies_debit_and_marks_reconciled(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    user_id = await _make_user(db)
    await credits.grant_trial_credits(db, user_id, 100)
    await reconciliation.record_failed_debit(db, user_id, 40, idempotency_key="c-1", attrs={})

    maker = async_sessionmaker(engine, expire_on_commit=False)
    reconciled = await reconciliation.reconcile_pending_debits(maker)
    assert reconciled == 1

    assert await _balance(db, user_id) == 60  # 100 - 40 applied
    row = await db.scalar(
        select(PendingCreditDebit).where(PendingCreditDebit.idempotency_key == "c-1")
    )
    assert row is not None
    assert row.status is DebitReconcileStatus.RECONCILED


async def test_reconcile_is_idempotent_when_already_debited(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    user_id = await _make_user(db)
    await credits.grant_trial_credits(db, user_id, 100)
    # The debit already succeeded inline under this key…
    await credits.debit_credits(db, user_id, 40, idempotency_key="c-2")
    # …but a pending row was also recorded (belt-and-suspenders). Reconcile must
    # NOT double-debit — the ledger key dedupes it.
    await reconciliation.record_failed_debit(db, user_id, 40, idempotency_key="c-2", attrs={})

    maker = async_sessionmaker(engine, expire_on_commit=False)
    await reconciliation.reconcile_pending_debits(maker)

    assert await _balance(db, user_id) == 60  # still debited exactly once
    row = await db.scalar(
        select(PendingCreditDebit).where(PendingCreditDebit.idempotency_key == "c-2")
    )
    assert row is not None
    assert row.status is DebitReconcileStatus.RECONCILED


def test_reconcile_job_is_registered_on_the_worker() -> None:
    """The sweep is wired as an ARQ function AND a 1-minute cron — a dead-letter
    row is retried even when no caller enqueues an immediate sweep."""
    from typing import Any

    from solus_api.connectors.worker import build_worker_settings
    from solus_api.core.config import Settings

    # build_worker_settings returns a bare `type` (the class is built lazily);
    # Any-typed access mirrors how ARQ itself consumes it.
    worker_settings: Any = build_worker_settings(
        Settings(
            _env_file=None,  # type: ignore[call-arg]  # valid pydantic-settings runtime kwarg
            supabase_jwt_secret="test-only",
            redis_url="redis://localhost:6379",
        )
    )
    names = {fn.__name__ for fn in worker_settings.functions}
    assert "reconcile_credit_debits" in names
    cron_names = {job.coroutine.__name__ for job in worker_settings.cron_jobs}
    assert "reconcile_credit_debits" in cron_names
