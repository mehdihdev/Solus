"""Cost formula + the post-call debit hook over the billing engine (ADR-024).

`compute_call_credits` (incl. MO-02b breakpoint pricing), the pre-flight
delegation to `billing.credits.check_spend_allowed`, `account_spend`, and
`track_cost`'s locked failure policy: atomic idempotent debit via the billing
engine; on failure defer to the dead-letter + immediate sweep enqueue; NEVER
raise. The billing engine's own internals are covered in test_credits.py /
test_reconciliation.py.
"""

import asyncio
import logging
import uuid
from typing import Any

import pytest
from solus_api.billing import credits as billing_credits
from solus_api.billing import reconciliation as billing_reconciliation
from solus_api.models import (
    CreditBalance,
    CreditLedger,
    CreditTxnType,
    DebitReconcileStatus,
    PendingCreditDebit,
    User,
)
from solus_api.orchestration.choice import ModelChoice
from solus_api.orchestration.config import CostConfig, ModelCatalogEntry
from solus_api.orchestration.cost import (
    RECONCILE_JOB_NAME,
    account_spend,
    compute_call_credits,
    has_sufficient_credits,
    track_cost,
)
from solus_api.orchestration.enums import Complexity, RouteType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def _model() -> ModelChoice:
    return ModelChoice(
        provider="anthropic",
        model_name="claude-sonnet-5",
        price_in=3.0,
        price_out=15.0,
        context_window=200_000,
        role="code_standard",
        complexity=Complexity.STANDARD,
        route_type=RouteType.CODE,
    )


def test_compute_call_credits_known_value() -> None:
    # 1M in @ $3 + 1M out @ $15 = $18; * 2.0 margin * 100 credits/$ = 3600.
    cost = CostConfig(credits_per_dollar=100.0)
    assert compute_call_credits(_model(), 1_000_000, 1_000_000, cost) == 3600


def test_compute_call_credits_rounds_up_nonzero() -> None:
    # A tiny real call still bills at least 1 credit (ceil), never 0.
    cost = CostConfig(credits_per_dollar=100.0)
    assert compute_call_credits(_model(), 1, 0, cost) == 1


def _long_priced_entry() -> ModelCatalogEntry:
    """A Gemini-Pro-shaped entry: $2/$12 flat, $4/$18 above 200K input tokens."""
    return ModelCatalogEntry(
        provider="google",
        name="gemini-pro-shaped",
        price_in=2.0,
        price_out=12.0,
        context_window=1_048_576,
        roles=["longctx_hard"],
        long_context_threshold_tokens=200_000,
        price_in_long=4.0,
        price_out_long=18.0,
    )


def _long_model() -> ModelChoice:
    """The ModelChoice route() would build FROM _long_priced_entry() — base
    prices always mirror the entry they were resolved from."""
    entry = _long_priced_entry()
    return ModelChoice(
        provider=entry.provider,
        model_name=entry.name,
        price_in=entry.price_in,
        price_out=entry.price_out,
        context_window=entry.context_window,
        role="longctx_hard",
        complexity=Complexity.HARD,
        route_type=RouteType.LONG_CONTEXT,
    )


def test_compute_call_credits_bills_long_rates_above_threshold() -> None:
    """MO-02b: the calls most likely to cross the breakpoint are exactly the
    LONG_CONTEXT-routed ones — flat rates would systematically under-bill them."""
    cost = CostConfig(credits_per_dollar=100.0)
    # 1M in @ $4 + 1M out @ $18 = $22; * 2.0 margin * 100 credits/$ = 4400.
    credits = compute_call_credits(
        _long_model(), 1_000_000, 1_000_000, cost, entry=_long_priced_entry()
    )
    assert credits == 4400


def test_compute_call_credits_at_or_below_threshold_uses_base_rates() -> None:
    cost = CostConfig(credits_per_dollar=100.0)
    # Exactly AT the threshold is not above it -> base rates apply.
    # 200K in @ $2 + 100K out @ $12 = $0.4 + $1.2 = $1.6; * 2.0 * 100 = 320.
    credits = compute_call_credits(
        _long_model(), 200_000, 100_000, cost, entry=_long_priced_entry()
    )
    assert credits == 320


def test_compute_call_credits_flat_entry_matches_no_entry() -> None:
    """Flat-priced entries (no breakpoint fields) bill identically to the
    entry-less call — the entry only matters when a threshold is configured."""
    cost = CostConfig(credits_per_dollar=100.0)
    flat = ModelCatalogEntry(
        provider="anthropic",
        name="m",
        price_in=3.0,
        price_out=15.0,
        context_window=1_000_000,
        roles=["code_standard"],
    )
    with_entry = compute_call_credits(_model(), 1_000_000, 1_000_000, cost, entry=flat)
    without = compute_call_credits(_model(), 1_000_000, 1_000_000, cost)
    assert with_entry == without == 3600


# --- track_cost over the billing engine (atomic, idempotent, reconciled) ------

_COST = CostConfig(credits_per_dollar=100.0)


async def _seed_user(db: AsyncSession, *, balance: int | None = None, spent_total: int = 0) -> User:
    tag = uuid.uuid4().hex[:10]
    user = User(supabase_user_id=f"sub-{tag}", email=f"{tag}@example.com")
    db.add(user)
    await db.flush()
    if balance is not None:
        db.add(CreditBalance(user_id=user.id, balance=balance, spent_total=spent_total))
    await db.commit()
    return user


async def _ledger_rows(db: AsyncSession, call_id: str) -> list[CreditLedger]:
    return list(
        (
            await db.scalars(select(CreditLedger).where(CreditLedger.idempotency_key == call_id))
        ).all()
    )


async def test_track_cost_debits_ledger_and_balance_atomically(db: AsyncSession) -> None:
    """Ticket gate #1: ledger debit == exactly compute_call_credits(...), keyed by
    call_id as the idempotency key, with the audit attrs, balance_after snapshot,
    and both cached totals updated."""
    user = await _seed_user(db, balance=500)
    model = _model()
    credits = compute_call_credits(model, 10_000, 5_000, _COST)
    await track_cost("call-debit", user.id, model, 10_000, 5_000, session=db, cost=_COST)
    rows = await _ledger_rows(db, "call-debit")
    assert len(rows) == 1
    row = rows[0]
    assert row.amount == -credits
    assert row.type == CreditTxnType.USAGE
    assert row.balance_after == 500 - credits
    assert row.attrs == {
        "call_id": "call-debit",
        "model_name": model.model_name,
        "role": model.role,
        "tokens_in": 10_000,
        "tokens_out": 5_000,
    }
    bal = await db.scalar(select(CreditBalance).where(CreditBalance.user_id == user.id))
    assert bal is not None
    assert bal.balance == 500 - credits
    assert bal.spent_total == credits


async def test_track_cost_creates_missing_balance_row(db: AsyncSession) -> None:
    """No CreditBalance row exists at provisioning today — the debit upserts one
    (balance goes negative for trial users; the ledger stays truthful)."""
    user = await _seed_user(db, balance=None)
    credits = compute_call_credits(_model(), 1_000, 1_000, _COST)
    await track_cost("call-norow", user.id, _model(), 1_000, 1_000, session=db, cost=_COST)
    bal = await db.scalar(select(CreditBalance).where(CreditBalance.user_id == user.id))
    assert bal is not None
    assert bal.balance == -credits
    assert bal.spent_total == credits


async def test_track_cost_same_call_id_twice_debits_once(db: AsyncSession) -> None:
    """Ticket gate #2 (CRITICAL): a retried call_id is a duplicate under the
    ledger idempotency key and no-ops — never a double debit."""
    user = await _seed_user(db, balance=1_000)
    # Capture the plain UUID: the retried call's rollback expires ORM instances.
    user_id = user.id
    credits = compute_call_credits(_model(), 2_000, 2_000, _COST)
    for _ in range(2):
        await track_cost("call-retry", user_id, _model(), 2_000, 2_000, session=db, cost=_COST)
    assert len(await _ledger_rows(db, "call-retry")) == 1
    bal = await db.scalar(select(CreditBalance).where(CreditBalance.user_id == user_id))
    assert bal is not None
    assert bal.balance == 1_000 - credits
    assert bal.spent_total == credits


async def test_track_cost_concurrent_same_call_id_is_race_safe(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """Two CONCURRENT debits with one call_id on separate sessions -> exactly one
    ledger row/debit (the balance-row lock serializes them; the partial-unique
    index is the backstop)."""
    user = await _seed_user(db, balance=1_000)
    credits = compute_call_credits(_model(), 3_000, 3_000, _COST)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def attempt() -> None:
        async with maker() as session:
            await track_cost(
                "call-race", user.id, _model(), 3_000, 3_000, session=session, cost=_COST
            )

    await asyncio.gather(attempt(), attempt())
    assert len(await _ledger_rows(db, "call-race")) == 1
    bal = await db.scalar(select(CreditBalance).where(CreditBalance.user_id == user.id))
    assert bal is not None
    assert bal.balance == 1_000 - credits
    assert bal.spent_total == credits


def _exploding_debit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exploding(*args: object, **kwargs: object) -> object:
        raise RuntimeError("db went away mid-debit")

    # Same module object cost.py imported — the patch is visible through it.
    monkeypatch.setattr(billing_credits, "debit_credits", exploding)


async def test_track_cost_failure_dead_letters_and_enqueues_sweep(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ticket gate #3: debit fails after the model already ran -> user keeps the
    result (no raise), the debit lands in the billing dead-letter, and the sweep
    job is enqueued for an immediate retry."""
    user = await _seed_user(db, balance=100)
    credits = compute_call_credits(_model(), 500, 500, _COST)
    _exploding_debit(monkeypatch)
    enqueued: list[tuple[str, dict[str, Any]]] = []

    async def fake_enqueue(job: str, payload: dict[str, Any]) -> None:
        enqueued.append((job, payload))

    await track_cost(
        "call-fail", user.id, _model(), 500, 500, session=db, cost=_COST, enqueue=fake_enqueue
    )
    assert enqueued == [(RECONCILE_JOB_NAME, {})]
    pending = await db.scalar(
        select(PendingCreditDebit).where(PendingCreditDebit.idempotency_key == "call-fail")
    )
    assert pending is not None
    assert pending.user_id == user.id
    assert pending.credits == credits
    assert pending.status == DebitReconcileStatus.PENDING
    assert pending.attrs["tokens_in"] == 500


async def test_track_cost_failure_without_enqueue_still_dead_letters(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Degraded path (no queue configured): the dead-letter row is still written —
    the worker cron sweeps it within a minute; still never raises."""
    user = await _seed_user(db, balance=100)
    _exploding_debit(monkeypatch)
    await track_cost("call-nofallback", user.id, _model(), 500, 500, session=db, cost=_COST)
    pending = await db.scalar(
        select(PendingCreditDebit).where(PendingCreditDebit.idempotency_key == "call-nofallback")
    )
    assert pending is not None


async def test_track_cost_total_failure_logs_payload_and_never_raises(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Worst case: the debit AND the dead-letter write AND the enqueue all fail.
    The payload is preserved in an ERROR log for manual recovery; never raises."""
    user = await _seed_user(db, balance=100)
    _exploding_debit(monkeypatch)

    async def exploding_record(*args: object, **kwargs: object) -> None:
        raise RuntimeError("dead-letter also down")

    async def broken_enqueue(job: str, payload: dict[str, Any]) -> None:
        raise ConnectionError("redis also down")

    monkeypatch.setattr(billing_reconciliation, "record_failed_debit", exploding_record)
    with caplog.at_level(logging.ERROR, logger="solus.orchestration.cost"):
        await track_cost(
            "call-allfail",
            user.id,
            _model(),
            500,
            500,
            session=db,
            cost=_COST,
            enqueue=broken_enqueue,
        )  # must not raise
    assert any("call-allfail" in record.getMessage() for record in caplog.records)


async def test_has_sufficient_credits_delegates_to_billing_gate(db: AsyncSession) -> None:
    """Pre-flight reads the cached balance via the billing gate — and balance 0
    blocks even a zero-cost estimate (the free-trial hard cap, SOLUSDEV-83)."""
    funded = await _seed_user(db, balance=100)
    broke = await _seed_user(db, balance=None)  # no row = 0 credits
    assert await has_sufficient_credits(funded.id, 50, session=db) is True
    assert await has_sufficient_credits(funded.id, 200, session=db) is False
    assert await has_sufficient_credits(broke.id, 1, session=db) is False
    assert await has_sufficient_credits(broke.id, 0, session=db) is False


async def test_account_spend_reports_all_time_usage(db: AsyncSession) -> None:
    """Documented semantics: all-time USAGE credits (== trial-period spend in v1)."""
    user = await _seed_user(db, balance=1_000)
    assert await account_spend(user.id, session=db) == 0
    await track_cost("call-spend", user.id, _model(), 10_000, 10_000, session=db, cost=_COST)
    credits = compute_call_credits(_model(), 10_000, 10_000, _COST)
    assert await account_spend(user.id, session=db) == credits
    nobody = await _seed_user(db, balance=None)
    assert await account_spend(nobody.id, session=db) == 0
