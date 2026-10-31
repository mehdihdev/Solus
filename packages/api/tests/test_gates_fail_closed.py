"""SOLUSDEV-321 P0-T8: the frequency cap fails CLOSED.

With Redis absent, erroring or slower than `REDIS_TIMEOUT_SECONDS`, the cap runs on the
per-process `_LocalFrequencyWindow`: the 21st call in a minute is still refused, the refusal is
still logged to the data-collection system (§7 abuse detection), and the switch warns once per
process per cause. The module-level window and the warn-once set are process state, so every
test here starts from fresh ones."""

import asyncio
import logging
import random
import time
import uuid
from typing import Any

import pytest
from solus_api.models import DataEvent, User
from solus_api.orchestration import gates
from solus_api.orchestration.config import LimitsConfig
from solus_api.orchestration.gates import FrequencyCapExceededError, check_frequency_cap
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_gates import BrokenRedis, FakeRedis

_NOW = 1_000.0
_LIMITS = LimitsConfig(max_calls_per_minute=20, frequency_window_seconds=60)
# A slow Redis costs every call the full timeout, so the slow-Redis tests use a small limit.
_FEW = LimitsConfig(max_calls_per_minute=3, frequency_window_seconds=60)
_LOGGER = "solus.orchestration.gates"


@pytest.fixture(autouse=True)
def _fc_fresh_process_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gates, "_local_window", gates._LocalFrequencyWindow())
    monkeypatch.setattr(gates, "_warned_causes", set())


class _FcSlowRedis(FakeRedis):
    """Accepts the call but never answers in time: a black-holed or overloaded Redis."""

    async def zremrangebyscore(self, key: str, low: float, high: float) -> int:
        await asyncio.sleep(2)
        return await super().zremrangebyscore(key, low, high)


class _FcSlowOldestRedis(FakeRedis):
    """Counts promptly, then stalls the read of the oldest call: a Redis that hangs mid-check."""

    async def zrange(self, key: str, start: int, stop: int, withscores: bool = False) -> list[Any]:
        await asyncio.sleep(2)
        return await super().zrange(key, start, stop, withscores)


def _fc_failing_on(command: str, reply: Any = None) -> FakeRedis:
    """A working `FakeRedis` except that `command` raises (an erroring Redis, one command) or,
    when `reply` is given, answers with that instead (a garbled one)."""
    redis = FakeRedis()

    async def broken(*_args: Any, **_kwargs: Any) -> Any:
        if reply is None:
            raise ConnectionError("redis unreachable")
        return reply

    setattr(redis, command, broken)
    return redis


async def _fc_consenting_user(db: AsyncSession) -> uuid.UUID:
    tag = uuid.uuid4().hex[:10]
    user = User(
        supabase_user_id=f"sub-{tag}", email=f"{tag}@example.com", data_collection_consent=True
    )
    db.add(user)
    await db.commit()
    return user.id


async def test_21st_call_in_a_minute_refused_without_redis() -> None:
    user_id = uuid.uuid4()
    for _ in range(20):
        await check_frequency_cap(user_id, redis=None, limits=_LIMITS, now=_NOW)
    with pytest.raises(FrequencyCapExceededError) as excinfo:
        await check_frequency_cap(user_id, redis=None, limits=_LIMITS, now=_NOW + 1)
    assert excinfo.value.retry_after_seconds == 59  # the oldest call leaves the window at +60
    assert "try again" in str(excinfo.value).lower()


async def test_local_window_is_per_user_and_recovers_after_the_window() -> None:
    busy, other = uuid.uuid4(), uuid.uuid4()
    for _ in range(20):
        await check_frequency_cap(busy, redis=None, limits=_LIMITS, now=_NOW)
    await check_frequency_cap(other, redis=None, limits=_LIMITS, now=_NOW + 1)  # unaffected
    with pytest.raises(FrequencyCapExceededError):
        await check_frequency_cap(busy, redis=None, limits=_LIMITS, now=_NOW + 59)
    # The oldest call has left the window (the Redis path expires it at exactly `window` old too).
    await check_frequency_cap(busy, redis=None, limits=_LIMITS, now=_NOW + 60)


async def test_local_refusal_emits_block_event(db: AsyncSession) -> None:
    """§7: a refusal on the local window is logged exactly like a Redis one, tagged `local`."""
    user_id = await _fc_consenting_user(db)
    for _ in range(20):
        await check_frequency_cap(user_id, redis=None, limits=_LIMITS, now=_NOW, session=db)
    with pytest.raises(FrequencyCapExceededError):
        await check_frequency_cap(user_id, redis=None, limits=_LIMITS, now=_NOW, session=db)
    event = await db.scalar(select(DataEvent).where(DataEvent.user_id == user_id))
    assert event is not None
    assert event.event_type == "orchestration.blocked"
    assert event.payload["reason"] == "frequency_cap"
    assert event.payload["limiter"] == "local"
    assert event.payload["retry_after"] == 60


async def test_redis_refusal_event_reports_the_redis_limiter(db: AsyncSession) -> None:
    user_id = await _fc_consenting_user(db)
    redis = FakeRedis()
    for _ in range(3):
        await check_frequency_cap(user_id, redis=redis, limits=_FEW, now=_NOW, session=db)
    with pytest.raises(FrequencyCapExceededError):
        await check_frequency_cap(user_id, redis=redis, limits=_FEW, now=_NOW, session=db)
    event = await db.scalar(select(DataEvent).where(DataEvent.user_id == user_id))
    assert event is not None
    assert event.payload["limiter"] == "redis"
    assert event.payload["retry_after"] == 60


async def test_redis_error_falls_back_to_local_window(caplog: pytest.LogCaptureFixture) -> None:
    """A CONFIGURED Redis that starts erroring is handled like `redis=None`: the connection error
    never escapes (not a mislabeled provider error) and the cap still holds."""
    user_id = uuid.uuid4()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        for _ in range(20):
            await check_frequency_cap(user_id, redis=BrokenRedis(), limits=_LIMITS, now=_NOW)
        with pytest.raises(FrequencyCapExceededError):
            await check_frequency_cap(user_id, redis=BrokenRedis(), limits=_LIMITS, now=_NOW)
    assert sum("redis_error" in record.getMessage() for record in caplog.records) == 1


@pytest.mark.parametrize("command", ["zremrangebyscore", "zcard", "zadd", "expire"])
async def test_any_single_failing_redis_command_still_fails_closed(command: str) -> None:
    """Formerly each of these was its own fail-open branch (read error, record error)."""
    redis = _fc_failing_on(command)
    user_id = uuid.uuid4()
    for _ in range(20):
        await check_frequency_cap(user_id, redis=redis, limits=_LIMITS, now=_NOW)
    with pytest.raises(FrequencyCapExceededError):
        await check_frequency_cap(user_id, redis=redis, limits=_LIMITS, now=_NOW)


@pytest.mark.parametrize("reply", [None, [("member",)]], ids=["raises", "reply-without-score"])
async def test_unreadable_oldest_call_still_refuses_with_a_full_window_retry(
    reply: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Redis already answered "over the limit"; a broken `zrange`, or a reply that cannot be
    parsed, only loses the retry hint: a broken read never unblocks and is not a fallback."""
    redis = _fc_failing_on("zrange", reply=reply)
    user_id = uuid.uuid4()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        for _ in range(3):
            await check_frequency_cap(user_id, redis=redis, limits=_FEW, now=_NOW)
        with pytest.raises(FrequencyCapExceededError) as excinfo:
            await check_frequency_cap(user_id, redis=redis, limits=_FEW, now=_NOW + 1)
    assert excinfo.value.retry_after_seconds == 60  # a full window, not the mirrored 59
    assert not caplog.records  # Redis answered, so there is no fallback warning


async def test_slow_redis_falls_back_within_250ms() -> None:
    """A hung Redis costs each check at most `REDIS_TIMEOUT_SECONDS` (not the client's 5 s connect
    timeout per command), and the cap keeps refusing on the local window meanwhile."""
    assert gates.REDIS_TIMEOUT_SECONDS == 0.25
    user_id = uuid.uuid4()
    for _ in range(3):
        started = time.monotonic()
        await check_frequency_cap(user_id, redis=_FcSlowRedis(), limits=_FEW, now=_NOW)
        assert time.monotonic() - started < 1.0
    started = time.monotonic()
    with pytest.raises(FrequencyCapExceededError):
        await check_frequency_cap(user_id, redis=_FcSlowRedis(), limits=_FEW, now=_NOW)
    assert time.monotonic() - started < 1.0


async def test_stalled_oldest_read_after_an_over_limit_count_still_refuses() -> None:
    """The timeout half of the broken-oldest-read rule: Redis holds 20, `zrange` stalls past the
    budget, and the 21st call is refused on the mirrored local window within ~0.25 s."""
    user_id = uuid.uuid4()
    redis = _FcSlowOldestRedis()
    for _ in range(20):
        await check_frequency_cap(user_id, redis=redis, limits=_LIMITS, now=_NOW)
    started = time.monotonic()
    with pytest.raises(FrequencyCapExceededError) as excinfo:
        await check_frequency_cap(user_id, redis=redis, limits=_LIMITS, now=_NOW + 1)
    assert time.monotonic() - started < 1.0
    assert excinfo.value.retry_after_seconds == 59  # the mirrored oldest call, not a full window


@pytest.mark.parametrize(
    "outage", [pytest.param(BrokenRedis, id="erroring"), pytest.param(_FcSlowRedis, id="stalled")]
)
async def test_twenty_via_redis_then_outage_refuses_the_21st(outage: type) -> None:
    """The likeliest manual QA: 20 calls through a healthy Redis, then Redis goes away mid-window.
    Redis-admitted calls are mirrored into the local window, so the 21st and 22nd are refused,
    with the retry hint the Redis window would have given."""
    user_id = uuid.uuid4()
    healthy = FakeRedis()
    for _ in range(20):
        await check_frequency_cap(user_id, redis=healthy, limits=_LIMITS, now=_NOW)
    for elapsed in (1, 2):
        started = time.monotonic()
        with pytest.raises(FrequencyCapExceededError) as excinfo:
            await check_frequency_cap(user_id, redis=outage(), limits=_LIMITS, now=_NOW + elapsed)
        assert time.monotonic() - started < 1.0
        assert excinfo.value.retry_after_seconds == 60 - elapsed


async def test_outer_cancellation_is_not_swallowed_by_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A long timeout, so the outer cancel can never lose a race to the 0.25 s one on a loaded box.
    monkeypatch.setattr(gates, "REDIS_TIMEOUT_SECONDS", 5.0)
    user_id = uuid.uuid4()
    task = asyncio.ensure_future(
        check_frequency_cap(user_id, redis=_FcSlowRedis(), limits=_FEW, now=_NOW)
    )
    await asyncio.sleep(0.05)  # inside the Redis call
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gates._local_window.oldest(user_id) is None  # the cancelled call recorded nothing


async def test_healthy_redis_mirrors_admitted_calls_into_the_local_window_quietly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every call Redis admits is mirrored into the local window, so an outage that starts later
    finds this process's history there. A Redis refusal is not recorded, and nothing is logged."""
    user_id = uuid.uuid4()
    redis = FakeRedis()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        for _ in range(3):
            await check_frequency_cap(user_id, redis=redis, limits=_FEW, now=_NOW)
        with pytest.raises(FrequencyCapExceededError):
            await check_frequency_cap(user_id, redis=redis, limits=_FEW, now=_NOW)
    assert gates._local_window.count(user_id, _NOW, 60) == 3  # the refused call was not recorded
    assert gates._local_window.oldest(user_id) == _NOW
    assert not caplog.records


async def test_a_call_redis_refuses_is_not_mirrored_into_the_local_window() -> None:
    """Redis is shared by the fleet, so it can be full while this process's window is not. A
    refused call must not be recorded locally, or a later outage would punish this process."""
    user_id = uuid.uuid4()
    redis = FakeRedis()
    for _ in range(3):  # three calls admitted by OTHER processes
        await redis.zadd(f"solus:freqcap:{user_id}", {uuid.uuid4().hex: _NOW})
    with pytest.raises(FrequencyCapExceededError):
        await check_frequency_cap(user_id, redis=redis, limits=_FEW, now=_NOW)
    assert gates._local_window.oldest(user_id) is None


async def test_mirrored_admissions_are_pruned_so_the_local_window_stays_bounded() -> None:
    """Mirroring goes through `count()`, which prunes: a user who calls every 10 s through a
    healthy Redis holds only the last window's calls locally, not every call ever made."""
    user_id = uuid.uuid4()
    redis = FakeRedis()
    for call in range(200):
        await check_frequency_cap(user_id, redis=redis, limits=_LIMITS, now=_NOW + 10 * call)
    assert len(gates._local_window._calls[user_id]) == 6  # ages 0, 10, ..., 50 s; 60 s is expired


@pytest.mark.parametrize(
    ("cause", "redis"),
    [
        pytest.param("redis_missing", None, id="redis_missing"),
        pytest.param("redis_error", BrokenRedis(), id="redis_error"),
        pytest.param("redis_slow", _FcSlowRedis(), id="redis_slow"),
    ],
)
async def test_warns_once(cause: str, redis: Any, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        for _ in range(2):  # two different users: once per PROCESS, not per user
            await check_frequency_cap(uuid.uuid4(), redis=redis, limits=_LIMITS, now=_NOW)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "local per-process window" in warnings[0].getMessage()
    assert cause in warnings[0].getMessage()
    assert "fail-open" not in warnings[0].getMessage()


async def test_each_cause_warns_independently(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        for redis in (None, BrokenRedis(), _FcSlowRedis()):
            await check_frequency_cap(uuid.uuid4(), redis=redis, limits=_LIMITS, now=_NOW)
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(messages) == 3  # one per cause, none swallowed by another cause's warning
    for cause in ("redis_missing", "redis_error", "redis_slow"):
        assert sum(cause in message for message in messages) == 1


def test_lru_bound_evicts_oldest_user() -> None:
    window = gates._LocalFrequencyWindow()
    users = [uuid.uuid4() for _ in range(4097)]
    for user in users:
        window.record(user, _NOW)
    assert window.oldest(users[0]) is None  # the least recently active user was forgotten
    assert window.count(users[0], _NOW, 60) == 0
    assert window.oldest(users[1]) == _NOW  # everyone else is still remembered
    assert window.count(users[-1], _NOW, 60) == 1


def test_lru_touch_keeps_an_active_user() -> None:
    window = gates._LocalFrequencyWindow()
    users = [uuid.uuid4() for _ in range(4096)]
    for user in users:
        window.record(user, _NOW)
    assert window.count(users[0], _NOW, 60) == 1  # touched: now the most recently active
    window.record(uuid.uuid4(), _NOW)  # one user over the bound
    assert window.count(users[0], _NOW, 60) == 1
    assert window.oldest(users[1]) is None  # the LRU victim is the next-least-recent user


def test_the_per_minute_limit_is_bounded_so_the_local_window_stays_small() -> None:
    """M25: the local window keeps up to `max_calls_per_minute` timestamps per remembered user,
    so the limit is capped at construction; 10,000 is accepted, one more is refused."""
    from pydantic import ValidationError

    assert LimitsConfig(max_calls_per_minute=10_000).max_calls_per_minute == 10_000
    with pytest.raises(ValidationError):
        LimitsConfig(max_calls_per_minute=10_001)


def test_local_window_prunes_expired_calls_and_forgets_idle_users() -> None:
    window = gates._LocalFrequencyWindow()
    user_id = uuid.uuid4()
    window.record(user_id, _NOW)
    window.record(user_id, _NOW + 10)
    assert window.count(user_id, _NOW + 59, 60) == 2
    assert window.count(user_id, _NOW + 60, 60) == 1  # exactly `window` old is expired
    assert window.oldest(user_id) == _NOW + 10
    assert window.count(user_id, _NOW + 70, 60) == 0
    assert window.oldest(user_id) is None  # an idle user no longer holds a slot


async def _fc_verdict(
    user_id: uuid.UUID, redis: FakeRedis | None, limits: LimitsConfig, now: float
) -> int | None:
    """`retry_after_seconds` when the call is refused, `None` when it is admitted."""
    try:
        await check_frequency_cap(user_id, redis=redis, limits=limits, now=now)
    except FrequencyCapExceededError as exc:
        return exc.retry_after_seconds
    return None


async def test_local_window_decides_like_redis_on_random_streams() -> None:
    """Both backends share one refusal arithmetic: for the same call stream they admit, refuse
    and report `retry_after` identically (counts only diverge across an outage)."""
    gaps = [0, 0, 0.5, 1, 3, 7, 11, 30, 61, 5, 10, 60, 59.999, 60.001]  # incl. the window edges
    for seed in range(100):
        rng = random.Random(seed)
        limits = LimitsConfig(
            max_calls_per_minute=rng.randint(1, 6), frequency_window_seconds=rng.choice([5, 10, 60])
        )
        redis, now = FakeRedis(), _NOW
        # The same stream is answered by two stores, so each backend gets its own user ids.
        via_redis, via_local = [uuid.uuid4() for _ in range(3)], [uuid.uuid4() for _ in range(3)]
        for call in range(60):
            now += rng.choice(gaps)
            slot = rng.randrange(3)
            verdict = await _fc_verdict(via_redis[slot], redis, limits, now)
            assert verdict == await _fc_verdict(via_local[slot], None, limits, now), (seed, call)
