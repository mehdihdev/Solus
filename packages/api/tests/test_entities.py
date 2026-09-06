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
    await client.post(f"/api/v1/projects/{project_id}/sources/{source['id']}/sync", headers=headers)
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
    # 3 synced entities + the project's own `.solus` node (SOLUSDEV-240).
    assert len(await _entities(client, alice_headers, project_id)) == 4
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
        e for e in await _entities(client, alice_headers, project_id) if e["source_key"] == ":repo"
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


async def _subgraph(
    client: AsyncClient, headers: dict[str, str], project_id: str, **params: Any
) -> dict[str, Any]:
    resp = await client.get(f"/api/v1/projects/{project_id}/graph", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def _repo_id(client: AsyncClient, headers: dict[str, str], project_id: str) -> str:
    entities = await _entities(client, headers, project_id)
    repo: str = next(e for e in entities if e["source_key"] == ":repo")["id"]
    return repo


async def test_subgraph_returns_the_focused_entity_and_its_neighbourhood(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """WS-01's focus-scope read: one call gives a widget everything it needs to re-scope."""
    project_id = await _project_with_graph(client, alice_headers)
    repo = await _repo_id(client, alice_headers, project_id)

    data = await _subgraph(client, alice_headers, project_id, root=repo, depth=1)
    assert {e["source_key"] for e in data["entities"]} == {
        ":repo",
        "src/main.py",
        "hardware/board.gbr",
    }
    assert len(data["edges"]) == 2
    assert data["truncated"] is False
    # Serialized with the SAME public keys as /entities, so the frontend has one entity type.
    assert set(data["entities"][0]) >= {"id", "type", "domain", "name", "source_key", "properties"}


async def test_subgraph_depth_zero_is_just_the_focused_entity(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project_with_graph(client, alice_headers)
    repo = await _repo_id(client, alice_headers, project_id)
    data = await _subgraph(client, alice_headers, project_id, root=repo, depth=0)
    assert len(data["entities"]) == 1
    assert data["edges"] == []


async def test_subgraph_reports_truncation(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project_with_graph(client, alice_headers)
    repo = await _repo_id(client, alice_headers, project_id)
    data = await _subgraph(client, alice_headers, project_id, root=repo, depth=1, limit=1)
    assert data["truncated"] is True
    assert len(data["entities"]) == 1


async def test_subgraph_rejects_depth_beyond_the_cap(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Bounded by the route, not just by convention — an unbounded depth is a whole-graph scan."""
    project_id = await _project_with_graph(client, alice_headers)
    repo = await _repo_id(client, alice_headers, project_id)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/graph",
        params={"root": repo, "depth": 5},
        headers=alice_headers,
    )
    assert resp.status_code == 422


async def test_subgraph_filters_by_relation_type(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project_with_graph(client, alice_headers)
    repo = await _repo_id(client, alice_headers, project_id)
    data = await _subgraph(
        client, alice_headers, project_id, root=repo, depth=1, relation_types="nonexistent"
    )
    assert len(data["entities"]) == 1  # only the root survives
    assert data["edges"] == []


async def test_subgraph_filters_by_entity_type(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Proves the `_csv` → `entity_types` wiring end to end, not just the traversal unit."""
    project_id = await _project_with_graph(client, alice_headers)
    repo = await _repo_id(client, alice_headers, project_id)
    data = await _subgraph(
        client, alice_headers, project_id, root=repo, depth=1, entity_types="design_export"
    )
    kinds = {e["type"] for e in data["entities"]}
    assert "design_export" in kinds
    assert "code_module" not in kinds  # filtered out; the root is kept regardless of its kind


async def test_subgraph_unknown_root_is_404(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project_with_graph(client, alice_headers)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/graph",
        params={"root": str(uuid.uuid4())},
        headers=alice_headers,
    )
    assert resp.status_code == 404


async def test_subgraph_cross_tenant_isolated(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """404, not 403 — no existence oracle for another team's entities."""
    project_id = await _project_with_graph(client, alice_headers)
    repo = await _repo_id(client, alice_headers, project_id)
    await me(client, bob_headers)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/graph", params={"root": repo}, headers=bob_headers
    )
    assert resp.status_code == 404


async def test_subgraph_confused_deputy_gets_the_same_404_as_a_nonexistent_id(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """The realistic isolation case: the caller is a legitimate member of BOTH projects and asks
    project A for a root that lives in project B. Must 404 — and with a body byte-identical to an
    unknown id, or the difference itself is an existence oracle for the other project's contents."""
    project_a = await _project_with_graph(client, alice_headers)
    project_b = await _project_with_graph(client, alice_headers)
    root_in_b = await _repo_id(client, alice_headers, project_b)

    foreign = await client.get(
        f"/api/v1/projects/{project_a}/graph", params={"root": root_in_b}, headers=alice_headers
    )
    unknown = await client.get(
        f"/api/v1/projects/{project_a}/graph",
        params={"root": str(uuid.uuid4())},
        headers=alice_headers,
    )

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()


async def test_subgraph_requires_authentication(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await _project_with_graph(client, alice_headers)
    repo = await _repo_id(client, alice_headers, project_id)
    resp = await client.get(f"/api/v1/projects/{project_id}/graph", params={"root": repo})
    assert resp.status_code == 401


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
