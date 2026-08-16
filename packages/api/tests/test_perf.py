"""SYS-05 semantic cache — bounded, TTL'd, tenant-keyed, measured.

Unit-pins the cache itself, then proves the `DbSolSystems` integration: one
embed per query (the key vector is reused for retrieval), near-duplicate reuse,
never across projects, empty results never cached (a just-recorded solution
must be findable immediately).
"""

from __future__ import annotations

import uuid

import pytest
from solus_api.agent.feeds import DbSolSystems
from solus_api.agent.interfaces import RetrievalFilter
from solus_api.agent.perf import SemanticCache
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.resolver import DbEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.models import Domain, GraphEntity, Membership, Project, Role, Team, User
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_exact_hit_normalizes_whitespace_and_case() -> None:
    cache = SemanticCache(clock=_Clock())
    project = uuid.uuid4()
    cache.store(project, "rag", "5||What is  the LM358?", None, ["hit"])
    assert cache.lookup(project, "rag", "5||what is the lm358?", None) == ["hit"]
    assert cache.lookup(project, "rag", "5||something else", None) is None
    stats = cache.stats()
    assert stats["hits"] == 1 and stats["misses"] == 1


def test_near_duplicate_embedding_hits_within_threshold() -> None:
    cache = SemanticCache(clock=_Clock(), similarity_threshold=0.95)
    project = uuid.uuid4()
    cache.store(project, "rag", "5||imu i2c address conflict", [1.0, 0.0], ["hit"])
    assert cache.lookup(project, "rag", "5||conflict on the imu's i2c address", [0.999, 0.02]) == [
        "hit"
    ]
    assert cache.lookup(project, "rag", "5||unrelated", [0.0, 1.0]) is None


def test_projects_never_share_entries() -> None:
    cache = SemanticCache(clock=_Clock())
    a, b = uuid.uuid4(), uuid.uuid4()
    cache.store(a, "rag", "5||the query", [1.0, 0.0], ["a-data"])
    assert cache.lookup(b, "rag", "5||the query", [1.0, 0.0]) is None  # exact AND semantic


def test_kinds_never_share_entries() -> None:
    cache = SemanticCache(clock=_Clock())
    project = uuid.uuid4()
    cache.store(project, "rag", "5||the query", [1.0, 0.0], ["rag-data"])
    assert cache.lookup(project, "error", "5||the query", [1.0, 0.0]) is None


def test_entries_expire_after_ttl() -> None:
    clock = _Clock()
    cache = SemanticCache(clock=clock, ttl_seconds=120.0)
    project = uuid.uuid4()
    cache.store(project, "rag", "5||q", [1.0], ["hit"])
    clock.now += 119.0
    assert cache.lookup(project, "rag", "5||q", None) == ["hit"]
    clock.now += 2.0
    assert cache.lookup(project, "rag", "5||q", [1.0]) is None
    assert cache.stats()["entries"] == 0  # expired entries are dropped, not kept


def test_bounded_size_evicts_least_recently_used() -> None:
    cache = SemanticCache(clock=_Clock(), max_entries=2)
    project = uuid.uuid4()
    cache.store(project, "rag", "1||a", None, ["a"])
    cache.store(project, "rag", "1||b", None, ["b"])
    assert cache.lookup(project, "rag", "1||a", None) == ["a"]  # refresh a
    cache.store(project, "rag", "1||c", None, ["c"])
    assert cache.lookup(project, "rag", "1||b", None) is None  # b was the LRU
    assert cache.lookup(project, "rag", "1||a", None) == ["a"]


# --- DbSolSystems integration ----------------------------------------------------


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_perf_project(db: AsyncSession, tag: str) -> Project:
    user = User(supabase_user_id=f"sub-{tag}-{uuid.uuid4().hex[:8]}", email=f"{tag}@ex.com")
    team = Team(name=tag)
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name=tag, created_by=user.id)
    db.add(project)
    await db.flush()
    return project


async def test_feeds_cache_serves_repeats_with_one_embed_per_query(
    db: AsyncSession, maker: async_sessionmaker[AsyncSession]
) -> None:
    project = await _seed_perf_project(db, "cache")
    db.add(
        GraphEntity(
            project_id=project.id,
            kind="part",
            domain=Domain.ELECTRICAL,
            name="imu sensor",
            external_ref="ref-imu",
            attrs={},
        )
    )
    await db.commit()

    embed_calls: list[str] = []

    async def recording_embed(text: str) -> list[float] | None:
        embed_calls.append(text)
        return None  # keyless: FTS path; the cache must still work on exact text

    systems = DbSolSystems(
        maker,
        TelemetryPlumbing(InMemoryTelemetryBuffer(), DbEntityResolver(maker)),
        embed=recording_embed,
        cache=SemanticCache(clock=_Clock()),
    )
    scoped = RetrievalFilter(project_id=project.id)
    first = await systems.rag_query("imu sensor", 5, scoped)
    assert [h.chunk for h in first] == ["imu sensor"]
    second = await systems.rag_query("imu  SENSOR", 5, scoped)  # normalized-equal
    assert second == first
    assert second is not first  # a COPY — callers never hold the cache's object
    assert embed_calls == ["imu sensor"]  # an exact hit costs ZERO embed calls
    stats = systems.cache_stats()
    assert stats["hits"] == 1

    different_k = await systems.rag_query("imu sensor", 3, scoped)
    assert different_k == first and systems.cache_stats()["hits"] == 1  # k bounds the bucket


async def test_semantic_hits_never_cross_k_or_filter_boundaries(
    db: AsyncSession, maker: async_sessionmaker[AsyncSession]
) -> None:
    """SEC H1: the similarity path must be bound by the same (k, filter) bucket as
    the exact path — a k=20 answer must never serve a k=3 ask, nor an unfiltered
    answer a domain-filtered one. Every query embeds to the SAME vector here, so
    only the bucket separates them."""
    project = await _seed_perf_project(db, "bucket")
    db.add(
        GraphEntity(
            project_id=project.id,
            kind="part",
            domain=Domain.ELECTRICAL,
            name="imu sensor",
            external_ref="ref-imu-b",
            attrs={},
        )
    )
    await db.commit()

    async def unit_embed(text: str) -> list[float] | None:
        return [1.0, 0.0]  # identical for every query: cosine 1.0 across the board

    systems = DbSolSystems(
        maker,
        TelemetryPlumbing(InMemoryTelemetryBuffer(), DbEntityResolver(maker)),
        embed=unit_embed,
        cache=SemanticCache(clock=_Clock()),
    )
    scoped = RetrievalFilter(project_id=project.id)
    first = await systems.rag_query("imu sensor", 5, scoped)
    assert [h.chunk for h in first] == ["imu sensor"]

    near = await systems.rag_query("sensor imu", 5, scoped)  # same vector, new wording
    assert near == first and systems.cache_stats()["hits"] == 1  # semantic hit, same bucket

    await systems.rag_query("imu sensor", 3, scoped)  # same vector, different k
    assert systems.cache_stats()["hits"] == 1  # NOT served from the k=5 entry

    await systems.rag_query(
        "imu sensor", 5, RetrievalFilter(project_id=project.id, domains=["electrical"])
    )
    assert systems.cache_stats()["hits"] == 1  # NOT served from the unfiltered entry


async def test_feeds_cache_never_caches_empty_results(
    db: AsyncSession, maker: async_sessionmaker[AsyncSession]
) -> None:
    """The flywheel must be readable immediately after a write: an empty result
    cached for the TTL would hide a solution recorded a second later."""
    project = await _seed_perf_project(db, "flywheel")
    await db.commit()

    systems = DbSolSystems(
        maker,
        TelemetryPlumbing(InMemoryTelemetryBuffer(), DbEntityResolver(maker)),
        cache=SemanticCache(clock=_Clock()),
    )
    scoped = RetrievalFilter(project_id=project.id)
    assert await systems.get_error_history("i2c conflict", 5, scoped) == []
    await systems.record_error_solution(project.id, "i2c conflict", "re-strap AD0", "electrical")
    hits = await systems.get_error_history("i2c conflict", 5, scoped)
    assert [h.chunk for h in hits] == ["i2c conflict"]  # not masked by a cached empty
