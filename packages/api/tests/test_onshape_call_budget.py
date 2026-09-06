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
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.registry import ConnectorContext, ConnectorRegistry
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
    SyncTrigger,
    Team,
)
from solus_api.services.connections import list_documents
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


# --------------------------------------------------------------- SOLUSDEV-241 (I1)
#
# The connection model's acceptance, measured the same way: OAuth binds at
# account scope, so two projects (or two teammates) on one account share ONE
# integration cache keyed on that account.


async def _seed_shared(
    maker: async_sessionmaker[AsyncSession],
    store: InMemorySecretStore,
    *,
    documents: list[str] | None = None,
    account: str = "acct-1",
) -> uuid.UUID:
    """One project + one CONNECTED source on `account`, its credentials in the
    SHARED store — the shape two projects bound to one connection have."""
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        secret_ref = f"connection/{uuid.uuid4()}/onshape"
        source = Source(
            project_id=project.id,
            team_id=team.id,
            type=SourceType.ONSHAPE,
            name="onshape",
            status=SourceStatus.CONNECTED,
            config={"documents": documents if documents is not None else [DID]},
            secret_ref=secret_ref,
            account_external_id=account,
        )
        db.add(source)
        await db.commit()
        source_id = source.id
    await store.put(secret_ref, "tok")
    await store.put(refresh_secret_ref(secret_ref), "rt")
    return source_id


class _Clock:
    """The cache's clock, so a test can move time instead of sleeping."""

    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now


def _shared_cache() -> tuple[IntegrationCache, _Clock]:
    clock = _Clock()
    return IntegrationCache(InMemoryCacheStore(clock=clock), clock=clock), clock


def _cached_registry(cache: IntegrationCache) -> ConnectorRegistry:
    """The production shape: a SCOPED factory that hands the connector the
    cache, the account it is charged to, and the trust window its purpose
    earns (a human: an hour; the sweep: five minutes; a webhook: never)."""
    windows = {"user": 3600.0, "scheduled": 300.0, "webhook": None}
    registry = ConnectorRegistry()
    registry.register(
        "onshape",
        lambda: OnshapeConnector(client_id="cid", client_secret="sec", poll_interval=0.0),
    )
    registry.register_scoped(
        "onshape",
        lambda ctx: OnshapeConnector(
            client_id="cid",
            client_secret="sec",
            poll_interval=0.0,
            cache=cache,
            account_ref=ctx.account_ref,
            signal_max_age_seconds=windows[ctx.purpose],
        ),
    )
    return registry


async def _sync_cached(
    maker: async_sessionmaker[AsyncSession],
    registry: ConnectorRegistry,
    source_id: uuid.UUID,
    store: Any,
    *,
    trigger: SyncTrigger = SyncTrigger.MANUAL,
) -> None:
    await execute_source_sync(
        source_id=source_id,
        sessionmaker=maker,
        registry=registry,
        secret_store=store,
        trigger=trigger,
        # A manual trigger carries a job in production; the purpose is derived
        # from the trigger, so none is needed here.
        store=None,
    )


async def _live_entities(maker: async_sessionmaker[AsyncSession], source_id: uuid.UUID) -> int:
    async with maker() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(GraphEntity)
            .where(GraphEntity.source_id == source_id, GraphEntity.deleted_at.is_(None))
        )
    return int(count or 0)


async def test_two_projects_sharing_one_document_pay_for_it_once(onshape: Any, maker: Any) -> None:
    """I1 acceptance — two projects share one Onshape document on one account:
    the second project's FIRST sync costs ZERO calls and lands the same graph."""
    fake, meter = onshape
    store = InMemorySecretStore()
    cache = IntegrationCache(InMemoryCacheStore())
    registry = _cached_registry(cache)
    source_a = await _seed_shared(maker, store)
    source_b = await _seed_shared(maker, store)

    await _sync_cached(maker, registry, source_a, store)
    assert meter.counted > 0, "the first project must actually fetch"
    landed = await _live_entities(maker, source_a)
    assert landed > 0

    meter.reset()
    await _sync_cached(maker, registry, source_b, store)

    assert meter.counted == 0, (
        f"the second project paid {meter.counted} calls for a cached document: "
        f"{dict(meter.by_route)}"
    )
    assert await _live_entities(maker, source_b) == landed, "project B got a different graph"


async def test_a_teammates_repeat_sync_costs_zero_calls(onshape: Any, maker: Any) -> None:
    """I1 acceptance — a repeat read costs zero: the signal recorded by the
    first sync answers the freshness gate, so not even the probe is paid."""
    fake, meter = onshape
    store = InMemorySecretStore()
    registry = _cached_registry(IntegrationCache(InMemoryCacheStore()))
    source_id = await _seed_shared(maker, store)

    await _sync_cached(maker, registry, source_id, store)
    meter.reset()
    await _sync_cached(maker, registry, source_id, store)

    assert meter.counted == 0, f"a repeat sync cost {meter.counted}: {dict(meter.by_route)}"


async def test_the_sweep_moves_the_signal_and_a_users_sync_then_sees_it(
    onshape: Any, maker: Any
) -> None:
    """Sync ONLY when the change signal moves — and the SWEEP is what moves it.

    A human's sync inside the window trusts the recorded signal (zero calls,
    even though upstream changed); the scheduled probe asks Onshape, sees the
    new microversion, and re-exports; the next human sync is current again for
    free.
    """
    fake, meter = onshape
    store = InMemorySecretStore()
    cache, clock = _shared_cache()
    registry = _cached_registry(cache)
    source_id = await _seed_shared(maker, store)
    await _sync_cached(maker, registry, source_id, store)

    fake.bump_microversion()
    meter.reset()
    await _sync_cached(maker, registry, source_id, store)
    assert meter.counted == 0, "a human's sync inside the window must not spend"

    # The sweep reuses a signal only a few minutes old (two projects on one
    # document then cost one probe per sweep); past that it asks.
    clock.now += 600
    meter.reset()
    await _sync_cached(maker, registry, source_id, store, trigger=SyncTrigger.SCHEDULED)
    assert meter.by_route["microversion"] >= 1, "the sweep must ask the provider"
    assert meter.by_route["translations_start"] >= 1, "the sweep saw the change and re-exported"

    meter.reset()
    await _sync_cached(maker, registry, source_id, store)
    assert meter.counted == 0, "after the sweep the human's sync is current for free"


async def test_a_webhook_sync_never_trusts_the_recorded_signal(onshape: Any, maker: Any) -> None:
    """A doorbell means 'it changed'. Whatever was recorded a moment ago, the
    webhook-triggered sync probes — and re-exports when the version moved."""
    fake, meter = onshape
    store = InMemorySecretStore()
    registry = _cached_registry(IntegrationCache(InMemoryCacheStore()))
    source_id = await _seed_shared(maker, store)
    await _sync_cached(maker, registry, source_id, store)

    fake.bump_microversion()
    meter.reset()
    await _sync_cached(maker, registry, source_id, store, trigger=SyncTrigger.WEBHOOK)
    assert meter.by_route["microversion"] >= 1
    assert meter.by_route["translations_start"] >= 1, "a real change was skipped"


async def test_the_shared_cache_never_crosses_accounts(onshape: Any, maker: Any) -> None:
    """Two accounts tracking the same document id each pay for their own
    fetch: a cache hit is only ever served to the credentials that earned it."""
    fake, meter = onshape
    store = InMemorySecretStore()
    registry = _cached_registry(IntegrationCache(InMemoryCacheStore()))
    source_a = await _seed_shared(maker, store, account="acct-1")
    source_b = await _seed_shared(maker, store, account="acct-2")

    await _sync_cached(maker, registry, source_a, store)
    meter.reset()
    await _sync_cached(maker, registry, source_b, store)
    assert meter.by_route["translations_start"] >= 1, "account 2 was served account 1's export"


async def test_listing_the_accounts_documents_costs_zero_calls_after_the_first(
    onshape: Any, maker: Any
) -> None:
    """I1 acceptance — listing is served from the cache after the first walk;
    only an explicit refresh walks the pages again."""
    fake, meter = onshape
    store = InMemorySecretStore()
    # About the cache, not the refresh cooldown (a unit test covers that).
    cache = IntegrationCache(InMemoryCacheStore(), listing_refresh_cooldown_seconds=0)
    registry = _cached_registry(cache)
    source_id = await _seed_shared(maker, store)
    async with maker() as db:
        source = await db.get(Source, source_id)
        assert source is not None and source.secret_ref
        secret_ref = source.secret_ref
    connector = registry.create_scoped(
        "onshape", ConnectorContext(account_ref="acct-1", purpose="user")
    )

    async def listing(refresh: bool = False) -> Any:
        return await list_documents(
            cache,
            connector=connector,
            secret_store=store,
            secret_ref=secret_ref,
            provider="onshape",
            account_ref="acct-1",
            refresh=refresh,
        )

    first = await listing()
    assert first.cached is False and len(first.value) > 0
    assert meter.by_route["document_list"] >= 1, "the first listing walks the pages"

    meter.reset()
    second = await listing()
    assert second.cached is True and second.value == first.value
    assert meter.counted == 0, f"a repeat listing cost {meter.counted}"

    meter.reset()
    third = await listing(refresh=True)
    assert third.cached is False
    assert meter.by_route["document_list"] >= 1, "an explicit refresh asks again"


async def test_one_changed_version_ingests_once_across_repeated_concurrent_hints(
    onshape: Any,
    maker: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Count full connector invocations and exports, not merely HTTP success.

    One document has several exportable elements: one ingestion may require
    one translation per element, but the same version is never ingested twice.
    """
    fake, meter = onshape
    secrets = InMemorySecretStore()
    cache = IntegrationCache(InMemoryCacheStore())
    registry = _cached_registry(cache)
    flights = InMemoryCacheStore()
    source_id = await _seed_shared(maker, secrets)
    ingestions = 0
    original_sync = OnshapeConnector.sync

    async def counted_sync(self: OnshapeConnector, ctx: Any) -> Any:
        nonlocal ingestions
        ingestions += 1
        return await original_sync(self, ctx)

    monkeypatch.setattr(OnshapeConnector, "sync", counted_sync)

    async def hint() -> None:
        await execute_source_sync(
            source_id=source_id,
            sessionmaker=maker,
            registry=registry,
            secret_store=secrets,
            store=flights,
            trigger=SyncTrigger.WEBHOOK,
        )

    await hint()
    exports_per_ingestion = meter.by_route["translations_start"]
    assert ingestions == 1 and exports_per_ingestion > 0
    fake.bump_microversion()
    meter.reset()
    await asyncio.gather(*(hint() for _ in range(8)))
    await hint()
    assert ingestions == 2, "one changed version must cause exactly one further ingestion"
    assert meter.by_route["translations_start"] == exports_per_ingestion
    meter.reset()
    await asyncio.gather(*(hint() for _ in range(3)))
    assert ingestions == 2
    assert meter.by_route["translations_start"] == 0
    async with maker() as db:
        statuses = (await db.scalars(select(Sync.status).where(Sync.source_id == source_id))).all()
        assert all(status is JobStatus.SUCCEEDED for status in statuses)


async def test_expired_payload_cache_does_not_trigger_ingestion(onshape: Any, maker: Any) -> None:
    fake, meter = onshape
    secrets = InMemorySecretStore()
    clock = _Clock()
    cache = IntegrationCache(InMemoryCacheStore(clock=clock), clock=clock, payload_ttl_seconds=1)
    registry = _cached_registry(cache)
    source_id = await _seed_shared(maker, secrets)
    await _sync_cached(maker, registry, source_id, secrets)
    clock.now += 2
    meter.reset()
    await _sync_cached(maker, registry, source_id, secrets)
    assert meter.counted == 0
    assert meter.by_route["translations_start"] == 0
