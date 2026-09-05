"""SOLUSDEV-241 (I1) — the connection model.

OAuth binds at ACCOUNT scope (Home); documents are selected per PROJECT
(Workspace). One grant, many projects; one document, many projects; one
integration cache shared by everyone holding that account's credentials.

Every test here drives the real routes with network-free connectors, and the
acceptance criteria are asserted as COUNTS on the fake lister — "listing costs
zero calls after the first" is measured, never claimed.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from conftest import ALICE, BOB, FakeGitHub, add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.contracts import Credentials
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.secrets import SecretNotFoundError


class _CountingAccountLevel(FakeGitHub):  # type: ignore[misc]  # conftest follow_imports=skip
    """An ACCOUNT-level connector (Onshape's shape) whose picker COUNTS every
    upstream listing it performs — the instrument behind the zero-call claims."""

    provider = "onshape"
    selection = {"mode": "multi", "config_key": "documents", "label": "document"}
    listings: ClassVar[int] = 0

    def validate_selection(self, ids: list[str]) -> None:
        # The real connector's rule, so the route's dispatch is what is tested.
        from solus_api.connectors.onshape import tracked_document_ids

        tracked_document_ids({"documents": ids})

    async def list_selectable(self, creds: Credentials) -> list[dict[str, Any]]:
        type(self).listings += 1
        return [
            {"id": "dA", "name": "Rover chassis", "subtitle": "Ada"},
            {"id": "dB", "name": "Gripper", "subtitle": "Ada"},
        ]


@pytest.fixture(autouse=True)
def _install_fakes(app: FastAPI, fake_registry: ConnectorRegistry) -> None:
    _CountingAccountLevel.listings = 0
    fake_registry.register("onshape", _CountingAccountLevel)
    app.state.connector_registry = fake_registry


async def _project(client: AsyncClient, headers: dict[str, str], name: str = "Rover") -> str:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"], name=name)
    project_id: str = project["id"]
    return project_id


async def _connect_account(
    client: AsyncClient, headers: dict[str, str], provider: str = "onshape"
) -> dict[str, Any]:
    """The Home flow: authorize with no project, then exchange."""
    await me(client, headers)
    start = await client.post(
        f"/api/v1/integrations/{provider}/oauth/start", json={}, headers=headers
    )
    assert start.status_code == 201, start.text
    started = start.json()["data"]
    assert started["source_id"] is None
    exchange = await client.post(
        f"/api/v1/integrations/{provider}/oauth/exchange",
        json={"state": started["state"], "code": "good"},
        headers=headers,
    )
    assert exchange.status_code == 200, exchange.text
    data: dict[str, Any] = exchange.json()["data"]
    return data


async def _bind(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    connection_id: str,
    provider: str = "onshape",
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": provider, "name": "cad", "connection_id": connection_id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def _connections(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    resp = await client.get("/api/v1/users/me/connections", headers=headers)
    assert resp.status_code == 200, resp.text
    data: list[dict[str, Any]] = resp.json()["data"]
    return data


# ----------------------------------------------------------- account scope


async def test_home_oauth_start_needs_no_project(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    resp = await client.post(
        "/api/v1/integrations/onshape/oauth/start", json={}, headers=alice_headers
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["connection_id"]
    assert data["source_id"] is None
    assert data["state"] in data["authorize_url"]
    # A handshake that has not completed is scaffolding, not an account.
    assert await _connections(client, alice_headers) == []


async def test_exchange_connects_the_account_and_never_leaks_secrets(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    data = await _connect_account(client, alice_headers)
    assert data["source"] is None
    connection = data["connection"]
    assert connection["status"] == "connected"
    assert connection["provider"] == "onshape"
    assert connection["account_login"] == "octocat"
    assert connection["projects"] == []
    for forbidden in ("token", "secret_ref", "refresh_token"):
        assert forbidden not in connection

    listed = await _connections(client, alice_headers)
    assert [c["id"] for c in listed] == [connection["id"]]


async def test_reauthorizing_the_same_account_reuses_one_connection(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    first = await _connect_account(client, alice_headers)
    second = await _connect_account(client, alice_headers)
    assert first["connection"]["id"] == second["connection"]["id"]
    assert len(await _connections(client, alice_headers)) == 1


async def test_project_start_binds_the_source_to_the_account(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """The wizard's path is unchanged: start WITH a project, get a source back
    — but the grant now lands on an account connection the source references."""
    project_id = await _project(client, alice_headers)
    start = await client.post(
        "/api/v1/integrations/onshape/oauth/start",
        json={"project_id": project_id},
        headers=alice_headers,
    )
    assert start.status_code == 201, start.text
    started = start.json()["data"]
    assert started["source_id"] and started["connection_id"]

    exchange = await client.post(
        "/api/v1/integrations/onshape/oauth/exchange",
        json={"state": started["state"], "code": "good"},
        headers=alice_headers,
    )
    assert exchange.status_code == 200, exchange.text
    data = exchange.json()["data"]
    assert data["source"]["id"] == started["source_id"]
    assert data["source"]["status"] == "connected"
    assert data["source"]["connection_id"] == started["connection_id"]
    assert data["connection"]["projects"] == [{"project_id": project_id, "name": "Rover"}]


async def test_web_callback_redirects_with_the_connection(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    start = await client.post(
        "/api/v1/integrations/github/oauth/start", json={}, headers=alice_headers
    )
    state = start.json()["data"]["state"]
    resp = await client.get(
        "/api/v1/integrations/github/oauth/callback", params={"code": "good", "state": state}
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "solus_connect=connected" in location
    assert "connection_id=" in location
    assert "source_id" not in location


# ----------------------------------------------------------- sharing a grant


async def test_two_projects_share_one_account_without_a_second_oauth(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    project_a = await _project(client, alice_headers, name="Rover")
    project_b = await _project(client, alice_headers, name="Arm")

    source_a = await _bind(client, alice_headers, project_a, connection["id"])
    source_b = await _bind(client, alice_headers, project_b, connection["id"])

    assert source_a["status"] == source_b["status"] == "connected"
    assert source_a["account_login"] == source_b["account_login"] == "octocat"
    assert source_a["connection_id"] == source_b["connection_id"] == connection["id"]
    listed = await _connections(client, alice_headers)
    assert {p["name"] for p in listed[0]["projects"]} == {"Rover", "Arm"}


async def test_binding_the_same_account_twice_in_one_project_reuses_the_source(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    project_id = await _project(client, alice_headers)
    first = await _bind(client, alice_headers, project_id, connection["id"])
    second = await _bind(client, alice_headers, project_id, connection["id"])
    assert first["id"] == second["id"]


async def test_binding_refuses_a_provider_mismatch_and_a_token(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    project_id = await _project(client, alice_headers)
    mismatch = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "github", "name": "fw", "connection_id": connection["id"]},
        headers=alice_headers,
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "connection_mismatch"
    both = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={
            "type": "onshape",
            "name": "cad",
            "connection_id": connection["id"],
            "token": "tok",
        },
        headers=alice_headers,
    )
    assert both.status_code == 400


# ----------------------------------------------------------- tenancy


async def test_connections_are_owner_only(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    await me(client, bob_headers)
    assert await _connections(client, bob_headers) == []
    docs = await client.get(
        f"/api/v1/users/me/connections/{connection['id']}/documents", headers=bob_headers
    )
    assert docs.status_code == 404
    revoke = await client.delete(
        f"/api/v1/users/me/connections/{connection['id']}", headers=bob_headers
    )
    assert revoke.status_code == 404
    # Still there for its owner.
    assert len(await _connections(client, alice_headers)) == 1


async def test_a_teammate_cannot_bind_someone_elses_account(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """Membership on the project does not make Alice's grant Bob's to bind —
    only the account's owner attaches it; teammates use it through the source."""
    connection = (await _connect_account(client, alice_headers))["connection"]
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/sources",
        json={"type": "onshape", "name": "cad", "connection_id": connection["id"]},
        headers=bob_headers,
    )
    assert resp.status_code == 404


async def test_a_teammate_uses_the_shared_grant_through_the_source(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    source = await _bind(client, alice_headers, project["id"], connection["id"])
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])

    picker = await client.get(
        f"/api/v1/projects/{project['id']}/sources/{source['id']}/selectable",
        headers=bob_headers,
    )
    assert picker.status_code == 200, picker.text
    assert {d["id"] for d in picker.json()["data"]} == {"dA", "dB"}
    sync = await client.post(
        f"/api/v1/projects/{project['id']}/sources/{source['id']}/sync", headers=bob_headers
    )
    assert sync.status_code == 202, sync.text


# ----------------------------------------------------------- revocation


async def test_revoke_disconnects_every_bound_source_and_deletes_the_secret(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    project_a = await _project(client, alice_headers, name="Rover")
    project_b = await _project(client, alice_headers, name="Arm")
    source_a = await _bind(client, alice_headers, project_a, connection["id"])
    source_b = await _bind(client, alice_headers, project_b, connection["id"])

    resp = await client.delete(
        f"/api/v1/users/me/connections/{connection['id']}", headers=alice_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["disconnected_sources"] == 2
    assert await _connections(client, alice_headers) == []

    for project_id, source in ((project_a, source_a), (project_b, source_b)):
        detail = await client.get(
            f"/api/v1/projects/{project_id}/sources/{source['id']}", headers=alice_headers
        )
        assert detail.json()["data"]["status"] == "disconnected"
        assert detail.json()["data"]["connection_id"] is None
        sync = await client.post(
            f"/api/v1/projects/{project_id}/sources/{source['id']}/sync", headers=alice_headers
        )
        assert sync.status_code == 409

    store = app.state.secret_store
    with pytest.raises(SecretNotFoundError):
        await store.get(f"connection/{connection['id']}/onshape")
    with pytest.raises(SecretNotFoundError):
        await store.get(f"connection/{connection['id']}/onshape/refresh")


async def test_disconnecting_one_source_keeps_the_shared_grant(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    project_a = await _project(client, alice_headers, name="Rover")
    project_b = await _project(client, alice_headers, name="Arm")
    source_a = await _bind(client, alice_headers, project_a, connection["id"])
    source_b = await _bind(client, alice_headers, project_b, connection["id"])

    gone = await client.delete(
        f"/api/v1/projects/{project_a}/sources/{source_a['id']}", headers=alice_headers
    )
    assert gone.status_code == 200, gone.text

    # The grant survives: the other project still syncs and the account is
    # still listed, now used by one project.
    assert await app.state.secret_store.get(f"connection/{connection['id']}/onshape")
    sync = await client.post(
        f"/api/v1/projects/{project_b}/sources/{source_b['id']}/sync", headers=alice_headers
    )
    assert sync.status_code == 202, sync.text
    listed = await _connections(client, alice_headers)
    assert [p["name"] for p in listed[0]["projects"]] == ["Arm"]


async def test_deleting_the_account_sweeps_connection_secrets(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    ref = f"connection/{connection['id']}/onshape"
    assert await app.state.secret_store.get(ref)
    resp = await client.delete("/api/v1/users/me", headers=alice_headers)
    assert resp.status_code == 204, resp.text
    with pytest.raises(SecretNotFoundError):
        await app.state.secret_store.get(ref)


# ----------------------------------------------------------- the listing cache


async def test_listing_documents_costs_zero_calls_after_the_first(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    # This test is about the cache, not the refresh cooldown (covered below).
    app.state.integration_cache.listing_refresh_cooldown_seconds = 0
    connection = (await _connect_account(client, alice_headers))["connection"]
    path = f"/api/v1/users/me/connections/{connection['id']}/documents"

    first = await client.get(path, headers=alice_headers)
    assert first.status_code == 200, first.text
    assert {d["id"] for d in first.json()["data"]} == {"dA", "dB"}
    assert first.json()["meta"]["cached"] is False
    assert _CountingAccountLevel.listings == 1

    second = await client.get(path, headers=alice_headers)
    assert second.json()["data"] == first.json()["data"]
    assert second.json()["meta"]["cached"] is True
    assert second.json()["meta"]["fetched_at"] == first.json()["meta"]["fetched_at"]
    assert _CountingAccountLevel.listings == 1, "a repeat listing reached the provider"

    refreshed = await client.get(path, params={"refresh": "true"}, headers=alice_headers)
    assert refreshed.json()["meta"]["cached"] is False
    assert _CountingAccountLevel.listings == 2


async def test_the_project_picker_shares_the_account_listing(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Home listed the account once; the Workspace picker, on ANY project bound
    to that account, is served from the same entry."""
    connection = (await _connect_account(client, alice_headers))["connection"]
    await client.get(
        f"/api/v1/users/me/connections/{connection['id']}/documents", headers=alice_headers
    )
    project_a = await _project(client, alice_headers, name="Rover")
    project_b = await _project(client, alice_headers, name="Arm")
    for project_id in (project_a, project_b):
        source = await _bind(client, alice_headers, project_id, connection["id"])
        picker = await client.get(
            f"/api/v1/projects/{project_id}/sources/{source['id']}/selectable",
            headers=alice_headers,
        )
        assert picker.status_code == 200, picker.text
        assert picker.json()["meta"]["cached"] is True
    assert _CountingAccountLevel.listings == 1


# ----------------------------------------------------------- per-project documents


async def test_add_and_remove_a_document_on_a_project(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    project_id = await _project(client, alice_headers)
    source = await _bind(client, alice_headers, project_id, connection["id"])
    base = f"/api/v1/projects/{project_id}/sources/{source['id']}/documents"

    added = await client.post(base, json={"id": "dB"}, headers=alice_headers)
    assert added.status_code == 202, added.text
    assert added.json()["data"]["job_id"]
    assert added.json()["data"]["source"]["config"]["documents"] == ["dB"]
    assert added.headers["Location"].startswith("/api/v1/jobs/")

    # Idempotent: already tracked means nothing to sync.
    again = await client.post(base, json={"id": "dB"}, headers=alice_headers)
    assert again.status_code == 200, again.text
    assert again.json()["data"]["job_id"] is None
    assert again.json()["data"]["status"] == "unchanged"

    more = await client.post(base, json={"id": "dA"}, headers=alice_headers)
    assert more.status_code == 202
    assert more.json()["data"]["source"]["config"]["documents"] == ["dB", "dA"]

    removed = await client.delete(f"{base}/dB", headers=alice_headers)
    assert removed.status_code == 202, removed.text
    assert removed.json()["data"]["source"]["config"]["documents"] == ["dA"]

    missing = await client.delete(f"{base}/dB", headers=alice_headers)
    assert missing.status_code == 404


async def test_document_routes_validate_ids_and_the_connector_shape(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    project_id = await _project(client, alice_headers)
    source = await _bind(client, alice_headers, project_id, connection["id"])
    base = f"/api/v1/projects/{project_id}/sources/{source['id']}/documents"

    bad = await client.post(base, json={"id": "../etc"}, headers=alice_headers)
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "config_invalid"

    # A single-selection connector (a repository source) has no document list.
    github = (await _connect_account(client, alice_headers, provider="github"))["connection"]
    repo = await _bind(client, alice_headers, project_id, github["id"], provider="github")
    unsupported = await client.post(
        f"/api/v1/projects/{project_id}/sources/{repo['id']}/documents",
        json={"id": "octocat/strider-fw"},
        headers=alice_headers,
    )
    assert unsupported.status_code == 400
    assert unsupported.json()["error"]["code"] == "unsupported"


async def test_document_routes_are_project_scoped(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    connection = (await _connect_account(client, alice_headers))["connection"]
    project_id = await _project(client, alice_headers)
    source = await _bind(client, alice_headers, project_id, connection["id"])
    await me(client, bob_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources/{source['id']}/documents",
        json={"id": "dB"},
        headers=bob_headers,
    )
    assert resp.status_code == 404


async def test_alice_identity_is_the_provisioned_user(alice_headers: dict[str, str]) -> None:
    """Guard the fixture assumption the tenancy tests above rely on."""
    assert ALICE["email"].startswith("alice")


# ----------------------------------------------------------- security review (I1)


async def test_a_stale_handshake_cannot_repoint_a_connected_account(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Two starts inside the reuse window share one pending row. Once the
    second completes, the first (still valid) state must be REFUSED — never
    allowed to overwrite the account the bound sources now mirror."""
    project_a = await _project(client, alice_headers, name="Rover")
    project_b = await _project(client, alice_headers, name="Arm")
    first = (
        await client.post(
            "/api/v1/integrations/onshape/oauth/start",
            json={"project_id": project_a},
            headers=alice_headers,
        )
    ).json()["data"]
    second = (
        await client.post(
            "/api/v1/integrations/onshape/oauth/start",
            json={"project_id": project_b},
            headers=alice_headers,
        )
    ).json()["data"]
    assert first["connection_id"] == second["connection_id"]

    done = await client.post(
        "/api/v1/integrations/onshape/oauth/exchange",
        json={"state": second["state"], "code": "good"},
        headers=alice_headers,
    )
    assert done.status_code == 200, done.text

    stale = await client.post(
        "/api/v1/integrations/onshape/oauth/exchange",
        json={"state": first["state"], "code": "good"},
        headers=alice_headers,
    )
    assert stale.status_code == 400
    assert stale.json()["error"]["code"] == "stale_handshake"
    # The account is untouched and still bound exactly as the winner left it.
    listed = await _connections(client, alice_headers)
    assert [c["status"] for c in listed] == ["connected"]
    assert [p["name"] for p in listed[0]["projects"]] == ["Arm"]


async def test_deleting_the_account_disconnects_sources_in_surviving_teams(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """Bob owns the team; Alice links her account and attaches Bob's project to
    it, then deletes her account. Bob's project must show the source
    DISCONNECTED — not CONNECTED on a ref whose secret is gone."""
    await me(client, bob_headers)
    team = await create_team(client, bob_headers)
    project = await create_project(client, bob_headers, team["id"])
    await me(client, alice_headers)
    await add_member(client, bob_headers, alice_headers, ALICE, team["id"])
    connection = (await _connect_account(client, alice_headers))["connection"]
    source = await _bind(client, alice_headers, project["id"], connection["id"])

    gone = await client.delete("/api/v1/users/me", headers=alice_headers)
    assert gone.status_code == 204, gone.text

    detail = await client.get(
        f"/api/v1/projects/{project['id']}/sources/{source['id']}", headers=bob_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["status"] == "disconnected"
    assert detail.json()["data"]["connection_id"] is None


async def test_listing_refresh_is_cooled_down_per_account(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """A refresh button held down — by anyone on the grant — buys one provider
    walk per cooldown window, not one per click."""
    connection = (await _connect_account(client, alice_headers))["connection"]
    path = f"/api/v1/users/me/connections/{connection['id']}/documents"
    await client.get(path, headers=alice_headers)
    assert _CountingAccountLevel.listings == 1
    for _ in range(5):
        resp = await client.get(path, params={"refresh": "true"}, headers=alice_headers)
        assert resp.status_code == 200
        assert resp.json()["meta"]["cached"] is True
    assert _CountingAccountLevel.listings == 1, "refresh inside the cooldown reached the provider"


async def test_access_cannot_be_patched_onto_a_source(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """The grant is the connection's; `source.config.access` is a mirror, never
    a member-editable setting."""
    connection = (await _connect_account(client, alice_headers))["connection"]
    project_id = await _project(client, alice_headers)
    source = await _bind(client, alice_headers, project_id, connection["id"])
    resp = await client.patch(
        f"/api/v1/projects/{project_id}/sources/{source['id']}",
        json={"config": {"access": "write", "documents": ["dA"]}},
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text
    config = resp.json()["data"]["config"]
    assert config.get("documents") == ["dA"]
    assert config.get("access") != "write"
