"""Integration tests for §2.5 Sources — connect/sync/disconnect, the repo
picker, sync history, secret non-leakage, and cross-tenant isolation."""

import uuid
from typing import Any

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.contracts import Connector
from solus_api.connectors.registry import ConnectorContext, ConnectorRegistry


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
    # 3 synced entities + `.solus` and five sections (SOLUSDEV-242).
    assert len(entities) == 9
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


async def test_selectable_picker_lists_what_the_source_can_track(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """One generic picker route for every connector — repos here, CAD documents
    for Onshape — so a new connector needs no new route."""
    project_id = await _project(client, alice_headers)
    source = await _connect(client, alice_headers, project_id)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/sources/{source['id']}/selectable", headers=alice_headers
    )
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert {i["id"] for i in items} == {
        "octocat/strider-fw",
        "octocat/strider-tools",
    }
    # Each item carries the exact config choosing it writes, so the caller never
    # has to know what a "repo" means.
    assert items[0]["config"] == {"repo": "octocat/strider-fw", "branch": "main"}


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
    # The entire manual `.solus` hierarchy survives a source cascade.
    assert sorted(e["name"] for e in entities) == [
        ".solus",
        "Code environment",
        "Documentation",
        "Error logging",
        "Hardware configs",
        "Project details",
    ]


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
    # 3 retained (orphaned to manual) + the six manual `.solus` nodes.
    assert len(entities) == 9
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
    # SOLUSDEV-102/100: a committed-export connector has no OAuth/token — there
    # is nothing to authenticate, so it lands CONNECTED on creation with the
    # connector's synthetic identity (previously it landed PENDING forever,
    # which made it permanently unsyncable — Phase 4 review finding).
    project_id = await _project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "altium", "name": "main-board", "config": {}},
        headers=alice_headers,
    )
    assert resp.status_code == 201, resp.text
    source = resp.json()["data"]
    assert source["type"] == "altium"
    assert source["status"] == "connected"
    assert source["account_login"] == "altium-export"


async def test_connect_kicad_source_and_sync_it(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    # SOLUSDEV-100 end-to-end: connect a kicad source with the committed netlist
    # CONTENT in config.export (the v1 scaffold), then trigger a real sync.
    from fixtures.kicad_sample import KICAD_XML

    project_id = await _project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "kicad", "name": "power-board", "config": {"export": KICAD_XML}},
        headers=alice_headers,
    )
    assert resp.status_code == 201, resp.text
    source = resp.json()["data"]
    assert source["type"] == "kicad"
    assert source["status"] == "connected"
    assert source["account_login"] == "kicad-export"
    # Security review (Phase 4): the bulk export content is stored, but never
    # echoed back by source serialization (§7 — response bloat, untrusted
    # content round-tripping on a hot endpoint).
    assert "export" not in source["config"]

    sync_resp = await client.post(
        f"/api/v1/projects/{project_id}/sources/{source['id']}/sync",
        headers=alice_headers,
    )
    assert sync_resp.status_code == 202, sync_resp.text


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


async def test_disconnect_deletes_the_oauth_refresh_secret_too(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    """Security review HIGH-2: the refresh token lives under its own ref and
    outlives the access token unless disconnect removes it. Leaving it lets
    Solus keep minting access tokens against the user's documents after the
    user believes they revoked us."""
    from solus_api.connectors.runtime import refresh_secret_ref
    from solus_api.connectors.secrets import SecretNotFoundError

    store = app.state.secret_store
    project_id = await _project(client, alice_headers)
    created = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        headers=alice_headers,
        json={"type": "github", "name": "octo/r", "token": "tok", "config": {}},
    )
    source_id = created.json()["data"]["id"]
    ref = f"source/{source_id}/github"
    await store.put(refresh_secret_ref(ref), "a-refresh-token")

    await client.delete(f"/api/v1/projects/{project_id}/sources/{source_id}", headers=alice_headers)

    with pytest.raises(SecretNotFoundError):
        await store.get(ref)
    with pytest.raises(SecretNotFoundError):
        await store.get(refresh_secret_ref(ref))


# --- SOLUSDEV-100 T4b: F3 acting-user threading on the manual trigger ---


class _SpyRegistry:
    """Wraps a real `ConnectorRegistry`, recording every `create_scoped` call
    so a test can assert WHO the manual `/sync` trigger resolved as the
    acting user, without needing a live bridge companion."""

    def __init__(self, inner: ConnectorRegistry) -> None:
        self._inner = inner
        self.scoped_calls: list[tuple[str, ConnectorContext]] = []

    def create(self, provider: str) -> Connector:
        return self._inner.create(provider)

    def create_scoped(self, provider: str, ctx: ConnectorContext) -> Connector:
        self.scoped_calls.append((provider, ctx))
        return self._inner.create_scoped(provider, ctx)

    def providers(self) -> list[str]:
        return self._inner.providers()

    def catalog(self) -> list[dict[str, Any]]:
        return self._inner.catalog()


async def test_manual_trigger_passes_the_requesting_user_as_acting_user(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    spy = _SpyRegistry(app.state.connector_registry)
    app.state.connector_registry = spy

    user = await me(client, alice_headers)
    project_id = await _project(client, alice_headers)
    source = await _connect(client, alice_headers, project_id)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources/{source['id']}/sync", headers=alice_headers
    )
    assert resp.status_code == 202, resp.text

    assert spy.scoped_calls, "trigger_sync must resolve the connector via create_scoped"
    provider, ctx = spy.scoped_calls[-1]
    assert provider == "github"
    assert ctx.project_id == uuid.UUID(project_id)
    assert ctx.acting_user_id == uuid.UUID(user["id"])
