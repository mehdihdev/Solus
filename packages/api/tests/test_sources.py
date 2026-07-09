"""Integration tests for §2.5 Sources — connect/sync/disconnect, the repo
picker, sync history, secret non-leakage, and cross-tenant isolation."""

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


async def _connect(
    client: AsyncClient, headers: dict[str, str], project_id: str, *, token: str | None = "tok"
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "github",
        "name": "strider-fw",
        "config": {"repo": "octocat/strider-fw", "branch": "main"},
    }
    if token is not None:
        body["token"] = token
    resp = await client.post(f"/api/v1/projects/{project_id}/sources", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def test_connect_with_token_marks_connected(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _connect(client, alice_headers, project_id)
    assert source["status"] == "connected"
    assert source["account_login"] == "octocat"
    # Secrets must never appear in a response (CLAUDE.md §7).
    assert "token" not in source
    assert "secret_ref" not in source


async def test_sync_lands_entities_and_relations(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _connect(client, alice_headers, project_id)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources/{source['id']}/sync", headers=alice_headers
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["data"]["status"] == "queued"
    assert resp.headers["Location"].startswith("/api/v1/jobs/")

    entities = (
        await client.get(f"/api/v1/projects/{project_id}/entities", headers=alice_headers)
    ).json()["data"]
    assert len(entities) == 3
    kinds = {e["type"] for e in entities}
    assert "design_export" in kinds  # W0-08 committed export surfaced

    syncs = (
        await client.get(
            f"/api/v1/projects/{project_id}/sources/{source['id']}/syncs", headers=alice_headers
        )
    ).json()["data"]
    assert len(syncs) == 1
    assert syncs[0]["status"] == "succeeded"
    assert syncs[0]["entities_created"] == 3
    assert syncs[0]["relations_created"] == 2


async def test_sync_rejected_when_not_connected(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    pending = await _connect(client, alice_headers, project_id, token=None)
    assert pending["status"] == "pending"
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources/{pending['id']}/sync", headers=alice_headers
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "not_connected"


async def test_repos_picker_lists_repositories(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _connect(client, alice_headers, project_id)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/sources/{source['id']}/repos", headers=alice_headers
    )
    assert resp.status_code == 200
    repos = resp.json()["data"]
    assert {r["full_name"] for r in repos} == {
        "octocat/strider-fw",
        "octocat/strider-tools",
    }


async def test_disconnect_cascades_entities_by_default(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _connect(client, alice_headers, project_id)
    await client.post(
        f"/api/v1/projects/{project_id}/sources/{source['id']}/sync", headers=alice_headers
    )
    resp = await client.delete(
        f"/api/v1/projects/{project_id}/sources/{source['id']}", headers=alice_headers
    )
    assert resp.status_code == 200
    entities = (
        await client.get(f"/api/v1/projects/{project_id}/entities", headers=alice_headers)
    ).json()["data"]
    assert entities == []


async def test_disconnect_can_retain_entities(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _connect(client, alice_headers, project_id)
    await client.post(
        f"/api/v1/projects/{project_id}/sources/{source['id']}/sync", headers=alice_headers
    )
    resp = await client.delete(
        f"/api/v1/projects/{project_id}/sources/{source['id']}?retain_entities=true",
        headers=alice_headers,
    )
    assert resp.status_code == 200
    entities = (
        await client.get(f"/api/v1/projects/{project_id}/entities", headers=alice_headers)
    ).json()["data"]
    assert len(entities) == 3
    assert all(e["origin"] == "manual" and e["source_id"] is None for e in entities)


async def test_token_connect_rejected_for_oauth_only_connector(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    # Register a GitLab connector that does NOT support token-connect.
    from conftest import FakeGitHub  # OAuthConnector base

    class OAuthOnly(FakeGitHub):
        provider = "gitlab"
        supports_token_connect = False

    app.state.connector_registry.register("gitlab", OAuthOnly)
    project_id = await _project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "gitlab", "name": "x", "config": {}, "token": "tok"},
        headers=alice_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "token_connect_unsupported"


async def test_connect_altium_committed_export_source(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    # SOLUSDEV-102: the `altium` provider is accepted by SourceCreate (Literal),
    # SourceType, and the DB CHECK constraint. As a committed-export connector it
    # has no OAuth/token, so it lands PENDING (awaiting the export) — 201, not a
    # 422 (Literal) or 500 (SourceType) that M2 would have caused.
    project_id = await _project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "altium", "name": "main-board", "config": {}},
        headers=alice_headers,
    )
    assert resp.status_code == 201, resp.text
    source = resp.json()["data"]
    assert source["type"] == "altium"
    assert source["status"] == "pending"


async def test_sync_debounced_while_in_progress(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    from solus_api.models import Source, SourceStatus

    project_id = await _project(client, alice_headers)
    source = await _connect(client, alice_headers, project_id)
    # Force the source into a SYNCING state, then a second trigger must 409.
    async with app.state.sessionmaker() as db:
        row = await db.get(Source, __import__("uuid").UUID(source["id"]))
        row.status = SourceStatus.SYNCING
        await db.commit()
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources/{source['id']}/sync", headers=alice_headers
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "sync_in_progress"


async def test_cross_tenant_isolation(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _connect(client, alice_headers, project_id)
    await me(client, bob_headers)

    # Bob is not a member of Alice's project — every route 404s (no existence leak).
    assert (
        await client.get(f"/api/v1/projects/{project_id}/sources", headers=bob_headers)
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/projects/{project_id}/sources/{source['id']}", headers=bob_headers
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/projects/{project_id}/sources/{source['id']}/sync", headers=bob_headers
        )
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/projects/{project_id}/entities", headers=bob_headers)
    ).status_code == 404
