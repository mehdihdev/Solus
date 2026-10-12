"""Materialising expired staff comps (SOLUSDEV-313 T6)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from solus_api.billing.comp_expiry import sweep_expired_comps
from solus_api.models import (
    Notification,
    NotificationType,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
Maker = async_sessionmaker[AsyncSession]


@pytest.fixture
def maker(engine: Any) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _user(maker: Maker, **fields: Any) -> uuid.UUID:
    uid = uuid.uuid4()
    async with maker() as s:
        s.add(User(id=uid, supabase_user_id=f"x-{uid}", email=f"{uid}@example.com"))
        await s.flush()
        fields = {"status": SubscriptionStatus.ACTIVE, **fields}
        s.add(
            Subscription(
                user_id=uid,
                plan=PlanType.BASIC,
                limits=default_limits(PlanType.BASIC),
                **fields,
            )
        )
        await s.commit()
    return uid


async def _sub(maker: Maker, uid: uuid.UUID) -> Subscription:
    async with maker() as s:
        sub = await s.scalar(select(Subscription).where(Subscription.user_id == uid))
    assert sub is not None
    return sub


async def _sweep(maker: Maker, **kw: Any) -> list[uuid.UUID]:
    async with maker() as s:
        return await sweep_expired_comps(s, now=NOW, **kw)


async def test_expired_comp_is_cleared_and_user_notified(maker: Maker) -> None:
    uid = await _user(
        maker,
        comp_plan=PlanType.PRO,
        comp_expires_at=NOW - timedelta(minutes=1),
        limits_override={"max_teams": 3},
    )
    assert await _sweep(maker) == [uid]
    row = await _sub(maker, uid)
    assert row.comp_plan is None and row.comp_expires_at is None
    assert row.plan is PlanType.BASIC and row.limits_override == {"max_teams": 3}
    async with maker() as s:
        (note,) = (await s.scalars(select(Notification).where(Notification.user_id == uid))).all()
    assert note.type is NotificationType.SUBSCRIPTION_ENDED
    assert note.body is not None and "complimentary Pro access ended" in note.body


async def test_boundary_expiry_exactly_now_is_swept(maker: Maker) -> None:
    uid = await _user(maker, comp_plan=PlanType.PRO, comp_expires_at=NOW)
    assert await _sweep(maker) == [uid]


async def test_second_sweep_is_a_noop(maker: Maker) -> None:
    uid = await _user(maker, comp_plan=PlanType.PRO, comp_expires_at=NOW - timedelta(days=1))
    await _sweep(maker)
    assert await _sweep(maker) == []
    async with maker() as s:
        notes = (await s.scalars(select(Notification).where(Notification.user_id == uid))).all()
    assert len(notes) == 1


async def test_unexpired_forever_stripe_backed_and_uncomped_rows_are_left_alone(
    maker: Maker,
) -> None:
    future = await _user(maker, comp_plan=PlanType.PRO, comp_expires_at=NOW + timedelta(days=1))
    forever = await _user(maker, comp_plan=PlanType.PRO, comp_expires_at=None)
    stripe = await _user(
        maker,
        comp_plan=PlanType.PRO,
        comp_expires_at=NOW - timedelta(days=1),
        stripe_subscription_id="sub_live1",
    )
    plain = await _user(maker)
    assert await _sweep(maker) == []
    for uid, plan in ((future, PlanType.PRO), (forever, PlanType.PRO), (stripe, PlanType.PRO)):
        assert (await _sub(maker, uid)).comp_plan is plan
    assert (await _sub(maker, plain)).comp_plan is None
    async with maker() as s:
        assert (await s.scalars(select(Notification))).all() == []


async def test_canceled_stripe_row_counts_as_local_and_is_swept(maker: Maker) -> None:
    uid = await _user(
        maker,
        comp_plan=PlanType.PRO,
        comp_expires_at=NOW - timedelta(days=1),
        stripe_subscription_id="sub_old1",
        status=SubscriptionStatus.CANCELED,
    )
    assert await _sweep(maker) == [uid]


async def test_sweep_is_batch_limited_and_resumes(maker: Maker) -> None:
    ids = [
        await _user(maker, comp_plan=PlanType.PRO, comp_expires_at=NOW - timedelta(days=3 - i))
        for i in range(3)
    ]
    first = await _sweep(maker, limit=2, max_batches=1)
    assert first == ids[:2]  # oldest expiry first
    assert await _sweep(maker, limit=2, max_batches=1) == [ids[2]]


async def _expired_users(maker: Maker, count: int) -> list[uuid.UUID]:
    return [
        await _user(
            maker, comp_plan=PlanType.PRO, comp_expires_at=NOW - timedelta(days=count + 1 - i)
        )
        for i in range(count)
    ]


async def test_sweep_loops_batches_until_nothing_is_left(maker: Maker) -> None:
    ids = await _expired_users(maker, 5)
    assert await _sweep(maker, limit=2) == ids  # 3 batches: 2 + 2 + 1
    async with maker() as s:
        assert len((await s.scalars(select(Notification))).all()) == 5
    assert await _sweep(maker, limit=2) == []


async def test_sweep_stops_at_the_batch_cap_and_the_next_run_resumes(maker: Maker) -> None:
    ids = await _expired_users(maker, 5)
    assert await _sweep(maker, limit=1, max_batches=3) == ids[:3]
    assert await _sweep(maker, limit=1, max_batches=3) == ids[3:]


async def test_each_batch_is_committed_before_the_next(maker: Maker) -> None:
    ids = await _expired_users(maker, 3)
    visible: list[int] = []
    async with maker() as s:
        real_commit = s.commit

        async def observing_commit() -> None:
            await real_commit()
            async with maker() as other:  # another session sees the batch right away
                visible.append(len((await other.scalars(select(Notification))).all()))

        s.commit = observing_commit  # type: ignore[method-assign]
        assert await sweep_expired_comps(s, now=NOW, limit=1) == ids
    assert visible[:3] == [1, 2, 3]


async def test_invalid_max_batches_rejected(maker: Maker) -> None:
    with pytest.raises(ValueError):
        await _sweep(maker, max_batches=0)


async def test_soft_deleted_rows_are_ignored(maker: Maker) -> None:
    uid = await _user(
        maker, comp_plan=PlanType.PRO, comp_expires_at=NOW - timedelta(days=1), deleted_at=NOW
    )
    assert await _sweep(maker) == []
    assert (await _sub(maker, uid)).comp_plan is PlanType.PRO


async def test_invalid_limit_rejected(maker: Maker) -> None:
    with pytest.raises(ValueError):
        await _sweep(maker, limit=0)


async def test_default_now_uses_the_clock(maker: Maker) -> None:
    uid = await _user(
        maker, comp_plan=PlanType.PRO, comp_expires_at=datetime(2020, 1, 1, tzinfo=UTC)
    )
    async with maker() as s:
        assert await sweep_expired_comps(s) == [uid]
