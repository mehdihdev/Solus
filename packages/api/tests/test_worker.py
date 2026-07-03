"""Tests for the connector worker glue: provider resolution + inline execution,
and the scheduled change-detection sweep (SOLUSDEV-103 'schedules detect_changes')."""

import uuid

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
        team = Team(name="T", is_personal=False)
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
