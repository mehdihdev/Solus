"""Cost formula + the real credit pre-flight gate and post-call debit (ADR-024)."""

from solus_api.billing import credits
from solus_api.models import CreditBalance, CreditLedger, CreditTxnType, User
from solus_api.orchestration.choice import ModelChoice
from solus_api.orchestration.config import CostConfig
from solus_api.orchestration.cost import (
    compute_call_credits,
    has_sufficient_credits,
    track_cost,
)
from solus_api.orchestration.enums import Complexity, RouteType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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


async def _make_user(session: AsyncSession, email: str = "cost@example.com") -> User:
    user = User(supabase_user_id=f"sub-{email}", email=email)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def test_has_sufficient_credits_reads_balance(db: AsyncSession) -> None:
    user = await _make_user(db)
    await credits.grant_trial_credits(db, user.id, 100)
    assert await has_sufficient_credits(user.id, 50, session=db) is True
    assert await has_sufficient_credits(user.id, 101, session=db) is False


async def test_track_cost_debits_actual_usage(db: AsyncSession) -> None:
    cost = CostConfig(credits_per_dollar=100.0)
    user = await _make_user(db)
    await credits.grant_trial_credits(db, user.id, 100)
    # 1000 in + 1000 out on sonnet: $0.018 * 2.0 * 100 = ceil 4 credits.
    expected = compute_call_credits(_model(), 1000, 1000, cost)
    assert expected == 4

    await track_cost("call-1", user.id, _model(), 1000, 1000, session=db, cost=cost)
    balance = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == user.id))
    assert balance == 100 - expected
    row = await db.scalar(select(CreditLedger).where(CreditLedger.idempotency_key == "call-1"))
    assert row is not None
    assert row.type is CreditTxnType.USAGE
    assert row.amount == -expected


async def test_track_cost_is_idempotent(db: AsyncSession) -> None:
    cost = CostConfig(credits_per_dollar=100.0)
    user = await _make_user(db)
    uid = user.id  # snapshot: the replay's duplicate path rolls back and expires ORM state
    await credits.grant_trial_credits(db, uid, 100)
    await track_cost("call-9", uid, _model(), 1000, 1000, session=db, cost=cost)
    await track_cost("call-9", uid, _model(), 1000, 1000, session=db, cost=cost)  # replay
    balance = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == uid))
    assert balance == 96  # debited exactly once (4 credits)
