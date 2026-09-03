"""Atomic, idempotent per-user credit operations (SOLUSDEV-83 / ADR-024).

Every mutation locks the user's cached balance row (`SELECT … FOR UPDATE`), so
concurrent operations on one account serialize — no lost updates, no double-spend.
Idempotency is enforced by a per-operation key: the append-only `credit_ledger`
has a partial-unique index on it, and each mutation checks-then-writes under the
lock, so a retry / webhook replay applies exactly once.

Two debit modes:
- guarded (`guard=True`): pre-purchase/reserve — refuses to drive the balance
  below zero (returns `insufficient`).
- unguarded (default): the post-call actual cost of a paid model call — recorded
  even if it dips the balance negative (ADR-024 W0-03: never fail a paid result;
  the pre-flight gate is the protection, not this debit).

Callers pass a session dedicated to the credit operation — these functions own
the transaction and commit it.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import CreditBalance, CreditLedger, CreditTxnType


@dataclass(frozen=True)
class CreditResult:
    applied: bool
    balance: int
    duplicate: bool = False
    insufficient: bool = False


def trial_grant_key(user_id: uuid.UUID) -> str:
    """Idempotency key for a user's one-time trial grant."""
    return f"trial-grant:{user_id}"


def plan_grant_key(user_id: uuid.UUID, plan: str) -> str:
    """Idempotency key for a plan's one-time starting-credit grant (ADR-023/024).
    Keyed per (user, plan): renewals never re-grant; an upgrade grants the new
    plan's amount exactly once."""
    return f"plan-grant:{user_id}:{plan}"


async def get_balance(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Cached balance for a user; 0 when no row exists yet."""
    bal = await session.scalar(
        select(CreditBalance.balance).where(CreditBalance.user_id == user_id)
    )
    return int(bal) if bal is not None else 0


async def check_spend_allowed(
    session: AsyncSession, user_id: uuid.UUID, estimated_credits: int
) -> bool:
    """Pre-flight gate (implements cost.has_sufficient_credits): allow a paid op
    only when the balance is positive and covers the estimate. At balance 0 this
    is the free-trial hard cap — paid operations are blocked.

    This read is unlocked (ADR-024 never blocks a served result), so N genuinely
    concurrent in-flight calls can each pass and overshoot by up to one call's
    actual cost PER concurrent slot before serialized pre-flights start blocking.
    Per-user concurrency/rate limits (ADR-019) bound N; the overshoot is bounded,
    not unbounded."""
    balance = await get_balance(session, user_id)
    return balance > 0 and balance >= estimated_credits


async def _ensure_balance_row(session: AsyncSession, user_id: uuid.UUID) -> None:
    # Concurrency-safe create-if-absent; ON CONFLICT DO NOTHING lets a second
    # concurrent op wait on the unique constraint and then no-op.
    await session.execute(
        pg_insert(CreditBalance)
        .values(user_id=user_id, balance=0)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )


async def _apply(
    session: AsyncSession,
    user_id: uuid.UUID,
    delta: int,
    txn_type: CreditTxnType,
    idempotency_key: str | None,
    attrs: dict[str, Any] | None,
    *,
    guard: bool,
    extension_id: uuid.UUID | None = None,
) -> CreditResult:
    """Lock the balance row, dedupe by key, apply the signed delta, append a
    ledger row, and commit. `delta` > 0 credits, < 0 debits. `extension_id`
    (ADR-035 §2) is attribution only — the row still debits `user_id`."""
    await _ensure_balance_row(session, user_id)
    bal_row = await session.scalar(
        select(CreditBalance).where(CreditBalance.user_id == user_id).with_for_update()
    )
    assert bal_row is not None  # guaranteed by _ensure_balance_row
    # Snapshot before any rollback — the ORM instance expires on rollback and a
    # later attribute access would trigger disallowed lazy IO.
    current = bal_row.balance

    if idempotency_key is not None:
        seen = await session.scalar(
            select(CreditLedger.id).where(CreditLedger.idempotency_key == idempotency_key)
        )
        if seen is not None:
            await session.rollback()
            return CreditResult(applied=False, balance=current, duplicate=True)

    if guard and delta < 0 and current + delta < 0:
        await session.rollback()
        return CreditResult(applied=False, balance=current, insufficient=True)

    new_balance = current + delta
    session.add(
        CreditLedger(
            user_id=user_id,
            amount=delta,
            type=txn_type,
            balance_after=new_balance,
            idempotency_key=idempotency_key,
            attrs=attrs or {},
            extension_id=extension_id,
        )
    )
    bal_row.balance = new_balance
    if txn_type is CreditTxnType.USAGE and delta < 0:
        # Rolling all-time USAGE total (MO-03): the trial cap's pre-flight
        # (cost.account_spend / gates.assert_can_spend) reads this O(1) instead
        # of scanning the ledger. Maintained here so inline debits AND
        # reconciliation sweeps both keep it truthful.
        bal_row.spent_total += -delta
    await session.commit()
    return CreditResult(applied=True, balance=new_balance)


async def grant_trial_credits(
    session: AsyncSession, user_id: uuid.UUID, amount: int
) -> CreditResult:
    """Grant the bounded free-trial credit allowance (ADR-024). Idempotent per
    user, so re-provisioning never double-grants."""
    return await _apply(
        session,
        user_id,
        amount,
        CreditTxnType.TRIAL_GRANT,
        trial_grant_key(user_id),
        {"reason": "trial_grant"},
        guard=False,
    )


async def add_credits(
    session: AsyncSession,
    user_id: uuid.UUID,
    amount: int,
    txn_type: CreditTxnType,
    *,
    idempotency_key: str,
    attrs: dict[str, Any] | None = None,
) -> CreditResult:
    """Add credits (purchase / refund / adjustment). Idempotent by key."""
    return await _apply(
        session, user_id, abs(amount), txn_type, idempotency_key, attrs, guard=False
    )


async def debit_credits(
    session: AsyncSession,
    user_id: uuid.UUID,
    credits_amount: int,
    *,
    idempotency_key: str,
    attrs: dict[str, Any] | None = None,
    guard: bool = False,
    extension_id: uuid.UUID | None = None,
) -> CreditResult:
    """Debit credits for one operation. Idempotent by key. `guard=True` refuses to
    go negative (reserve); default records the actual paid cost regardless.
    `extension_id` records which extension caused the debit (SOLUSDEV-235)."""
    return await _apply(
        session,
        user_id,
        -abs(credits_amount),
        CreditTxnType.USAGE,
        idempotency_key,
        attrs,
        guard=guard,
        extension_id=extension_id,
    )
