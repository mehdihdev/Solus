"""Account document-tree boundary, auth, and I1 cache regressions (SOLUSDEV-261)."""

from typing import Any, ClassVar

import pytest
from conftest import FakeGitHub
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.registry import ConnectorRegistry
from test_connections import _connect_account

OWNER = "a" * 24
FOLDER = "b" * 24
DOCUMENT = "c" * 24


class TreeConnector(FakeGitHub):  # type: ignore[misc,unused-ignore]
    provider = "onshape"
    supports_document_tree = True
    calls: ClassVar[list[tuple[str, int]]] = []
    fail: ClassVar[bool] = False

    async def list_document_tree(
        self, creds: Credentials, node: str, offset: int
    ) -> dict[str, Any]:
        type(self).calls.append((node, offset))
        if self.fail:
            raise ConnectorError("api_error", "Provider unavailable")
        return {
            "items": [{"id": DOCUMENT, "name": "Chassis", "kind": "document", "node": None}],
            "next_offset": None,
        }


@pytest.fixture(autouse=True)
def install(app: FastAPI, fake_registry: ConnectorRegistry) -> None:
    TreeConnector.calls = []
    TreeConnector.fail = False
    fake_registry.register("onshape", TreeConnector)
    app.state.connector_registry = fake_registry


async def path_for(client: AsyncClient, headers: dict[str, str], provider: str = "onshape") -> str:
    result = await _connect_account(client, headers, provider)
    return f"/api/v1/users/me/connections/{result['connection']['id']}/document-tree"


async def test_tree_cache_and_page_isolation(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    path = await path_for(client, alice_headers)
    first = await client.get(path, headers=alice_headers)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["items"][0]["id"] == DOCUMENT
    assert first.json()["meta"]["cached"] is False
    second = await client.get(path, headers=alice_headers)
    assert second.json()["meta"]["cached"] is True
    assert TreeConnector.calls == [("root", 0)]
    await client.get(path, params={"node": f"folder:{FOLDER}"}, headers=alice_headers)
    await client.get(path, params={"node": f"folder:{FOLDER}", "offset": 20}, headers=alice_headers)
    assert TreeConnector.calls == [("root", 0), (f"folder:{FOLDER}", 0), (f"folder:{FOLDER}", 20)]


async def test_tree_cache_only_miss_never_resolves_credentials(
    client: AsyncClient, alice_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = await path_for(client, alice_headers)

    async def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("cache-only attempted to resolve credentials")

    monkeypatch.setattr("solus_api.services.document_tree.resolve_credentials", forbidden)
    response = await client.get(path, params={"cache_only": True}, headers=alice_headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "listing_not_cached"
    assert TreeConnector.calls == []


@pytest.mark.parametrize(
    "params",
    [
        {"node": "folder:../bad"},
        {"offset": -1},
        {"offset": 100001},
        {"node": "root", "offset": 20},
        {"refresh": True, "cache_only": True},
    ],
)
async def test_tree_invalid_query_has_no_provider_io(
    client: AsyncClient, alice_headers: dict[str, str], params: dict[str, Any]
) -> None:
    path = await path_for(client, alice_headers)
    response = await client.get(path, params=params, headers=alice_headers)
    assert response.status_code == 422
    assert TreeConnector.calls == []


async def test_tree_owner_auth_verified_and_provider_boundaries(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    unverified_headers: dict[str, str],
) -> None:
    path = await path_for(client, alice_headers)
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=bob_headers)).status_code == 404
    assert (await client.get(path, headers=alice_headers)).status_code == 200
    assert (
        await client.get(path, params={"cache_only": True}, headers=bob_headers)
    ).status_code == 404
    assert (await client.get(path, headers=unverified_headers)).status_code == 403
    unsupported = await path_for(client, alice_headers, "github")
    assert (await client.get(unsupported, headers=alice_headers)).status_code == 400
    assert TreeConnector.calls == [("root", 0)]


async def test_tree_refresh_cooldown_failure_and_revocation(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    path = await path_for(client, alice_headers)
    await client.get(path, headers=alice_headers)
    assert (await client.get(path, params={"refresh": True}, headers=alice_headers)).json()["meta"][
        "cached"
    ] is True
    assert len(TreeConnector.calls) == 1
    app.state.integration_cache.listing_refresh_cooldown_seconds = 0
    TreeConnector.fail = True
    assert (
        await client.get(path, params={"refresh": True}, headers=alice_headers)
    ).status_code == 502
    cached = await client.get(path, params={"cache_only": True}, headers=alice_headers)
    assert cached.status_code == 200
    assert cached.json()["meta"]["cached"] is True
    assert (
        await client.delete(path.removesuffix("/document-tree"), headers=alice_headers)
    ).status_code == 200
    assert (await client.get(path, headers=alice_headers)).status_code == 404
    key = app.state.integration_cache.payload_key("onshape", "42", "root", "0", "document-tree")
    assert await app.state.integration_cache.get(key) is None


async def test_connection_exposes_generic_tree_capability(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await path_for(client, alice_headers)
    response = await client.get("/api/v1/users/me/connections", headers=alice_headers)
    assert response.json()["data"][0]["document_tree"] is True


async def test_tree_refreshes_expired_oauth_once(
    client: AsyncClient, alice_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens: list[str] = []

    async def exchange(self: TreeConnector, **kwargs: Any) -> Credentials:
        return Credentials(token="expired", refresh_token="refresh-old")

    async def refresh(self: TreeConnector, creds: Credentials) -> Credentials:
        return Credentials(token="renewed", refresh_token="refresh-new")

    original = TreeConnector.list_document_tree

    async def listing(
        self: TreeConnector, creds: Credentials, node: str, offset: int
    ) -> dict[str, Any]:
        tokens.append(creds.token)
        if creds.token == "expired":
            raise ConnectorError("invalid_credentials", "Expired")
        return await original(self, creds, node, offset)

    monkeypatch.setattr(TreeConnector, "exchange_code", exchange)
    monkeypatch.setattr(TreeConnector, "refresh_credentials", refresh)
    monkeypatch.setattr(TreeConnector, "list_document_tree", listing)
    path = await path_for(client, alice_headers)
    assert (await client.get(path, headers=alice_headers)).status_code == 200
    assert tokens == ["expired", "renewed"]


async def test_tree_account_caches_are_isolated(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.connectors.contracts import AccountInfo

    first = await path_for(client, alice_headers)
    await client.get(first, headers=alice_headers)

    async def validate(self: TreeConnector, creds: Credentials) -> AccountInfo:
        return AccountInfo(external_id="other-account", login="other")

    monkeypatch.setattr(TreeConnector, "validate_credentials", validate)
    second = await path_for(client, bob_headers)
    response = await client.get(second, params={"cache_only": True}, headers=bob_headers)
    assert response.status_code == 409
    assert TreeConnector.calls == [("root", 0)]


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"items": "bad", "next_offset": None},
        {
            "items": [{"id": DOCUMENT, "name": "Bad", "kind": "folder", "node": None}],
            "next_offset": None,
        },
        {"items": [], "next_offset": 0},
    ],
)
@pytest.mark.parametrize("cache_only", [True, False])
async def test_malformed_cached_tree_is_rejected(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    value: Any,
    cache_only: bool,
) -> None:
    path = await path_for(client, alice_headers)
    await client.get(path, headers=alice_headers)
    cache = app.state.integration_cache
    key = cache.payload_key("onshape", "42", "root", "0", "document-tree")
    entry = await cache.get(key)
    entry["value"] = value
    await cache.put(key, entry, cache.listing_ttl_seconds)
    response = await client.get(path, params={"cache_only": cache_only}, headers=alice_headers)
    assert response.status_code == (409 if cache_only else 502)
    assert TreeConnector.calls == [("root", 0)]
    assert await cache.get(key) is None


async def test_concurrent_tree_loads_share_one_provider_call(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
) -> None:
    import asyncio

    path = await path_for(client, alice_headers)
    responses = await asyncio.gather(*(client.get(path, headers=alice_headers) for _ in range(3)))
    assert all(response.status_code == 200 for response in responses)
    assert TreeConnector.calls == [("root", 0)]
    app.state.integration_cache.listing_refresh_cooldown_seconds = 0
    refreshed = await client.get(path, params={"refresh": True}, headers=alice_headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["meta"]["cached"] is False
    assert TreeConnector.calls == [("root", 0), ("root", 0)]
