"""Bounded recent-values buffer backends (SOLUS-LNK-06).

Proves the buffer is bounded (no unbounded growth under backpressure), project-isolated,
and that the in-memory and Redis backends behave identically for the read shape.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from solus_api.graph.buffer import (
    DEFAULT_CAPACITY,
    InMemoryTelemetryBuffer,
    RedisTelemetryBuffer,
)

_T0 = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)


async def test_buffer_appends_and_reads_back_in_order() -> None:
    buf = InMemoryTelemetryBuffer()
    project, entity = uuid.uuid4(), uuid.uuid4()
    for i in range(3):
        await buf.append(project, entity, "rpm", _T0 + timedelta(seconds=i), float(i))
    samples = await buf.recent(project, entity, "rpm")
    assert [s.value for s in samples] == [0.0, 1.0, 2.0]
    assert [s.timestamp for s in samples] == [
        _T0,
        _T0 + timedelta(seconds=1),
        _T0 + timedelta(seconds=2),
    ]


async def test_buffer_is_bounded_no_unbounded_growth() -> None:
    buf = InMemoryTelemetryBuffer(capacity=4)
    project, entity = uuid.uuid4(), uuid.uuid4()
    for i in range(50):  # backpressure: far more than capacity
        await buf.append(project, entity, "rpm", _T0 + timedelta(seconds=i), float(i))
    samples = await buf.recent(project, entity, "rpm")
    assert len(samples) == 4  # only the last `capacity` retained
    assert [s.value for s in samples] == [46.0, 47.0, 48.0, 49.0]


async def test_buffer_recent_honors_limit_and_since() -> None:
    buf = InMemoryTelemetryBuffer()
    project, entity = uuid.uuid4(), uuid.uuid4()
    for i in range(10):
        await buf.append(project, entity, "rpm", _T0 + timedelta(seconds=i), float(i))
    assert len(await buf.recent(project, entity, "rpm", limit=3)) == 3
    since = _T0 + timedelta(seconds=7)
    later = await buf.recent(project, entity, "rpm", since=since)
    assert [s.value for s in later] == [7.0, 8.0, 9.0]


async def test_buffer_isolates_by_project() -> None:
    buf = InMemoryTelemetryBuffer()
    entity = uuid.uuid4()
    a, b = uuid.uuid4(), uuid.uuid4()
    await buf.append(a, entity, "rpm", _T0, 1.0)
    assert await buf.recent(b, entity, "rpm") == []  # team B sees none of team A's feed


async def test_buffer_tracks_signal_and_entity_indexes() -> None:
    buf = InMemoryTelemetryBuffer()
    project, entity = uuid.uuid4(), uuid.uuid4()
    await buf.append(project, entity, "rpm", _T0, 1.0)
    await buf.append(project, entity, "temp", _T0, 2.0)
    assert await buf.signal_names(project, entity) == ["rpm", "temp"]
    assert await buf.entity_ids(project) == [entity]


def test_buffer_rejects_non_positive_capacity() -> None:
    with pytest.raises(ValueError):
        InMemoryTelemetryBuffer(capacity=0)
    with pytest.raises(ValueError):
        RedisTelemetryBuffer(_FakeRedis(), capacity=-1)


async def test_buffer_limit_zero_returns_nothing() -> None:
    """Regression: limit=0 must return [] — not the whole buffer (Python -0 == 0 slice bug)."""
    buf = InMemoryTelemetryBuffer()
    project, entity = uuid.uuid4(), uuid.uuid4()
    for i in range(5):
        await buf.append(project, entity, "rpm", _T0 + timedelta(seconds=i), float(i))
    assert await buf.recent(project, entity, "rpm", limit=0) == []


async def test_buffer_negative_limit_is_rejected() -> None:
    buf = InMemoryTelemetryBuffer()
    project, entity = uuid.uuid4(), uuid.uuid4()
    await buf.append(project, entity, "rpm", _T0, 1.0)
    with pytest.raises(ValueError):
        await buf.recent(project, entity, "rpm", limit=-1)


async def test_redis_buffer_limit_zero_returns_nothing() -> None:
    buf = RedisTelemetryBuffer(_FakeRedis(), capacity=100)
    project, entity = uuid.uuid4(), uuid.uuid4()
    for i in range(5):
        await buf.append(project, entity, "rpm", _T0 + timedelta(seconds=i), float(i))
    assert await buf.recent(project, entity, "rpm", limit=0) == []


async def test_default_capacity_is_sane() -> None:
    assert DEFAULT_CAPACITY >= 64


class _FakeRedis:
    """Minimal in-process stand-in for redis.asyncio.Redis exercising the ops
    RedisTelemetryBuffer uses — proves key construction, LTRIM bounding, and JSON
    round-tripping without a live Redis."""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.sets: dict[str, set[str]] = {}
        self.expiries: dict[str, int] = {}

    async def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    async def ltrim(self, key: str, start: int, end: int) -> None:
        data = self.lists.get(key, [])
        self.lists[key] = data[start:] if end == -1 else data[start : end + 1]

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        data = self.lists.get(key, [])
        return data[start:] if end == -1 else data[start : end + 1]

    async def sadd(self, key: str, member: str) -> int:
        self.sets.setdefault(key, set()).add(member)
        return 1

    async def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    async def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds


async def test_redis_buffer_round_trips_and_bounds() -> None:
    buf = RedisTelemetryBuffer(_FakeRedis(), capacity=4)
    project, entity = uuid.uuid4(), uuid.uuid4()
    for i in range(20):
        await buf.append(project, entity, "rpm", _T0 + timedelta(seconds=i), float(i))
    samples = await buf.recent(project, entity, "rpm")
    assert len(samples) == 4  # LTRIM bound holds
    assert [s.value for s in samples] == [16.0, 17.0, 18.0, 19.0]
    assert await buf.signal_names(project, entity) == ["rpm"]
    assert entity in await buf.entity_ids(project)


async def test_redis_buffer_recent_honors_since_and_limit() -> None:
    buf = RedisTelemetryBuffer(_FakeRedis(), capacity=100)
    project, entity = uuid.uuid4(), uuid.uuid4()
    for i in range(10):
        await buf.append(project, entity, "rpm", _T0 + timedelta(seconds=i), float(i))
    later = await buf.recent(project, entity, "rpm", since=_T0 + timedelta(seconds=8))
    assert [s.value for s in later] == [8.0, 9.0]
    assert len(await buf.recent(project, entity, "rpm", limit=2)) == 2


async def test_redis_buffer_sets_ttl_to_avoid_stale_growth() -> None:
    fake = _FakeRedis()
    buf = RedisTelemetryBuffer(fake, capacity=4)
    project, entity = uuid.uuid4(), uuid.uuid4()
    await buf.append(project, entity, "rpm", _T0, 1.0)
    assert fake.expiries  # every key gets a TTL so idle feeds expire


@pytest.mark.parametrize("redis", [False, True])
async def test_buffers_preserve_units_per_sample_without_converting(redis: bool) -> None:
    buf = RedisTelemetryBuffer(_FakeRedis()) if redis else InMemoryTelemetryBuffer()
    project, entity = uuid.uuid4(), uuid.uuid4()
    for value, unit in [(1.0, "rad"), (90.0, "deg"), (4095.0, None)]:
        await buf.append(project, entity, "position", _T0, value, unit=unit)
    samples = await buf.recent(project, entity, "position")
    assert [(s.value, s.unit) for s in samples] == [(1.0, "rad"), (90.0, "deg"), (4095.0, None)]
    assert await buf.recent(uuid.uuid4(), entity, "position") == []


async def test_redis_reads_legacy_samples_without_units() -> None:
    fake = _FakeRedis()
    buf = RedisTelemetryBuffer(fake)
    project, entity = uuid.uuid4(), uuid.uuid4()
    await fake.rpush(
        f"solus:telem:v:{project}:{entity}:position",
        json.dumps({"t": _T0.isoformat(), "v": 3.0}),
    )
    samples = await buf.recent(project, entity, "position")
    assert samples[0].value == 3.0 and samples[0].unit is None
