"""Atomic, idempotent credit deduction + trial grant (SOLUSDEV-83 / ADR-024).

The money core: concurrent calls must never double-spend, never go negative on
the guarded path, and a repeated idempotency key must apply exactly once.
"""

import asyncio
import uuid

from conftest import bearer
from httpx import AsyncClient
from solus_api.billing import credits
from solus_api.models import CreditBalance, CreditLedger, CreditTxnType, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


async def _make_user(session: AsyncSession, email: str = "credit@example.com") -> uuid.UUID:
    user = User(supabase_user_id=f"sub-{email}", email=email)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    # Return the plain id: a rollback inside a credit op expires ORM instances,
    # and real callers pass a uuid anyway.
    return user.id


async def _balance(session: AsyncSession, user_id: uuid.UUID) -> int | None:
    # Select the scalar column (not the ORM object) so a read after the credit
    # op's commit/rollback doesn't trigger expired-attribute lazy IO.
    bal: int | None = await session.scalar(
        select(CreditBalance.balance).where(CreditBalance.user_id == user_id)
    )
    return bal


async def test_grant_trial_credits_creates_balance_and_ledger(db: AsyncSession) -> None:
    user_id = await _make_user(db)
    await credits.grant_trial_credits(db, user_id, 1000)
    assert await _balance(db, user_id) == 1000
    ledger = (
        await db.scalars(select(CreditLedger).where(CreditLedger.type == CreditTxnType.TRIAL_GRANT))
    ).all()
    assert len(ledger) == 1
    assert ledger[0].amount == 1000
    assert ledger[0].balance_after == 1000


async def test_grant_trial_credits_is_idempotent(db: AsyncSession) -> None:
    user_id = await _make_user(db)
    await credits.grant_trial_credits(db, user_id, 1000)
    await credits.grant_trial_credits(db, user_id, 1000)  # replay
    assert await _balance(db, user_id) == 1000  # not 2000


async def test_check_spend_allowed(db: AsyncSession) -> None:
    user_id = await _make_user(db)
    await credits.grant_trial_credits(db, user_id, 100)
    assert await credits.check_spend_allowed(db, user_id, 50) is True
    assert await credits.check_spend_allowed(db, user_id, 100) is True
    assert await credits.check_spend_allowed(db, user_id, 101) is False


async def test_check_spend_allowed_blocks_at_zero(db: AsyncSession) -> None:
    user_id = await _make_user(db)
    await credits.grant_trial_credits(db, user_id, 0)
    assert await credits.check_spend_allowed(db, user_id, 1) is False


async def test_debit_applies_and_writes_usage_ledger(db: AsyncSession) -> None:
    user_id = await _make_user(db)
    await credits.grant_trial_credits(db, user_id, 100)
    result = await credits.debit_credits(db, user_id, 30, idempotency_key="call-1")
    assert result.applied is True
    assert result.balance == 70
    assert await _balance(db, user_id) == 70


async def test_debit_is_idempotent(db: AsyncSession) -> None:
    user_id = await _make_user(db)
    await credits.grant_trial_credits(db, user_id, 100)
    await credits.debit_credits(db, user_id, 30, idempotency_key="call-1")
    dup = await credits.debit_credits(db, user_id, 30, idempotency_key="call-1")
    assert dup.duplicate is True
    assert await _balance(db, user_id) == 70  # applied once


async def test_guarded_debit_rejects_when_insufficient(db: AsyncSession) -> None:
    user_id = await _make_user(db)
    await credits.grant_trial_credits(db, user_id, 20)
    result = await credits.debit_credits(db, user_id, 50, idempotency_key="p-1", guard=True)
    assert result.insufficient is True
    assert result.applied is False
    assert await _balance(db, user_id) == 20  # never went negative


async def test_ungarded_post_call_debit_may_exceed_balance(db: AsyncSession) -> None:
    # ADR-024 W0-03: a paid call's actual cost is recorded even if it dips the
    # balance below zero (the pre-flight gate is the protection, not this debit).
    user_id = await _make_user(db)
    await credits.grant_trial_credits(db, user_id, 20)
    result = await credits.debit_credits(db, user_id, 50, idempotency_key="c-1")
    assert result.applied is True
    assert await _balance(db, user_id) == -30


async def test_add_credits_purchase(db: AsyncSession) -> None:
    user_id = await _make_user(db)
    await credits.grant_trial_credits(db, user_id, 100)
    result = await credits.add_credits(
        db, user_id, 500, CreditTxnType.PURCHASE, idempotency_key="pack-1"
    )
    assert result.applied is True
    assert await _balance(db, user_id) == 600


async def test_first_login_grants_trial_credits(client: AsyncClient, db: AsyncSession) -> None:
    headers = bearer("sub-trial", "trial@example.com")
    resp = await client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 200
    uid = uuid.UUID(resp.json()["data"]["id"])
    assert await _balance(db, uid) == 1000  # default trial_credit_grant


# --- concurrency ----------------------------------------------------------


async def test_concurrent_same_key_applies_once(db: AsyncSession, engine: AsyncEngine) -> None:
    user_id = await _make_user(db)
    await credits.grant_trial_credits(db, user_id, 1000)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def one() -> None:
        async with maker() as s:
            await credits.debit_credits(s, user_id, 100, idempotency_key="same")

    await asyncio.gather(*[one() for _ in range(10)])

    ledger_count = await db.scalar(
        select(func.count()).select_from(CreditLedger).where(CreditLedger.idempotency_key == "same")
    )
    assert ledger_count == 1
    assert await _balance(db, user_id) == 900  # debited exactly once


async def test_concurrent_guarded_debits_never_overspend(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    user_id = await _make_user(db)
    await credits.grant_trial_credits(db, user_id, 100)  # affords exactly 5 × 20
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def one(i: int) -> bool:
        async with maker() as s:
            r = await credits.debit_credits(s, user_id, 20, idempotency_key=f"g-{i}", guard=True)
            return r.applied

    results = await asyncio.gather(*[one(i) for i in range(12)])
    assert sum(results) == 5  # only 5 of 12 succeed
    assert await _balance(db, user_id) == 0  # never negative
