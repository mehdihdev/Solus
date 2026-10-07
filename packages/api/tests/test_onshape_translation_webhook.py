"""ADR-038 §2: `translation.complete` replaces status polling where a webhook is healthy.

The payload is a doorbell. The record kept for a completion carries NO result id
from the payload, scope comes from the Source row (never the payload), and only a
translation this account itself started can be recorded.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fixtures.onshape_sample import TRANSLATION_ACTIVE, TRANSLATION_DONE, TRANSLATION_FAILED
from httpx import AsyncClient
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import (
    ONSHAPE_API_BASE,
    OnshapeConnector,
    translation_done_key,
    translation_pending_key,
)
from solus_api.connectors.webhook_token import WEBHOOK_TOKEN_KEY, mint_webhook_token
from solus_api.models import Project, Source, SourceStatus, SourceType, Team
from solus_api.services import onshape_webhooks as hooks
from solus_api.services.connections import account_ref_for
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

EVENT = "onshape.model.translation.complete"
TRANSLATION = "translation-req-1"
POLL = f"{ONSHAPE_API_BASE}/api/v8/translations/{TRANSLATION}"


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(maker: Any, account: str) -> tuple[Source, str]:
    token, digest = mint_webhook_token()
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
            type=SourceType.ONSHAPE,
            name="onshape",
            status=SourceStatus.CONNECTED,
            config={WEBHOOK_TOKEN_KEY: digest, "documents": ["doc1"]},
            account_external_id=account,
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
    return source, token


def _cache(client: AsyncClient) -> IntegrationCache:
    return client._transport.app.state.integration_cache  # type: ignore[attr-defined,no-any-return]


async def _deliver(
    client: AsyncClient, source: Source, token: str, **payload: Any
) -> httpx.Response:
    body = {"event": EVENT, "documentId": "doc1", "translationId": TRANSLATION, **payload}
    return await client.post(f"/api/v1/webhooks/onshape/{source.id}/{token}", json=body)


# ------------------------------------------------------------ the webhook side


async def test_a_completion_for_a_translation_this_account_started_is_recorded(
    client: AsyncClient, maker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = AsyncMock()
    monkeypatch.setattr("solus_api.routers.webhooks._probe_source", probe)
    source, token = await _seed(maker, "acct-a")
    cache = _cache(client)
    ref = account_ref_for(source)
    await cache.put(translation_pending_key(ref, TRANSLATION), {"state": "pending"}, 600)

    response = await _deliver(client, source, token, resultExternalDataIds=["../../evil"])

    assert response.status_code == 204
    record = await cache.get(translation_done_key(ref, TRANSLATION))
    assert record == {"state": "complete"}, "nothing from the payload is retained"
    # Our own export finishing is not a change to the document: nothing is scheduled.
    probe.assert_not_awaited()
    async with maker() as db:
        state = hooks.state_for(await db.get(Source, source.id))
    assert state.get("generation", 0) == 0


async def test_a_completion_nobody_started_is_ignored(
    client: AsyncClient, maker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("solus_api.routers.webhooks._probe_source", AsyncMock())
    source, token = await _seed(maker, "acct-a")
    cache = _cache(client)

    assert (await _deliver(client, source, token)).status_code == 204

    assert await cache.get(translation_done_key(account_ref_for(source), TRANSLATION)) is None


async def test_another_accounts_webhook_cannot_complete_this_accounts_translation(
    client: AsyncClient, maker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cross-tenant: account A started translation X. Source B (a different
    account, with its own URL token) is told about X. Nothing is recorded for A —
    and none of B's scope is derived from the payload."""
    monkeypatch.setattr("solus_api.routers.webhooks._probe_source", AsyncMock())
    victim, _ = await _seed(maker, "acct-a")
    attacker, attacker_token = await _seed(maker, "acct-b")
    cache = _cache(client)
    await cache.put(
        translation_pending_key(account_ref_for(victim), TRANSLATION), {"state": "pending"}, 600
    )

    response = await _deliver(
        client,
        attacker,
        attacker_token,
        accountId="acct-a",  # payload-claimed scope must be ignored
        sourceId=str(victim.id),
    )

    assert response.status_code == 204
    assert await cache.get(translation_done_key(account_ref_for(victim), TRANSLATION)) is None
    assert await cache.get(translation_done_key(account_ref_for(attacker), TRANSLATION)) is None


@pytest.mark.parametrize("bad", ["", "../x", "a" * 65, "id with space", 7, None, ["x"]])
async def test_a_malformed_translation_id_is_ignored(
    client: AsyncClient, maker: Any, monkeypatch: pytest.MonkeyPatch, bad: Any
) -> None:
    monkeypatch.setattr("solus_api.routers.webhooks._probe_source", AsyncMock())
    source, token = await _seed(maker, "acct-a")
    assert (await _deliver(client, source, token, translationId=bad)).status_code == 204


async def test_a_completion_for_an_untracked_document_is_ignored(
    client: AsyncClient, maker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("solus_api.routers.webhooks._probe_source", AsyncMock())
    source, token = await _seed(maker, "acct-a")
    cache = _cache(client)
    ref = account_ref_for(source)
    await cache.put(translation_pending_key(ref, TRANSLATION), {"state": "pending"}, 600)

    await _deliver(client, source, token, documentId="foreign")

    assert await cache.get(translation_done_key(ref, TRANSLATION)) is None


# --------------------------------------------------------- the connector's wait


def _connector(healthy: bool = True, cache: IntegrationCache | None = None) -> OnshapeConnector:
    connector = OnshapeConnector(
        client_id="c",
        client_secret="s",
        poll_interval=0.0,
        cache=cache or IntegrationCache(InMemoryCacheStore()),
        account_ref="acct-a",
    )
    connector.webhook_healthy = healthy
    return connector


def _polls() -> int:
    return sum(1 for call in respx.calls if "/api/v8/translations/" in call.request.url.path)


@respx.mock
async def test_a_recorded_completion_replaces_the_poll_loop_with_one_confirming_read() -> None:
    cache = IntegrationCache(InMemoryCacheStore())
    connector = _connector(cache=cache)
    await cache.put(translation_done_key("acct-a", TRANSLATION), {"state": "complete"}, 600)
    respx.get(POLL).mock(return_value=httpx.Response(200, json=TRANSLATION_DONE))

    async with connector.http(Credentials(token="t")) as client:
        external = await connector._poll_until_done(client, TRANSLATION)

    assert external == "external-data-1"
    assert _polls() == 1


@respx.mock
async def test_a_recorded_completion_that_the_provider_denies_keeps_waiting() -> None:
    cache = IntegrationCache(InMemoryCacheStore())
    connector = _connector(cache=cache)
    await cache.put(translation_done_key("acct-a", TRANSLATION), {"state": "complete"}, 600)
    respx.get(POLL).mock(
        side_effect=[
            httpx.Response(200, json=TRANSLATION_ACTIVE),
            *[httpx.Response(200, json=TRANSLATION_DONE)] * 200,
        ]
    )
    async with connector.http(Credentials(token="t")) as client:
        assert await connector._poll_until_done(client, TRANSLATION) == "external-data-1"
    assert _polls() <= 3, "never a per-tick poll, even when the record and provider disagree"


@respx.mock
async def test_a_recorded_failure_surfaces_through_the_confirming_read() -> None:
    cache = IntegrationCache(InMemoryCacheStore())
    connector = _connector(cache=cache)
    await cache.put(translation_done_key("acct-a", TRANSLATION), {"state": "complete"}, 600)
    respx.get(POLL).mock(return_value=httpx.Response(200, json=TRANSLATION_FAILED))
    async with connector.http(Credentials(token="t")) as client:
        with pytest.raises(ConnectorError) as caught:
            await connector._poll_until_done(client, TRANSLATION)
    assert caught.value.code == "export_unavailable"


@respx.mock
async def test_without_a_record_a_healthy_source_polls_only_on_a_sparse_backoff() -> None:
    connector = _connector()
    respx.get(POLL).mock(
        side_effect=[
            httpx.Response(200, json=TRANSLATION_ACTIVE),
            httpx.Response(200, json=TRANSLATION_ACTIVE),
            httpx.Response(200, json=TRANSLATION_DONE),
        ]
    )
    async with connector.http(Credentials(token="t")) as client:
        assert await connector._poll_until_done(client, TRANSLATION) == "external-data-1"
    assert _polls() == 3


@respx.mock
async def test_the_sparse_fallback_is_bounded() -> None:
    connector = _connector()
    respx.get(POLL).mock(return_value=httpx.Response(200, json=TRANSLATION_ACTIVE))
    async with connector.http(Credentials(token="t")) as client:
        with pytest.raises(ConnectorError) as caught:
            await connector._poll_until_done(client, TRANSLATION)
    assert caught.value.code == "export_timeout"
    # 2, 5, 15, 30, 30, 30 s: six calls over two minutes, not one per second.
    assert _polls() <= 6


@respx.mock
async def test_an_unhealthy_source_keeps_todays_polling() -> None:
    connector = _connector(healthy=False)
    respx.get(POLL).mock(
        side_effect=[
            *[httpx.Response(200, json=TRANSLATION_ACTIVE)] * 4,
            httpx.Response(200, json=TRANSLATION_DONE),
        ]
    )
    cache = connector._cache
    assert cache is not None
    await cache.put(translation_done_key("acct-a", TRANSLATION), {"state": "complete"}, 600)
    async with connector.http(Credentials(token="t")) as client:
        assert await connector._poll_until_done(client, TRANSLATION) == "external-data-1"
    assert _polls() == 5, "a record is only trusted from a source with a healthy subscription"


@respx.mock
async def test_the_wait_without_a_cache_polls_as_before() -> None:
    connector = OnshapeConnector(client_id="c", client_secret="s", poll_interval=0.0)
    connector.webhook_healthy = True
    respx.get(POLL).mock(
        side_effect=[
            httpx.Response(200, json=TRANSLATION_ACTIVE),
            httpx.Response(200, json=TRANSLATION_DONE),
        ]
    )
    async with connector.http(Credentials(token="t")) as client:
        assert await connector._poll_until_done(client, TRANSLATION) == "external-data-1"
    assert _polls() == 2


@respx.mock
async def test_a_healthy_export_announces_the_translation_it_started() -> None:
    cache = IntegrationCache(InMemoryCacheStore())
    connector = _connector(cache=cache)
    respx.post(url__regex=r".*/translations$").mock(
        return_value=httpx.Response(200, json={"id": TRANSLATION, "requestState": "ACTIVE"})
    )
    respx.get(POLL).mock(return_value=httpx.Response(200, json=TRANSLATION_DONE))
    respx.get(url__regex=r".*/externaldata/.*").mock(return_value=httpx.Response(200, text="STEP"))
    async with connector.http(Credentials(token="t")) as client:
        await connector._fetch_step(client, "doc1", "ws1", "el1")
    pending = await cache.get(translation_pending_key("acct-a", TRANSLATION))
    assert pending == {"state": "pending"}


@respx.mock
async def test_an_unhealthy_export_writes_no_marker() -> None:
    cache = IntegrationCache(InMemoryCacheStore())
    connector = _connector(healthy=False, cache=cache)
    respx.post(url__regex=r".*/translations$").mock(
        return_value=httpx.Response(200, json={"id": TRANSLATION, "requestState": "ACTIVE"})
    )
    respx.get(POLL).mock(return_value=httpx.Response(200, json=TRANSLATION_DONE))
    respx.get(url__regex=r".*/externaldata/.*").mock(return_value=httpx.Response(200, text="STEP"))
    async with connector.http(Credentials(token="t")) as client:
        await connector._fetch_step(client, "doc1", "ws1", "el1")
    assert await cache.get(translation_pending_key("acct-a", TRANSLATION)) is None


async def test_a_started_translation_completed_by_webhook_costs_one_status_read(
    client: AsyncClient, maker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: connector starts (marker), the webhook arrives (record), the
    wait confirms with ONE read instead of a poll ladder."""
    monkeypatch.setattr("solus_api.routers.webhooks._probe_source", AsyncMock())
    source, token = await _seed(maker, "acct-a")
    cache = _cache(client)
    connector = OnshapeConnector(
        client_id="c",
        client_secret="s",
        poll_interval=0.0,
        cache=cache,
        account_ref=account_ref_for(source),
    )
    connector.webhook_healthy = True
    announce = connector._announce_translation

    async def announce_then_webhook(request_id: str) -> None:
        await announce(request_id)
        assert (await _deliver(client, source, token, translationId=request_id)).status_code == 204

    connector._announce_translation = announce_then_webhook  # type: ignore[method-assign]
    with respx.mock(assert_all_called=False) as router:
        router.post(url__regex=r".*/translations$").mock(
            return_value=httpx.Response(200, json={"id": TRANSLATION, "requestState": "ACTIVE"})
        )
        poll = router.get(POLL).mock(return_value=httpx.Response(200, json=TRANSLATION_DONE))
        router.get(url__regex=r".*/externaldata/.*").mock(
            return_value=httpx.Response(200, text="STEP")
        )
        async with connector.http(Credentials(token="t")) as http:
            await connector._fetch_step(http, "doc1", "ws1", "el1")
    assert poll.call_count == 1
    assert uuid.UUID(str(source.id))
