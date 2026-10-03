"""ADR-038 §1: revoking a grant reliably deletes the durable CAD, retrying until it is gone."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import (
    AccountConnection,
    CadPurgeRequest,
    ConnectionStatus,
    Project,
    Source,
    SourceStatus,
    SourceType,
    Team,
    User,
)
from solus_api.services.cad_purge import (
    DELAYED_PASS_SECONDS,
    PASSES,
    enqueue_cad_purge,
    run_cad_purges_after_commit,
    run_due_cad_purges,
    schedule_cad_purge,
    scope_hash,
)
from solus_api.services.connections import revoke_connection
from solus_api.storage.cad_store import LocalCadStore, account_hash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
MIB = 1024 * 1024


def _store(tmp_path: Path) -> LocalCadStore:
    return LocalCadStore(str(tmp_path / "cad"), max_object_bytes=64 * MIB)


def _cache(tmp_path: Path) -> tuple[IntegrationCache, LocalCadStore]:
    cad = _store(tmp_path)
    return IntegrationCache(InMemoryCacheStore(), durable_store=cad), cad


async def _rows(db: AsyncSession) -> list[CadPurgeRequest]:
    db.expire_all()
    return list((await db.scalars(select(CadPurgeRequest))).all())


class _FlakyStore:
    """Wraps a real store; `delete_account_hash` fails while `failing` is set."""

    def __init__(self, inner: LocalCadStore) -> None:
        self.inner = inner
        self.max_object_bytes = inner.max_object_bytes
        self.failing = True
        self.calls = 0

    async def put(self, account_scope: str, data: bytes) -> str:
        return await self.inner.put(account_scope, data)

    async def get(self, object_key: str) -> bytes | None:
        return await self.inner.get(object_key)

    async def delete(self, object_key: str) -> None:
        await self.inner.delete(object_key)

    async def delete_account(self, account_scope: str) -> int:
        return await self.delete_account_hash(account_hash(account_scope))

    async def delete_account_hash(self, digest: str) -> int:
        self.calls += 1
        if self.failing:
            raise OSError("s3 is down")
        return await self.inner.delete_account_hash(digest)


# ------------------------------------------------------------------ the record


async def test_the_record_holds_only_the_opaque_account_hash(db: AsyncSession) -> None:
    digest = scope_hash("onshape", "acct-with-an-email@example.com")
    await enqueue_cad_purge(db, [digest], now=NOW)
    await db.commit()

    [row] = await _rows(db)
    assert row.account_hash == digest == account_hash("onshape:acct-with-an-email@example.com")
    assert row.passes_remaining == PASSES and row.attempts == 0 and row.next_attempt_at == NOW
    columns = {column.name for column in CadPurgeRequest.__table__.columns}
    assert columns == {
        "id",
        "account_hash",
        "passes_remaining",
        "attempts",
        "next_attempt_at",
        "created_at",
    }


async def test_enqueueing_twice_keeps_one_record_and_resets_it(db: AsyncSession) -> None:
    digest = scope_hash("onshape", "a")
    await enqueue_cad_purge(db, [digest], now=NOW)
    await db.commit()
    [row] = await _rows(db)
    row.passes_remaining, row.attempts = 1, 4
    await db.commit()

    await enqueue_cad_purge(db, [digest, digest], now=NOW)
    await db.commit()

    [again] = await _rows(db)
    assert (again.passes_remaining, again.attempts) == (PASSES, 0)


# ------------------------------------------------------------------ the purge


async def test_a_purge_deletes_the_prefix_and_runs_a_second_time_after_a_delay(
    db: AsyncSession, tmp_path: Path
) -> None:
    cad = _store(tmp_path)
    await enqueue_cad_purge(db, [scope_hash("onshape", "a")], now=NOW)
    await db.commit()
    first = await cad.put("onshape:a", b"first")
    other = await cad.put("onshape:b", b"keep")

    assert await run_due_cad_purges(db, cad, now=NOW) == 1
    assert await cad.get(first) is None and await cad.get(other) == b"keep"
    [row] = await _rows(db)
    assert row.passes_remaining == PASSES - 1
    assert row.next_attempt_at == NOW + timedelta(seconds=DELAYED_PASS_SECONDS)

    # An in-flight sync's write that landed after the first pass...
    late = await cad.put("onshape:a", b"late write")
    # ...is not touched before the delay is up,
    assert await run_due_cad_purges(db, cad, now=NOW + timedelta(seconds=1)) == 0
    assert await cad.get(late) == b"late write"
    # but the second pass catches it and clears the record.
    later = NOW + timedelta(seconds=DELAYED_PASS_SECONDS + 1)
    assert await run_due_cad_purges(db, cad, now=later) == 1
    assert await cad.get(late) is None
    assert await _rows(db) == []


async def test_a_failing_purge_is_kept_and_retried_with_backoff_never_dropped(
    db: AsyncSession, tmp_path: Path
) -> None:
    flaky = _FlakyStore(_store(tmp_path))
    key = await flaky.put("onshape:a", b"secret")
    await enqueue_cad_purge(db, [scope_hash("onshape", "a")], now=NOW)
    await db.commit()

    delays = []
    clock = NOW
    for _ in range(3):
        assert await run_due_cad_purges(db, flaky, now=clock) == 0  # never raises
        [row] = await _rows(db)
        assert row.passes_remaining == PASSES  # a failure is not a completed pass
        delays.append((row.next_attempt_at - clock).total_seconds())
        clock = row.next_attempt_at
    assert delays == [60, 120, 240]
    assert await flaky.get(key) == b"secret"

    flaky.failing = False
    assert await run_due_cad_purges(db, flaky, now=clock) == 1
    assert await flaky.get(key) is None
    [row] = await _rows(db)
    assert row.attempts == 0 and row.passes_remaining == PASSES - 1


async def test_the_backoff_is_capped(db: AsyncSession, tmp_path: Path) -> None:
    flaky = _FlakyStore(_store(tmp_path))
    await enqueue_cad_purge(db, [scope_hash("onshape", "a")], now=NOW)
    await db.commit()
    [row] = await _rows(db)
    row.attempts = 40
    await db.commit()
    await run_due_cad_purges(db, flaky, now=NOW)
    [after] = await _rows(db)
    assert (after.next_attempt_at - NOW).total_seconds() == 3600


async def test_without_a_store_records_wait_untouched(db: AsyncSession) -> None:
    await enqueue_cad_purge(db, [scope_hash("onshape", "a")], now=NOW)
    await db.commit()
    assert await run_due_cad_purges(db, None, now=NOW) == 0
    [row] = await _rows(db)
    assert row.passes_remaining == PASSES


async def test_after_commit_runner_swallows_failures_and_timeouts(
    db: AsyncSession, tmp_path: Path
) -> None:
    flaky = _FlakyStore(_store(tmp_path))
    await enqueue_cad_purge(db, [scope_hash("onshape", "a")], now=NOW)
    await db.commit()
    await run_cad_purges_after_commit(db, flaky)  # must not raise
    assert len(await _rows(db)) == 1

    class _Hangs(_FlakyStore):
        async def delete_account_hash(self, digest: str) -> int:
            await asyncio.sleep(30)
            return 0

    await run_cad_purges_after_commit(db, _Hangs(_store(tmp_path)), timeout_seconds=0.05)
    assert len(await _rows(db)) == 1  # the record survives for the next attempt


# ------------------------------------------------------------------ scheduling


async def test_schedule_tombstones_every_scope_and_queues_one_record_each(
    db: AsyncSession, tmp_path: Path
) -> None:
    cache, cad = _cache(tmp_path)
    await schedule_cad_purge(db, cache, "onshape", ["acct", "source:1", "acct"])
    await db.commit()

    assert {row.account_hash for row in await _rows(db)} == {
        scope_hash("onshape", "acct"),
        scope_hash("onshape", "source:1"),
    }
    key = IntegrationCache.payload_key("onshape", "acct", "d", "v", "revision-v3-export")
    assert await cache.put(key, "late", 60) is False  # tombstoned
    assert await cad.delete_account("onshape:acct") == 0


async def test_schedule_is_a_no_op_without_a_durable_store(db: AsyncSession) -> None:
    cache = IntegrationCache(InMemoryCacheStore())
    await schedule_cad_purge(db, cache, "onshape", ["acct"])
    await db.commit()
    assert await _rows(db) == []


# ------------------------------------------------------------------ revocation


async def _grant(
    db: AsyncSession,
    *,
    connection_account: str | None = "acct-1",
    source_account: str | None = "acct-1",
) -> tuple[AccountConnection, Source]:
    user = User(supabase_user_id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:8]}@example.com")
    team = Team(name="T")
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name="P")
    db.add(project)
    await db.flush()
    connection = AccountConnection(
        user_id=user.id,
        provider=SourceType.ONSHAPE,
        status=ConnectionStatus.CONNECTED,
        account_external_id=connection_account,
        secret_ref=f"connection/{uuid.uuid4()}/onshape",
    )
    db.add(connection)
    await db.flush()
    source = Source(
        project_id=project.id,
        team_id=team.id,
        type=SourceType.ONSHAPE,
        name="onshape",
        status=SourceStatus.CONNECTED,
        config={"documents": ["d1"]},
        account_external_id=source_account,
        connection_id=connection.id,
        secret_ref=connection.secret_ref,
    )
    db.add(source)
    await db.commit()
    return connection, source


async def test_revocation_queues_a_purge_for_the_connection_and_source_scopes(
    db: AsyncSession, tmp_path: Path
) -> None:
    cache, cad = _cache(tmp_path)
    connection, source = await _grant(db, connection_account=None, source_account=None)
    connection_ref, source_ref = f"connection:{connection.id}", f"source:{source.id}"
    conn_key = await cad.put(f"onshape:{connection_ref}", b"conn")
    src_key = await cad.put(f"onshape:{source_ref}", b"src")

    await revoke_connection(db, InMemorySecretStore(), connection, cache)
    await db.commit()

    # Nothing was deleted inline by revoke_connection: the record owns that, so it
    # commits (or rolls back) atomically with the revocation itself.
    assert await cad.get(conn_key) == b"conn" and await cad.get(src_key) == b"src"
    assert {row.account_hash for row in await _rows(db)} == {
        scope_hash("onshape", connection_ref),
        scope_hash("onshape", source_ref),
    }
    assert await run_due_cad_purges(db, cad, now=datetime.now(UTC)) == 2
    assert await cad.get(conn_key) is None and await cad.get(src_key) is None


async def test_revocation_with_a_shared_external_id_queues_a_single_scope(
    db: AsyncSession, tmp_path: Path
) -> None:
    cache, _ = _cache(tmp_path)
    connection, _source = await _grant(db)
    await revoke_connection(db, InMemorySecretStore(), connection, cache)
    await db.commit()
    assert [row.account_hash for row in await _rows(db)] == [scope_hash("onshape", "acct-1")]


async def test_a_rolled_back_revocation_queues_nothing(db: AsyncSession, tmp_path: Path) -> None:
    cache, _ = _cache(tmp_path)
    connection, _source = await _grant(db)
    await revoke_connection(db, InMemorySecretStore(), connection, cache)
    await db.rollback()
    assert await _rows(db) == []


async def test_a_broken_store_never_blocks_the_revocation(db: AsyncSession, tmp_path: Path) -> None:
    flaky = _FlakyStore(_store(tmp_path))
    cache = IntegrationCache(InMemoryCacheStore(), durable_store=flaky)
    connection, _source = await _grant(db)
    await flaky.put("onshape:acct-1", b"secret")

    await revoke_connection(db, InMemorySecretStore(), connection, cache)
    await db.commit()
    await run_cad_purges_after_commit(db, flaky)

    await db.refresh(connection)
    assert connection.status is ConnectionStatus.REVOKED
    assert len(await _rows(db)) == 1  # still pending: never silently dropped

    flaky.failing = False
    assert await run_due_cad_purges(db, flaky, now=datetime.now(UTC) + timedelta(minutes=5)) == 1
    assert await flaky.inner.delete_account("onshape:acct-1") == 0
