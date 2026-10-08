"""`grant_plan_credits` parity with the helper it was extracted from (SOLUSDEV-313)."""

import uuid
from typing import Any

import pytest
from solus_api.billing.plan_grants import grant_plan_credits
from solus_api.models import (
    CreditBalance,
    CreditLedger,
    CreditTxnType,
    Notification,
    NotificationType,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

GRANTS = {"basic": 2500, "pro": 10000}


async def _user_with_sub(
    maker: async_sessionmaker[AsyncSession],
    plan: PlanType = PlanType.BASIC,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
) -> uuid.UUID:
    uid = uuid.uuid4()
    async with maker() as s:
        s.add(User(id=uid, supabase_user_id=f"x-{uid}", email=f"{uid}@example.com"))
        await s.flush()
        s.add(Subscription(user_id=uid, plan=plan, status=status, limits=default_limits(plan)))
        await s.commit()
    return uid


async def _grant(maker: async_sessionmaker[AsyncSession], uid: uuid.UUID, grants: Any) -> None:
    async with maker() as s:
        sub = await s.scalar(select(Subscription).where(Subscription.user_id == uid))
        assert sub is not None
        await grant_plan_credits(s, sub, grants)
        await s.commit()


async def _grant_count(maker: async_sessionmaker[AsyncSession], uid: uuid.UUID) -> int:
    async with maker() as s:
        return int(
            await s.scalar(
                select(func.count())
                .select_from(CreditLedger)
                .where(
                    CreditLedger.user_id == uid,
                    CreditLedger.type == CreditTxnType.PLAN_GRANT,
                )
            )
            or 0
        )


@pytest.fixture
def maker(engine: Any) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_live_plan_is_granted_once_and_notified(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    uid = await _user_with_sub(maker)
    await _grant(maker, uid, GRANTS)
    async with maker() as s:
        bal = await s.scalar(select(CreditBalance).where(CreditBalance.user_id == uid))
        notes = (await s.scalars(select(Notification).where(Notification.user_id == uid))).all()
    assert bal is not None and bal.balance == 2500
    assert [n.type for n in notes] == [NotificationType.PAYMENT_SUCCEEDED]


async def test_replay_is_idempotent_and_silent(maker: async_sessionmaker[AsyncSession]) -> None:
    uid = await _user_with_sub(maker)
    await _grant(maker, uid, GRANTS)
    await _grant(maker, uid, GRANTS)
    assert await _grant_count(maker, uid) == 1
    async with maker() as s:
        count = await s.scalar(
            select(func.count()).select_from(Notification).where(Notification.user_id == uid)
        )
    assert count == 1


async def test_upgrade_grants_the_new_plan_exactly_once(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    uid = await _user_with_sub(maker)
    await _grant(maker, uid, GRANTS)
    async with maker() as s:
        sub = await s.scalar(select(Subscription).where(Subscription.user_id == uid))
        assert sub is not None
        sub.plan = PlanType.PRO
        await s.commit()
    await _grant(maker, uid, GRANTS)
    await _grant(maker, uid, GRANTS)
    assert await _grant_count(maker, uid) == 2


@pytest.mark.parametrize("status", [SubscriptionStatus.CANCELED, SubscriptionStatus.PAST_DUE])
async def test_non_live_status_grants_nothing(
    maker: async_sessionmaker[AsyncSession], status: SubscriptionStatus
) -> None:
    uid = await _user_with_sub(maker, status=status)
    await _grant(maker, uid, GRANTS)
    assert await _grant_count(maker, uid) == 0


async def test_trialing_is_live_and_granted(maker: async_sessionmaker[AsyncSession]) -> None:
    uid = await _user_with_sub(maker, status=SubscriptionStatus.TRIALING)
    await _grant(maker, uid, GRANTS)
    assert await _grant_count(maker, uid) == 1


@pytest.mark.parametrize("grants", [{}, {"basic": 0}, {"pro": 5}])
async def test_missing_or_zero_amount_for_the_plan_is_a_no_op(
    maker: async_sessionmaker[AsyncSession], grants: dict[str, int]
) -> None:
    uid = await _user_with_sub(maker)
    await _grant(maker, uid, grants)
    assert await _grant_count(maker, uid) == 0


async def test_pending_changes_are_committed_before_the_grant(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Commit-before-grant: a duplicate-key rollback must not discard pending updates."""
    uid = await _user_with_sub(maker)
    await _grant(maker, uid, GRANTS)
    async with maker() as s:
        sub = await s.scalar(select(Subscription).where(Subscription.user_id == uid))
        assert sub is not None
        sub.seat_count = 7  # pending, uncommitted
        await grant_plan_credits(s, sub, GRANTS)  # duplicate key -> credit tx rolls back
    async with maker() as s:
        sub = await s.scalar(select(Subscription).where(Subscription.user_id == uid))
        assert sub is not None and sub.seat_count == 7
