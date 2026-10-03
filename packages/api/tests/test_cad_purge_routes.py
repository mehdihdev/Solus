"""ADR-038 §1: every path that ends a grant purges the durable CAD behind it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.models import (
    AccountConnection,
    CadPurgeRequest,
    ConnectionStatus,
    Project,
    Source,
    SourceStatus,
    SourceType,
)
from solus_api.services.cad_purge import PASSES, run_due_cad_purges, scope_hash
from solus_api.storage.cad_store import LocalCadStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MIB = 1024 * 1024


class _FailingStore(LocalCadStore):
    failing = True

    async def delete_account_hash(self, digest: str) -> int:
        if self.failing:
            raise OSError("s3 is down")
        return await super().delete_account_hash(digest)


@pytest.fixture
def cad(app: FastAPI, tmp_path: Path) -> LocalCadStore:
    store = _FailingStore(str(tmp_path / "cad"), max_object_bytes=64 * MIB)
    store.failing = False
    app.state.integration_cache = IntegrationCache(InMemoryCacheStore(), durable_store=store)
    return store


async def _records(db: AsyncSession) -> list[CadPurgeRequest]:
    db.expire_all()
    return list((await db.scalars(select(CadPurgeRequest))).all())


async def _project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return team["id"], project["id"]


async def _user_id(client: AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    return uuid.UUID((await me(client, headers))["id"])


async def _connection(
    db: AsyncSession, user_id: uuid.UUID, account: str | None = "acct-1"
) -> AccountConnection:
    connection = AccountConnection(
        user_id=user_id,
        provider=SourceType.ONSHAPE,
        status=ConnectionStatus.CONNECTED,
        account_external_id=account,
        secret_ref=f"connection/{uuid.uuid4()}/onshape",
    )
    db.add(connection)
    await db.commit()
    return connection


async def _source(
    db: AsyncSession,
    project_id: str,
    *,
    account: str | None,
    secret_ref: str | None = None,
    connection_id: uuid.UUID | None = None,
) -> Source:
    project = await db.get(Project, uuid.UUID(project_id))
    assert project is not None
    source = Source(
        project_id=project.id,
        team_id=project.team_id,
        type=SourceType.ONSHAPE,
        name="onshape",
        status=SourceStatus.CONNECTED,
        config={"documents": ["d1"]},
        account_external_id=account,
        connection_id=connection_id,
        secret_ref=secret_ref or f"source/{uuid.uuid4()}/onshape",
    )
    db.add(source)
    await db.commit()
    return source


# ------------------------------------------------------------------ revoke


async def test_revoking_a_connection_deletes_the_durable_cad_and_keeps_a_second_pass(
    client: AsyncClient,
    db: AsyncSession,
    cad: LocalCadStore,
    alice_headers: dict[str, str],
) -> None:
    user_id = await _user_id(client, alice_headers)
    connection = await _connection(db, user_id)
    mine = await cad.put("onshape:acct-1", b"alice's STEP")
    other = await cad.put("onshape:acct-other", b"someone else's")

    resp = await client.delete(
        f"/api/v1/users/me/connections/{connection.id}", headers=alice_headers
    )

    assert resp.status_code == 200, resp.text
    assert await cad.get(mine) is None
    assert await cad.get(other) == b"someone else's"
    [record] = await _records(db)
    assert record.account_hash == scope_hash("onshape", "acct-1")
    assert record.passes_remaining == PASSES - 1  # the delayed pass is still owed


async def test_a_store_outage_does_not_block_the_revoke_and_the_purge_is_retried(
    client: AsyncClient,
    db: AsyncSession,
    cad: LocalCadStore,
    alice_headers: dict[str, str],
) -> None:
    assert isinstance(cad, _FailingStore)
    cad.failing = True
    user_id = await _user_id(client, alice_headers)
    connection = await _connection(db, user_id)
    key = await cad.put("onshape:acct-1", b"alice's STEP")

    resp = await client.delete(
        f"/api/v1/users/me/connections/{connection.id}", headers=alice_headers
    )

    assert resp.status_code == 200, resp.text
    assert await cad.get(key) == b"alice's STEP"
    [record] = await _records(db)
    assert record.passes_remaining == PASSES and record.attempts == 1

    cad.failing = False
    later = datetime.now(UTC) + timedelta(hours=2)
    assert await run_due_cad_purges(db, cad, now=later) == 1
    assert await cad.get(key) is None


async def test_the_next_revoke_request_retries_someone_elses_due_purge(
    client: AsyncClient,
    db: AsyncSession,
    cad: LocalCadStore,
    alice_headers: dict[str, str],
) -> None:
    """No worker: any later revoke-related request drains what is due."""
    assert isinstance(cad, _FailingStore)
    user_id = await _user_id(client, alice_headers)
    stale = await cad.put("onshape:acct-stale", b"left behind")
    db.add(
        CadPurgeRequest(
            account_hash=scope_hash("onshape", "acct-stale"),
            passes_remaining=PASSES,
            attempts=3,
            next_attempt_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    connection = await _connection(db, user_id)

    resp = await client.delete(
        f"/api/v1/users/me/connections/{connection.id}", headers=alice_headers
    )

    assert resp.status_code == 200
    assert await cad.get(stale) is None


# ------------------------------------------------------------------ legacy disconnect


async def _disconnect(
    client: AsyncClient, headers: dict[str, str], project_id: str, source: Source
) -> None:
    resp = await client.delete(
        f"/api/v1/projects/{project_id}/sources/{source.id}", headers=headers
    )
    assert resp.status_code == 200, resp.text


async def test_disconnecting_a_legacy_grant_purges_its_durable_cad(
    client: AsyncClient,
    db: AsyncSession,
    cad: LocalCadStore,
    alice_headers: dict[str, str],
) -> None:
    _, project_id = await _project(client, alice_headers)
    source = await _source(db, project_id, account="acct-legacy")
    key = await cad.put("onshape:acct-legacy", b"legacy export")
    other = await cad.put("onshape:acct-keep", b"keep")

    await _disconnect(client, alice_headers, project_id, source)

    assert await cad.get(key) is None and await cad.get(other) == b"keep"
    assert [r.account_hash for r in await _records(db)] == [scope_hash("onshape", "acct-legacy")]


async def test_a_legacy_source_without_an_account_id_purges_its_own_scope(
    client: AsyncClient,
    db: AsyncSession,
    cad: LocalCadStore,
    alice_headers: dict[str, str],
) -> None:
    _, project_id = await _project(client, alice_headers)
    source = await _source(db, project_id, account=None)
    key = await cad.put(f"onshape:source:{source.id}", b"export")

    await _disconnect(client, alice_headers, project_id, source)

    assert await cad.get(key) is None


async def test_a_legacy_disconnect_keeps_the_cache_another_live_source_still_uses(
    client: AsyncClient,
    db: AsyncSession,
    cad: LocalCadStore,
    alice_headers: dict[str, str],
) -> None:
    team_id, project_id = await _project(client, alice_headers)
    second = (await create_project(client, alice_headers, team_id, name="Arm"))["id"]
    first_source = await _source(db, project_id, account="acct-shared")
    await _source(db, second, account="acct-shared")
    key = await cad.put("onshape:acct-shared", b"shared export")

    await _disconnect(client, alice_headers, project_id, first_source)

    assert await cad.get(key) == b"shared export"
    assert await _records(db) == []


async def test_a_legacy_disconnect_keeps_the_cache_a_live_connection_still_uses(
    client: AsyncClient,
    db: AsyncSession,
    cad: LocalCadStore,
    alice_headers: dict[str, str],
) -> None:
    _, project_id = await _project(client, alice_headers)
    await _connection(db, await _user_id(client, alice_headers), account="acct-shared")
    source = await _source(db, project_id, account="acct-shared")
    key = await cad.put("onshape:acct-shared", b"shared export")

    await _disconnect(client, alice_headers, project_id, source)

    assert await cad.get(key) == b"shared export"
    assert await _records(db) == []


async def test_a_revoked_connection_does_not_count_as_a_live_user(
    client: AsyncClient,
    db: AsyncSession,
    cad: LocalCadStore,
    alice_headers: dict[str, str],
) -> None:
    _, project_id = await _project(client, alice_headers)
    dead = await _connection(db, await _user_id(client, alice_headers), account="acct-x")
    dead.status = ConnectionStatus.REVOKED
    await db.commit()
    source = await _source(db, project_id, account="acct-x")
    key = await cad.put("onshape:acct-x", b"export")

    await _disconnect(client, alice_headers, project_id, source)

    assert await cad.get(key) is None


async def test_disconnecting_a_connection_owned_source_purges_nothing(
    client: AsyncClient,
    db: AsyncSession,
    cad: LocalCadStore,
    alice_headers: dict[str, str],
) -> None:
    _, project_id = await _project(client, alice_headers)
    connection = await _connection(db, await _user_id(client, alice_headers))
    source = await _source(
        db,
        project_id,
        account="acct-1",
        secret_ref=connection.secret_ref,
        connection_id=connection.id,
    )
    key = await cad.put("onshape:acct-1", b"the account's export")

    await _disconnect(client, alice_headers, project_id, source)

    assert await cad.get(key) == b"the account's export"
    assert await _records(db) == []


# ------------------------------------------------------------------ account deletion


class _Admin:
    configured = True

    async def delete_user(self, supabase_user_id: str) -> bool:
        return True


async def test_deleting_the_account_purges_connection_and_legacy_source_cad(
    client: AsyncClient,
    app: FastAPI,
    db: AsyncSession,
    cad: LocalCadStore,
    alice_headers: dict[str, str],
) -> None:
    app.state.supabase_admin = _Admin()
    _, project_id = await _project(client, alice_headers)
    await _connection(db, await _user_id(client, alice_headers), account="acct-conn")
    await _source(db, project_id, account="acct-legacy")
    conn_key = await cad.put("onshape:acct-conn", b"connection export")
    legacy_key = await cad.put("onshape:acct-legacy", b"legacy export")
    other = await cad.put("onshape:acct-bystander", b"bystander")

    resp = await client.delete("/api/v1/users/me", headers=alice_headers)

    assert resp.status_code == 204, resp.text
    assert await cad.get(conn_key) is None
    assert await cad.get(legacy_key) is None
    assert await cad.get(other) == b"bystander"


# ------------------------------------------------------------------ project / team teardown


async def test_deleting_a_project_purges_its_legacy_grants_cad(
    client: AsyncClient,
    db: AsyncSession,
    cad: LocalCadStore,
    alice_headers: dict[str, str],
) -> None:
    _, project_id = await _project(client, alice_headers)
    await _source(db, project_id, account="acct-legacy")
    key = await cad.put("onshape:acct-legacy", b"legacy export")

    resp = await client.delete(f"/api/v1/projects/{project_id}?confirm=true", headers=alice_headers)

    assert resp.status_code == 204, resp.text
    assert await cad.get(key) is None


async def test_deleting_a_team_purges_its_legacy_grants_cad(
    client: AsyncClient,
    db: AsyncSession,
    cad: LocalCadStore,
    alice_headers: dict[str, str],
) -> None:
    team_id, project_id = await _project(client, alice_headers)
    await _source(db, project_id, account="acct-legacy")
    key = await cad.put("onshape:acct-legacy", b"legacy export")

    resp = await client.delete(f"/api/v1/teams/{team_id}?confirm=true", headers=alice_headers)

    assert resp.status_code == 204, resp.text
    assert await cad.get(key) is None
