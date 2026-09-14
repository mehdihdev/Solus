"""Only account-scoped immutable default-configuration reads may be reused."""

from unittest.mock import AsyncMock

import pytest
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache


def reader(account="account-a", cache=None):
    from solus_api.connectors.onshape_read_cache import OnshapeReadCache

    return OnshapeReadCache(cache or IntegrationCache(InMemoryCacheStore()), account)


def args():
    return dict(
        document_id="doc",
        element_id="element",
        revision_kind="m",
        revision_id="revision",
        kind="feature_spec",
    )


async def test_immutable_cache_hits_are_isolated_from_caller_mutation():
    cache = reader()
    fetch = AsyncMock(return_value={"parameters": [{"name": "depth"}]})
    first = await cache.fetch(**args(), fetch=fetch)
    first["parameters"][0]["name"] = "changed"
    assert await cache.fetch(**args(), fetch=fetch) == {"parameters": [{"name": "depth"}]}
    fetch.assert_awaited_once()


async def test_account_revision_kind_and_resource_never_alias():
    store = IntegrationCache(InMemoryCacheStore())
    first, second = reader(cache=store), reader("account-b", store)
    fetch = AsyncMock(return_value={"value": 1})
    await first.fetch(**args(), fetch=fetch)
    await second.fetch(**args(), fetch=fetch)
    for changes in (
        {"revision_id": "other"},
        {"revision_kind": "v"},
        {"element_id": "other"},
        {"document_id": "other"},
        {"kind": "donor_geometry"},
    ):
        await first.fetch(**{**args(), **changes}, fetch=fetch)
    assert fetch.await_count == 7


@pytest.mark.parametrize(
    "changes",
    [
        {"revision_kind": "w"},
        {"revision_id": ""},
        {"document_id": "../other"},
        {"kind": "mutable_target"},
    ],
)
async def test_mutable_or_invalid_keys_refuse_before_fetch(changes):
    fetch = AsyncMock()
    with pytest.raises(ValueError):
        await reader().fetch(**{**args(), **changes}, fetch=fetch)
    fetch.assert_not_awaited()


async def test_failed_fetch_is_never_cached():
    cache = reader()
    fetch = AsyncMock(side_effect=[RuntimeError("unauthorized"), {"value": 2}])
    with pytest.raises(RuntimeError):
        await cache.fetch(**args(), fetch=fetch)
    assert await cache.fetch(**args(), fetch=fetch) == {"value": 2}
    assert fetch.await_count == 2


def test_empty_account_cannot_share_cache():
    with pytest.raises(ValueError):
        reader("")


@pytest.mark.parametrize("account", ["account-a", None])
async def test_connector_immutable_body_details_uses_revision_bound_route(account):
    from solus_api.connectors.onshape import OnshapeConnector

    cache = IntegrationCache(InMemoryCacheStore())
    connector = OnshapeConnector(
        client_id="id", client_secret="secret", cache=cache, account_ref=account
    )
    bodies = {"microversionId": "revision", "bodies": []}
    fetch = AsyncMock(return_value=bodies)
    connector.get_json = fetch
    await connector.immutable_body_details(
        None, document_id="doc", element_id="element", microversion_id="revision"
    )
    await connector.immutable_body_details(
        None, document_id="doc", element_id="element", microversion_id="revision"
    )
    assert fetch.await_count == (1 if account else 2)
    first = fetch.await_args_list[0]
    assert first.args[1] == "/api/v6/partstudios/d/doc/m/revision/e/element/bodydetails"
    assert first.kwargs["params"] == {"includeGeometricData": "true"}
    fetch.return_value = {"microversionId": "next", "bodies": []}
    await connector.immutable_body_details(
        None, document_id="doc", element_id="element", microversion_id="next"
    )
    assert fetch.await_count == (2 if account else 3)


async def test_body_details_error_or_wrong_revision_is_not_cached():
    from solus_api.connectors.contracts import ConnectorError
    from solus_api.connectors.onshape import OnshapeConnector

    connector = OnshapeConnector(
        client_id="id",
        client_secret="secret",
        cache=IntegrationCache(InMemoryCacheStore()),
        account_ref="a",
    )
    fetch = AsyncMock(
        side_effect=[
            {"errorEnum": "FAILED", "microversionId": "revision"},
            {"microversionId": "wrong"},
            {"microversionId": "revision"},
            {
                "microversionId": {"btType": "BTMicroversionId-366", "theId": "revision"},
                "bodies": [],
            },
        ]
    )
    connector.get_json = fetch
    for _ in range(3):
        with pytest.raises(ConnectorError):
            await connector.immutable_body_details(
                None, document_id="doc", element_id="element", microversion_id="revision"
            )
    result = await connector.immutable_body_details(
        None, document_id="doc", element_id="element", microversion_id="revision"
    )
    assert result["bodies"] == [] and fetch.await_count == 4


async def test_large_donor_snapshot_is_usable_but_not_stored_above_cache_limit():
    cache = reader()
    payload = {"geometry": "x" * (9 * 1024 * 1024)}
    fetch = AsyncMock(return_value=payload)
    request = {**args(), "kind": "donor_geometry"}
    first = await cache.fetch(**request, fetch=fetch)
    assert first == payload and first is not payload
    assert await cache.fetch(**request, fetch=fetch) == payload
    assert fetch.await_count == 2


@pytest.mark.parametrize("kind,mebibytes", [("donor_geometry", 33), ("feature_spec", 9)])
async def test_kind_specific_acquisition_cap_refuses_and_does_not_cache(kind, mebibytes):
    cache = reader()
    fetch = AsyncMock(side_effect=[{"data": "x" * (mebibytes * 1024 * 1024)}, {"valid": True}])
    request = {**args(), "kind": kind}
    with pytest.raises(ValueError):
        await cache.fetch(**request, fetch=fetch)
    assert await cache.fetch(**request, fetch=fetch) == {"valid": True}
    assert fetch.await_count == 2


@pytest.mark.parametrize("kind,mebibytes", [("donor_geometry", 33), ("feature_spec", 9)])
async def test_kind_specific_snapshot_validation_also_applies_to_cache_hits(kind, mebibytes):
    from solus_api.connectors.integration_cache import Fetched

    cache = IntegrationCache(InMemoryCacheStore())
    cache.fetch = AsyncMock(
        return_value=Fetched({"data": "x" * (mebibytes * 1024 * 1024)}, True, "now")
    )
    fetch = AsyncMock()
    with pytest.raises(ValueError):
        await reader(cache=cache).fetch(**{**args(), "kind": kind}, fetch=fetch)
    fetch.assert_not_awaited()
