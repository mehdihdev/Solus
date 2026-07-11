"""Bounded recent-values buffers for telemetry (SOLUS-LNK-06).

The buffer holds the LIVE recent samples per `(project, entity, signal)` — the feed Live Bench
and a Foxglove bridge (CON-03) read, and the source `get_telemetry` summarizes. It is bounded by
design: each signal keeps only the last `capacity` samples, so a fast producer (backpressure) or a
long-running stream can never grow it without bound.

Two interchangeable backends behind the `TelemetryBuffer` Protocol, mirroring the codebase's
Redis-optional convention (see `connectors/worker.py`): `InMemoryTelemetryBuffer` for local/dev and
tests, `RedisTelemetryBuffer` when `settings.redis_url` is configured. Keys are project-scoped so no
tenant sees another's feed (§7). Redis keys also carry a TTL so idle feeds expire.
"""

import json
from collections import deque
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from solus_api.graph.packet import RecentSample

DEFAULT_CAPACITY = 512  # samples retained per (entity, signal) ring
DEFAULT_TTL_SECONDS = 3600  # Redis keys expire after an hour idle → no stale growth

_KEY_PREFIX = "solus:telem"


class RedisClient(Protocol):
    """The narrow slice of `redis.asyncio.Redis` the buffer uses — typed structurally so no hard
    `redis` import is needed and any conforming client (or a test double) satisfies it."""

    async def rpush(self, key: str, value: str) -> Any: ...
    async def ltrim(self, key: str, start: int, end: int) -> Any: ...
    async def lrange(self, key: str, start: int, end: int) -> Iterable[str]: ...
    async def sadd(self, key: str, member: str) -> Any: ...
    async def smembers(self, key: str) -> Iterable[str]: ...
    async def expire(self, key: str, seconds: int) -> Any: ...


class TelemetryBuffer(Protocol):
    """The recent-values buffer seam. Both backends satisfy it structurally."""

    async def append(
        self, project_id: UUID, entity_id: UUID, signal: str, timestamp: datetime, value: float
    ) -> None: ...

    async def recent(
        self,
        project_id: UUID,
        entity_id: UUID,
        signal: str,
        *,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> list[RecentSample]: ...

    async def signal_names(self, project_id: UUID, entity_id: UUID) -> list[str]: ...

    async def entity_ids(self, project_id: UUID) -> list[UUID]: ...


def _apply_since_limit(
    samples: list[RecentSample], since: datetime | None, limit: int | None
) -> list[RecentSample]:
    """Pure read-shaping shared by both backends: drop pre-`since`, keep the last `limit`."""
    if since is not None:
        samples = [s for s in samples if s.timestamp >= since]
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        # NB: `samples[-limit:]` is wrong for limit==0 (Python -0 == 0 → whole list).
        samples = samples[-limit:] if limit else []
    return samples


class InMemoryTelemetryBuffer:
    """Process-local bounded ring buffer (default/dev/test backend). Each `(project, entity,
    signal)` is a `deque(maxlen=capacity)`, so growth is bounded per signal automatically."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._rings: dict[tuple[UUID, UUID, str], deque[RecentSample]] = {}
        self._signals: dict[tuple[UUID, UUID], list[str]] = {}
        self._entities: dict[UUID, list[UUID]] = {}

    async def append(
        self, project_id: UUID, entity_id: UUID, signal: str, timestamp: datetime, value: float
    ) -> None:
        ring = self._rings.setdefault((project_id, entity_id, signal), deque(maxlen=self._capacity))
        ring.append(RecentSample(timestamp=timestamp, value=value))
        signals = self._signals.setdefault((project_id, entity_id), [])
        if signal not in signals:
            signals.append(signal)
        entities = self._entities.setdefault(project_id, [])
        if entity_id not in entities:
            entities.append(entity_id)

    async def recent(
        self,
        project_id: UUID,
        entity_id: UUID,
        signal: str,
        *,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> list[RecentSample]:
        ring = self._rings.get((project_id, entity_id, signal))
        return _apply_since_limit(list(ring) if ring else [], since, limit)

    async def signal_names(self, project_id: UUID, entity_id: UUID) -> list[str]:
        return list(self._signals.get((project_id, entity_id), []))

    async def entity_ids(self, project_id: UUID) -> list[UUID]:
        return list(self._entities.get(project_id, []))


class RedisTelemetryBuffer:
    """Redis-backed bounded buffer for the deployed path. Each ring is a Redis LIST trimmed to
    `capacity` (LTRIM), with per-entity signal and per-project entity index SETs; every key carries
    a TTL so idle feeds expire. The client is any `redis.asyncio.Redis` (duck-typed for testing)."""

    def __init__(
        self,
        client: RedisClient,
        capacity: int = DEFAULT_CAPACITY,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._redis = client
        self._capacity = capacity
        self._ttl = ttl_seconds

    def _ring_key(self, project_id: UUID, entity_id: UUID, signal: str) -> str:
        return f"{_KEY_PREFIX}:v:{project_id}:{entity_id}:{signal}"

    def _signals_key(self, project_id: UUID, entity_id: UUID) -> str:
        return f"{_KEY_PREFIX}:s:{project_id}:{entity_id}"

    def _entities_key(self, project_id: UUID) -> str:
        return f"{_KEY_PREFIX}:e:{project_id}"

    async def append(
        self, project_id: UUID, entity_id: UUID, signal: str, timestamp: datetime, value: float
    ) -> None:
        ring_key = self._ring_key(project_id, entity_id, signal)
        signals_key = self._signals_key(project_id, entity_id)
        entities_key = self._entities_key(project_id)
        await self._redis.rpush(ring_key, json.dumps({"t": timestamp.isoformat(), "v": value}))
        await self._redis.ltrim(ring_key, -self._capacity, -1)  # bound to last `capacity`
        await self._redis.sadd(signals_key, signal)
        await self._redis.sadd(entities_key, str(entity_id))
        for key in (ring_key, signals_key, entities_key):
            await self._redis.expire(key, self._ttl)

    async def recent(
        self,
        project_id: UUID,
        entity_id: UUID,
        signal: str,
        *,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> list[RecentSample]:
        raw = await self._redis.lrange(self._ring_key(project_id, entity_id, signal), 0, -1)
        samples = [
            RecentSample(timestamp=datetime.fromisoformat(d["t"]), value=d["v"])
            for d in (json.loads(item) for item in raw)
        ]
        return _apply_since_limit(samples, since, limit)

    async def signal_names(self, project_id: UUID, entity_id: UUID) -> list[str]:
        members = await self._redis.smembers(self._signals_key(project_id, entity_id))
        return sorted(members)  # SET is unordered → sort for a deterministic read

    async def entity_ids(self, project_id: UUID) -> list[UUID]:
        members = await self._redis.smembers(self._entities_key(project_id))
        return [UUID(m) for m in sorted(members)]
