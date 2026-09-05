"""Integration tests for §2.5 Integrations — catalog + the GitHub OAuth
handshake, including CSRF-state rejection and exchange-failure handling."""

from typing import Any

import pytest
from conftest import FakeGitHub, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.registry import ConnectorRegistry


class _FakeAccountLevel(FakeGitHub):  # type: ignore[misc]  # conftest follow_imports=skip
    """An ACCOUNT-level connector (Onshape and every CAD tool after it): one
    grant covers the whole account and the tracked set lives in that source's
    config, so a second source for the same provider is only ever a duplicate."""

    provider = "onshape"
    selection = {"mode": "multi", "config_key": "documents", "label": "document"}


@pytest.fixture(autouse=True)
def _install_fake_github(app: FastAPI, fake_registry: ConnectorRegistry) -> None:
    fake_registry.register("onshape", _FakeAccountLevel)
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


async def _start_provider(
    client: AsyncClient, headers: dict[str, str], project_id: str, provider: str
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/integrations/{provider}/oauth/start",
        json={"project_id": project_id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def _source_ids(client: AsyncClient, headers: dict[str, str], project_id: str) -> list[str]:
    resp = await client.get(f"/api/v1/projects/{project_id}/sources", headers=headers)
    assert resp.status_code == 200, resp.text
    return [s["id"] for s in resp.json()["data"]]


async def test_reconnecting_an_account_level_provider_reuses_one_source(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Retrying a connect used to mint a fresh source every time, so each attempt
    that reached the provider left another duplicate of the same account behind."""
    project_id = await _project(client, alice_headers)

    first = await _start_provider(client, alice_headers, project_id, "onshape")
    second = await _start_provider(client, alice_headers, project_id, "onshape")

    assert first["source_id"] == second["source_id"]
    assert len(await _source_ids(client, alice_headers, project_id)) == 1


async def test_repo_level_providers_still_get_a_source_each(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """The other half: a GitHub source names ONE repository, so two sources in a
    project is a legitimate setup and must never be collapsed."""
    project_id = await _project(client, alice_headers)

    first = await _start(client, alice_headers, project_id)
    second = await _start(client, alice_headers, project_id)

    assert first["source_id"] != second["source_id"]
    assert len(await _source_ids(client, alice_headers, project_id)) == 2


async def test_catalog_lists_github(client: AsyncClient, alice_headers: dict[str, str]) -> None:
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
    # SOLUSDEV-241: the exchange lands on an ACCOUNT connection; the project's
    # source rides beside it when the handshake started from a project.
    payload = exchange.json()["data"]
    source = payload["source"]
    assert source["status"] == "connected"
    assert source["account_login"] == "octocat"
    assert source["connection_id"] == payload["connection"]["id"]
    assert payload["connection"]["status"] == "connected"


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


# ── SOLUSDEV-72: bridge-hosted local tools (the generic Fusion-tile source) ─────


async def test_local_tools_lists_vendor_run_loopback_servers(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    resp = await client.get("/api/v1/integrations/local-tools", headers=alice_headers)
    assert resp.status_code == 200, resp.text
    tools = resp.json()["data"]
    by_type = {t["type"]: t for t in tools}
    # Fusion is the one vendor-run loopback server today; the next tool appears
    # here by catalog entry alone — zero frontend edits.
    fusion = by_type["fusion"]
    assert fusion["display_name"] == "Fusion"
    assert fusion["hosting"] == "vendor-run"
    assert fusion["url_host"] == "127.0.0.1:27182"
    assert fusion["requires"] == "companion"
    assert "licen" in fusion["connect_notice"].lower()
    # Command-launched forks (kicad, altium…) are NOT local-bridge tiles.
    assert "kicad" not in by_type and "web_search" not in by_type


async def test_local_tools_requires_authentication(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/integrations/local-tools")
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://127.0.0.1:53682/auth/callback?solus_cb=abc",
        "http://localhost:53682/auth/callback",
        "http://localhost:5173/auth/callback",
    ],
)
async def test_oauth_start_keeps_the_loopback_redirects_for_dev(
    client: AsyncClient, alice_headers: dict[str, str], redirect_uri: str
) -> None:
    """SOLUSDEV-242 (H2) pins the allowlist: both loopback hosts, any port —
    the desktop's loopback flow and the dev renderer depend on them."""
    await me(client, alice_headers)
    resp = await client.post(
        "/api/v1/integrations/github/oauth/start",
        json={"redirect_uri": redirect_uri},
        headers=alice_headers,
    )
    assert resp.status_code == 201, resp.text
    assert redirect_uri.split("?")[0] in resp.json()["data"]["authorize_url"].replace(
        "%3A", ":"
    ).replace("%2F", "/")
