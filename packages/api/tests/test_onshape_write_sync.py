"""An applied CAD write schedules fresh, tenant-scoped graph ingestion."""

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
    Project,
    Source,
    SourceStatus,
    SourceType,
    Team,
    User,
)
from solus_api.services.onshape_write_sync import schedule_onshape_write_sync
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

Scope = tuple[async_sessionmaker[AsyncSession], Source, AccountConnection]


@pytest.fixture
async def scope(engine: AsyncEngine) -> Scope:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = User(supabase_user_id=str(uuid.uuid4()), email="sync@example.test")
        team = Team(name="CAD")
        db.add_all([user, team])
        await db.flush()
        project = Project(team_id=team.id, name="Robot")
        db.add(project)
        await db.flush()
        connection = AccountConnection(
            user_id=user.id,
            provider=SourceType.ONSHAPE,
            status=ConnectionStatus.CONNECTED,
            secret_ref="test-reference",
        )
        db.add(connection)
        await db.flush()
        source = Source(
            project_id=project.id,
            team_id=team.id,
            type=SourceType.ONSHAPE,
            status=SourceStatus.CONNECTED,
            name="CAD",
            config={"documents": ["doc1"]},
            connection_id=connection.id,
            secret_ref=connection.secret_ref,
        )
        db.add(source)
        await db.commit()
    return maker, source, connection


async def test_invalidates_only_target_signal_before_enqueue(scope: Scope) -> None:
    maker, source, connection = scope
    store = InMemoryCacheStore()
    keys = [
        IntegrationCache.signal_key("onshape", ref, "doc1")
        for ref in (
            f"source:{source.id}",
            f"connection:{connection.id}",
        )
    ]
    for key in [*keys, "untouched-payload"]:
        await store.set(key, "cached", 300)
    job_id = uuid.uuid4()

    async def enqueue(db: AsyncSession, selected: Source) -> uuid.UUID:
        assert selected.id == source.id
        assert all([await store.get(key) is None for key in keys])
        assert await store.get("untouched-payload") == "cached"
        return job_id

    result = await schedule_onshape_write_sync(
        maker,
        project_id=source.project_id,
        team_id=source.team_id,
        tool_name="onshape.update_feature",
        args={"document_id": "doc1"},
        store=store,
        enqueue=enqueue,
    )
    assert result == {"status": "queued", "job_id": str(job_id)}


@pytest.mark.parametrize(
    "change", ["project", "team", "document", "disconnected", "revoked", "revision"]
)
async def test_never_schedules_outside_live_scope(scope: Scope, change: str) -> None:
    maker, source, connection = scope
    project_id, team_id, document_id = source.project_id, source.team_id, "doc1"
    if change == "project":
        project_id = uuid.uuid4()
    elif change == "team":
        team_id = uuid.uuid4()
    elif change == "document":
        document_id = "other"
    else:
        async with maker() as db:
            row = await db.get(Source, source.id)
            assert row is not None
            if change == "disconnected":
                row.status = SourceStatus.DISCONNECTED
            elif change == "revision":
                row.revision_base_source_id = source.id
            else:
                account = await db.get(AccountConnection, connection.id)
                assert account is not None
                account.status = ConnectionStatus.REVOKED
            await db.commit()
    enqueue = AsyncMock()
    result = await schedule_onshape_write_sync(
        maker,
        project_id=project_id,
        team_id=team_id,
        tool_name="onshape.update_feature",
        args={"document_id": document_id},
        store=InMemoryCacheStore(),
        enqueue=enqueue,
    )
    assert result is not None and result["status"] == "unavailable"
    enqueue.assert_not_awaited()


@pytest.mark.parametrize("tool", ["onshape.list_parts", "hosted.anything", "onshape.unknown"])
async def test_non_native_writes_do_not_schedule(scope: Scope, tool: str) -> None:
    maker, source, _ = scope
    enqueue = AsyncMock()
    result = await schedule_onshape_write_sync(
        maker,
        project_id=source.project_id,
        team_id=source.team_id,
        tool_name=tool,
        args={"document_id": "doc1"},
        store=None,
        enqueue=enqueue,
    )
    assert result is None
    enqueue.assert_not_awaited()


@pytest.mark.parametrize("failure", ["cache", "enqueue"])
async def test_scheduling_failure_is_separate_from_applied_write(
    scope: Scope, failure: str
) -> None:
    maker, source, _ = scope
    store = InMemoryCacheStore()
    enqueue = AsyncMock(return_value=uuid.uuid4())
    if failure == "cache":
        store.delete = AsyncMock(side_effect=RuntimeError("private vendor detail"))  # type: ignore[method-assign]
    else:
        enqueue.side_effect = RuntimeError("private vendor detail")
    result = await schedule_onshape_write_sync(
        maker,
        project_id=source.project_id,
        team_id=source.team_id,
        tool_name="onshape.update_feature",
        args={"document_id": "doc1"},
        store=store,
        enqueue=enqueue,
    )
    assert result == {
        "status": "failed",
        "message": "CAD change applied; graph sync could not be scheduled. "
        "Retry source sync, not the CAD change.",
    }
    if failure == "cache":
        enqueue.assert_not_awaited()


@pytest.mark.parametrize("hang", ["cache", "enqueue"])
async def test_scheduling_has_a_deadline(
    scope: Scope, monkeypatch: pytest.MonkeyPatch, hang: str
) -> None:
    from solus_api.services import onshape_write_sync

    maker, source, _ = scope
    monkeypatch.setattr(onshape_write_sync, "SCHEDULING_TIMEOUT_SECONDS", 0.05, raising=False)
    store = InMemoryCacheStore()

    async def never_returns(*args: Any) -> None:
        await asyncio.Event().wait()

    enqueue = AsyncMock(return_value=uuid.uuid4())
    if hang == "cache":
        store.delete = never_returns  # type: ignore[method-assign,assignment]
    else:
        enqueue.side_effect = never_returns
    result = await asyncio.wait_for(
        schedule_onshape_write_sync(
            maker,
            project_id=source.project_id,
            team_id=source.team_id,
            tool_name="onshape.update_feature",
            args={"document_id": "doc1"},
            store=store,
            enqueue=enqueue,
        ),
        timeout=1,
    )
    assert result is not None and result["status"] == "failed"
