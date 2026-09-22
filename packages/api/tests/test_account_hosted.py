"""Account-owned hosted grants: owner binding, atomic exchange and live revocation."""

import asyncio
import uuid
from typing import Any

import pytest
from conftest import BOB, add_member
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools.hosted_tools import SourceHostedAuth, load_hosted_inventory
from solus_api.agent.tools.remote_mcp import FS_MCP, RemoteAuthError
from solus_api.connectors import hosted_oauth
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.secrets import SecretNotFoundError
from solus_api.models import AccountConnection, ConnectionStatus
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_connections import _bind, _connect_account, _CountingAccountLevel, _project
from test_hosted_routes import _install_fake_server

SERVER = FS_MCP.name


@pytest.fixture(autouse=True)
def install(
    app: FastAPI, fake_registry: ConnectorRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_registry.register("onshape", _CountingAccountLevel)
    app.state.connector_registry = fake_registry
    _install_fake_server(monkeypatch, ["get_featurescript", "put_featurescript", "logout"])


async def account(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    return (await _connect_account(client, headers))["connection"]


def base(connection: dict[str, Any]) -> str:
    return f"/api/v1/users/me/connections/{connection['id']}/hosted/{SERVER}"


async def enable(
    client: AsyncClient, headers: dict[str, str], connection: dict[str, Any]
) -> dict[str, Any]:
    path = base(connection)
    start = await client.post(f"{path}/oauth/start", headers=headers)
    assert start.status_code == 201, start.text
    body = start.json()["data"]
    response = await client.post(
        f"{path}/oauth/exchange", json={"state": body["state"], "code": "code"}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_account_status_and_enable_are_owner_only(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    unverified_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    connection = await account(client, alice_headers)
    path = base(connection)
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=bob_headers)).status_code == 404
    assert (await client.post(f"{path}/oauth/start", headers=unverified_headers)).status_code == 403
    status = await client.get(path, headers=alice_headers)
    assert status.status_code == 200, status.text
    assert status.json()["data"]["state"] == "not_enabled"
    assert (await enable(client, alice_headers, connection))["tool_count"] == 2
    row = await db.get(AccountConnection, uuid.UUID(connection["id"]))
    assert row is not None
    assert len(row.config["_hosted"][SERVER]["tools"]) == 2
    for forbidden in ("secret_ref", "access_token", "client_secret", "code_verifier"):
        assert forbidden not in (await client.get(path, headers=alice_headers)).text


async def test_account_hosted_refuses_wrong_provider_unknown_server_and_strict_body(
    client: AsyncClient,
    alice_headers: dict[str, str],
) -> None:
    github = (await _connect_account(client, alice_headers, "github"))["connection"]
    assert (await client.get(base(github), headers=alice_headers)).status_code == 400
    connection = await account(client, alice_headers)
    assert (
        await client.get(base(connection).replace(SERVER, "unknown"), headers=alice_headers)
    ).status_code == 404
    response = await client.post(
        f"{base(connection)}/oauth/exchange",
        json={"state": "s", "code": "c", "redirect_uri": "https://evil.invalid"},
        headers=alice_headers,
    )
    assert response.status_code == 422


async def test_one_account_grant_serves_two_sources_and_survives_one_source_deletion(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    connection = await account(client, alice_headers)
    await enable(client, alice_headers, connection)
    first = await _project(client, alice_headers, "First")
    second = await _project(client, alice_headers, "Second")
    source_a = await _bind(client, alice_headers, first, connection["id"])
    await _bind(client, alice_headers, second, connection["id"])
    for project in (first, second):
        inventory = await load_hosted_inventory(db, uuid.UUID(project))
        assert SERVER in inventory
        listing = await client.get(f"/api/v1/projects/{project}/sol/tools", headers=alice_headers)
        assert f"{SERVER}.put_featurescript" in {tool["name"] for tool in listing.json()["data"]}
    row = await db.get(AccountConnection, uuid.UUID(connection["id"]))
    assert row is not None
    ref = hosted_oauth.token_secret_ref(row.secret_ref or "", SERVER)
    assert await app.state.secret_store.get(ref)
    assert (
        await client.delete(
            f"/api/v1/projects/{first}/sources/{source_a['id']}", headers=alice_headers
        )
    ).status_code == 200
    assert await app.state.secret_store.get(ref)
    assert SERVER in await load_hosted_inventory(db, uuid.UUID(second))
    assert (
        await client.delete(
            f"/api/v1/users/me/connections/{connection['id']}", headers=alice_headers
        )
    ).status_code == 200
    with pytest.raises(SecretNotFoundError):
        await app.state.secret_store.get(ref)
    db.expire_all()
    assert await load_hosted_inventory(db, uuid.UUID(second)) == {}


async def test_teammate_can_read_account_source_status_but_cannot_change_grant(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    connection = await account(client, alice_headers)
    await enable(client, alice_headers, connection)
    project = await _project(client, alice_headers)
    source = await _bind(client, alice_headers, project, connection["id"])
    from conftest import me
    from solus_api.models import Role

    await me(client, bob_headers)
    project_row = (await client.get(f"/api/v1/projects/{project}", headers=alice_headers)).json()[
        "data"
    ]
    await add_member(
        client, alice_headers, bob_headers, BOB, project_row["team_id"], role=Role.MEMBER.value
    )
    path = f"/api/v1/projects/{project}/sources/{source['id']}/hosted/{SERVER}"
    response = await client.get(path, headers=bob_headers)
    assert response.status_code == 200
    assert response.json()["data"]["state"] == "ready"
    for suffix in ("probe", "oauth/start"):
        assert (await client.post(f"{path}/{suffix}", headers=bob_headers)).status_code == 404


async def test_concurrent_exchange_consumes_state_before_one_vendor_call(
    client: AsyncClient,
    alice_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await account(client, alice_headers)
    path = base(connection)
    start = await client.post(f"{path}/oauth/start", headers=alice_headers)
    assert start.status_code == 201, start.text
    state = start.json()["data"]["state"]
    entered, release = asyncio.Event(), asyncio.Event()
    original = hosted_oauth.exchange_code
    calls = 0

    async def exchange(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(hosted_oauth, "exchange_code", exchange)
    first = asyncio.create_task(
        client.post(
            f"{path}/oauth/exchange", json={"state": state, "code": "c"}, headers=alice_headers
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        second = await client.post(
            f"{path}/oauth/exchange", json={"state": state, "code": "c"}, headers=alice_headers
        )
        assert second.status_code == 404
    finally:
        release.set()
    assert (await first).status_code == 200
    assert calls == 1


async def test_revoke_during_exchange_cannot_restore_hosted_credentials(
    client: AsyncClient,
    alice_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    app: FastAPI,
    db: AsyncSession,
) -> None:
    connection = await account(client, alice_headers)
    path = base(connection)
    start = await client.post(f"{path}/oauth/start", headers=alice_headers)
    assert start.status_code == 201, start.text
    row = await db.get(AccountConnection, uuid.UUID(connection["id"]))
    assert row is not None
    ref = hosted_oauth.token_secret_ref(row.secret_ref or "", SERVER)
    original = hosted_oauth.exchange_code

    async def exchange(*args: Any, **kwargs: Any) -> Any:
        response = await client.delete(
            f"/api/v1/users/me/connections/{connection['id']}", headers=alice_headers
        )
        assert response.status_code == 200
        return await original(*args, **kwargs)

    monkeypatch.setattr(hosted_oauth, "exchange_code", exchange)
    response = await client.post(
        f"{path}/oauth/exchange",
        json={"state": start.json()["data"]["state"], "code": "c"},
        headers=alice_headers,
    )
    assert response.status_code == 404
    with pytest.raises(SecretNotFoundError):
        await app.state.secret_store.get(ref)


async def test_invocation_rechecks_account_even_if_source_still_claims_connected(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    connection = await account(client, alice_headers)
    await enable(client, alice_headers, connection)
    project = await _project(client, alice_headers)
    await _bind(client, alice_headers, project, connection["id"])
    auth = SourceHostedAuth(
        session_factory=async_sessionmaker(db.bind, expire_on_commit=False),
        project_id=uuid.UUID(project),
        spec=FS_MCP,
        secret_store=app.state.secret_store,
    )
    assert "Authorization" in await auth.headers()
    row = await db.get(AccountConnection, uuid.UUID(connection["id"]))
    assert row is not None
    row.status = ConnectionStatus.REVOKED
    await db.commit()
    with pytest.raises(RemoteAuthError):
        await auth.headers()
    assert await load_hosted_inventory(db, uuid.UUID(project)) == {}


@pytest.mark.parametrize("code", ["reconnect_required", "scope_escalation", "not_enabled"])
async def test_permanent_grant_failure_clears_cached_readiness(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    connection = await account(client, alice_headers)
    await enable(client, alice_headers, connection)
    project = await _project(client, alice_headers)
    await _bind(client, alice_headers, project, connection["id"])
    auth = SourceHostedAuth(
        session_factory=async_sessionmaker(db.bind, expire_on_commit=False),
        project_id=uuid.UUID(project),
        spec=FS_MCP,
        secret_store=app.state.secret_store,
    )

    async def refuse(_ref: str) -> dict[str, str]:
        raise RemoteAuthError(code, "vendor credential text must not be stored")

    monkeypatch.setattr(auth, "_token_headers", refuse)
    with pytest.raises(RemoteAuthError):
        await auth.headers()
    status = (await client.get(base(connection), headers=alice_headers)).json()["data"]
    assert status["state"] == "not_enabled"
    assert status["tool_count"] == 0
    assert "Reconnect" in status["detail"]
    assert "vendor credential" not in status["detail"]
    db.expire_all()
    assert await load_hosted_inventory(db, uuid.UUID(project)) == {}


async def test_expired_state_is_consumed_and_wrong_account_cannot_claim_it(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    from datetime import timedelta

    from solus_api.models import OAuthState, utcnow

    connection = await account(client, alice_headers)
    start = (await client.post(f"{base(connection)}/oauth/start", headers=alice_headers)).json()[
        "data"
    ]
    row = await db.get(AccountConnection, uuid.UUID(connection["id"]))
    assert row is not None
    other = AccountConnection(
        user_id=row.user_id,
        provider=row.provider,
        status=ConnectionStatus.CONNECTED,
        secret_ref="connection/other/onshape",
        account_external_id="other",
    )
    db.add(other)
    await db.commit()
    wrong = await client.post(
        f"{base({'id': str(other.id)})}/oauth/exchange",
        json={"state": start["state"], "code": "c"},
        headers=alice_headers,
    )
    assert wrong.status_code == 404
    state = await db.get(OAuthState, start["state"])
    assert state is not None
    state.expires_at = utcnow() - timedelta(minutes=1)
    await db.commit()
    expired = await client.post(
        f"{base(connection)}/oauth/exchange",
        json={"state": start["state"], "code": "c"},
        headers=alice_headers,
    )
    assert expired.status_code == 400
    assert expired.json()["error"]["code"] == "expired_state"
    db.expire_all()
    assert await db.get(OAuthState, start["state"]) is None


async def test_source_alias_stores_state_only_on_account_and_status_is_offline(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.models import Source

    connection = await account(client, alice_headers)
    project = await _project(client, alice_headers)
    source = await _bind(client, alice_headers, project, connection["id"])
    path = f"/api/v1/projects/{project}/sources/{source['id']}/hosted/{SERVER}"
    start = (await client.post(f"{path}/oauth/start", headers=alice_headers)).json()["data"]
    done = await client.post(
        f"{path}/oauth/exchange", json={"state": start["state"], "code": "c"}, headers=alice_headers
    )
    assert done.status_code == 200
    assert (await client.post(f"{base(connection)}/probe", headers=alice_headers)).json()["data"][
        "state"
    ] == "ready"
    db.expire_all()
    stored = await db.get(Source, uuid.UUID(source["id"]))
    assert stored is not None and "_hosted" not in stored.config and "hosted" not in stored.config

    async def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("status must not contact the vendor")

    monkeypatch.setattr(hosted_oauth, "ensure_client", forbidden)
    assert (await client.get(base(connection), headers=alice_headers)).json()["data"][
        "state"
    ] == "ready"
    assert (await client.get(path, headers=alice_headers)).json()["data"]["state"] == "ready"


async def test_user_deletion_removes_account_hosted_secret_family(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    connection = await account(client, alice_headers)
    await enable(client, alice_headers, connection)
    row = await db.get(AccountConnection, uuid.UUID(connection["id"]))
    assert row is not None
    ref = hosted_oauth.token_secret_ref(row.secret_ref or "", SERVER)
    assert await app.state.secret_store.get(ref)
    assert (await client.delete("/api/v1/users/me", headers=alice_headers)).status_code == 204
    with pytest.raises(SecretNotFoundError):
        await app.state.secret_store.get(ref)


async def test_inventory_scope_is_bound_to_same_source_at_invocation(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    from solus_api.models import Source

    connection = await account(client, alice_headers)
    await enable(client, alice_headers, connection)
    project = await _project(client, alice_headers)
    source = await _bind(client, alice_headers, project, connection["id"])
    inventory = (await load_hosted_inventory(db, uuid.UUID(project)))[SERVER]
    auth = SourceHostedAuth(
        session_factory=async_sessionmaker(db.bind, expire_on_commit=False),
        project_id=uuid.UUID(project),
        spec=FS_MCP,
        secret_store=app.state.secret_store,
        source_id=inventory["source_id"],
        connection_id=inventory["connection_id"],
    )
    assert "Authorization" in await auth.headers()
    stored = await db.get(Source, uuid.UUID(source["id"]))
    assert stored is not None
    stored.connection_id = None
    await db.commit()
    with pytest.raises(RemoteAuthError):
        await auth.headers()


async def test_revoke_waits_for_inflight_refresh_then_deletes_refreshed_token(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await account(client, alice_headers)
    await enable(client, alice_headers, connection)
    row = await db.get(AccountConnection, uuid.UUID(connection["id"]))
    assert row is not None
    ref = hosted_oauth.token_secret_ref(row.secret_ref or "", SERVER)
    await app.state.secret_store.put(
        ref, hosted_oauth.HostedToken("expired", "refresh", 0).to_json()
    )
    entered, release = asyncio.Event(), asyncio.Event()
    original = hosted_oauth.refresh_token

    async def refresh(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(hosted_oauth, "refresh_token", refresh)
    probing = asyncio.create_task(client.post(f"{base(connection)}/probe", headers=alice_headers))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        revoking = asyncio.create_task(
            client.delete(f"/api/v1/users/me/connections/{connection['id']}", headers=alice_headers)
        )
    finally:
        release.set()
    assert (await probing).status_code == 200
    assert (await revoking).status_code == 200
    with pytest.raises(SecretNotFoundError):
        await app.state.secret_store.get(ref)


async def test_foreign_account_mutations_touch_no_secrets_or_vendor_and_preserve_state(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await account(client, alice_headers)
    path = base(connection)
    start = await client.post(f"{path}/oauth/start", headers=alice_headers)
    state = start.json()["data"]["state"]

    async def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Foreign caller reached hosted credentials or vendor")

    with monkeypatch.context() as guard:
        guard.setattr(app.state.secret_store, "get", forbidden)
        guard.setattr(app.state.secret_store, "put", forbidden)
        guard.setattr(hosted_oauth, "ensure_client", forbidden)
        guard.setattr(hosted_oauth, "exchange_code", forbidden)
        for suffix in ("oauth/start", "probe", "oauth/exchange"):
            kwargs = {"json": {"state": state, "code": "c"}} if suffix == "oauth/exchange" else {}
            response = await client.post(f"{path}/{suffix}", headers=bob_headers, **kwargs)
            assert response.status_code == 404
    owner = await client.post(
        f"{path}/oauth/exchange", json={"state": state, "code": "c"}, headers=alice_headers
    )
    assert owner.status_code == 200
