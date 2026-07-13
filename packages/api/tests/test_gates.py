"""MO-03 pre-flight gates: Redis frequency cap + trial/balance spend gate."""

import logging
import uuid
from typing import Any

import pytest
from solus_api.models import (
    CreditBalance,
    DataEvent,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
)
from solus_api.orchestration.config import LimitsConfig
from solus_api.orchestration.gates import (
    FrequencyCapExceededError,
    InsufficientCreditsError,
    TrialCapReachedError,
    assert_can_spend,
    check_frequency_cap,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class FakeRedis:
    """The five sorted-set commands the sliding-window cap uses — no network."""

    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}
        self.expirations: dict[str, int] = {}

    async def zremrangebyscore(self, key: str, low: float, high: float) -> int:
        zset = self.zsets.setdefault(key, {})
        stale = [m for m, score in zset.items() if low <= score <= high]
        for member in stale:
            del zset[member]
        return len(stale)

    async def zcard(self, key: str) -> int:
        return len(self.zsets.get(key, {}))

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        self.zsets.setdefault(key, {}).update(mapping)
        return len(mapping)

    async def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True

    async def zrange(self, key: str, start: int, stop: int, withscores: bool = False) -> list[Any]:
        ordered = sorted(self.zsets.get(key, {}).items(), key=lambda item: item[1])
        window = ordered[start : stop + 1 if stop >= 0 else None]
        return [(m, s) for m, s in window] if withscores else [m for m, _ in window]


_LIMITS = LimitsConfig(max_calls_per_minute=3, frequency_window_seconds=60)


async def test_frequency_cap_blocks_at_limit_and_recovers_after_window() -> None:
    user_id = uuid.uuid4()
    redis = FakeRedis()
    for _ in range(3):
        await check_frequency_cap(user_id, redis=redis, limits=_LIMITS, now=1_000.0)
    with pytest.raises(FrequencyCapExceededError) as excinfo:
        await check_frequency_cap(user_id, redis=redis, limits=_LIMITS, now=1_001.0)
    assert 0 < excinfo.value.retry_after_seconds <= 60
    assert "try again" in str(excinfo.value).lower()  # transient, NOT an upgrade error
    # After the window slides past the oldest call, the user can retry.
    await check_frequency_cap(user_id, redis=redis, limits=_LIMITS, now=1_061.0)


async def test_frequency_cap_is_per_user_with_expiry() -> None:
    redis = FakeRedis()
    alice, bob = uuid.uuid4(), uuid.uuid4()
    for _ in range(3):
        await check_frequency_cap(alice, redis=redis, limits=_LIMITS, now=1_000.0)
    await check_frequency_cap(bob, redis=redis, limits=_LIMITS, now=1_000.0)  # unaffected
    assert redis.expirations[f"solus:freqcap:{alice}"] == 60  # TTL set — keys self-clean


async def test_frequency_cap_fails_open_without_redis(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """User-confirmed policy: no Redis -> proceed with a loud structured warning
    (the DB-backed spend cap still bounds sequential damage)."""
    with caplog.at_level(logging.WARNING, logger="solus.orchestration.gates"):
        await check_frequency_cap(uuid.uuid4(), redis=None, limits=_LIMITS)
    assert any("fail-open" in record.message for record in caplog.records)


class BrokenRedis:
    """A configured-but-unreachable Redis: every command raises."""

    async def zremrangebyscore(self, key: str, low: float, high: float) -> int:
        raise ConnectionError("redis unreachable")

    async def zcard(self, key: str) -> int:
        raise ConnectionError("redis unreachable")

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        raise ConnectionError("redis unreachable")

    async def expire(self, key: str, seconds: int) -> bool:
        raise ConnectionError("redis unreachable")

    async def zrange(self, key: str, start: int, stop: int, withscores: bool = False) -> list[Any]:
        raise ConnectionError("redis unreachable")


async def test_frequency_cap_fails_open_when_redis_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Security-review MEDIUM-2: a CONFIGURED Redis that starts erroring must
    apply the SAME fail-open policy — never fail closed as a mislabeled
    provider error, never take down all model calls."""
    with caplog.at_level(logging.WARNING, logger="solus.orchestration.gates"):
        await check_frequency_cap(uuid.uuid4(), redis=BrokenRedis(), limits=_LIMITS)
    assert any("fail-open" in record.message for record in caplog.records)


async def _seed(
    db: AsyncSession,
    *,
    status: SubscriptionStatus | None,
    balance: int | None = None,
    spent_total: int = 0,
    consent: bool = False,
) -> uuid.UUID:
    tag = uuid.uuid4().hex[:10]
    user = User(
        supabase_user_id=f"sub-{tag}",
        email=f"{tag}@example.com",
        data_collection_consent=consent,
    )
    db.add(user)
    await db.flush()
    if status is not None:
        db.add(Subscription(user_id=user.id, plan=PlanType.BASIC, status=status))
    if balance is not None:
        db.add(CreditBalance(user_id=user.id, balance=balance, spent_total=spent_total))
    await db.commit()
    return user.id


async def test_trialing_user_at_cap_is_blocked_with_upgrade_error(db: AsyncSession) -> None:
    limits = LimitsConfig(trial_credit_cap=100)
    user_id = await _seed(db, status=SubscriptionStatus.TRIALING, balance=0, spent_total=100)
    with pytest.raises(TrialCapReachedError) as excinfo:
        await assert_can_spend(user_id, session=db, limits=limits)
    message = str(excinfo.value)
    assert "trial" in message.lower()
    assert "upgrade" in message.lower()
    assert excinfo.value.upgrade_url == "/settings/billing"


async def test_trialing_user_under_cap_passes_even_with_zero_balance(db: AsyncSession) -> None:
    """Trial users are cap-gated, not balance-gated (no grant flow exists yet;
    their balance may go negative during trial — the ledger stays truthful)."""
    limits = LimitsConfig(trial_credit_cap=100)
    user_id = await _seed(db, status=SubscriptionStatus.TRIALING, balance=0, spent_total=99)
    await assert_can_spend(user_id, session=db, limits=limits)  # no raise


async def test_active_user_is_gated_on_balance_not_trial_cap(db: AsyncSession) -> None:
    limits = LimitsConfig(trial_credit_cap=100)
    broke = await _seed(db, status=SubscriptionStatus.ACTIVE, balance=0, spent_total=10_000)
    funded = await _seed(db, status=SubscriptionStatus.ACTIVE, balance=5, spent_total=10_000)
    with pytest.raises(InsufficientCreditsError):
        await assert_can_spend(broke, session=db, limits=limits)
    await assert_can_spend(funded, session=db, limits=limits)  # spend over cap is fine when paid


async def test_user_without_subscription_is_blocked_on_empty_balance(db: AsyncSession) -> None:
    user_id = await _seed(db, status=None, balance=None)
    with pytest.raises(InsufficientCreditsError):
        await assert_can_spend(user_id, session=db, limits=LimitsConfig())


async def test_block_emits_consented_data_event(db: AsyncSession) -> None:
    """§7: budget/rate-limit blocks are logged to the data-collection system."""
    limits = LimitsConfig(trial_credit_cap=50)
    user_id = await _seed(
        db, status=SubscriptionStatus.TRIALING, balance=0, spent_total=50, consent=True
    )
    with pytest.raises(TrialCapReachedError):
        await assert_can_spend(user_id, session=db, limits=limits)
    event = await db.scalar(select(DataEvent).where(DataEvent.user_id == user_id))
    assert event is not None
    assert event.event_type == "orchestration.blocked"
    assert event.payload["reason"] == "trial_cap_reached"
