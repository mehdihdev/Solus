"""Tests for the connector worker glue: provider resolution + inline execution,
and the scheduled change-detection sweep (SOLUSDEV-103 'schedules detect_changes')."""

import uuid
from typing import Any

import pytest
from solus_api.connectors.contracts import (
    AccountInfo,
    AuthKind,
    Connector,
    Credentials,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.connectors.worker import execute_source_sync, run_change_detection
from solus_api.models import (
    JobStatus,
    Project,
    Source,
    SourceStatus,
    SourceType,
    Sync,
    Team,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


class StubConnector(Connector):
    provider = "github"
    auth_kind = AuthKind.OAUTH

    def __init__(self, *, changed: bool = True) -> None:
        self._changed = changed

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        return AccountInfo(external_id="1", login="octo")

    async def sync(self, ctx: SyncContext) -> SyncResult:
        return SyncResult(cursor={"sha": "synced"})

    async def detect_changes(self, ctx: SyncContext) -> bool:
        return self._changed


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _source(maker: async_sessionmaker[AsyncSession], store: InMemorySecretStore) -> Source:
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        source = Source(
            project_id=project.id,
            team_id=team.id,
            type=SourceType.GITHUB,
            name="octo/r",
            status=SourceStatus.CONNECTED,
            config={"repo": "octo/r"},
            secret_ref=f"source/{uuid.uuid4()}",
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
    await store.put(source.secret_ref or "", "tok")
    return source


async def test_execute_source_sync_resolves_provider(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    store = InMemorySecretStore()
    source = await _source(maker, store)
    registry = ConnectorRegistry()
    registry.register("github", StubConnector)

    sync_id = await execute_source_sync(
        sessionmaker=maker,
        registry=registry,
        secret_store=store,
        source_id=source.id,
    )
    async with maker() as db:
        sync = await db.get(Sync, sync_id)
        assert sync is not None
        assert sync.status == JobStatus.SUCCEEDED


async def test_change_detection_enqueues_only_changed_sources(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    store = InMemorySecretStore()
    changed_source = await _source(maker, store)
    unchanged_source = await _source(maker, store)
    # Make one source's connector report "no change".
    registry = ConnectorRegistry()

    def factory() -> Connector:
        return StubConnector(changed=True)

    registry.register("github", factory)

    enqueued: list[uuid.UUID] = []

    async def fake_enqueue(source_id: uuid.UUID) -> None:
        enqueued.append(source_id)

    # First mark the unchanged source's connector to report no change by giving
    # it a cursor the stub considers current — simulate via a no-change registry.
    no_change_registry = ConnectorRegistry()
    no_change_registry.register("github", lambda: StubConnector(changed=False))

    await run_change_detection(
        sessionmaker=maker,
        registry=registry,
        secret_store=store,
        enqueue=fake_enqueue,
    )
    assert set(enqueued) == {changed_source.id, unchanged_source.id}

    enqueued.clear()
    await run_change_detection(
        sessionmaker=maker,
        registry=no_change_registry,
        secret_store=store,
        enqueue=fake_enqueue,
    )
    assert enqueued == []


# ------------------------------------- SOLUSDEV-167: the sweep must stay fair


async def test_one_large_tenant_cannot_starve_every_other_team(engine: Any) -> None:
    """The bug the first attempt at this shipped: `LIMIT` in SQL with the
    per-team cap applied afterwards in Python. One tenant with more sources than
    the limit filled the whole snapshot, only 3 of theirs were probed, and NO
    other team's sources entered the sweep at all — and because the skipped ones
    were never synced, their NULL `last_synced_at` kept them pinned at the head
    of `NULLS FIRST` forever. Self-sustaining starvation, produced by the
    fairness code.
    """
    import uuid as _uuid

    from solus_api.connectors.worker import (
        _MAX_SOURCES_PER_SWEEP,
        _MAX_SOURCES_PER_TEAM_PER_SWEEP,
        _fair_sweep_query,
    )
    from solus_api.models import Project, Source, SourceStatus, SourceType, Team
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        big, small = Team(name="big"), Team(name="small")
        db.add_all([big, small])
        await db.flush()
        projects = {}
        for team in (big, small):
            project = Project(team_id=team.id, name=f"p-{team.name}")
            db.add(project)
            await db.flush()
            projects[team.name] = project
        # The big tenant alone exceeds the global sweep limit.
        for i in range(_MAX_SOURCES_PER_SWEEP + 20):
            db.add(
                Source(
                    project_id=projects["big"].id,
                    team_id=big.id,
                    type=SourceType.KICAD,
                    name=f"big-{i}",
                    status=SourceStatus.CONNECTED,
                    config={},
                )
            )
        db.add(
            Source(
                project_id=projects["small"].id,
                team_id=small.id,
                type=SourceType.KICAD,
                name="small-1",
                status=SourceStatus.CONNECTED,
                config={},
            )
        )
        await db.commit()
        small_team_id = small.id
        big_team_id = big.id

    async with maker() as db:
        picked = list((await db.scalars(_fair_sweep_query())).all())

    by_team: dict[_uuid.UUID, int] = {}
    for source in picked:
        by_team[source.team_id] = by_team.get(source.team_id, 0) + 1

    assert by_team.get(small_team_id, 0) >= 1, "the small tenant was starved out of the sweep"
    assert by_team.get(big_team_id, 0) <= _MAX_SOURCES_PER_TEAM_PER_SWEEP, (
        "one tenant took more than its per-sweep share"
    )


async def test_onshape_reconciliation_acknowledges_only_captured_generation(maker, monkeypatch):
    from solus_api.connectors.worker import _run
    from solus_api.services.onshape_webhooks import hint_state, save_state, state_for

    store = InMemorySecretStore()
    source = await _source(maker, store)
    async with maker() as db:
        row = await db.get(Source, source.id)
        row.type = SourceType.ONSHAPE
        save_state(row, hint_state({}))
        await db.commit()

    async def reconcile(**kwargs):
        async with maker() as db:
            row = await db.get(Source, source.id, with_for_update=True)
            save_state(row, hint_state(state_for(row)))
            sync = Sync(source_id=row.id, project_id=row.project_id, status=JobStatus.SUCCEEDED)
            db.add(sync)
            await db.commit()
            return sync.id

    monkeypatch.setattr("solus_api.connectors.worker.run_sync", reconcile)
    from solus_api.models import SyncTrigger

    await _run(
        StubConnector(), source.id, maker, store, SyncTrigger.WEBHOOK, None, None, False, None
    )
    async with maker() as db:
        row = await db.get(Source, source.id)
        assert state_for(row)["generation"] == 2
        assert state_for(row)["acknowledged"] == 1


async def test_healthy_onshape_subscription_spends_zero_polling_calls(maker):
    from unittest.mock import AsyncMock

    from solus_api.models import utcnow
    from solus_api.services.onshape_webhooks import save_state

    store = InMemorySecretStore()
    source = await _source(maker, store)
    async with maker() as db:
        row = await db.get(Source, source.id)
        row.type = SourceType.ONSHAPE
        row.config = {"documents": ["doc"]}
        save_state(
            row,
            {
                "status": "registered",
                "subscriptions": {"doc": "hook"},
                "deliveries": {"doc": utcnow().isoformat()},
            },
        )
        await db.commit()
    registry = ConnectorRegistry()  # No Onshape factory: a provider call would fail.
    enqueue = AsyncMock()
    assert (
        await run_change_detection(
            sessionmaker=maker, registry=registry, secret_store=store, enqueue=enqueue
        )
        == 0
    )
    enqueue.assert_not_called()


async def test_queued_webhook_bypasses_warm_signal_before_acknowledging(maker):
    from unittest.mock import AsyncMock

    from solus_api.connectors.httpcache import InMemoryCacheStore
    from solus_api.connectors.integration_cache import IntegrationCache
    from solus_api.connectors.onshape import PROJECTION_VERSION, OnshapeConnector
    from solus_api.connectors.worker import sync_source
    from solus_api.services.connections import account_ref_for
    from solus_api.services.onshape_webhooks import hint_state, save_state, state_for

    store = InMemorySecretStore()
    source = await _source(maker, store)
    document, workspace = "a" * 24, "b" * 24
    async with maker() as db:
        row = await db.get(Source, source.id)
        row.type = SourceType.ONSHAPE
        row.config = {"documents": [document]}
        row.cursor = {
            "microversions": {document: "old"},
            "workspaces": {document: workspace},
            "projection_version": PROJECTION_VERSION,
        }
        save_state(row, hint_state({}))
        await db.commit()
    cache = IntegrationCache(InMemoryCacheStore())
    await cache.record_signal(
        cache.signal_key("onshape", account_ref_for(source), document),
        {"workspace": workspace, "version": "old"},
    )
    fresh_probe = AsyncMock(return_value="new")
    synced = AsyncMock(return_value=SyncResult(cursor={"microversions": {document: "new"}}))

    def factory(ctx):
        connector = OnshapeConnector(
            client_id="test",
            client_secret="test",
            cache=cache,
            account_ref=ctx.account_ref,
            signal_max_age_seconds=None if ctx.purpose == "webhook" else 300,
        )
        connector._current_microversion = fresh_probe
        connector.sync = synced
        return connector

    registry = ConnectorRegistry()
    registry.register_scoped("onshape", factory)
    await sync_source(
        {"sessionmaker": maker, "registry": registry, "secret_store": store},
        str(source.id),
        webhook=True,
    )
    fresh_probe.assert_awaited_once()
    synced.assert_awaited_once()
    async with maker() as db:
        row = await db.get(Source, source.id)
        assert row.cursor["microversions"][document] == "new"
        assert state_for(row)["acknowledged"] == 1


async def test_recovery_ranks_dirty_sources_before_clean_team_neighbors(maker):
    from datetime import timedelta
    from unittest.mock import AsyncMock

    from solus_api.connectors.worker import recover_onshape_hints
    from solus_api.models import utcnow
    from solus_api.services.onshape_webhooks import hint_state, save_state

    store = InMemorySecretStore()
    source = await _source(maker, store)
    async with maker() as db:
        row = await db.get(Source, source.id)
        row.type = SourceType.ONSHAPE
        row.last_synced_at = utcnow()
        save_state(row, hint_state({}))
        for index in range(3):
            db.add(
                Source(
                    project_id=row.project_id,
                    team_id=row.team_id,
                    type=SourceType.ONSHAPE,
                    name=f"healthy{index}",
                    status=SourceStatus.CONNECTED,
                    config={},
                    last_synced_at=utcnow() - timedelta(days=1),
                )
            )
        await db.commit()
    redis = AsyncMock()
    assert await recover_onshape_hints({"sessionmaker": maker, "redis": redis}) == 1
    redis.enqueue_job.assert_awaited_once_with(
        "sync_source", str(source.id), _job_id=f"onshape-recovery:{source.id}", webhook=True
    )


async def test_healthy_local_skips_rotate_so_fourth_source_is_probed(maker):
    from datetime import timedelta
    from unittest.mock import AsyncMock

    from solus_api.models import utcnow
    from solus_api.services.onshape_webhooks import save_state

    store = InMemorySecretStore()
    source = await _source(maker, store)
    async with maker() as db:
        row = await db.get(Source, source.id)
        row.type = SourceType.ONSHAPE
        row.last_synced_at = utcnow()
        for index in range(3):
            healthy = Source(
                project_id=row.project_id,
                team_id=row.team_id,
                type=SourceType.ONSHAPE,
                name=f"healthy{index}",
                status=SourceStatus.CONNECTED,
                config={"documents": ["doc"]},
                last_synced_at=utcnow() - timedelta(days=1),
            )
            save_state(
                healthy,
                {
                    "status": "registered",
                    "subscriptions": {"doc": "hook"},
                    "deliveries": {"doc": utcnow().isoformat()},
                },
            )
            db.add(healthy)
        await db.commit()
    registry = ConnectorRegistry()
    registry.register("onshape", StubConnector)
    enqueue = AsyncMock()
    kwargs = dict(sessionmaker=maker, registry=registry, secret_store=store, enqueue=enqueue)
    assert await run_change_detection(**kwargs) == 0
    assert await run_change_detection(**kwargs) == 1
    enqueue.assert_awaited_once_with(source.id)
