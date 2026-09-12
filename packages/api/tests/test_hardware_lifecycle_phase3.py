"""Deletion releases stale bindings and compatibility reads never create config."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from solus_api.models import GraphEdge, GraphEntity, SolusEntry, utcnow
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_ownership import _create, _project, _url


def _connection(entity_id: str, part_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "entity_id": entity_id,
        "identity": {"kind": "usb_serial", "binding": "phase3-fixture"},
        "protocol": {"driver_id": "fixture", "params": {"baud": 115200}},
        "bus_map": [{"protocol": "fixture", "address": "1", "part_entity_id": part_id}]
        if part_id
        else [],
        "provenance": {key: {"by": "user"} for key in ("identity", "protocol", "bus_map")},
    }


async def _save(
    client: AsyncClient,
    headers: dict[str, str],
    project: str,
    config: dict[str, Any],
    version: int = 0,
) -> None:
    response = await client.put(
        _url(project, f"entities/{config['entity_id']}/config"),
        headers={**headers, "If-Match": str(version)},
        json={"config": config},
    )
    assert response.status_code == 200, response.text


async def test_get_config_is_pure_and_first_put_creates_it(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = await _project(client, alice_headers)
    robot = (await _create(client, alice_headers, project, kind="robot", name="Read fixture"))[
        "entity"
    ]
    before = [
        await db.scalar(select(func.count()).select_from(model))
        for model in (GraphEntity, GraphEdge, SolusEntry)
    ]
    await db.commit()

    async def forbidden_lock(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("GET must not lock or initialize configuration")

    with monkeypatch.context() as patch:
        patch.setattr("solus_api.hardware.store.lock_project", forbidden_lock)
        response = await client.get(
            _url(project, f"robots/{robot['id']}/config"), headers=alice_headers
        )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["entry_id"] is None
    after = [
        await db.scalar(select(func.count()).select_from(model))
        for model in (GraphEntity, GraphEdge, SolusEntry)
    ]
    assert after == before
    await db.commit()
    await _save(client, alice_headers, project, _connection(robot["id"]))
    response = await client.get(
        _url(project, f"robots/{robot['id']}/config"), headers=alice_headers
    )
    assert response.json()["data"]["entry_id"] is not None


async def test_delete_releases_owner_and_retained_part_endpoints(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project = await _project(client, alice_headers)
    robot = (await _create(client, alice_headers, project, kind="robot", name="Old fixture"))[
        "entity"
    ]
    part = (
        await _create(
            client,
            alice_headers,
            project,
            kind="part",
            name="Retained fixture",
            parent_id=robot["id"],
            category="sensors",
        )
    )["entity"]
    await _save(client, alice_headers, project, _connection(robot["id"], part["id"]))
    response = await client.delete(
        f"/api/v1/projects/{project}/entities/{robot['id']}",
        headers={**alice_headers, "If-Match": str(robot["version"])},
    )
    assert response.status_code == 200, response.text
    edges = list(
        await db.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == uuid.UUID(project),
                GraphEdge.relation_type == "binds",
                GraphEdge.deleted_at.is_(None),
            )
        )
    )
    assert len(edges) == 2 and all(edge.attrs["enabled"] is False for edge in edges)
    await db.commit()
    newer = (await _create(client, alice_headers, project, kind="robot", name="New fixture"))[
        "entity"
    ]
    await _save(client, alice_headers, project, _connection(newer["id"], part["id"]))
    live_part = await db.get(GraphEntity, uuid.UUID(part["id"]))
    assert live_part is not None and live_part.deleted_at is None


@pytest.mark.parametrize("deleted", ["subject", "config", "config_node", "target"])
async def test_historical_bindings_do_not_block_new_claims(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, deleted: str
) -> None:
    project = await _project(client, alice_headers)
    robot = (await _create(client, alice_headers, project, kind="robot", name="Old fixture"))[
        "entity"
    ]
    part = (await _create(client, alice_headers, project, kind="part", name="Part fixture"))[
        "entity"
    ]
    await _save(client, alice_headers, project, _connection(robot["id"], part["id"]))
    entry = await db.scalar(
        select(SolusEntry).where(SolusEntry.configured_entity_id == uuid.UUID(robot["id"]))
    )
    assert entry is not None
    if deleted == "config":
        entry.deleted_at = utcnow()
    else:
        identity = (
            entry.entity_id
            if deleted == "config_node"
            else uuid.UUID(part["id"] if deleted == "target" else robot["id"])
        )
        node = await db.get(GraphEntity, identity)
        assert node is not None
        node.deleted_at = utcnow()
    if deleted == "target":
        # The owner's bare endpoint still legitimately belongs to its live config.
        own = await db.scalar(
            select(GraphEdge).where(
                GraphEdge.src_id == entry.entity_id,
                GraphEdge.dst_id == uuid.UUID(robot["id"]),
                GraphEdge.relation_type == "binds",
            )
        )
        assert own is not None
        own.attrs = {**own.attrs, "enabled": False}
    await db.commit()
    newer = (await _create(client, alice_headers, project, kind="robot", name="New fixture"))[
        "entity"
    ]
    new_part = (await _create(client, alice_headers, project, kind="part", name="New part"))[
        "entity"
    ]
    await _save(client, alice_headers, project, _connection(newer["id"], new_part["id"]))


async def test_part_config_version_conflict_and_deleted_subject_are_safe(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project = await _project(client, alice_headers)
    part = (await _create(client, alice_headers, project, kind="part", name="Versioned part"))[
        "entity"
    ]
    document = _connection(part["id"])
    await _save(client, alice_headers, project, document)
    endpoint = _url(project, f"entities/{part['id']}/config")
    stale = await client.put(
        endpoint, headers={**alice_headers, "If-Match": "0"}, json={"config": document}
    )
    assert stale.status_code == 409, stale.text
    saved = await client.get(endpoint, headers=alice_headers)
    assert saved.json()["data"]["version"] == 1
    node = await db.get(GraphEntity, uuid.UUID(part["id"]))
    assert node is not None
    node.deleted_at = utcnow()
    await db.commit()
    read = await client.get(endpoint, headers=alice_headers)
    write = await client.put(
        endpoint, headers={**alice_headers, "If-Match": "1"}, json={"config": document}
    )
    assert read.status_code == write.status_code == 404


async def test_delete_preserves_retained_parts_independent_connection(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project = await _project(client, alice_headers)
    robot = (await _create(client, alice_headers, project, kind="robot", name="Robot fixture"))[
        "entity"
    ]
    part = (
        await _create(
            client,
            alice_headers,
            project,
            kind="part",
            name="Independent controller",
            parent_id=robot["id"],
            category="sensors",
        )
    )["entity"]
    sensor = (
        await _create(
            client,
            alice_headers,
            project,
            kind="part",
            name="Controller sensor",
            parent_id=robot["id"],
            category="sensors",
        )
    )["entity"]
    await _save(client, alice_headers, project, _connection(part["id"], sensor["id"]))
    response = await client.delete(
        f"/api/v1/projects/{project}/entities/{robot['id']}",
        headers={**alice_headers, "If-Match": str(robot["version"])},
    )
    assert response.status_code == 200, response.text
    entry = await db.scalar(
        select(SolusEntry).where(SolusEntry.configured_entity_id == uuid.UUID(part["id"]))
    )
    assert entry is not None and entry.deleted_at is None
    bindings = list(
        await db.scalars(
            select(GraphEdge).where(
                GraphEdge.src_id == entry.entity_id,
                GraphEdge.relation_type == "binds",
                GraphEdge.deleted_at.is_(None),
            )
        )
    )
    assert len(bindings) == 2 and all(binding.attrs["enabled"] is True for binding in bindings)
    await db.commit()
    response = await client.get(_url(project, "parts?ownership=unassigned"), headers=alice_headers)
    assert part["id"] in {item["id"] for item in response.json()["data"]}
