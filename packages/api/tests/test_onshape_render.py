"""SOLUSDEV-321 P5 (R104, D4) — `connectors/onshape_render.py`: one shaded view of a synced element.

The view is of the revision the graph was synced at, on the immutable `m/` route, and only when the
sync's element listing for that revision is cached: it never probes. It runs under a scoped,
metered connector whose purpose is `agent`, so the existing quota meter refuses it above
`integration_degrade_ratio` before anything leaves the process. One call per (microversion,
element, view, size), kept in the integration cache. Every Onshape exchange here is scripted
(`httpx.MockTransport`): no call leaves the process.
"""

from __future__ import annotations

import base64
import io
import uuid
from typing import Any

import httpx
import pytest
from PIL import Image
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector
from solus_api.connectors.onshape_render import (
    ELEMENTS_KIND,
    _cached_collection,
    render_synced_view,
    shaded_view,
)
from solus_api.connectors.quota import CallMeter
from solus_api.connectors.registry import ConnectorContext
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import Source, SourceStatus, SourceType
from test_connector_quota import FakeRedis

DOC, ELEMENT, MICROVERSION = "a1" * 12, "b2" * 12, "c3" * 12
ACCOUNT = "acct-render"
SHADED_PATH = f"/api/v6/partstudios/d/{DOC}/m/{MICROVERSION}/e/{ELEMENT}/shadedviews"


def _view_png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (32, 24), (90, 90, 200)).save(out, format="PNG")
    return out.getvalue()


async def _cache_holding_listing(*rows: list[str]) -> IntegrationCache:
    """The integration cache as a sync leaves it: the element listing of the synced revision."""
    cache = IntegrationCache(InMemoryCacheStore())
    if rows:
        key = IntegrationCache.payload_key("onshape", ACCOUNT, DOC, MICROVERSION, ELEMENTS_KIND)
        entry = {"value": list(rows), "fetched_at": "2026-10-29T00:00:00+00:00", "fetched_ts": 0}
        await cache.put(key, entry, 3600)
    return cache


async def _metered(used: int) -> CallMeter:
    """An agent's meter over a scripted ledger that has already spent `used` of 10 calls."""
    meter = CallMeter(
        FakeRedis(),
        provider="onshape",
        account_ref=ACCOUNT,
        year=2026,
        allowance=10,
        degrade_ratio=0.7,
        purpose="agent",
    )
    for _ in range(used):
        await meter.record(200)
    return meter


def _connector_for(meter: CallMeter | None, cache: IntegrationCache | None) -> OnshapeConnector:
    return OnshapeConnector(
        client_id="x", client_secret="y", meter=meter, cache=cache, account_ref=ACCOUNT
    )


def _scripted_onshape(seen: list[httpx.Request], body: dict[str, Any]) -> httpx.AsyncClient:
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    return httpx.AsyncClient(base_url=ONSHAPE_API_BASE, transport=httpx.MockTransport(answer))


def _images(png: bytes) -> dict[str, Any]:
    return {"images": [base64.b64encode(png).decode()]}


async def _view(connector: OnshapeConnector, client: httpx.AsyncClient, view: str) -> bytes:
    return await shaded_view(
        connector,
        client,
        document_id=DOC,
        element_id=ELEMENT,
        microversion=MICROVERSION,
        view=view,
        width=320,
        height=240,
    )


async def test_refused_above_degrade_ratio() -> None:
    """Seven of ten calls spent is the 0.7 ratio: an agent's view is refused by the meter before
    any request is made, cached document or not."""
    meter = await _metered(7)
    connector = _connector_for(meter, await _cache_holding_listing([ELEMENT, "PARTSTUDIO", "e1"]))
    seen: list[httpx.Request] = []
    async with _scripted_onshape(seen, _images(_view_png())) as client:
        with pytest.raises(ConnectorError) as refused:
            await _view(connector, client, "front")

    assert refused.value.code == "quota_degraded"
    assert seen == []


async def test_one_call_per_revision_and_view_then_the_cache() -> None:
    png = _view_png()
    connector = _connector_for(
        await _metered(0), await _cache_holding_listing([ELEMENT, "PARTSTUDIO", "e1"])
    )
    seen: list[httpx.Request] = []
    async with _scripted_onshape(seen, _images(png)) as client:
        assert await _view(connector, client, "front") == png
        assert await _view(connector, client, "front") == png  # the cache, no call
        assert await _view(connector, client, "top") == png  # another view, one more call

    assert [request.url.path for request in seen] == [SHADED_PATH, SHADED_PATH]
    first = dict(seen[0].url.params)
    assert first["viewMatrix"] == "front" and first["outputWidth"] == "320"
    assert first["outputHeight"] == "240"


@pytest.mark.parametrize(
    "rows",
    [
        (),  # no listing cached for the synced revision
        ([ELEMENT, "DRAWING", "e1"],),  # the element is no part studio or assembly
        (["f" * 24, "PARTSTUDIO", "e1"],),  # another element
    ],
)
async def test_never_calls_without_a_cached_document(rows: tuple[list[str], ...]) -> None:
    connector = _connector_for(await _metered(0), await _cache_holding_listing(*rows))
    seen: list[httpx.Request] = []
    async with _scripted_onshape(seen, _images(_view_png())) as client:
        with pytest.raises(ConnectorError) as refused:
            await _view(connector, client, "front")

    assert refused.value.code == "not_found"
    assert seen == []


async def test_refuses_without_a_meter_or_a_cache() -> None:
    cache = await _cache_holding_listing([ELEMENT, "PARTSTUDIO", "e1"])
    seen: list[httpx.Request] = []
    async with _scripted_onshape(seen, _images(_view_png())) as client:
        for connector in (_connector_for(None, cache), _connector_for(await _metered(0), None)):
            with pytest.raises(ConnectorError) as refused:
                await _view(connector, client, "front")
            assert refused.value.code == "unavailable"
    assert seen == []


@pytest.mark.parametrize(
    "body",
    [
        {"images": [base64.b64encode(b"GIF89a not a png").decode()]},
        {"images": ["%%% not base64 %%%"]},
        {"images": []},
        {"error": "nope"},
    ],
)
async def test_what_onshape_returns_is_checked_before_it_is_kept(body: dict[str, Any]) -> None:
    connector = _connector_for(
        await _metered(0), await _cache_holding_listing([ELEMENT, "ASSEMBLY", "e1"])
    )
    seen: list[httpx.Request] = []
    async with _scripted_onshape(seen, body) as client:
        for _ in range(2):  # nothing refused is kept: the second ask calls again
            with pytest.raises(ConnectorError) as refused:
                await _view(connector, client, "iso")
            assert refused.value.code == "api_error"
    assert [request.url.path for request in seen] == [
        SHADED_PATH.replace("partstudios", "assemblies")
    ] * 2


class _RecordingRegistry:
    """Hands out the connector a test built, and records the context it was asked for."""

    def __init__(self, connector: OnshapeConnector) -> None:
        self.connector = connector
        self.contexts: list[tuple[str, ConnectorContext]] = []

    def create_scoped(self, provider: str, ctx: ConnectorContext) -> OnshapeConnector:
        self.contexts.append((provider, ctx))
        return self.connector


async def test_the_view_runs_under_an_agent_read_of_the_sources_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    png = _view_png()
    connector = _connector_for(
        await _metered(0), await _cache_holding_listing([ELEMENT, "PARTSTUDIO", "e1"])
    )
    seen: list[httpx.Request] = []
    monkeypatch.setattr(
        OnshapeConnector, "http", staticmethod(lambda creds: _scripted_onshape(seen, _images(png)))
    )
    secrets = InMemorySecretStore()
    await secrets.put("sources/onshape-1", "token-value")
    project_id, team_id, owner = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    source = Source(
        id=uuid.uuid4(),
        project_id=project_id,
        team_id=team_id,
        type=SourceType.ONSHAPE,
        name="cad",
        status=SourceStatus.CONNECTED,
        config={"documents": [DOC]},
        secret_ref="sources/onshape-1",
        account_external_id=ACCOUNT,
        created_by=owner,
    )
    registry = _RecordingRegistry(connector)
    target = {"document_id": DOC, "element_id": ELEMENT, "observed_microversion": MICROVERSION}

    async def view(**overrides: Any) -> bytes:
        request: dict[str, Any] = {
            "registry": registry,
            "source": source,
            "account": None,
            "secret_store": secrets,
            "project_id": project_id,
            "team_id": team_id,
            "target": target,
            "view": "front",
            "width": 320,
            "height": 240,
            **overrides,
        }
        return await render_synced_view(**request)

    assert await view() == png
    ((provider, ctx),) = registry.contexts
    assert provider == "onshape"
    assert (ctx.purpose, ctx.label, ctx.account_ref) == ("agent", "agent_read", ACCOUNT)
    assert (ctx.project_id, ctx.team_id, ctx.acting_user_id) == (project_id, team_id, owner)

    for refused in (
        {"target": {**target, "observed_microversion": None}},  # no synced revision to render
        {"target": {**target, "document_id": "../" + DOC}},
        {"source": Source(**{**_columns(source), "config": {"documents": []}})},  # untracked
    ):
        with pytest.raises(ConnectorError):
            await view(**refused)
    assert len(seen) == 1 and len(registry.contexts) == 1


def _columns(source: Source) -> dict[str, Any]:
    return {
        column: getattr(source, column)
        for column in (
            "id",
            "project_id",
            "team_id",
            "type",
            "name",
            "status",
            "config",
            "secret_ref",
            "account_external_id",
            "created_by",
        )
    }


async def test_the_listing_key_is_the_syncs_own() -> None:
    """The view reads the element listing the sync wrote: a listing the sync caches through its
    own key builder and cache (`_payload_key("elements", …)`, `_cached`) is the one the view
    finds, so a synced document is a cached document (P5 fix 1, M9)."""
    cache = IntegrationCache(InMemoryCacheStore())
    connector = _connector_for(None, cache)
    assert connector._payload_key("elements", DOC, MICROVERSION) == IntegrationCache.payload_key(
        "onshape", ACCOUNT, DOC, MICROVERSION, ELEMENTS_KIND
    )

    async def listing() -> list[tuple[str, str, str]]:
        return [(ELEMENT, "PARTSTUDIO", "arm")]

    await connector._cached(connector._payload_key("elements", DOC, MICROVERSION), listing)
    assert await _cached_collection(cache, ACCOUNT, DOC, ELEMENT, MICROVERSION) == "partstudios"
