"""Sync executor tests — state persistence, entity/relation upsert, incremental
reconciliation, and failure recording (SOLUSDEV-103 acceptance criteria)."""

import uuid

import pytest
from solus_api.connectors.contracts import (
    AccountInfo,
    AuthKind,
    Connector,
    ConnectorError,
    Credentials,
    Domain,
    EntityOut,
    RelationOut,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.runtime import run_sync
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import (
    Entity,
    JobStatus,
    Project,
    Relation,
    Source,
    SourceStatus,
    SourceType,
    Sync,
    SyncTrigger,
    Team,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


class ScriptedConnector(Connector):
    """Returns a queued list of SyncResults (or raises) across successive syncs."""

    provider = "fake"
    auth_kind = AuthKind.PAT

    def __init__(self, results: list[SyncResult | Exception]) -> None:
        self._results = results
        self._i = 0

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        return AccountInfo(external_id="1", login="octo")

    async def sync(self, ctx: SyncContext) -> SyncResult:
        item = self._results[self._i]
        self._i += 1
        if isinstance(item, Exception):
            raise item
        return item

    async def detect_changes(self, ctx: SyncContext) -> bool:
        return True


def _entity(key: str, name: str | None = None) -> EntityOut:
    return EntityOut(
        source_key=key, type="code_file", domain=Domain.SOFTWARE, name=name or key
    )


async def _seed_source(
    maker: async_sessionmaker[AsyncSession], store: InMemorySecretStore
) -> Source:
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
            config={"repo": "octo/r", "branch": "main"},
            secret_ref=f"source/{uuid.uuid4()}",
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
    await store.put(source.secret_ref or "", "tok")
    return source


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_sync_persists_entities_and_relations(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    result = SyncResult(
        entities=[_entity("pkg"), _entity("pkg/a.py")],
        relations=[RelationOut(from_key="pkg", to_key="pkg/a.py", type="contains")],
        cursor={"sha": "abc"},
    )
    connector = ScriptedConnector([result])

    sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )

    async with maker() as db:
        sync = await db.get(Sync, sync_id)
        assert sync is not None
        assert sync.status == JobStatus.SUCCEEDED
        assert sync.entities_created == 2
        assert sync.relations_created == 1
        assert sync.trigger == SyncTrigger.MANUAL
        entities = (await db.scalars(select(Entity).where(Entity.source_id == source.id))).all()
        assert {e.source_key for e in entities} == {"pkg", "pkg/a.py"}
        rel_count = await db.scalar(
            select(func.count()).select_from(Relation).where(Relation.source_id == source.id)
        )
        assert rel_count == 1
        refreshed = await db.get(Source, source.id)
        assert refreshed is not None
        assert refreshed.status == SourceStatus.CONNECTED
        assert refreshed.cursor == {"sha": "abc"}
        assert refreshed.last_synced_at is not None


async def test_resync_updates_and_reconciles(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    first = SyncResult(
        entities=[_entity("pkg"), _entity("pkg/a.py"), _entity("pkg/old.py")],
        relations=[RelationOut(from_key="pkg", to_key="pkg/a.py", type="contains")],
        cursor={"sha": "1"},
    )
    # second sync: a.py renamed, old.py removed, new.py added; relation changes.
    second = SyncResult(
        entities=[_entity("pkg"), _entity("pkg/a.py", name="renamed.py"), _entity("pkg/new.py")],
        relations=[RelationOut(from_key="pkg", to_key="pkg/new.py", type="contains")],
        cursor={"sha": "2"},
    )
    connector = ScriptedConnector([first, second])

    await run_sync(source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store)
    second_sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )

    async with maker() as db:
        entities = (await db.scalars(select(Entity).where(Entity.source_id == source.id))).all()
        by_key = {e.source_key: e for e in entities}
        assert set(by_key) == {"pkg", "pkg/a.py", "pkg/new.py"}  # old.py reconciled away
        assert by_key["pkg/a.py"].name == "renamed.py"
        assert by_key["pkg/a.py"].version == 2  # bumped on update
        sync = await db.get(Sync, second_sync_id)
        assert sync is not None
        assert sync.entities_updated >= 1
        assert sync.relations_created == 1
        assert sync.relations_deleted == 1


async def test_sync_records_connector_failure(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    connector = ScriptedConnector([ConnectorError("repo_not_found", "no such repo")])

    sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )

    async with maker() as db:
        sync = await db.get(Sync, sync_id)
        assert sync is not None
        assert sync.status == JobStatus.FAILED
        assert sync.errors and sync.errors[0]["message"] == "no such repo"
        source_row = await db.get(Source, source.id)
        assert source_row is not None
        assert source_row.status == SourceStatus.ERROR
        assert source_row.last_error is not None
        assert source_row.last_error["code"] == "repo_not_found"


async def test_sync_fails_without_credentials(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    store = InMemorySecretStore()  # secret never put
    source = await _seed_source(maker, store)
    await store.delete(source.secret_ref or "")
    connector = ScriptedConnector([SyncResult()])

    sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )
    async with maker() as db:
        sync = await db.get(Sync, sync_id)
        assert sync is not None
        assert sync.status == JobStatus.FAILED
