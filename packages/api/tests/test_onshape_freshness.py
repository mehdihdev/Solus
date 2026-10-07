"""ADR-038 §2: webhook-first freshness.

Registration reaches the provider on every dispatch path, Solus's own writes
carry a session id, the sweep probes only sources that lack a healthy
subscription, a daily check notices a vanished subscription, and the waste found
in the audit (evidence discarded by queued jobs, a failing source re-enqueued
every minute, the account listing wiped by model edits) is gone.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from httpx import AsyncClient
from solus_api.connectors import worker
from solus_api.connectors.contracts import (
    AccountInfo,
    AuthKind,
    Connector,
    ConnectorError,
    Credentials,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.registry import ConnectorContext, ConnectorRegistry
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.connectors.webhook_token import WEBHOOK_TOKEN_KEY, mint_webhook_token
from solus_api.models import (
    Project,
    Source,
    SourceStatus,
    SourceType,
    SyncTrigger,
    Team,
    utcnow,
)
from solus_api.services import onshape_webhooks as hooks
from solus_api.services.connections import account_ref_for
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

PUBLIC = "https://api.solus.example"


def _call(mock: AsyncMock) -> Any:
    assert mock.await_args is not None
    return mock.await_args


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(
    maker: Any,
    *,
    state: dict[str, Any] | None = None,
    documents: list[str] | None = None,
    register: bool = False,
    account: str | None = None,
) -> tuple[Source, InMemorySecretStore, str]:
    token, digest = mint_webhook_token()
    secrets = InMemorySecretStore()
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        config: dict[str, Any] = {"documents": documents if documents is not None else ["doc1"]}
        if register:
            config[WEBHOOK_TOKEN_KEY] = digest
        source = Source(
            project_id=project.id,
            team_id=team.id,
            type=SourceType.ONSHAPE,
            name="onshape",
            status=SourceStatus.CONNECTED,
            config=config,
            secret_ref=f"source/{uuid.uuid4()}",
            account_external_id=account,
        )
        if state is not None:
            hooks.save_state(source, state)
        db.add(source)
        await db.commit()
        await db.refresh(source)
    await secrets.put(source.secret_ref or "", "tok")
    return source, secrets, token


def _healthy(**extra: Any) -> dict[str, Any]:
    return {
        "status": "registered",
        "subscriptions": {"doc1": "hook1"},
        "deliveries": {"doc1": utcnow().isoformat()},
        **extra,
    }


class _Client:
    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class StubOnshape(Connector):
    """Records the context it was built with; never touches a network."""

    provider = "onshape"
    auth_kind = AuthKind.OAUTH

    def __init__(self, ctx: ConnectorContext | None = None, *, changed: bool = False) -> None:
        self.ctx = ctx or ConnectorContext()
        self._changed = changed
        self.request = AsyncMock(return_value=httpx.Response(200, json={"id": "hook1"}))
        self.detect = AsyncMock(return_value=changed)

    @staticmethod
    def http(creds: Credentials) -> _Client:
        return _Client()

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        return AccountInfo(external_id="1", login="x")

    async def sync(self, ctx: SyncContext) -> SyncResult:
        return SyncResult(cursor={})

    async def detect_changes(self, ctx: SyncContext) -> bool:
        return bool(await self.detect())


def _registry(built: list[StubOnshape], *, changed: bool = False) -> ConnectorRegistry:
    registry = ConnectorRegistry()

    def factory(ctx: ConnectorContext) -> StubOnshape:
        connector = StubOnshape(ctx, changed=changed)
        built.append(connector)
        return connector

    registry.register("onshape", lambda: StubOnshape())
    registry.register_scoped("onshape", factory)
    return registry


# ------------------------------------------------------------- 1. registration


async def test_registration_sends_exactly_the_adr_038_subscription(maker: Any) -> None:
    source, _, _ = await _seed(maker)
    connector = AsyncMock()
    connector.request.return_value = httpx.Response(200, json={"id": "webhook1"})
    async with maker() as db:
        row = await db.get(Source, source.id)
        await hooks.register_onshape_webhooks(
            db, row, connector, AsyncMock(), PUBLIC, external_session_id="solus-prod"
        )
    method, path = connector.request.call_args.args[1:3]
    body = connector.request.call_args.kwargs["json_body"]
    assert (method, path) == ("POST", "/api/v6/webhooks")
    assert body["documentId"] == "doc1"
    assert body["events"] == [
        "onshape.model.lifecycle.changed",
        "onshape.model.translation.complete",
        "onshape.model.lifecycle.createversion",
    ]
    assert body["options"] == {"collapseEvents": True}
    assert body["isTransient"] is False
    assert body["externalSessionId"] == "solus-prod"
    assert body["url"].startswith(f"{PUBLIC}/api/v1/webhooks/onshape/{source.id}/")


async def test_reregistering_a_registered_source_makes_no_provider_call(maker: Any) -> None:
    source, _, _ = await _seed(maker)
    connector = AsyncMock()
    connector.request.return_value = httpx.Response(200, json={"id": "webhook1"})
    async with maker() as db:
        row = await db.get(Source, source.id)
        await hooks.register_onshape_webhooks(db, row, connector, AsyncMock(), PUBLIC)
        calls = connector.request.call_count
        await hooks.register_onshape_webhooks(db, row, connector, AsyncMock(), PUBLIC)
        await hooks.register_onshape_webhooks(db, row, connector, AsyncMock(), PUBLIC)
    assert calls == 1
    assert connector.request.call_count == 1, "idempotent: no duplicate subscriptions"


async def test_registration_stamps_the_health_baseline(maker: Any) -> None:
    source, _, _ = await _seed(maker)
    connector = AsyncMock()
    connector.request.return_value = httpx.Response(200, json={"id": "webhook1"})
    async with maker() as db:
        row = await db.get(Source, source.id)
        state = await hooks.register_onshape_webhooks(db, row, connector, AsyncMock(), PUBLIC)
    assert state["health_checked_at"]


async def _execute(maker: Any, source: Source, secrets: Any, registry: Any, **kwargs: Any) -> None:
    await worker.execute_source_sync(
        sessionmaker=maker, registry=registry, secret_store=secrets, source_id=source.id, **kwargs
    )


@pytest.fixture
def no_run(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    run = AsyncMock(return_value=None)
    monkeypatch.setattr(worker, "_run_with_scene", run)
    return run


def _ambient(monkeypatch: pytest.MonkeyPatch, base: str, **extra: Any) -> None:
    settings = type(
        "S",
        (),
        {"public_api_base_url": base, "onshape_session_id": "solus-test", **extra},
    )()
    monkeypatch.setattr(worker, "ambient_settings", lambda: settings)


async def test_the_arq_path_registers_with_the_workers_public_url(
    maker: Any, no_run: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, secrets, _ = await _seed(maker)
    register = AsyncMock()
    monkeypatch.setattr(hooks, "register_onshape_webhooks", register)
    ctx = {
        "sessionmaker": maker,
        "registry": _registry([]),
        "secret_store": secrets,
        "settings": type("S", (), {"public_api_base_url": PUBLIC, "onshape_session_id": "s"})(),
    }

    await worker.sync_source(ctx, str(source.id))

    register.assert_awaited_once()
    assert _call(register).args[4] == PUBLIC


async def test_the_inline_path_registers_too_without_a_callback_argument(
    maker: Any, no_run: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`routers/sources.py::_run_inline` passes no callback base; the dispatch seam
    both paths reach (`execute_source_sync`) resolves it from settings."""
    source, secrets, _ = await _seed(maker)
    register = AsyncMock()
    monkeypatch.setattr(hooks, "register_onshape_webhooks", register)
    _ambient(monkeypatch, PUBLIC)

    await _execute(maker, source, secrets, _registry([]), job_id=None)

    register.assert_awaited_once()
    assert _call(register).args[4] == PUBLIC
    assert _call(register).kwargs["external_session_id"] == "solus-test"


@pytest.mark.parametrize(
    "base", ["http://localhost:8000", "http://api.solus.example", "https://127.0.0.1"]
)
async def test_a_local_or_plain_http_base_never_reaches_the_provider(
    maker: Any, no_run: AsyncMock, monkeypatch: pytest.MonkeyPatch, base: str
) -> None:
    source, secrets, _ = await _seed(maker)
    built: list[StubOnshape] = []
    _ambient(monkeypatch, base)

    await _execute(maker, source, secrets, _registry(built))

    assert all(connector.request.await_count == 0 for connector in built)
    async with maker() as db:
        state = hooks.state_for(await db.get(Source, source.id))
    assert state.get("status") != "registered"
    assert not hooks.healthy_subscription(state, ["doc1"])


# -------------------------------------------------------- 2. X-Session-ID (writes)


@respx.mock
async def test_x_session_id_rides_on_writes_only() -> None:
    route = respx.route(host="cad.onshape.com").mock(return_value=httpx.Response(200, json={}))
    connector = OnshapeConnector(client_id="c", client_secret="s", session_id="solus-test")
    async with connector.http(Credentials(token="t")) as client:
        await connector.request(client, "GET", "/api/v6/read", what="read")
        await connector.request(client, "POST", "/api/v6/write", what="write", json_body={})
        await connector.request(client, "DELETE", "/api/v6/webhooks/x", what="delete")
    get, post, delete = (call.request for call in route.calls)
    assert "x-session-id" not in get.headers
    assert post.headers["x-session-id"] == "solus-test"
    assert delete.headers["x-session-id"] == "solus-test"


@respx.mock
async def test_x_session_id_defaults_to_the_configured_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors import onshape

    _ambient_session = type("S", (), {"onshape_session_id": "from-settings"})()
    monkeypatch.setattr(onshape, "ambient_settings", lambda: _ambient_session)
    route = respx.route(host="cad.onshape.com").mock(return_value=httpx.Response(200, json={}))
    connector = OnshapeConnector(client_id="c", client_secret="s")
    async with connector.http(Credentials(token="t")) as client:
        await connector.request(client, "POST", "/api/v6/write", what="write", json_body={})
    assert route.calls[0].request.headers["x-session-id"] == "from-settings"


@respx.mock
async def test_an_unusable_session_id_falls_back_rather_than_breaking_writes() -> None:
    route = respx.route(host="cad.onshape.com").mock(return_value=httpx.Response(200, json={}))
    connector = OnshapeConnector(client_id="c", client_secret="s", session_id="bad\nvalue")
    async with connector.http(Credentials(token="t")) as client:
        await connector.request(client, "POST", "/api/v6/write", what="write", json_body={})
    assert route.calls[0].request.headers["x-session-id"] == "solus-api"


# ----------------------------------------------------------- 5. sweep disposition


def _config(state: dict[str, Any]) -> dict[str, Any]:
    return {"documents": ["doc1"], hooks.STATE_KEY: state}


def test_a_healthy_subscription_is_not_probed_hourly() -> None:
    fresh = _healthy(health_checked_at=utcnow().isoformat())
    assert worker._onshape_disposition("onshape", _config(fresh)) == "healthy"
    assert worker._onshape_disposition("onshape", _config(_healthy())) == "healthy"


def test_a_healthy_subscription_is_checked_once_a_day() -> None:
    stale = _healthy(health_checked_at=(utcnow() - timedelta(hours=25)).isoformat())
    assert worker._onshape_disposition("onshape", _config(stale)) == "check"


def test_an_unhealthy_subscription_falls_back_to_the_hourly_probe() -> None:
    assert worker._onshape_disposition("onshape", _config({"status": "failed"})) == "probe"
    assert worker._onshape_disposition("onshape", {"documents": ["doc1"]}) == "probe"
    assert worker._onshape_disposition("github", {}) == "probe"


async def test_the_sweep_probes_only_sources_without_a_healthy_subscription(maker: Any) -> None:
    healthy, secrets, _ = await _seed(maker, state=_healthy())
    unhealthy, _, _ = await _seed(maker, state={"status": "failed"})
    for source in (unhealthy,):
        await secrets.put(source.secret_ref or "", "tok")
    built: list[StubOnshape] = []
    enqueue = AsyncMock()

    await worker.run_change_detection(
        sessionmaker=maker, registry=_registry(built), secret_store=secrets, enqueue=enqueue
    )

    assert len(built) == 1, "only the source without a healthy subscription is probed"
    built[0].detect.assert_awaited_once()
    assert built[0].ctx.label == "sweep"
    enqueue.assert_not_awaited()
    assert healthy.id != unhealthy.id


async def test_the_daily_check_makes_one_cheap_call_per_subscription(maker: Any) -> None:
    state = _healthy(health_checked_at=(utcnow() - timedelta(hours=25)).isoformat())
    source, secrets, _ = await _seed(maker, state=state)
    built: list[StubOnshape] = []

    await worker.run_change_detection(
        sessionmaker=maker, registry=_registry(built), secret_store=secrets, enqueue=AsyncMock()
    )

    assert len(built) == 1
    built[0].request.assert_awaited_once()
    assert _call(built[0].request).args[1:3] == ("GET", "/api/v6/webhooks/hook1")
    built[0].detect.assert_not_awaited()
    async with maker() as db:
        row = await db.get(Source, source.id)
        refreshed = hooks.state_for(row)
    assert refreshed["status"] == "registered"
    assert hooks.healthy_subscription(refreshed, ["doc1"])
    assert refreshed["health_checked_at"] > state["health_checked_at"]
    # Checked today: the next sweep spends nothing on it.
    built.clear()
    await worker.run_change_detection(
        sessionmaker=maker, registry=_registry(built), secret_store=secrets, enqueue=AsyncMock()
    )
    assert built == []


async def test_a_vanished_subscription_reenables_the_hourly_fallback(maker: Any) -> None:
    state = _healthy(health_checked_at=(utcnow() - timedelta(hours=25)).isoformat())
    source, secrets, _ = await _seed(maker, state=state)
    built: list[StubOnshape] = []
    registry = _registry(built)
    original = registry._scoped_factories["onshape"]

    def gone(ctx: ConnectorContext) -> StubOnshape:
        connector = cast(StubOnshape, original(ctx))
        connector.request.side_effect = ConnectorError("not_found", "Onshape has no webhook")
        return connector

    registry.register_scoped("onshape", gone)

    await worker.run_change_detection(
        sessionmaker=maker, registry=registry, secret_store=secrets, enqueue=AsyncMock()
    )

    async with maker() as db:
        row = await db.get(Source, source.id)
        refreshed = hooks.state_for(row)
        config = dict(row.config)
        status = row.status
    assert not hooks.healthy_subscription(refreshed, ["doc1"])
    assert refreshed["reason"] == "subscription_missing"
    assert refreshed["subscriptions"] == {}
    assert worker._onshape_disposition("onshape", config) == "probe"
    assert status is SourceStatus.CONNECTED, "a failed health check never errors the source"


async def test_a_transient_check_failure_keeps_the_subscription(maker: Any) -> None:
    state = _healthy(health_checked_at=(utcnow() - timedelta(hours=25)).isoformat())
    source, secrets, _ = await _seed(maker, state=state)
    registry = _registry([])
    original = registry._scoped_factories["onshape"]

    def flaky(ctx: ConnectorContext) -> StubOnshape:
        connector = cast(StubOnshape, original(ctx))
        connector.request.side_effect = ConnectorError("api_unreachable", "down")
        return connector

    registry.register_scoped("onshape", flaky)
    await worker.run_change_detection(
        sessionmaker=maker, registry=registry, secret_store=secrets, enqueue=AsyncMock()
    )
    async with maker() as db:
        refreshed = hooks.state_for(await db.get(Source, source.id))
    assert hooks.healthy_subscription(refreshed, ["doc1"])


async def test_a_baseline_is_stamped_locally_for_old_states_without_a_call(maker: Any) -> None:
    source, secrets, _ = await _seed(maker, state=_healthy())
    built: list[StubOnshape] = []

    await worker.run_change_detection(
        sessionmaker=maker, registry=_registry(built), secret_store=secrets, enqueue=AsyncMock()
    )

    assert built == []
    async with maker() as db:
        assert hooks.state_for(await db.get(Source, source.id))["health_checked_at"]


# ----------------------------------------------------- 6a. queued trigger evidence


async def test_a_sweep_queued_job_keeps_the_sweeps_evidence(maker: Any) -> None:
    source, _, _ = await _seed(maker)
    assert (
        await worker._queued_sync_trigger(maker, str(source.id), None, False)
        is SyncTrigger.SCHEDULED
    )


async def test_a_hint_that_arrives_after_the_job_queued_still_bypasses_the_signal(
    maker: Any,
) -> None:
    source, _, _ = await _seed(maker, state=hooks.hint_state({}, event_id="late"))
    assert (
        await worker._queued_sync_trigger(maker, str(source.id), None, False) is SyncTrigger.WEBHOOK
    )


async def test_manual_and_webhook_flags_keep_their_triggers(maker: Any) -> None:
    source, _, _ = await _seed(maker)
    assert (
        await worker._queued_sync_trigger(maker, str(source.id), str(uuid.uuid4()), False)
        is SyncTrigger.MANUAL
    )
    assert (
        await worker._queued_sync_trigger(maker, str(source.id), None, True) is SyncTrigger.WEBHOOK
    )


async def test_the_queued_sweep_job_does_not_probe_again(
    maker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus_api.connectors.httpcache import InMemoryCacheStore
    from solus_api.connectors.onshape import PROJECTION_VERSION

    document, workspace = "a" * 24, "b" * 24
    source, secrets, _ = await _seed(maker, documents=[document])
    async with maker() as db:
        row = await db.get(Source, source.id)
        row.cursor = {
            "microversions": {document: "old"},
            "workspaces": {document: workspace},
            "projection_version": PROJECTION_VERSION,
        }
        await db.commit()
    cache = IntegrationCache(InMemoryCacheStore())
    await cache.record_signal(
        cache.signal_key("onshape", account_ref_for(source), document),
        {"workspace": workspace, "version": "new"},
    )
    fresh_probe = AsyncMock(return_value="new")
    synced = AsyncMock(return_value=SyncResult(cursor={"microversions": {document: "new"}}))

    def factory(ctx: ConnectorContext) -> OnshapeConnector:
        connector = OnshapeConnector(
            client_id="t",
            client_secret="t",
            cache=cache,
            account_ref=ctx.account_ref,
            signal_max_age_seconds=None if ctx.purpose == "webhook" else 300,
        )
        connector._current_microversion = fresh_probe  # type: ignore[method-assign]
        connector.sync = synced  # type: ignore[method-assign]
        return connector

    registry = ConnectorRegistry()
    registry.register_scoped("onshape", factory)
    await worker.sync_source(
        {"sessionmaker": maker, "registry": registry, "secret_store": secrets}, str(source.id)
    )

    fresh_probe.assert_not_awaited()
    synced.assert_awaited_once()


# ----------------------------------------------------------- 6b. recovery backoff


async def test_a_failing_dirty_source_backs_off_exponentially(maker: Any) -> None:
    source, _, _ = await _seed(maker, state=hooks.hint_state({}, event_id="x"))
    pool = AsyncMock()

    async def recover() -> int:
        return await worker.recover_onshape_hints({"sessionmaker": maker, "redis": pool})

    async def state() -> dict[str, Any]:
        async with maker() as db:
            return hooks.state_for(await db.get(Source, source.id))

    async def expire() -> None:
        async with maker() as db:
            row = await db.get(Source, source.id, with_for_update=True)
            hooks.save_state(
                row,
                {**hooks.state_for(row), "recover_after": (utcnow() - timedelta(1)).isoformat()},
            )
            await db.commit()

    delays: list[float] = []
    for _ in range(8):
        assert await recover() == 1
        current = await state()
        from datetime import datetime

        delays.append(
            round((datetime.fromisoformat(current["recover_after"]) - utcnow()).total_seconds())
        )
        # Immediately afterwards the source is NOT due again: no per-minute re-enqueue.
        assert await recover() == 0
        await expire()
    assert delays[:3] == [60, 120, 240]
    assert delays[-1] == 3600
    assert max(delays) == 3600
    assert pool.enqueue_job.await_count == 8


async def test_recovery_enqueues_the_quiet_job_labelled_recovery(maker: Any) -> None:
    source, _, _ = await _seed(maker, state=hooks.hint_state({}, event_id="x"))
    pool = AsyncMock()
    await worker.recover_onshape_hints({"sessionmaker": maker, "redis": pool})
    pool.enqueue_job.assert_awaited_once_with(
        "sync_source",
        str(source.id),
        _job_id=f"onshape-quiet:{source.id}",
        webhook=True,
        quiet=True,
        label="recovery",
    )


async def test_recovery_that_finds_a_pending_job_does_not_count_a_failure(maker: Any) -> None:
    source, _, _ = await _seed(maker, state=hooks.hint_state({}, event_id="x"))
    pool = AsyncMock()
    pool.enqueue_job.return_value = None  # arq: a job with this id is already queued
    await worker.recover_onshape_hints({"sessionmaker": maker, "redis": pool})
    async with maker() as db:
        state = hooks.state_for(await db.get(Source, source.id))
    assert "recovery_attempts" not in state and "recover_after" not in state


async def test_a_successful_reconciliation_resets_the_backoff(
    maker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus_api.models import JobStatus, Sync

    state = hooks.hint_state({}, event_id="x")
    state.update(recovery_attempts=5, recover_after=(utcnow() + timedelta(hours=1)).isoformat())
    source, secrets, _ = await _seed(maker, state=state)

    async def succeed(**kwargs: Any) -> uuid.UUID:
        async with maker() as db:
            sync = Sync(
                source_id=source.id, project_id=source.project_id, status=JobStatus.SUCCEEDED
            )
            db.add(sync)
            await db.commit()
            return sync.id

    monkeypatch.setattr(worker, "run_sync", succeed)
    await worker._run(
        StubOnshape(), source.id, maker, secrets, SyncTrigger.WEBHOOK, None, None, False, None
    )
    async with maker() as db:
        reset = hooks.state_for(await db.get(Source, source.id))
    assert reset["acknowledged"] == 1
    assert "recovery_attempts" not in reset and "recover_after" not in reset


# ------------------------------------------------- 6c. listing wipe, and the hints


async def _post(client: AsyncClient, source: Source, token: str, body: dict[str, Any]) -> int:
    response = await client.post(f"/api/v1/webhooks/onshape/{source.id}/{token}", json=body)
    return response.status_code


async def test_model_edits_do_not_wipe_the_account_listing(
    client: AsyncClient, maker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("solus_api.routers.webhooks._probe_source", AsyncMock())
    source, _, token = await _seed(maker, register=True, account="acct-1")
    cache: IntegrationCache = client._transport.app.state.integration_cache  # type: ignore[attr-defined]
    key = cache.listing_key("onshape", account_ref_for(source))
    await cache.put(key, {"items": []}, 600)

    for index, event in enumerate(
        (
            "onshape.model.lifecycle.changed",
            "onshape.model.lifecycle.createversion",
            "onshape.model.translation.complete",
        )
    ):
        assert await _post(client, source, token, {"event": event, "messageId": f"m{index}"}) == 204

    assert await cache.get(key) == {"items": []}


async def test_no_onshape_event_wipes_the_listing_even_a_document_lifecycle_one(
    client: AsyncClient, maker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Document events are not subscribed (EVENTS is model-only), so no Onshape delivery can
    ever change the listing; the old `onshape.document.*` wipe branch was unreachable in
    production and is gone. A spoofed or stray document event must not wipe it either."""
    monkeypatch.setattr("solus_api.routers.webhooks._probe_source", AsyncMock())
    source, _, token = await _seed(maker, register=True, account="acct-1")
    cache: IntegrationCache = client._transport.app.state.integration_cache  # type: ignore[attr-defined]
    key = cache.listing_key("onshape", account_ref_for(source))
    await cache.put(key, {"items": []}, 600)

    assert (
        await _post(
            client,
            source,
            token,
            {"event": "onshape.document.lifecycle.statechange", "messageId": "doc-event"},
        )
        == 204
    )

    assert await cache.get(key) == {"items": []}
    assert not any(event.startswith("onshape.document.") for event in hooks.EVENTS)


# ------------------------------------------------------------ 7. metering hooks


def _metered() -> tuple[OnshapeConnector, MagicMock]:
    meter = MagicMock()
    meter.admit = AsyncMock()
    meter.record = AsyncMock()
    meter.observe_rate_limit = AsyncMock()
    return OnshapeConnector(client_id="c", client_secret="s", meter=meter), meter


@respx.mock
async def test_the_rate_limit_header_reaches_the_meter() -> None:
    respx.route(host="cad.onshape.com").mock(
        return_value=httpx.Response(200, json={}, headers={"X-Rate-Limit-Remaining": "57"})
    )
    connector, meter = _metered()
    async with connector.http(Credentials(token="t")) as client:
        await connector.request(client, "GET", "/api/v6/x", what="x")
    meter.observe_rate_limit.assert_awaited_once_with(57, None)


@respx.mock
async def test_retry_after_travels_with_a_throttled_response() -> None:
    respx.route(host="cad.onshape.com").mock(
        side_effect=[
            httpx.Response(
                429, json={}, headers={"X-Rate-Limit-Remaining": "0", "Retry-After": "0"}
            ),
            httpx.Response(200, json={}),
        ]
    )
    connector, meter = _metered()
    async with connector.http(Credentials(token="t")) as client:
        await connector.request(client, "GET", "/api/v6/x", what="x")
    meter.observe_rate_limit.assert_awaited_once_with(0, 0.0)


@respx.mock
@pytest.mark.parametrize("header", [None, "", "lots", "-3"])
async def test_a_missing_or_garbage_rate_limit_header_is_not_reported(header: str | None) -> None:
    headers = {} if header is None else {"X-Rate-Limit-Remaining": header}
    respx.route(host="cad.onshape.com").mock(
        return_value=httpx.Response(200, json={}, headers=headers)
    )
    connector, meter = _metered()
    async with connector.http(Credentials(token="t")) as client:
        await connector.request(client, "GET", "/api/v6/x", what="x")
    if header == "-3":
        meter.observe_rate_limit.assert_awaited_once_with(-3, None)  # the meter bounds it
    else:
        meter.observe_rate_limit.assert_not_awaited()


@respx.mock
async def test_the_download_path_reports_the_rate_limit_too() -> None:
    respx.route(host="cad.onshape.com").mock(
        return_value=httpx.Response(200, text="ISO", headers={"X-Rate-Limit-Remaining": "40"})
    )
    connector, meter = _metered()
    async with connector.http(Credentials(token="t")) as client:
        await connector._download_bounded(client, "/api/v6/documents/d/x/externaldata/y")
    meter.observe_rate_limit.assert_awaited_once_with(40, None)


@pytest.mark.parametrize(
    ("trigger", "label"),
    [
        (SyncTrigger.WEBHOOK, "webhook"),
        (SyncTrigger.SCHEDULED, "sweep"),
        (SyncTrigger.MANUAL, "sync"),
    ],
)
async def test_syncs_label_their_calls_by_trigger(
    maker: Any, no_run: AsyncMock, trigger: SyncTrigger, label: str
) -> None:
    source, secrets, _ = await _seed(maker)
    built: list[StubOnshape] = []
    await _execute(maker, source, secrets, _registry(built), trigger=trigger)
    assert built[0].ctx.label == label


async def test_an_explicit_recovery_label_wins(maker: Any, no_run: AsyncMock) -> None:
    source, secrets, _ = await _seed(maker)
    built: list[StubOnshape] = []
    await _execute(
        maker, source, secrets, _registry(built), trigger=SyncTrigger.WEBHOOK, label="recovery"
    )
    assert built[0].ctx.label == "recovery"


async def test_sync_source_forwards_the_label(maker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    source, _, _ = await _seed(maker)
    execute = AsyncMock(return_value=None)
    monkeypatch.setattr(worker, "execute_source_sync", execute)
    await worker.sync_source(
        {"sessionmaker": maker, "registry": object(), "secret_store": object()},
        str(source.id),
        webhook=True,
        label="recovery",
    )
    assert _call(execute).kwargs["label"] == "recovery"


async def test_an_unknown_label_is_refused(maker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    source, _, _ = await _seed(maker)
    execute = AsyncMock(return_value=None)
    monkeypatch.setattr(worker, "execute_source_sync", execute)
    await worker.sync_source(
        {"sessionmaker": maker, "registry": object(), "secret_store": object()},
        str(source.id),
        label="not-a-label",
    )
    assert _call(execute).kwargs["label"] is None


# ------------------------------------------------------- the sweep's own hint


async def test_a_sweep_detected_change_is_enqueued_as_a_deferred_quiet_job(maker: Any) -> None:
    source, _, _ = await _seed(maker)
    pool = AsyncMock()
    settings = type("S", (), {"onshape_quiet_period_seconds": 90})()

    await worker._enqueue_sweep_hit(
        {"sessionmaker": maker, "redis": pool, "settings": settings}, source.id
    )

    pool.enqueue_job.assert_awaited_once_with(
        "sync_source",
        str(source.id),
        _job_id=f"onshape-quiet:{source.id}",
        _defer_by=90,
        quiet=True,
    )
    async with maker() as db:
        state = hooks.state_for(await db.get(Source, source.id))
    assert state["last_hint_at"]
    assert "generation" not in state, "the sweep's evidence is not turned into a doorbell"


async def test_a_sweep_hit_for_another_provider_is_not_delayed(maker: Any) -> None:
    source, _, _ = await _seed(maker)
    async with maker() as db:
        row = await db.get(Source, source.id)
        row.type = SourceType.GITHUB
        await db.commit()
    pool = AsyncMock()
    await worker._enqueue_sweep_hit({"sessionmaker": maker, "redis": pool}, source.id)
    pool.enqueue_job.assert_awaited_once_with("sync_source", str(source.id))


def test_the_worker_keeps_no_result_so_a_stable_job_id_can_be_reused() -> None:
    """arq refuses to enqueue a job id whose RESULT key still exists. A stable
    per-source id with the default one-hour result retention would silently drop
    every hint for an hour after the first sync."""
    from solus_api.core.config import Settings

    settings = Settings(database_url="postgresql+asyncpg://x:x@localhost/x")  # type: ignore[call-arg]
    functions = {
        f.name: f
        for f in cast(Any, worker.build_worker_settings(settings)).functions
        if hasattr(f, "name")
    }
    assert functions["sync_source"].keep_result_s == 0


def test_mirror_handle_exposes_the_cache_and_account_read_only() -> None:
    from solus_api.connectors.httpcache import InMemoryCacheStore

    cache = IntegrationCache(InMemoryCacheStore())
    connector = OnshapeConnector(client_id="c", client_secret="s", cache=cache, account_ref="acct")
    assert connector.mirror_handle() == (cache, "acct")


def test_mirror_handle_is_empty_without_cache_or_account_identity() -> None:
    from solus_api.connectors.httpcache import InMemoryCacheStore

    cache = IntegrationCache(InMemoryCacheStore())
    assert OnshapeConnector(client_id="c", client_secret="s").mirror_handle() == (None, None)
    # A cache without an account identity is dropped by the constructor: never keyed blindly.
    assert OnshapeConnector(client_id="c", client_secret="s", cache=cache).mirror_handle() == (
        None,
        None,
    )
