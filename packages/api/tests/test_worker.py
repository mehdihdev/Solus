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
