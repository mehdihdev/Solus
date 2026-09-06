"""SOLUSDEV-242 Phase 3 quota, account identity, and real document roots."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from conftest import FakeGitHub
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.contracts import ConnectorError, Credentials, SyncContext
from solus_api.connectors.httpcache import InMemoryCacheStore, release_flight, single_flight
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.runtime import run_sync
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import AccountConnection, ConnectionStatus, Source, SourceStatus, Sync
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_connections import _bind, _connect_account, _CountingAccountLevel, _project
from test_runtime import ScriptedConnector, _seed_source


class _RepositoryAccount(FakeGitHub):  # type: ignore[misc]
    selection = {"mode": "single", "config_key": "repo", "label": "repository"}


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def install_fake(app: FastAPI, fake_registry: ConnectorRegistry) -> None:
    _CountingAccountLevel.listings = 0
    fake_registry.register("onshape", _CountingAccountLevel)
    fake_registry.register("github", _RepositoryAccount)
    app.state.connector_registry = fake_registry


@pytest.mark.parametrize("scope", ["account", "source"])
async def test_cache_only_miss_never_reads_credentials_or_provider(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    url = f"/api/v1/users/me/connections/{connection['id']}/documents"
    if scope == "source":
        project = await _project(client, alice_headers)
        source = await _bind(client, alice_headers, project, connection["id"])
        url = f"/api/v1/projects/{project}/sources/{source['id']}/selectable"
    resolve = AsyncMock(side_effect=AssertionError("cache-only must not resolve credentials"))
    monkeypatch.setattr("solus_api.services.connections.resolve_credentials", resolve)
    response = await client.get(url, params={"cache_only": True}, headers=alice_headers)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "listing_not_cached"
    resolve.assert_not_awaited()
    assert _CountingAccountLevel.listings == 0


async def test_cache_only_hit_and_conflicting_refresh(
    client: AsyncClient,
    alice_headers: dict[str, str],
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    url = f"/api/v1/users/me/connections/{connection['id']}/documents"
    loaded = await client.get(url, headers=alice_headers)
    cached = await client.get(url, params={"cache_only": True}, headers=alice_headers)
    assert cached.json()["data"] == loaded.json()["data"]
    assert cached.json()["meta"]["cached"] is True
    bad = await client.get(url, params={"cache_only": True, "refresh": True}, headers=alice_headers)
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "validation_error"
    assert _CountingAccountLevel.listings == 1


async def test_exact_reuse_preserves_sync_state_and_bypasses_slot_check(
    client: AsyncClient,
    alice_headers: dict[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    project = await _project(client, alice_headers)
    source = await _bind(client, alice_headers, project, connection["id"])
    async with maker() as db:
        row = await db.get(Source, uuid.UUID(source["id"]))
        assert row is not None
        row.status = SourceStatus.SYNCING
        row.last_error = {"code": "previous", "message": "keep"}
        await db.commit()
    cap = AsyncMock(side_effect=AssertionError("reuse consumes no new slot"))
    monkeypatch.setattr("solus_api.routers.sources.check_can_add_integration", cap)
    reused = await _bind(client, alice_headers, project, connection["id"])
    assert reused["id"] == source["id"]
    assert reused["status"] == "syncing"
    assert reused["last_error"]["code"] == "previous"
    cap.assert_not_awaited()


async def test_other_account_never_rebinds_existing_source(
    client: AsyncClient,
    alice_headers: dict[str, str],
    maker: async_sessionmaker[AsyncSession],
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    project = await _project(client, alice_headers)
    original = await _bind(client, alice_headers, project, connection["id"])
    async with maker() as db:
        old = await db.get(AccountConnection, uuid.UUID(connection["id"]))
        assert old is not None
        other = AccountConnection(
            user_id=old.user_id,
            provider=old.provider,
            status=ConnectionStatus.CONNECTED,
            secret_ref="connection/test-other/onshape",
            account_external_id="other-provider-account",
            account_login="other",
        )
        db.add(other)
        await db.commit()
        other_id = str(other.id)
    new = await _bind(client, alice_headers, project, other_id)
    assert new["id"] != original["id"]
    async with maker() as db:
        row = await db.get(Source, uuid.UUID(original["id"]))
        assert row is not None and str(row.connection_id) == connection["id"]


async def test_concurrent_document_additions_retain_both_and_duplicate_one_job(
    client: AsyncClient,
    alice_headers: dict[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    project = await _project(client, alice_headers)
    source = await _bind(client, alice_headers, project, connection["id"])
    dispatch = AsyncMock()
    monkeypatch.setattr("solus_api.routers.sources._dispatch_sync", dispatch)
    url = f"/api/v1/projects/{project}/sources/{source['id']}/documents"
    responses = await asyncio.gather(
        *[client.post(url, json={"id": doc}, headers=alice_headers) for doc in ("dA", "dA", "dB")]
    )
    assert sorted(r.status_code for r in responses) == [200, 202, 202]
    assert dispatch.await_count == 2
    async with maker() as db:
        row = await db.get(Source, uuid.UUID(source["id"]))
        assert row is not None and set(row.config["documents"]) == {"dA", "dB"}


async def test_flight_timeout_cannot_enter_or_release_the_owner() -> None:
    store = InMemoryCacheStore()
    owner = await single_flight(store, "f", ttl_seconds=10)
    with pytest.raises(ConnectorError) as caught:
        await single_flight(store, "f", ttl_seconds=10, wait_seconds=0)
    assert caught.value.code == "single_flight_busy"
    assert await store.get("f") is not None
    await release_flight(store, "f", owner)


async def test_expired_owner_cannot_release_successor() -> None:
    now = [0.0]
    store = InMemoryCacheStore(clock=lambda: now[0])
    old = await single_flight(store, "f", ttl_seconds=1)
    now[0] = 2.0
    new = await single_flight(store, "f", ttl_seconds=10)
    await release_flight(store, "f", old)
    assert await store.get("f") == new
    await release_flight(store, "f", new)
    assert await store.get("f") is None


async def test_probe_failure_defers_without_sync_and_retains_sweep_eligibility(
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    async with maker() as db:
        row = await db.get(Source, source.id)
        assert row is not None
        row.cursor = {"sha": "known"}
        await db.commit()
    connector = ScriptedConnector([])
    monkeypatch.setattr(
        connector,
        "detect_changes",
        AsyncMock(side_effect=ConnectorError("upstream_error", "try later")),
    )
    sync_call = AsyncMock(side_effect=AssertionError("no change evidence"))
    monkeypatch.setattr(connector, "sync", sync_call)
    sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )
    sync_call.assert_not_awaited()
    async with maker() as db:
        row = await db.get(Source, source.id)
        sync = await db.get(Sync, sync_id)
        assert row is not None and row.status is SourceStatus.CONNECTED
        assert row.last_error is not None and row.last_error["code"] == "upstream_error"
        assert row.last_synced_at is None, "a failed probe must not claim a fresh sync"
        assert sync is not None and sync.status.value == "failed"


async def test_onshape_probe_propagates_ambiguous_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = OnshapeConnector(client_id="test", client_secret="test")
    monkeypatch.setattr(
        connector, "_probe", AsyncMock(side_effect=ConnectorError("upstream_error", "retry"))
    )
    with pytest.raises(ConnectorError):
        await connector.detect_changes(
            SyncContext(
                credentials=Credentials(token="test"),
                config={"documents": ["dA"]},
                cursor={"microversions": {"dA": "v1"}},
            )
        )


async def test_empty_document_gets_real_root_without_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors.onshape import _DocumentPlan

    connector = OnshapeConnector(client_id="test", client_secret="test")
    monkeypatch.setattr(
        connector, "_plan", AsyncMock(return_value=[_DocumentPlan("dA", "wA", "v1", [])])
    )
    listing = AsyncMock(side_effect=AssertionError("no implicit listing"))
    monkeypatch.setattr(connector, "list_selectable", listing)
    result = await connector.sync(
        SyncContext(credentials=Credentials(token="test"), config={"documents": ["dA"]})
    )
    assert len(result.entities) == 1
    root = result.entities[0]
    assert (root.source_key, root.type, root.domain.value, root.name) == (
        "dA:document",
        "cad_document",
        "mechanical",
        "dA",
    )
    assert root.properties["document_id"] == "dA"
    listing.assert_not_awaited()


async def test_probe_refresh_passes_rotated_credentials_to_sync(
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors.contracts import SyncResult
    from solus_api.connectors.runtime import refresh_secret_ref

    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    assert source.secret_ref is not None
    await store.put(refresh_secret_ref(source.secret_ref), "old-refresh-placeholder")
    async with maker() as db:
        row = await db.get(Source, source.id)
        assert row is not None
        row.cursor = {"sha": "known"}
        await db.commit()
    connector = OnshapeConnector(client_id="test", client_secret="test")
    fresh = Credentials(token="fresh-placeholder", refresh_token="rotated-placeholder")
    refresh = AsyncMock(return_value=fresh)
    probe = AsyncMock(side_effect=[ConnectorError("invalid_credentials", "expired"), True])
    sync = AsyncMock(return_value=SyncResult(cursor={"sha": "next"}))
    monkeypatch.setattr(connector, "refresh_credentials", refresh)
    monkeypatch.setattr(connector, "detect_changes", probe)
    monkeypatch.setattr(connector, "sync", sync)
    await run_sync(source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store)
    assert refresh.await_count == 1 and probe.await_count == 2
    assert sync.call_args.args[0].credentials == fresh
    assert await store.get(refresh_secret_ref(source.secret_ref)) == fresh.refresh_token


@pytest.mark.parametrize("value", [None, {}, ["bad"], [{"id": "dA"}], [{"id": 7, "name": "bad"}]])
async def test_malformed_cache_only_listing_never_fetches(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    value: Any,
) -> None:
    from solus_api.connectors.integration_cache import IntegrationCache

    connection = (await _connect_account(client, alice_headers))["connection"]
    cache: IntegrationCache = app.state.integration_cache
    await cache.put(
        cache.listing_key("onshape", "42"),
        {"value": value, "fetched_at": "2026-09-05T00:00:00+00:00"},
        60,
    )
    response = await client.get(
        f"/api/v1/users/me/connections/{connection['id']}/documents",
        params={"cache_only": True},
        headers=alice_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "listing_not_cached"
    assert _CountingAccountLevel.listings == 0


async def test_document_backfill_is_additive_idempotent_and_project_scoped(
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from solus_api.connectors.contracts import Domain, EntityOut, RelationOut, SyncResult
    from solus_api.connectors.runtime import apply_sync_result
    from solus_api.models import GraphEdge, GraphEntity, SourceType
    from sqlalchemy import Connection, select

    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/c7f242e9a842_solusdev_242_document_roots.py"
    )
    assert path.exists(), "local document-wrapper backfill migration is required"
    spec = importlib.util.spec_from_file_location("phase3_document_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    store = InMemorySecretStore()
    sources = [await _seed_source(maker, store), await _seed_source(maker, store)]
    old_ids: set[uuid.UUID] = set()
    async with maker() as db:
        for source in sources:
            row = await db.get(Source, source.id)
            assert row is not None
            row.type = SourceType.ONSHAPE
            row.config = {"documents": ["dA", "empty"]}
            result = SyncResult(
                entities=[
                    EntityOut(
                        source_key=f"dA:e1:{key}",
                        type="part",
                        domain=Domain.MECHANICAL,
                        name=key,
                        properties={"document_id": "dA", "element_id": "e1"},
                    )
                    for key in ("assembly", "part")
                ],
                relations=[
                    RelationOut(from_key="dA:e1:part", to_key="dA:e1:assembly", type="part_of")
                ],
            )
            await apply_sync_result(db, row, result)
        await db.commit()
        old_ids = set((await db.scalars(select(GraphEntity.id))).all())

    def backfill(conn: Connection) -> None:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.upgrade()

    async with maker() as db:
        conn = await db.connection()
        await conn.run_sync(backfill)
        await db.commit()
    async with maker() as db:
        first_ids = set((await db.scalars(select(GraphEntity.id))).all())
        assert old_ids <= first_ids
        assert len(first_ids - old_ids) == 4
        roots = (
            await db.scalars(select(GraphEntity).where(GraphEntity.kind == "cad_document"))
        ).all()
        assert {(r.source_id, r.attrs["document_id"]) for r in roots} == {
            (s.id, doc) for s in sources for doc in ("dA", "empty")
        }
        edges = (await db.scalars(select(GraphEdge))).all()
        assert sum(e.relation_type == "part_of" for e in edges) == 2
        assert sum(e.relation_type == "contains" for e in edges) == 2
        for edge in edges:
            left = await db.get(GraphEntity, edge.src_id)
            right = await db.get(GraphEntity, edge.dst_id)
            assert left is not None and right is not None
            assert left.project_id == right.project_id == edge.project_id
        conn = await db.connection()
        await conn.run_sync(backfill)
        await db.commit()
    async with maker() as db:
        assert set((await db.scalars(select(GraphEntity.id))).all()) == first_ids
        assert len((await db.scalars(select(GraphEdge))).all()) == len(edges)


async def test_a_new_document_can_queue_while_another_is_ingesting(
    client: AsyncClient,
    alice_headers: dict[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    project = await _project(client, alice_headers)
    source = await _bind(client, alice_headers, project, connection["id"])
    async with maker() as db:
        row = await db.get(Source, uuid.UUID(source["id"]))
        assert row is not None
        row.config = {"documents": ["dA"]}
        row.status = SourceStatus.SYNCING
        await db.commit()
    dispatch = AsyncMock()
    monkeypatch.setattr("solus_api.routers.sources._dispatch_sync", dispatch)
    url = f"/api/v1/projects/{project}/sources/{source['id']}/documents"
    new = await client.post(url, json={"id": "dB"}, headers=alice_headers)
    assert new.status_code == 202, new.text
    duplicate = await client.post(url, json={"id": "dA"}, headers=alice_headers)
    assert duplicate.status_code == 200 and duplicate.json()["data"]["job_id"] is None
    assert dispatch.await_count == 1
    assert set(new.json()["data"]["source"]["config"]["documents"]) == {"dA", "dB"}


async def test_repository_identity_reuses_exact_selection_only(
    client: AsyncClient,
    alice_headers: dict[str, str],
) -> None:
    connection = (await _connect_account(client, alice_headers, "github"))["connection"]
    project = await _project(client, alice_headers)

    async def bind(repo: str, branch: str) -> dict[str, Any]:
        response = await client.post(
            f"/api/v1/projects/{project}/sources",
            headers=alice_headers,
            json={
                "type": "github",
                "name": repo,
                "connection_id": connection["id"],
                "config": {"repo": repo, "branch": branch},
            },
        )
        assert response.status_code == 201, response.text
        return dict(response.json()["data"])

    first = await bind("robot/firmware", "main")
    same = await bind("robot/firmware", "main")
    different_repo = await bind("robot/software", "main")
    different_branch = await bind("robot/firmware", "dev")
    assert first["id"] == same["id"]
    assert len({first["id"], different_repo["id"], different_branch["id"]}) == 3


async def test_cached_metadata_names_document_without_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors.integration_cache import IntegrationCache
    from solus_api.connectors.onshape import _DocumentPlan

    cache = IntegrationCache(InMemoryCacheStore())
    await cache.put(
        cache.listing_key("onshape", "acct"),
        {
            "value": [{"id": "dA", "name": "Chassis"}],
            "fetched_at": "2026-09-05T00:00:00+00:00",
        },
        60,
    )
    connector = OnshapeConnector(
        client_id="test", client_secret="test", cache=cache, account_ref="acct"
    )
    monkeypatch.setattr(
        connector, "_plan", AsyncMock(return_value=[_DocumentPlan("dA", "wA", "v1", [])])
    )
    result = await connector.sync(
        SyncContext(credentials=Credentials(token="test"), config={"documents": ["dA"]})
    )
    assert result.entities[0].name == "Chassis"


@pytest.mark.parametrize(
    "failure", [ConnectorError("upstream_error", "retry"), TimeoutError(), RuntimeError("retry")]
)
async def test_sweep_probe_failures_never_enqueue_and_retry_next_sweep(
    maker: async_sessionmaker[AsyncSession],
    failure: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors.worker import run_change_detection

    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    connector = ScriptedConnector([])
    probe = AsyncMock(side_effect=[failure, False])
    monkeypatch.setattr(connector, "detect_changes", probe)
    registry = ConnectorRegistry()
    registry.register("github", lambda: connector)
    enqueue = AsyncMock()
    for _ in range(2):
        assert (
            await run_change_detection(
                sessionmaker=maker, registry=registry, secret_store=store, enqueue=enqueue
            )
            == 0
        )
    enqueue.assert_not_awaited()
    assert probe.await_count == 2
    async with maker() as db:
        row = await db.get(Source, source.id)
        assert row is not None and row.status is SourceStatus.CONNECTED
        assert row.last_synced_at is None, "failed sweep probes must preserve last successful sync"


async def test_permanent_probe_auth_failure_stays_visible(
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    async with maker() as db:
        row = await db.get(Source, source.id)
        assert row is not None
        row.cursor = {"sha": "known"}
        await db.commit()
    connector = ScriptedConnector([])
    monkeypatch.setattr(
        connector,
        "detect_changes",
        AsyncMock(side_effect=ConnectorError("invalid_credentials", "reconnect")),
    )
    sync_call = AsyncMock()
    monkeypatch.setattr(connector, "sync", sync_call)
    await run_sync(source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store)
    sync_call.assert_not_awaited()
    async with maker() as db:
        row = await db.get(Source, source.id)
        assert row is not None and row.status is SourceStatus.ERROR
        assert row.last_error is not None and row.last_error["code"] == "invalid_credentials"


async def test_failed_flight_never_runs_provider_or_overwrites_other_sync_state(
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors.worker import execute_source_sync
    from solus_api.models import Job, JobKind, JobStatus

    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    async with maker() as db:
        row = await db.get(Source, source.id)
        assert row is not None
        row.status = SourceStatus.SYNCING
        job = Job(
            project_id=row.project_id,
            team_id=row.team_id,
            kind=JobKind.SYNC,
            status=JobStatus.QUEUED,
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    connector = ScriptedConnector([])
    sync_call = AsyncMock()
    monkeypatch.setattr(connector, "sync", sync_call)
    registry = ConnectorRegistry()
    registry.register("github", lambda: connector)
    monkeypatch.setattr(
        "solus_api.connectors.worker.single_flight",
        AsyncMock(side_effect=ConnectorError("single_flight_busy", "retry")),
    )
    release = AsyncMock()
    monkeypatch.setattr("solus_api.connectors.worker.release_flight", release)
    assert (
        await execute_source_sync(
            source_id=source.id,
            sessionmaker=maker,
            registry=registry,
            secret_store=store,
            store=InMemoryCacheStore(),
            job_id=job_id,
        )
        is None
    )
    sync_call.assert_not_awaited()
    release.assert_not_awaited()
    async with maker() as db:
        row = await db.get(Source, source.id)
        recorded_job = await db.get(Job, job_id)
        assert row is not None and row.status is SourceStatus.SYNCING
        assert recorded_job is not None and recorded_job.status is JobStatus.FAILED


async def test_cache_outage_is_an_honest_cache_only_miss(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    monkeypatch.setattr(
        app.state.integration_cache._store, "get", AsyncMock(side_effect=RuntimeError("offline"))
    )
    response = await client.get(
        f"/api/v1/users/me/connections/{connection['id']}/documents",
        params={"cache_only": True},
        headers=alice_headers,
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "listing_not_cached"
    assert _CountingAccountLevel.listings == 0


async def test_fetch_does_not_call_provider_or_release_when_claim_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors.integration_cache import IntegrationCache

    store = InMemoryCacheStore()
    monkeypatch.setattr(store, "claim", AsyncMock(side_effect=RuntimeError("offline")))
    release = AsyncMock()
    monkeypatch.setattr(store, "release", release)
    fetch = AsyncMock()
    with pytest.raises(ConnectorError) as caught:
        await IntegrationCache(store).fetch("listing", ttl_seconds=60, fetch=fetch)
    assert caught.value.code == "single_flight_unavailable"
    fetch.assert_not_awaited()
    release.assert_not_awaited()


@pytest.mark.parametrize("identity", ["42", "another-account", None])
async def test_legacy_adoption_requires_known_matching_account_identity(
    client: AsyncClient,
    alice_headers: dict[str, str],
    maker: async_sessionmaker[AsyncSession],
    identity: str | None,
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    project = await _project(client, alice_headers)
    original = await _bind(client, alice_headers, project, connection["id"])
    async with maker() as db:
        row = await db.get(Source, uuid.UUID(original["id"]))
        assert row is not None
        row.connection_id = None
        row.account_external_id = identity
        row.status = SourceStatus.SYNCING
        row.last_error = {"code": "existing", "message": "preserve"}
        await db.commit()
    attached = await _bind(client, alice_headers, project, connection["id"])
    assert (attached["id"] == original["id"]) is (identity == "42")
    if identity == "42":
        assert attached["status"] == "syncing"
        assert attached["last_error"]["code"] == "existing"


async def test_cache_only_listing_has_same_owner_boundary(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    url = f"/api/v1/users/me/connections/{connection['id']}/documents"
    await client.get(url, headers=alice_headers)
    response = await client.get(url, params={"cache_only": True}, headers=bob_headers)
    assert response.status_code == 404
    assert (await client.get(url, params={"cache_only": True})).status_code == 401
    assert _CountingAccountLevel.listings == 1


async def test_cache_renews_lease_during_a_slow_export(monkeypatch: pytest.MonkeyPatch) -> None:
    from solus_api.connectors.integration_cache import IntegrationCache

    monkeypatch.setattr("solus_api.connectors.integration_cache._FETCH_FLIGHT_SECONDS", 1)
    cache = IntegrationCache(InMemoryCacheStore())
    started = asyncio.Event()
    finish = asyncio.Event()
    calls = 0

    async def fetch() -> str:
        nonlocal calls
        calls += 1
        started.set()
        await finish.wait()
        return "export"

    first = asyncio.create_task(cache.fetch("export", ttl_seconds=60, fetch=fetch))
    await started.wait()
    second = None
    try:
        await asyncio.sleep(1.1)
        second = asyncio.create_task(cache.fetch("export", ttl_seconds=60, fetch=fetch))
        await asyncio.sleep(0.15)
        assert calls == 1, "a still-running export must retain its lease beyond the original TTL"
    finally:
        finish.set()
        await asyncio.gather(first, *([second] if second else []), return_exceptions=True)


async def test_lost_export_lease_cancels_work_and_preserves_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors.integration_cache import IntegrationCache

    monkeypatch.setattr("solus_api.connectors.integration_cache._FETCH_FLIGHT_SECONDS", 1)
    store = InMemoryCacheStore()
    cache = IntegrationCache(store)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fetch() -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return "never"

    task = asyncio.create_task(cache.fetch("export", ttl_seconds=60, fetch=fetch))
    await started.wait()
    await store.set("export:flight", "successor", 10)
    try:
        await asyncio.sleep(0.5)
        assert task.done(), "lost lease must cancel the provider operation promptly"
        with pytest.raises(ConnectorError) as caught:
            await task
        assert caught.value.code == "single_flight_lost"
        assert cancelled.is_set()
        assert await store.get("export:flight") == "successor"
        assert await store.get("export") is None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_accepted_document_job_waits_for_slow_owner_then_ingests_selection(
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors.contracts import SyncResult
    from solus_api.connectors.worker import execute_source_sync
    from solus_api.models import Job, JobKind, JobStatus

    monkeypatch.setattr("solus_api.connectors.worker._SYNC_FLIGHT_TTL_SECONDS", 1)
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    flights = InMemoryCacheStore()
    started = asyncio.Event()
    finish = asyncio.Event()
    configs: list[dict[str, Any]] = []
    connector = ScriptedConnector([])

    async def sync(ctx: SyncContext) -> SyncResult:
        configs.append(ctx.config)
        if len(configs) == 1:
            started.set()
            await finish.wait()
        return SyncResult(cursor={"documents": ctx.config.get("documents", [])})

    async def probe(ctx: SyncContext) -> bool:
        return ctx.cursor.get("documents") != ctx.config.get("documents")

    monkeypatch.setattr(connector, "sync", sync)
    monkeypatch.setattr(connector, "detect_changes", probe)
    registry = ConnectorRegistry()
    registry.register("github", lambda: connector)

    async def shortened_flight(*args: Any, **kwargs: Any) -> str:
        kwargs["wait_seconds"] = None if kwargs.get("wait_seconds", 30) is None else 0.05
        return await single_flight(*args, **kwargs)

    monkeypatch.setattr("solus_api.connectors.worker.single_flight", shortened_flight)
    async with maker() as db:
        row = await db.get(Source, source.id)
        assert row is not None
        row.config = {"documents": ["dA"]}
        await db.commit()
    first = asyncio.create_task(
        execute_source_sync(
            source_id=source.id,
            sessionmaker=maker,
            registry=registry,
            secret_store=store,
            store=flights,
        )
    )
    await started.wait()
    async with maker() as db:
        row = await db.get(Source, source.id)
        assert row is not None
        row.config = {"documents": ["dA", "dB"]}
        job = Job(
            project_id=row.project_id,
            team_id=row.team_id,
            kind=JobKind.SYNC,
            status=JobStatus.QUEUED,
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    await asyncio.sleep(1.1)  # the owner must renew even before another job arrives
    second = asyncio.create_task(
        execute_source_sync(
            source_id=source.id,
            job_id=job_id,
            sessionmaker=maker,
            registry=registry,
            secret_store=store,
            store=flights,
        )
    )
    try:
        await asyncio.sleep(0.15)
        assert not second.done(), (
            "accepted selection must not fail at the duplicate-hint wait deadline"
        )
    finally:
        finish.set()
        await asyncio.gather(first, second)
    async with maker() as db:
        recorded = await db.get(Job, job_id)
        row = await db.get(Source, source.id)
        assert recorded is not None and recorded.status is JobStatus.SUCCEEDED
        assert row is not None and row.cursor["documents"] == ["dA", "dB"]
    assert len(configs) == 2


@pytest.mark.parametrize("hung", [False, True])
async def test_renewal_store_failure_cancels_export_before_expiry(
    monkeypatch: pytest.MonkeyPatch,
    hung: bool,
) -> None:
    from solus_api.connectors.integration_cache import IntegrationCache

    monkeypatch.setattr("solus_api.connectors.integration_cache._FETCH_FLIGHT_SECONDS", 1)
    store = InMemoryCacheStore()
    entered = asyncio.Event()
    stopped = asyncio.Event()

    async def fetch() -> str:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
        return "never"

    task = asyncio.create_task(IntegrationCache(store).fetch("export", ttl_seconds=60, fetch=fetch))
    await entered.wait()

    async def broken_renew(*args: Any, **kwargs: Any) -> bool:
        if hung:
            await asyncio.Event().wait()
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(store, "renew", broken_renew)
    with pytest.raises(ConnectorError) as caught:
        await asyncio.wait_for(task, 0.95)
    assert caught.value.code == "single_flight_lost"
    assert stopped.is_set()
    assert await store.get("export") is None


async def test_initial_renewal_failure_closes_accepted_job(
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors.worker import execute_source_sync
    from solus_api.models import Job, JobKind, JobStatus

    secrets = InMemorySecretStore()
    source = await _seed_source(maker, secrets)
    async with maker() as db:
        job = Job(
            project_id=source.project_id,
            team_id=source.team_id,
            kind=JobKind.SYNC,
            status=JobStatus.QUEUED,
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    flights = InMemoryCacheStore()
    monkeypatch.setattr(flights, "renew", AsyncMock(return_value=False))
    connector = ScriptedConnector([])
    registry = ConnectorRegistry()
    registry.register("github", lambda: connector)
    assert (
        await execute_source_sync(
            source_id=source.id,
            job_id=job_id,
            sessionmaker=maker,
            registry=registry,
            secret_store=secrets,
            store=flights,
        )
        is None
    )
    async with maker() as db:
        recorded = await db.get(Job, job_id)
        row = await db.get(Source, source.id)
        assert recorded is not None and recorded.status is JobStatus.FAILED
        assert row is not None and row.status is SourceStatus.CONNECTED


@pytest.mark.parametrize("use_store", [True, False])
async def test_operation_deadline_cancels_sync_and_restores_eligibility(
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    use_store: bool,
) -> None:
    from solus_api.connectors.worker import execute_source_sync
    from solus_api.models import Job, JobKind, JobStatus
    from sqlalchemy import select

    monkeypatch.setattr("solus_api.connectors.worker._SYNC_OPERATION_SECONDS", 0.15)
    secrets = InMemorySecretStore()
    source = await _seed_source(maker, secrets)
    async with maker() as db:
        job = Job(
            project_id=source.project_id,
            team_id=source.team_id,
            kind=JobKind.SYNC,
            status=JobStatus.QUEUED,
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    cancelled = asyncio.Event()

    async def sync(ctx: SyncContext) -> Any:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    connector = ScriptedConnector([])
    monkeypatch.setattr(connector, "sync", sync)
    registry = ConnectorRegistry()
    registry.register("github", lambda: connector)
    hub = AsyncMock()
    flights = InMemoryCacheStore()
    assert (
        await asyncio.wait_for(
            execute_source_sync(
                source_id=source.id,
                job_id=job_id,
                sessionmaker=maker,
                registry=registry,
                secret_store=secrets,
                store=flights if use_store else None,
                hub=hub,
            ),
            1,
        )
        is None
    )
    assert cancelled.is_set()
    hub.publish.assert_not_awaited()
    async with maker() as db:
        recorded = await db.get(Job, job_id)
        row = await db.get(Source, source.id)
        recorded_sync = await db.scalar(select(Sync).where(Sync.job_id == job_id))
        assert recorded is not None and recorded.status is JobStatus.FAILED
        assert recorded_sync is not None and recorded_sync.status is JobStatus.FAILED
        assert row is not None and row.status is SourceStatus.CONNECTED
        assert row.last_synced_at is None
    assert await flights.get(f"solus:ic:sync:{source.id}") is None


async def test_arq_busy_selection_defers_then_completes_without_losing_job(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    from arq import Retry
    from solus_api.connectors.contracts import SyncResult
    from solus_api.connectors.worker import sync_source
    from solus_api.models import Job, JobKind, JobStatus

    secrets = InMemorySecretStore()
    source = await _seed_source(maker, secrets)
    async with maker() as db:
        job = Job(
            project_id=source.project_id,
            team_id=source.team_id,
            kind=JobKind.SYNC,
            status=JobStatus.QUEUED,
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    flights = InMemoryCacheStore()
    key = f"solus:ic:sync:{source.id}"
    owner = await single_flight(flights, key, ttl_seconds=300)
    registry = ConnectorRegistry()
    registry.register("github", lambda: ScriptedConnector([SyncResult(cursor={"sha": "next"})]))
    ctx = {
        "sessionmaker": maker,
        "registry": registry,
        "secret_store": secrets,
        "integration_store": flights,
        "job_try": 1,
    }
    with pytest.raises(Retry):
        await sync_source(ctx, str(source.id), str(job_id))
    async with maker() as db:
        queued = await db.get(Job, job_id)
        assert queued is not None and queued.status is JobStatus.QUEUED
    await release_flight(flights, key, owner)
    assert await sync_source(ctx, str(source.id), str(job_id))
    async with maker() as db:
        done = await db.get(Job, job_id)
        assert done is not None and done.status is JobStatus.SUCCEEDED


async def test_cancellation_during_setup_closes_the_committed_job(
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors import runtime
    from solus_api.connectors.worker import execute_source_sync
    from solus_api.models import Job, JobKind, JobStatus
    from sqlalchemy import select

    secrets = InMemorySecretStore()
    source = await _seed_source(maker, secrets)
    async with maker() as db:
        job = Job(
            project_id=source.project_id,
            team_id=source.team_id,
            kind=JobKind.SYNC,
            status=JobStatus.QUEUED,
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    setup_committed = asyncio.Event()
    setup_return = asyncio.Event()
    begin = runtime._begin_sync

    async def slow_begin(*args: Any, **kwargs: Any) -> Any:
        result = await begin(*args, **kwargs)
        setup_committed.set()
        await setup_return.wait()
        return result

    monkeypatch.setattr(runtime, "_begin_sync", slow_begin)
    registry = ConnectorRegistry()
    registry.register("github", lambda: ScriptedConnector([]))
    task = asyncio.create_task(
        execute_source_sync(
            source_id=source.id,
            job_id=job_id,
            sessionmaker=maker,
            registry=registry,
            secret_store=secrets,
            store=InMemoryCacheStore(),
        )
    )
    await setup_committed.wait()
    task.cancel()
    await asyncio.sleep(0)
    setup_return.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with maker() as db:
        recorded = await db.get(Job, job_id)
        row = await db.get(Source, source.id)
        sync = await db.scalar(select(Sync).where(Sync.job_id == job_id))
        assert recorded is not None and recorded.status is JobStatus.FAILED
        assert sync is not None and sync.status is JobStatus.FAILED
        assert row is not None and row.status is SourceStatus.CONNECTED


async def test_canceled_owner_does_not_reset_a_successor_source_or_release_lease(
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors.runtime import _begin_sync
    from solus_api.connectors.worker import execute_source_sync
    from solus_api.models import Job, JobKind, JobStatus, SyncTrigger

    monkeypatch.setattr("solus_api.connectors.worker._SYNC_FLIGHT_TTL_SECONDS", 1)
    secrets = InMemorySecretStore()
    source = await _seed_source(maker, secrets)
    async with maker() as db:
        jobs = [
            Job(
                project_id=source.project_id,
                team_id=source.team_id,
                kind=JobKind.SYNC,
                status=JobStatus.QUEUED,
            )
            for _ in range(2)
        ]
        db.add_all(jobs)
        await db.commit()
        old_id, new_id = (j.id for j in jobs)
    started = asyncio.Event()

    async def sync(ctx: SyncContext) -> Any:
        started.set()
        await asyncio.Event().wait()

    connector = ScriptedConnector([])
    monkeypatch.setattr(connector, "sync", sync)
    registry = ConnectorRegistry()
    registry.register("github", lambda: connector)
    flights = InMemoryCacheStore()
    task = asyncio.create_task(
        execute_source_sync(
            source_id=source.id,
            job_id=old_id,
            sessionmaker=maker,
            registry=registry,
            secret_store=secrets,
            store=flights,
        )
    )
    await started.wait()
    await _begin_sync(maker, source.id, SyncTrigger.MANUAL, new_id)
    key = f"solus:ic:sync:{source.id}"
    await flights.set(key, "successor", 10)
    assert await asyncio.wait_for(task, 1) is None
    async with maker() as db:
        row = await db.get(Source, source.id)
        old = await db.get(Job, old_id)
        new = await db.get(Job, new_id)
        assert row is not None and row.status is SourceStatus.SYNCING and row.last_error is None
        assert old is not None and old.status is JobStatus.FAILED
        assert new is not None and new.status is JobStatus.RUNNING
    assert await flights.get(key) == "successor"


async def test_arq_queue_expiry_uses_wall_time_and_per_sync_limits(
    maker: async_sessionmaker[AsyncSession],
    settings: Any,
) -> None:
    from datetime import timedelta

    from solus_api.connectors.worker import build_worker_settings, sync_source
    from solus_api.models import Job, JobKind, JobStatus, utcnow

    secrets = InMemorySecretStore()
    source = await _seed_source(maker, secrets)
    async with maker() as db:
        job = Job(
            project_id=source.project_id,
            team_id=source.team_id,
            kind=JobKind.SYNC,
            status=JobStatus.QUEUED,
            created_at=utcnow() - timedelta(hours=3),
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    registry = ConnectorRegistry()
    registry.register("github", lambda: ScriptedConnector([]))
    result = await sync_source(
        {
            "sessionmaker": maker,
            "registry": registry,
            "secret_store": secrets,
            "integration_store": InMemoryCacheStore(),
            "job_try": 1,
        },
        str(source.id),
        str(job_id),
    )
    assert result == ""
    async with maker() as db:
        recorded = await db.get(Job, job_id)
        assert recorded is not None and recorded.status is JobStatus.FAILED
        assert recorded.error is not None and recorded.error["code"] == "sync_queue_timeout"
    config: Any = build_worker_settings(settings)
    sync_function = config.functions[0]
    assert sync_function.name == "sync_source" and sync_function.timeout_s == 3660
    assert sync_function.max_tries == 241
    assert not hasattr(config, "job_timeout"), "unrelated worker functions retain their timeout"


async def test_cancellation_while_queued_closes_job_without_releasing_owner(
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors.worker import execute_source_sync
    from solus_api.models import Job, JobKind, JobStatus

    secrets = InMemorySecretStore()
    source = await _seed_source(maker, secrets)
    async with maker() as db:
        job = Job(
            project_id=source.project_id,
            team_id=source.team_id,
            kind=JobKind.SYNC,
            status=JobStatus.QUEUED,
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    flights = InMemoryCacheStore()
    key = f"solus:ic:sync:{source.id}"
    owner = await single_flight(flights, key, ttl_seconds=300)
    waiting = asyncio.Event()
    original_claim = flights.claim

    async def claim(*args: Any, **kwargs: Any) -> bool:
        result = await original_claim(*args, **kwargs)
        waiting.set()
        return result

    monkeypatch.setattr(flights, "claim", claim)
    registry = ConnectorRegistry()
    registry.register("github", lambda: ScriptedConnector([]))
    task = asyncio.create_task(
        execute_source_sync(
            source_id=source.id,
            job_id=job_id,
            sessionmaker=maker,
            registry=registry,
            secret_store=secrets,
            store=flights,
        )
    )
    await waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with maker() as db:
        recorded = await db.get(Job, job_id)
        row = await db.get(Source, source.id)
        assert recorded is not None and recorded.status is JobStatus.FAILED
        assert recorded.error is not None and recorded.error["code"] == "sync_cancelled"
        assert row is not None and row.status is SourceStatus.CONNECTED
    assert await flights.get(key) == owner


@pytest.mark.parametrize("scope", ["current", "foreign", "completed"])
async def test_arq_max_tries_preserves_foreign_and_completed_jobs(
    maker: async_sessionmaker[AsyncSession],
    scope: str,
) -> None:
    from solus_api.connectors.worker import sync_source
    from solus_api.models import Job, JobKind, JobStatus

    secrets = InMemorySecretStore()
    source = await _seed_source(maker, secrets)
    job_source = await _seed_source(maker, secrets) if scope == "foreign" else source
    status = JobStatus.SUCCEEDED if scope == "completed" else JobStatus.QUEUED
    async with maker() as db:
        job = Job(
            project_id=job_source.project_id,
            team_id=job_source.team_id,
            kind=JobKind.SYNC,
            status=status,
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    flights = InMemoryCacheStore()
    key = f"solus:ic:sync:{source.id}"
    owner = await single_flight(flights, key, ttl_seconds=300)
    registry = ConnectorRegistry()
    registry.register("github", lambda: ScriptedConnector([]))
    assert (
        await sync_source(
            {
                "sessionmaker": maker,
                "registry": registry,
                "secret_store": secrets,
                "integration_store": flights,
                "job_try": 241,
            },
            str(source.id),
            str(job_id),
        )
        == ""
    )
    async with maker() as db:
        recorded = await db.get(Job, job_id)
        assert recorded is not None
        assert recorded.status is (JobStatus.FAILED if scope == "current" else status)
        if scope == "current":
            assert recorded.error is not None and recorded.error["code"] == "sync_queue_timeout"
        else:
            assert recorded.error is None
    assert await flights.get(key) == owner


async def test_hung_renewal_and_release_finish_with_lost_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors.integration_cache import IntegrationCache

    monkeypatch.setattr("solus_api.connectors.integration_cache._FETCH_FLIGHT_SECONDS", 1)
    monkeypatch.setattr(
        "solus_api.connectors.httpcache._FLIGHT_RELEASE_SECONDS", 0.05, raising=False
    )
    store = InMemoryCacheStore()
    entered = asyncio.Event()
    stopped = asyncio.Event()

    async def fetch() -> str:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
        return "never"

    task = asyncio.create_task(IntegrationCache(store).fetch("export", ttl_seconds=60, fetch=fetch))
    await entered.wait()

    async def hang(*args: Any, **kwargs: Any) -> Any:
        await asyncio.Event().wait()

    monkeypatch.setattr(store, "renew", hang)
    monkeypatch.setattr(store, "release", hang)
    await store.set("export:flight", "successor", 10)
    with pytest.raises(ConnectorError) as caught:
        await asyncio.wait_for(task, 0.95)
    assert caught.value.code == "single_flight_lost"
    assert stopped.is_set()
    assert await store.get("export:flight") == "successor"
    assert await store.get("export") is None
