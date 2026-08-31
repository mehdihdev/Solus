"""SOLUSDEV-167 acceptance: the Onshape call budget, measured (not claimed).

These tests are written to FAIL against the code as it stands. That is the
point — they are the gate the cache/change-signal work is built against, and
each one names the acceptance criterion it proves.

Every number here is `Meter.counted` — 2xx/3xx against the Onshape API host,
which is exactly what Onshape's ANNUAL 2,500-call/user quota counts.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import respx
from conftest import requires_occt
from fixtures.onshape_fake import FakeOnshape, Meter
from solus_api.connectors.httpcache import CacheStore, InMemoryCacheStore
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.runtime import refresh_secret_ref
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.connectors.worker import execute_source_sync
from solus_api.models import (
    GraphEdge,
    GraphEntity,
    JobStatus,
    Project,
    Source,
    SourceStatus,
    SourceType,
    Sync,
    Team,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

#: Every test here drives a real sync, so all of them need the STEP reader.
#: Without OCCT the sync FAILS and each call-count assertion below measures
#: the wrong thing — an unreadable failure, not a useful one.
pytestmark = requires_occt

DID = "dA"


@pytest.fixture
async def onshape() -> AsyncIterator[tuple[FakeOnshape, Meter]]:
    """A scripted Onshape with a catch-all route, so nothing escapes the meter."""
    fake = FakeOnshape()
    async with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=fake)
        yield fake, Meter(router)
    # A path nobody scripted must never look free.
    assert fake.unhandled == [], f"unhandled Onshape endpoints: {fake.unhandled}"


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_source(
    maker: async_sessionmaker[AsyncSession], *, documents: list[str] | None = None
) -> tuple[uuid.UUID, InMemorySecretStore]:
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        secret_ref = f"source/{uuid.uuid4()}/onshape"
        source = Source(
            project_id=project.id,
            team_id=team.id,
            type=SourceType.ONSHAPE,
            name="onshape",
            status=SourceStatus.CONNECTED,
            config={"documents": documents if documents is not None else [DID]},
            secret_ref=secret_ref,
            account_external_id="acct-1",
        )
        db.add(source)
        await db.commit()
        source_id = source.id
    store = InMemorySecretStore()
    # The access token and the refresh token live under separate refs
    # (`resolve_credentials` / `refresh_secret_ref`), not one JSON blob.
    await store.put(secret_ref, "tok")
    await store.put(refresh_secret_ref(secret_ref), "rt")
    return source_id, store


def _registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(
        "onshape",
        lambda: OnshapeConnector(client_id="cid", client_secret="sec", poll_interval=0.0),
    )
    return registry


async def _sync(
    maker: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    store: Any,
    cache: CacheStore | None = None,
) -> None:
    await execute_source_sync(
        source_id=source_id,
        sessionmaker=maker,
        registry=_registry(),
        secret_store=store,
        store=cache,
    )


# --------------------------------------------------------------- acceptance #1


async def test_repeat_sync_of_an_unchanged_document_costs_only_the_probe(
    onshape: Any, maker: Any
) -> None:
    """AC#1 — a repeated read of an unchanged document costs ZERO paid calls
    beyond the cheap change probe.

    Asserted against the PROBE COUNT, not against a zero entity delta: a sync
    that skips work reports zero created/updated too, so an entity-count
    assertion would pass on a skip that still paid for a full export.
    """
    fake, meter = onshape
    source_id, store = await _seed_source(maker)

    await _sync(maker, source_id, store)
    first = meter.counted
    assert first > 0, "the first sync must actually fetch"

    meter.reset()
    await _sync(maker, source_id, store)

    # Nothing moved upstream, so the second sync must not re-export. The only
    # calls it may make are the change probe's.
    assert meter.by_route["translations_start"] == 0, (
        f"re-exported an unchanged document: {dict(meter.by_route)}"
    )
    assert meter.by_route["externaldata"] == 0
    assert meter.counted <= 2, (
        f"an unchanged re-sync cost {meter.counted} calls: {dict(meter.by_route)}"
    )


async def test_a_changed_document_is_still_re_exported(onshape: Any, maker: Any) -> None:
    """The other half of AC#1: cheap must not mean stale."""
    fake, meter = onshape
    source_id, store = await _seed_source(maker)
    await _sync(maker, source_id, store)

    fake.bump_microversion()
    meter.reset()
    await _sync(maker, source_id, store)

    assert meter.by_route["translations_start"] >= 1, "a real change was skipped"


# --------------------------------------------------------------- acceptance #4


async def test_concurrent_syncs_of_one_source_make_one_upstream_export(
    onshape: Any, maker: Any
) -> None:
    """AC#4 — N concurrent requests for the same resource collapse to ONE
    upstream call.

    Measured AT THE PEAK: the upstream is held open, so `entered` is the number
    of callers that genuinely reached the network simultaneously. A final tally
    would also be satisfied by accidental serialization.
    """
    fake, meter = onshape
    source_id, store = await _seed_source(maker)
    cache = InMemoryCacheStore()
    gate = fake.block_on("translations_start")

    tasks = [asyncio.create_task(_sync(maker, source_id, store, cache)) for _ in range(20)]

    # Wait on a CONDITION, not a clock. A fixed sleep here is load-sensitive:
    # under a full-suite run the tasks are scheduled more slowly and a single
    # sample can miss the moment that matters. Instead, watch until the winner
    # has reached upstream and the count has settled — and fail the instant a
    # second caller gets through, rather than only if it happens to be through
    # when we look.
    entered_at_peak = 0
    stable = 0
    for _ in range(200):  # bounded: ~10s worst case
        await asyncio.sleep(0.05)
        entered_at_peak = fake.entered["translations_start"]
        if entered_at_peak > 1:
            break  # violation — report it immediately
        stable = stable + 1 if entered_at_peak == 1 else 0
        if stable >= 10:  # a full 0.5s with everyone else parked
            break

    gate.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    assert entered_at_peak == 1, (
        f"{entered_at_peak} concurrent callers reached Onshape; expected 1 (single-flight)"
    )


# --------------------------------------------------------------- acceptance #7


async def test_resync_is_idempotent_no_duplicates_no_orphans(onshape: Any, maker: Any) -> None:
    """AC#7 — re-sync creates no duplicate entities and no orphaned edges."""
    fake, meter = onshape
    source_id, store = await _seed_source(maker)

    await _sync(maker, source_id, store)
    async with maker() as db:
        first = await db.scalar(
            select(func.count())
            .select_from(GraphEntity)
            .where(GraphEntity.source_id == source_id, GraphEntity.deleted_at.is_(None))
        )
    assert first and first > 0, "the fixture must land entities for this to mean anything"

    fake.bump_microversion()  # force the write path to actually run again
    await _sync(maker, source_id, store)

    async with maker() as db:
        second = await db.scalar(
            select(func.count())
            .select_from(GraphEntity)
            .where(GraphEntity.source_id == source_id, GraphEntity.deleted_at.is_(None))
        )
        live = select(GraphEntity.id).where(GraphEntity.deleted_at.is_(None)).scalar_subquery()
        orphans = await db.scalar(
            select(func.count())
            .select_from(GraphEdge)
            .where(
                GraphEdge.source_id == source_id,
                GraphEdge.deleted_at.is_(None),
                ~GraphEdge.src_id.in_(live) | ~GraphEdge.dst_id.in_(live),
            )
        )
    assert second == first, f"re-sync duplicated entities: {first} -> {second}"
    assert orphans == 0, f"{orphans} edges point at a tombstoned endpoint"


async def test_concurrent_resync_leaves_no_duplicates(onshape: Any, maker: Any) -> None:
    """AC#7 under concurrency — driven BELOW the route, because the 409
    in-flight guard covers only the manual path and the scheduled enqueue has no
    dedup.

    HONEST LIMIT: the collision window here is narrow. `apply_sync_result`
    SELECTs live rows before branching, so a run only INSERTs twice if both
    syncs read before either commits; released from one gate they mostly stagger
    on parse time and serialize by luck. The reliable demonstration of the same
    unguarded write path is
    `test_concurrent_syncs_of_one_source_make_one_upstream_export`, which raises
    UniqueViolationError on uq_graph_entity_source_ref every run. This test is
    the regression guard once the per-source advisory lock lands; that one is
    the proof the lock is needed.
    """
    fake, meter = onshape
    source_id, store = await _seed_source(maker)
    await _sync(maker, source_id, store)

    fake.bump_microversion()
    # Release both syncs from the SAME point so they reach the graph write
    # together. Without the gate this is a coin flip: the pair often happens to
    # serialize on the event loop and the test passes on luck, not on a lock.
    gate = fake.block_on("externaldata")
    tasks = [asyncio.create_task(_sync(maker, source_id, store)) for _ in range(12)]
    await asyncio.sleep(0.15)
    gate.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    async with maker() as db:
        rows = (
            await db.scalars(
                select(GraphEntity.external_ref).where(
                    GraphEntity.source_id == source_id, GraphEntity.deleted_at.is_(None)
                )
            )
        ).all()
        statuses = (await db.scalars(select(Sync.status).where(Sync.source_id == source_id))).all()
    assert len(rows) == len(set(rows)), "concurrent re-sync produced duplicate external_refs"
    # Without this, the test passes for the WRONG reason: `apply_sync_result` is
    # SELECT-then-insert with no lock, so a concurrent pair raises
    # UniqueViolationError on uq_graph_entity_source_ref, the transaction rolls
    # back, and "no duplicates" is true only because nothing was written.
    assert all(st is JobStatus.SUCCEEDED for st in statuses), (
        f"a concurrent re-sync failed instead of serializing: {statuses}"
    )
