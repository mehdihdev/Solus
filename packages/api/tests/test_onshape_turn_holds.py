"""Durable CAD turn holds defer reconciliation without losing dirty generations."""

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import Source, utcnow
from solus_api.services import onshape_webhooks as state
from solus_api.services import onshape_write_sync as service
from test_onshape_write_sync import scope as scope_fixture


@pytest.fixture
async def scope(engine):
    return await scope_fixture.__wrapped__(engine)


def test_independent_holds_keep_generation_and_expire(monkeypatch):
    now = utcnow()
    monkeypatch.setattr(state, "utcnow", lambda: now)
    first, second = uuid.uuid4(), uuid.uuid4()
    value = state.hint_state({})
    value = state.add_write_hold(value, first, now + timedelta(seconds=300))
    value = state.add_write_hold(value, second, now + timedelta(seconds=300))
    assert not state.claim_schedule(value)[1]
    assert not state.recovery_due(value)
    released = state.release_write_hold(value, first)
    assert set(state.active_write_holds(released)) == {str(second)}
    assert released["generation"] == 1
    now += timedelta(seconds=331)
    assert state.recovery_due(released)
    assert state.claim_schedule(released)[1]


def test_hold_deadline_is_fixed_and_capacity_never_evicts():
    now = utcnow()
    owner = uuid.uuid4()
    value = state.add_write_hold({}, owner, now + timedelta(seconds=200))
    expiry = state.active_write_holds(value)[str(owner)]
    value = state.add_write_hold(value, owner, now + timedelta(seconds=300))
    assert state.active_write_holds(value)[str(owner)] == expiry
    for _ in range(31):
        value = state.add_write_hold(value, uuid.uuid4(), now + timedelta(seconds=300))
    with pytest.raises(ConnectorError):
        state.add_write_hold(value, uuid.uuid4(), now + timedelta(seconds=300))
    assert len(state.active_write_holds(value)) == 32


async def test_two_turns_only_final_release_enqueues_and_preserves_dirty(scope):
    maker, source, _ = scope
    owners = [uuid.uuid4(), uuid.uuid4()]
    for owner in owners:
        assert (
            await service.hold_onshape_write_sync(
                maker,
                project_id=source.project_id,
                team_id=source.team_id,
                tool_name="onshape.update_feature",
                args={"document_id": "doc1"},
                store=InMemoryCacheStore(),
                turn_id=owner,
                turn_deadline=utcnow() + timedelta(seconds=300),
            )
            == source.id
        )
    enqueue = AsyncMock(return_value=uuid.uuid4())
    for i, owner in enumerate(owners):
        result = await service.release_onshape_write_sync(
            maker,
            project_id=source.project_id,
            team_id=source.team_id,
            source_id=source.id,
            turn_id=owner,
            enqueue=enqueue,
        )
        assert result["status"] == ("deferred" if i == 0 else "queued")
    enqueue.assert_awaited_once()
    async with maker() as db:
        current = state.state_for(await db.get(Source, source.id))
        assert current["generation"] == 2
        assert state.dirty(current)
        assert not state.active_write_holds(current)


async def test_held_worker_defers_before_connector_or_provider_even_without_cache(scope):
    from solus_api.connectors.worker import execute_source_sync

    maker, source, _ = scope
    async with maker() as db:
        row = await db.get(Source, source.id)
        state.save_state(
            row,
            {
                "generation": 1,
                "write_turn_holds": {
                    str(uuid.uuid4()): (utcnow() + timedelta(seconds=300)).isoformat(),
                },
            },
        )
        await db.commit()
    registry = AsyncMock()
    with pytest.raises(ConnectorError, match="deferred"):
        await execute_source_sync(
            sessionmaker=maker,
            registry=registry,
            secret_store=InMemorySecretStore(),
            source_id=source.id,
            defer_on_busy=True,
            store=None,
        )
    registry.create_scoped.assert_not_called()


@pytest.mark.parametrize("change", ["project", "team", "document", "revoked", "error"])
async def test_hold_refuses_invalid_scope_without_dirty_state(scope, change):
    from solus_api.models import AccountConnection, ConnectionStatus, SourceStatus

    maker, source, connection = scope
    project, team, document = source.project_id, source.team_id, "doc1"
    if change == "project":
        project = uuid.uuid4()
    elif change == "team":
        team = uuid.uuid4()
    elif change == "document":
        document = "foreign"
    else:
        async with maker() as db:
            if change == "revoked":
                row = await db.get(AccountConnection, connection.id)
                row.status = ConnectionStatus.REVOKED
            else:
                row = await db.get(Source, source.id)
                row.status = SourceStatus.ERROR
                row.last_error = {"code": "quota_exhausted"}
            await db.commit()
    with pytest.raises(ConnectorError):
        await service.hold_onshape_write_sync(
            maker,
            project_id=project,
            team_id=team,
            tool_name="onshape.update_feature",
            args={"document_id": document},
            store=None,
            turn_id=uuid.uuid4(),
            turn_deadline=utcnow() + timedelta(seconds=300),
        )
    async with maker() as db:
        assert not state.dirty(state.state_for(await db.get(Source, source.id)))


async def test_revision_changed_source_can_hold_but_enqueue_failure_retains_recovery(scope):
    from solus_api.models import SourceStatus

    maker, source, _ = scope
    owner = uuid.uuid4()
    async with maker() as db:
        row = await db.get(Source, source.id)
        row.status = SourceStatus.ERROR
        row.last_error = {"code": "revision_changed"}
        await db.commit()
    await service.hold_onshape_write_sync(
        maker,
        project_id=source.project_id,
        team_id=source.team_id,
        tool_name="onshape.update_feature",
        args={"document_id": "doc1"},
        store=None,
        turn_id=owner,
        turn_deadline=utcnow() + timedelta(seconds=300),
    )
    result = await service.release_onshape_write_sync(
        maker,
        project_id=source.project_id,
        team_id=source.team_id,
        source_id=source.id,
        turn_id=owner,
        enqueue=AsyncMock(side_effect=RuntimeError("private")),
    )
    assert result == {"status": "failed"}
    async with maker() as db:
        current = state.state_for(await db.get(Source, source.id))
        assert state.recovery_due(current)
        assert not state.active_write_holds(current)


async def test_foreign_release_cannot_remove_owner(scope):
    maker, source, _ = scope
    owner = uuid.uuid4()
    await service.hold_onshape_write_sync(
        maker,
        project_id=source.project_id,
        team_id=source.team_id,
        tool_name="onshape.update_feature",
        args={"document_id": "doc1"},
        store=None,
        turn_id=owner,
        turn_deadline=utcnow() + timedelta(seconds=300),
    )
    enqueue = AsyncMock()
    result = await service.release_onshape_write_sync(
        maker,
        project_id=uuid.uuid4(),
        team_id=source.team_id,
        source_id=source.id,
        turn_id=owner,
        enqueue=enqueue,
    )
    assert result == {"status": "unavailable"}
    await service.release_onshape_write_sync(
        maker,
        project_id=source.project_id,
        team_id=source.team_id,
        source_id=source.id,
        turn_id=uuid.uuid4(),
        enqueue=enqueue,
    )
    enqueue.assert_not_awaited()
    async with maker() as db:
        assert str(owner) in state.active_write_holds(
            state.state_for(await db.get(Source, source.id))
        )


async def test_cache_invalidation_failure_prevents_hold_admission(scope):
    maker, source, _ = scope
    store = InMemoryCacheStore()
    store.delete = AsyncMock(side_effect=RuntimeError("private"))
    with pytest.raises(ConnectorError, match="not started"):
        await service.hold_onshape_write_sync(
            maker,
            project_id=source.project_id,
            team_id=source.team_id,
            tool_name="onshape.update_feature",
            args={"document_id": "doc1"},
            store=store,
            turn_id=uuid.uuid4(),
            turn_deadline=utcnow() + timedelta(seconds=300),
        )
    async with maker() as db:
        assert not state.dirty(state.state_for(await db.get(Source, source.id)))


async def test_queued_worker_rechecks_hold_after_acquiring_source_flight(scope, monkeypatch):
    from unittest.mock import MagicMock

    from solus_api.connectors import worker
    from solus_api.models import Job, JobKind, JobStatus

    maker, source, _ = scope
    async with maker() as db:
        job = Job(
            project_id=source.project_id,
            team_id=source.team_id,
            kind=JobKind.SYNC,
            status=JobStatus.QUEUED,
        )
        db.add(job)
        await db.commit()

    async def acquire(*args, **kwargs):
        async with maker() as db:
            row = await db.get(Source, source.id)
            state.save_state(
                row,
                state.add_write_hold(
                    state.hint_state({}), uuid.uuid4(), utcnow() + timedelta(seconds=300)
                ),
            )
            await db.commit()
        return "owner"

    async def run_in_flight(*args, run, **kwargs):
        return await run()

    monkeypatch.setattr(worker, "single_flight", acquire)
    monkeypatch.setattr(worker, "run_in_flight", run_in_flight)
    release = AsyncMock()
    monkeypatch.setattr(worker, "release_flight", release)
    monkeypatch.setattr(worker, "_ensure_onshape_subscription", AsyncMock())
    run = AsyncMock()
    monkeypatch.setattr(worker, "_run", run)
    with pytest.raises(ConnectorError, match="deferred"):
        await worker.execute_source_sync(
            sessionmaker=maker,
            registry=MagicMock(),
            secret_store=InMemorySecretStore(),
            source_id=source.id,
            job_id=job.id,
            defer_on_busy=True,
            store=InMemoryCacheStore(),
        )
    run.assert_not_awaited()
    release.assert_awaited_once()
    async with maker() as db:
        assert (await db.get(Job, job.id)).status == JobStatus.QUEUED


async def test_recovery_does_not_enqueue_held_generation(scope):
    from solus_api.connectors.worker import recover_onshape_hints

    maker, source, _ = scope
    async with maker() as db:
        row = await db.get(Source, source.id)
        state.save_state(
            row,
            state.add_write_hold(
                state.hint_state({}), uuid.uuid4(), utcnow() + timedelta(seconds=300)
            ),
        )
        await db.commit()
    redis = AsyncMock()
    assert await recover_onshape_hints({"sessionmaker": maker, "redis": redis}) == 0
    redis.enqueue_job.assert_not_awaited()


async def test_no_cache_worker_rechecks_hold_after_subscription_setup(scope, monkeypatch):
    from unittest.mock import MagicMock

    from solus_api.connectors import worker

    maker, source, _ = scope

    async def subscribe(*args):
        async with maker() as db:
            row = await db.get(Source, source.id)
            state.save_state(
                row,
                state.add_write_hold(
                    state.hint_state({}), uuid.uuid4(), utcnow() + timedelta(seconds=300)
                ),
            )
            await db.commit()

    monkeypatch.setattr(worker, "_ensure_onshape_subscription", subscribe)
    run = AsyncMock()
    monkeypatch.setattr(worker, "_run", run)
    with pytest.raises(ConnectorError, match="deferred"):
        await worker.execute_source_sync(
            sessionmaker=maker,
            registry=MagicMock(),
            secret_store=InMemorySecretStore(),
            source_id=source.id,
            defer_on_busy=True,
            store=None,
        )
    run.assert_not_awaited()


async def test_concurrent_hold_updates_do_not_lose_an_owner_or_generation(scope):
    import asyncio

    maker, source, _ = scope
    owners = [uuid.uuid4(), uuid.uuid4()]
    deadline = utcnow() + timedelta(seconds=300)
    results = await asyncio.gather(
        *[
            service.hold_onshape_write_sync(
                maker,
                project_id=source.project_id,
                team_id=source.team_id,
                tool_name="onshape.update_feature",
                args={"document_id": "doc1"},
                store=None,
                turn_id=owner,
                turn_deadline=deadline,
            )
            for owner in owners
        ]
    )
    assert results == [source.id, source.id]
    async with maker() as db:
        current = state.state_for(await db.get(Source, source.id))
        assert current["generation"] == 2
        assert set(state.active_write_holds(current)) == {str(owner) for owner in owners}


@pytest.mark.parametrize("seconds", [-31, 301])
def test_hold_rejects_expired_or_unbounded_deadline(seconds):
    with pytest.raises(ConnectorError):
        state.add_write_hold({}, uuid.uuid4(), utcnow() + timedelta(seconds=seconds))
