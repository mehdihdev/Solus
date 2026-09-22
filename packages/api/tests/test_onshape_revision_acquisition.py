"""Acquisition may associate cached data only with the revision actually read."""

from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fixtures.onshape_fake import FakeOnshape
from fixtures.onshape_sample import CURRENT_MICROVERSION
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.export_common import ErrorRecorder
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import PROJECTION_VERSION, OnshapeConnector, _Target

REV = str(CURRENT_MICROVERSION["microversion"])


def connector() -> OnshapeConnector:
    return OnshapeConnector(
        client_id="id",
        client_secret="secret",
        account_ref="account",
        cache=IntegrationCache(InMemoryCacheStore()),
        poll_interval=0,
    )


async def test_elements_and_metadata_read_the_planned_immutable_revision() -> None:
    subject = connector()
    read = AsyncMock(return_value=[])
    subject.get_json = read
    async with httpx.AsyncClient(base_url="https://cad.onshape.com") as client:
        await subject._elements_at(client, "doc", "workspace", REV)
        await subject._fetch_part_metadata(
            client, "doc", "workspace", "element", ErrorRecorder(), version=REV
        )
    paths = [call.args[1] for call in read.await_args_list]
    assert paths == [
        f"/api/v6/documents/d/doc/m/{REV}/elements",
        f"/api/v6/parts/d/doc/m/{REV}/e/element",
    ]


@pytest.mark.parametrize("drift", ["before", "download"])
async def test_workspace_translation_drift_never_publishes_revision_cache(drift: str) -> None:
    subject = connector()
    fake = FakeOnshape(poll_depth=0)
    if drift == "before":
        fake.bump_microversion("different")

    async def upstream(request: httpx.Request) -> httpx.Response:
        response = await fake(request)
        if drift == "download" and "/externaldata/" in request.url.path:
            fake.bump_microversion("different")
        return response

    target = _Target("doc", "workspace", "element")
    key = subject._payload_key("export", "doc", REV, "element")
    async with (
        respx.mock(assert_all_called=False) as router,
        httpx.AsyncClient(base_url="https://cad.onshape.com") as client,
    ):
        router.route().mock(side_effect=upstream)
        with pytest.raises(ConnectorError, match="revision"):
            await subject._cached(key, lambda: subject._geometry_export(client, target, REV))
    assert subject._cache is not None
    assert await subject._cache.get(key) is None
    assert fake.entered["translations_start"] == (0 if drift == "before" else 1)
    assert fake.entered["microversion"] == (1 if drift == "before" else 2)


async def test_cold_export_brackets_download_but_verified_cache_hit_spends_no_calls() -> None:
    subject = connector()
    fake = FakeOnshape(poll_depth=0)
    order: list[str] = []

    async def upstream(request: httpx.Request) -> httpx.Response:
        order.append(request.url.path)
        return await fake(request)

    target = _Target("doc", "workspace", "element")
    key = subject._payload_key("export", "doc", REV, "element")
    async with (
        respx.mock(assert_all_called=False) as router,
        httpx.AsyncClient(base_url="https://cad.onshape.com") as client,
    ):
        router.route().mock(side_effect=upstream)
        first = await subject._cached(key, lambda: subject._geometry_export(client, target, REV))
        calls = len(order)
        assert (
            await subject._cached(key, lambda: subject._geometry_export(client, target, REV))
            == first
        )
        assert len(order) == calls
    assert order[0].endswith("/currentmicroversion")
    assert order[-1].endswith("/currentmicroversion")
    assert "/externaldata/" in order[-2]


def test_unverified_old_payload_keys_and_projection_are_not_reused() -> None:
    subject = connector()
    old = IntegrationCache.payload_key("onshape", "account", "doc", REV, "export", "element")
    assert subject._payload_key("export", "doc", REV, "element") != old
    assert PROJECTION_VERSION != "cad-geometry-v1"


async def test_late_revision_drift_refuses_complete_snapshot_and_leaves_cursor_untouched() -> None:
    from solus_api.connectors.contracts import Credentials, SyncContext
    from solus_api.connectors.onshape import _DocumentPlan

    subject = connector()
    subject._plan = AsyncMock(
        return_value=[
            _DocumentPlan(
                "doc",
                "workspace",
                REV,
                [_Target("doc", "workspace", "first"), _Target("doc", "workspace", "late")],
            )
        ]
    )
    subject._current_microversion = AsyncMock(return_value="changed")
    seen: list[str] = []

    async def ingest(
        client: httpx.AsyncClient, target: _Target, recorder: ErrorRecorder, *, version: str
    ):
        seen.append(target.element_id)
        if target.element_id == "late":
            await subject._geometry_export(client, target, version)
        return [], []

    subject._ingest = ingest
    ctx = SyncContext(
        credentials=Credentials(token="token"),
        config={"documents": ["doc"]},
        cursor={"microversions": {"doc": "old"}},
    )
    with pytest.raises(ConnectorError, match="revision"):
        await subject.sync(ctx)
    assert seen == ["first", "late"]
    assert ctx.cursor == {"microversions": {"doc": "old"}}


@pytest.mark.parametrize("revision", ["", "../bad"])
async def test_invalid_revision_never_reaches_immutable_reads_or_cache(revision: str) -> None:
    subject = connector()
    read = AsyncMock(return_value=[])
    subject.get_json = read
    async with httpx.AsyncClient() as client:
        with pytest.raises(ConnectorError, match="revision"):
            await subject._elements_at(client, "doc", "workspace", revision)
        with pytest.raises(ConnectorError, match="revision"):
            await subject._fetch_part_metadata(
                client, "doc", "workspace", "element", ErrorRecorder(), version=revision
            )
    read.assert_not_awaited()
    assert subject._cache is not None
    assert await subject._cache.get(subject._payload_key("elements", "doc", revision)) is None
    assert (
        await subject._cache.get(subject._payload_key("parts", "doc", revision, "element")) is None
    )


async def test_export_drift_invalidates_only_target_signal_and_next_locate_probes() -> None:
    from solus_api.connectors.contracts import Credentials, SyncContext

    subject = connector()
    subject._signal_max_age = 600
    cache = subject._cache
    assert cache is not None
    key = subject._signal_key("doc")
    other_document = subject._signal_key("other")
    other_account = IntegrationCache.signal_key("onshape", "another-account", "doc")
    for signal in (key, other_document, other_account):
        await cache.record_signal(signal, {"workspace": "workspace", "version": REV})
    payload_key = subject._payload_key("export", "doc", REV, "element")
    await cache.fetch(payload_key, ttl_seconds=600, fetch=AsyncMock(return_value="verified STEP"))
    stored_payload = await cache.get(payload_key)
    subject._current_microversion = AsyncMock(return_value="changed")
    ctx = SyncContext(
        credentials=Credentials(token="token"),
        config={"documents": ["doc"]},
        cursor={"workspaces": {"doc": "workspace"}},
    )
    async with httpx.AsyncClient() as client:
        assert await subject._locate(client, ctx, "doc") == ("workspace", REV)
        subject._current_microversion.assert_not_awaited()
        with pytest.raises(ConnectorError, match="revision"):
            await subject._require_export_revision(
                client, _Target("doc", "workspace", "element"), REV
            )
        assert await cache.get(key) is None
        assert await cache.get(other_document) is not None
        assert await cache.get(other_account) is not None
        assert await cache.get(payload_key) == stored_payload
        assert await subject._locate(client, ctx, "doc") == ("workspace", "changed")
    assert subject._current_microversion.await_count == 2


async def test_export_drift_without_cache_still_refuses_without_retry() -> None:
    subject = OnshapeConnector(client_id="id", client_secret="secret")
    subject._current_microversion = AsyncMock(return_value="changed")
    async with httpx.AsyncClient() as client:
        with pytest.raises(ConnectorError, match="revision"):
            await subject._require_export_revision(
                client, _Target("doc", "workspace", "element"), REV
            )
    subject._current_microversion.assert_awaited_once()
