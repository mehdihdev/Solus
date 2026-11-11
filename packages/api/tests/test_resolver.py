"""SOLUSDEV-72: the caching entity resolver — positive results are cached with a
TTL so a 50 Hz per-joint stream costs ~1 query per device per TTL, not one per
packet. Negative results are deliberately NOT cached: a just-linked entity must
attach on the next packet, never after a stale-miss window.

SOLUSDEV-322 P5-T2: the session-level `source` tag. A real session resolves by `external_ref`
only; a sim session's packets (`source=<provider>`) also match a part's `attrs.sim_aliases`
rows `{provider, device_id}` — in ONE query, an `external_ref` hit winning — so a simulated
joint lands on the same part node as the real one. The cache keys on the source too."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from alembic import command
from alembic.config import Config
from solus_api.graph.resolver import CachingEntityResolver, DbEntityResolver, EntityResolver
from solus_api.models import Domain, GraphEntity, Project, Team
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

API_DIR = Path(__file__).resolve().parents[1]
PREVIOUS = "a32200000001"
INDEX = "ix_graph_entity_sim_aliases"
#: Vendor-free provider tags, as the ledger's discriminator spells them.
SIM = "sim-provider-a"
OTHER = "sim-provider-b"
REAL_REF = "usb:FAKE-ARM-0001/3"
SIM_DEVICE = "world/arm/elbow"


class CountingResolver:
    """A pre-322 fake: no `source` keyword. The cache must keep working with it."""

    def __init__(self, mapping: dict[tuple[uuid.UUID, str], uuid.UUID]) -> None:
        self._mapping = mapping
        self.calls = 0

    async def resolve(self, project_id: uuid.UUID, device_id: str) -> uuid.UUID | None:
        self.calls += 1
        return self._mapping.get((project_id, device_id))


def _legacy(inner: CountingResolver) -> EntityResolver:
    """The pre-322 shape deliberately lacks the protocol's `source` keyword; cast once here."""
    return cast(EntityResolver, inner)


class SourceAwareResolver:
    def __init__(self, mapping: dict[tuple[uuid.UUID, str | None, str], uuid.UUID]) -> None:
        self._mapping = mapping
        self.calls: list[tuple[uuid.UUID, str, str | None]] = []

    async def resolve(
        self, project_id: uuid.UUID, device_id: str, *, source: str | None = None
    ) -> uuid.UUID | None:
        self.calls.append((project_id, device_id, source))
        return self._mapping.get((project_id, source, device_id))


async def test_positive_results_are_cached_within_ttl() -> None:
    project, entity = uuid.uuid4(), uuid.uuid4()
    inner = CountingResolver({(project, "dev"): entity})
    now = [0.0]
    resolver = CachingEntityResolver(_legacy(inner), ttl_seconds=30.0, clock=lambda: now[0])

    for _ in range(50):
        assert await resolver.resolve(project, "dev") == entity
    assert inner.calls == 1

    now[0] = 31.0  # TTL elapsed → one fresh lookup
    assert await resolver.resolve(project, "dev") == entity
    assert inner.calls == 2


async def test_negative_results_are_never_cached() -> None:
    project, entity = uuid.uuid4(), uuid.uuid4()
    inner = CountingResolver({})
    resolver = CachingEntityResolver(_legacy(inner), ttl_seconds=30.0, clock=lambda: 0.0)

    assert await resolver.resolve(project, "dev") is None
    inner._mapping[(project, "dev")] = entity  # the entity gets linked mid-stream
    assert await resolver.resolve(project, "dev") == entity  # attaches immediately


async def test_cache_is_bounded_and_keyed_by_project() -> None:
    project_a, project_b = uuid.uuid4(), uuid.uuid4()
    entity_a, entity_b = uuid.uuid4(), uuid.uuid4()
    inner = CountingResolver({(project_a, "dev"): entity_a, (project_b, "dev"): entity_b})
    resolver = CachingEntityResolver(
        _legacy(inner), ttl_seconds=30.0, max_entries=2, clock=lambda: 0.0
    )

    assert await resolver.resolve(project_a, "dev") == entity_a
    assert await resolver.resolve(project_b, "dev") == entity_b  # same device id, own entry

    # Overflow evicts rather than grows.
    for i in range(5):
        await resolver.resolve(project_a, f"dev{i}")
    assert await resolver.resolve(project_a, "dev") == entity_a  # still correct, maybe re-fetched


async def test_cache_keys_include_source() -> None:
    """The same device id under a real session and under a sim session are two cache entries,
    each resolved once; `source=` reaches the inner resolver only when it is set, so a fake
    without the keyword still serves a real session."""
    project, real, sim = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    inner = SourceAwareResolver({(project, None, "dev"): real, (project, SIM, "dev"): sim})
    resolver = CachingEntityResolver(inner, ttl_seconds=30.0, clock=lambda: 0.0)

    for _ in range(2):
        assert await resolver.resolve(project, "dev") == real
        assert await resolver.resolve(project, "dev", source=SIM) == sim
    assert await resolver.resolve(project, "dev", source=OTHER) is None  # not the SIM entry

    assert inner.calls == [
        (project, "dev", None),
        (project, "dev", SIM),
        (project, "dev", OTHER),
    ]
    legacy = CountingResolver({(project, "dev"): real})
    cached = CachingEntityResolver(_legacy(legacy), clock=lambda: 0.0)
    assert await cached.resolve(project, "dev") == real


# --- against the real database -------------------------------------------------------------


async def _project(maker: async_sessionmaker[AsyncSession], tag: str) -> uuid.UUID:
    async with maker() as db:
        team = Team(name=f"resolver-{tag}-{uuid.uuid4().hex[:6]}")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name=f"resolver-{tag}")
        db.add(project)
        await db.commit()
        return project.id


def _part(
    project: uuid.UUID,
    name: str,
    *,
    external_ref: str | None = None,
    aliases: list[dict[str, str]] | None = None,
) -> GraphEntity:
    attrs: dict[str, Any] = {"sim_aliases": aliases} if aliases is not None else {}
    return GraphEntity(
        project_id=project,
        kind="part",
        domain=Domain.ELECTRICAL,
        origin="manual",
        name=name,
        external_ref=external_ref,
        attrs=attrs,
    )


async def _seed(
    maker: async_sessionmaker[AsyncSession], project: uuid.UUID, *parts: GraphEntity
) -> list[uuid.UUID]:
    async with maker() as db:
        db.add_all(parts)
        await db.commit()
        return [part.id for part in parts]


@contextmanager
def _counting_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *_: Any) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


async def test_real_source_resolves_by_external_ref_only_never_by_alias(
    engine: AsyncEngine,
) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project = await _project(maker, "real")
    real_id, _ = await _seed(
        maker,
        project,
        _part(project, "servo 3", external_ref=REAL_REF),
        _part(project, "elbow twin", aliases=[{"provider": SIM, "device_id": SIM_DEVICE}]),
    )
    resolver = DbEntityResolver(maker)

    assert await resolver.resolve(project, REAL_REF) == real_id
    assert await resolver.resolve(project, SIM_DEVICE) is None  # no source: aliases are not read
    assert await resolver.resolve(project, SIM_DEVICE, source=None) is None


async def test_sim_source_resolves_alias_in_one_query_with_external_ref_winning(
    engine: AsyncEngine,
) -> None:
    """Two parts answer to `SIM_DEVICE` under the sim source — one by `external_ref`, one by an
    alias row. One statement, and the `external_ref` hit wins."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project = await _project(maker, "winner")
    aliased_id, ref_id = await _seed(
        maker,
        project,
        _part(project, "aliased", aliases=[{"provider": SIM, "device_id": SIM_DEVICE}]),
        _part(project, "by ref", external_ref=SIM_DEVICE),
    )
    resolver = DbEntityResolver(maker)

    with _counting_statements(engine) as statements:
        resolved = await resolver.resolve(project, SIM_DEVICE, source=SIM)

    assert resolved == ref_id != aliased_id
    assert len(statements) == 1, statements


async def test_sim_source_resolves_alias_after_external_ref_miss(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project, stranger = await _project(maker, "alias"), await _project(maker, "stranger")
    (aliased_id,) = await _seed(
        maker,
        project,
        _part(
            project,
            "servo 3",
            external_ref=REAL_REF,
            aliases=[
                {"provider": OTHER, "device_id": "x"},
                {"provider": SIM, "device_id": SIM_DEVICE},
            ],
        ),
    )
    resolver = DbEntityResolver(maker)

    assert await resolver.resolve(project, SIM_DEVICE, source=SIM) == aliased_id
    assert (
        await resolver.resolve(project, REAL_REF, source=SIM) == aliased_id
    )  # real id still works
    assert await resolver.resolve(stranger, SIM_DEVICE, source=SIM) is None  # project-scoped (§7)


async def test_alias_of_another_provider_does_not_match(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project = await _project(maker, "provider")
    await _seed(
        maker,
        project,
        _part(project, "servo 3", aliases=[{"provider": SIM, "device_id": SIM_DEVICE}]),
    )
    resolver = DbEntityResolver(maker)

    assert await resolver.resolve(project, SIM_DEVICE, source=OTHER) is None
    assert await resolver.resolve(project, SIM_DEVICE, source=SIM) is not None


async def test_unmapped_sim_device_stays_unresolved(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project = await _project(maker, "unmapped")
    await _seed(
        maker,
        project,
        _part(project, "servo 3", aliases=[{"provider": SIM, "device_id": SIM_DEVICE}]),
    )
    resolver = DbEntityResolver(maker)

    assert await resolver.resolve(project, "world/arm/wrist", source=SIM) is None
    assert await resolver.resolve(project, "world/arm", source=SIM) is None  # no prefix matching


def _index_present(url: str) -> bool:
    async def check() -> bool:
        eng = create_async_engine(url)
        try:
            async with eng.connect() as conn:
                return (
                    await conn.scalar(
                        text("SELECT 1 FROM pg_indexes WHERE indexname = :name"), {"name": INDEX}
                    )
                ) is not None
        finally:
            await eng.dispose()

    return asyncio.run(check())


def test_migration_round_trip(_schema: None) -> None:
    """`a32200000002` reverses cleanly and reapplies; head is restored in `finally` so a mid-test
    failure cannot poison the rest of the session (pattern `test_sessions_ledger.py`)."""
    url = os.environ["SOLUS_DATABASE_URL"]
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    assert _index_present(url)
    try:
        command.downgrade(cfg, PREVIOUS)
        assert not _index_present(url)
    finally:
        command.upgrade(cfg, "head")
    assert _index_present(url)
