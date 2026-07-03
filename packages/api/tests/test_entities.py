"""Integration tests for §2.4 graph reads — entity list/filter/detail and the
relations of an entity. Graph is seeded by a real connector sync."""

import uuid
from typing import Any

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.registry import ConnectorRegistry


@pytest.fixture(autouse=True)
def _install_fake_github(app: FastAPI, fake_registry: ConnectorRegistry) -> None:
    app.state.connector_registry = fake_registry


async def _project_with_graph(client: AsyncClient, headers: dict[str, str]) -> str:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    project_id: str = project["id"]
    source = (
        await client.post(
            f"/api/v1/projects/{project_id}/sources",
            json={"type": "github", "name": "fw", "config": {"repo": "o/r"}, "token": "tok"},
            headers=headers,
        )
    ).json()["data"]
    await client.post(
        f"/api/v1/projects/{project_id}/sources/{source['id']}/sync", headers=headers
    )
    return project_id


async def _entities(
    client: AsyncClient, headers: dict[str, str], project_id: str, **params: Any
) -> list[dict[str, Any]]:
    resp = await client.get(
        f"/api/v1/projects/{project_id}/entities", params=params, headers=headers
    )
    assert resp.status_code == 200, resp.text
    data: list[dict[str, Any]] = resp.json()["data"]
    return data


async def test_filter_entities_by_type_and_domain(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project_with_graph(client, alice_headers)
    assert len(await _entities(client, alice_headers, project_id)) == 3
    exports = await _entities(client, alice_headers, project_id, type="design_export")
    assert len(exports) == 1
    assert exports[0]["domain"] == "electrical"
    electrical = await _entities(client, alice_headers, project_id, domain="electrical")
    assert len(electrical) == 1


async def test_entity_detail_and_relations(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project_with_graph(client, alice_headers)
    repo = next(
        e
        for e in await _entities(client, alice_headers, project_id)
        if e["source_key"] == ":repo"
    )
    detail = (
        await client.get(
            f"/api/v1/projects/{project_id}/entities/{repo['id']}", headers=alice_headers
        )
    ).json()["data"]
    assert detail["origin"] == "connector"

    relations = (
        await client.get(
            f"/api/v1/projects/{project_id}/entities/{repo['id']}/relations",
            params={"direction": "out"},
            headers=alice_headers,
        )
    ).json()["data"]
    assert len(relations) == 2  # repo contains main.py + board.gbr


async def test_entity_not_found(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    project_id = await _project_with_graph(client, alice_headers)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/entities/{uuid.uuid4()}", headers=alice_headers
    )
    assert resp.status_code == 404


async def test_entities_cross_tenant_isolated(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id = await _project_with_graph(client, alice_headers)
    entity = (await _entities(client, alice_headers, project_id))[0]
    await me(client, bob_headers)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/entities/{entity['id']}", headers=bob_headers
    )
    assert resp.status_code == 404
