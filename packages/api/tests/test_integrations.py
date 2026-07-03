"""Integration tests for §2.5 Integrations — catalog + the GitHub OAuth
handshake, including CSRF-state rejection and exchange-failure handling."""

from typing import Any

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.registry import ConnectorRegistry


@pytest.fixture(autouse=True)
def _install_fake_github(app: FastAPI, fake_registry: ConnectorRegistry) -> None:
    app.state.connector_registry = fake_registry


async def _project(client: AsyncClient, headers: dict[str, str]) -> str:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    project_id: str = project["id"]
    return project_id


async def _start(client: AsyncClient, headers: dict[str, str], project_id: str) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/integrations/github/oauth/start",
        json={"project_id": project_id, "repo": "octocat/strider-fw"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def test_catalog_lists_github(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    resp = await client.get("/api/v1/integrations", headers=alice_headers)
    assert resp.status_code == 200
    catalog = resp.json()["data"]
    github = next(c for c in catalog if c["type"] == "github")
    assert github["auth_kind"] == "oauth"
    assert "repo" in github["config_fields"]
    assert "repo" in github["scopes"]


async def test_oauth_start_creates_pending_source(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    data = await _start(client, alice_headers, project_id)
    assert "state" in data
    assert data["state"] in data["authorize_url"]
    assert "source_id" in data

    source = (
        await client.get(
            f"/api/v1/projects/{project_id}/sources/{data['source_id']}", headers=alice_headers
        )
    ).json()["data"]
    assert source["status"] == "pending"


async def test_oauth_callback_connects_source(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    data = await _start(client, alice_headers, project_id)

    resp = await client.get(
        "/api/v1/integrations/github/oauth/callback",
        params={"code": "good", "state": data["state"]},
    )
    assert resp.status_code == 302
    assert "solus_connect=connected" in resp.headers["location"]

    source = (
        await client.get(
            f"/api/v1/projects/{project_id}/sources/{data['source_id']}", headers=alice_headers
        )
    ).json()["data"]
    assert source["status"] == "connected"
    assert source["account_login"] == "octocat"


async def test_oauth_callback_rejects_unknown_state(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/integrations/github/oauth/callback",
        params={"code": "good", "state": "forged-state"},
    )
    assert resp.status_code == 302
    assert "solus_connect=invalid_state" in resp.headers["location"]


async def test_oauth_callback_handles_exchange_failure(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    data = await _start(client, alice_headers, project_id)

    resp = await client.get(
        "/api/v1/integrations/github/oauth/callback",
        params={"code": "bad-code", "state": data["state"]},
    )
    assert resp.status_code == 302
    assert "solus_connect=oauth_failed" in resp.headers["location"]

    source = (
        await client.get(
            f"/api/v1/projects/{project_id}/sources/{data['source_id']}", headers=alice_headers
        )
    ).json()["data"]
    assert source["status"] == "error"


async def test_oauth_start_unknown_provider(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    resp = await client.post(
        "/api/v1/integrations/bitbucket/oauth/start",
        json={"project_id": project_id},
        headers=alice_headers,
    )
    assert resp.status_code == 404


async def test_oauth_exchange_connects_source(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    resp = await client.post(
        "/api/v1/integrations/github/oauth/start",
        json={
            "project_id": project_id,
            "redirect_uri": "http://127.0.0.1:53682/auth/callback?solus_cb=abc",
        },
        headers=alice_headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]

    exchange = await client.post(
        "/api/v1/integrations/github/oauth/exchange",
        json={"state": data["state"], "code": "good"},
        headers=alice_headers,
    )
    assert exchange.status_code == 200, exchange.text
    source = exchange.json()["data"]
    assert source["status"] == "connected"
    assert source["account_login"] == "octocat"


async def test_oauth_exchange_rejects_foreign_state(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    data = await _start(client, alice_headers, project_id)
    await me(client, bob_headers)
    resp = await client.post(
        "/api/v1/integrations/github/oauth/exchange",
        json={"state": data["state"], "code": "good"},
        headers=bob_headers,
    )
    assert resp.status_code == 404


async def test_oauth_start_rejects_untrusted_redirect_uri(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    resp = await client.post(
        "/api/v1/integrations/github/oauth/start",
        json={"project_id": project_id, "redirect_uri": "https://evil.example.com/steal"},
        headers=alice_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_redirect_uri"


async def test_oauth_start_requires_membership(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    await me(client, bob_headers)
    resp = await client.post(
        "/api/v1/integrations/github/oauth/start",
        json={"project_id": project_id},
        headers=bob_headers,
    )
    assert resp.status_code == 404
