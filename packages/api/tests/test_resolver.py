"""SOLUSDEV-72: the caching entity resolver — positive results are cached with a
TTL so a 50 Hz per-joint stream costs ~1 query per device per TTL, not one per
packet. Negative results are deliberately NOT cached: a just-linked entity must
attach on the next packet, never after a stale-miss window."""

import uuid

from solus_api.graph.resolver import CachingEntityResolver


class CountingResolver:
    def __init__(self, mapping: dict[tuple[uuid.UUID, str], uuid.UUID]) -> None:
        self._mapping = mapping
        self.calls = 0

    async def resolve(self, project_id: uuid.UUID, device_id: str) -> uuid.UUID | None:
        self.calls += 1
        return self._mapping.get((project_id, device_id))


async def test_positive_results_are_cached_within_ttl() -> None:
    project, entity = uuid.uuid4(), uuid.uuid4()
    inner = CountingResolver({(project, "dev"): entity})
    now = [0.0]
    resolver = CachingEntityResolver(inner, ttl_seconds=30.0, clock=lambda: now[0])

    for _ in range(50):
        assert await resolver.resolve(project, "dev") == entity
    assert inner.calls == 1

    now[0] = 31.0  # TTL elapsed → one fresh lookup
    assert await resolver.resolve(project, "dev") == entity
    assert inner.calls == 2


async def test_negative_results_are_never_cached() -> None:
    project, entity = uuid.uuid4(), uuid.uuid4()
    inner = CountingResolver({})
    resolver = CachingEntityResolver(inner, ttl_seconds=30.0, clock=lambda: 0.0)

    assert await resolver.resolve(project, "dev") is None
    inner._mapping[(project, "dev")] = entity  # the entity gets linked mid-stream
    assert await resolver.resolve(project, "dev") == entity  # attaches immediately


async def test_cache_is_bounded_and_keyed_by_project() -> None:
    project_a, project_b = uuid.uuid4(), uuid.uuid4()
    entity_a, entity_b = uuid.uuid4(), uuid.uuid4()
    inner = CountingResolver({(project_a, "dev"): entity_a, (project_b, "dev"): entity_b})
    resolver = CachingEntityResolver(inner, ttl_seconds=30.0, max_entries=2, clock=lambda: 0.0)

    assert await resolver.resolve(project_a, "dev") == entity_a
    assert await resolver.resolve(project_b, "dev") == entity_b  # same device id, own entry

    # Overflow evicts rather than grows.
    for i in range(5):
        await resolver.resolve(project_a, f"dev{i}")
    assert await resolver.resolve(project_a, "dev") == entity_a  # still correct, maybe re-fetched
