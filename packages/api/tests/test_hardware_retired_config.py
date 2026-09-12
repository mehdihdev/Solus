"""Retired or inconsistent graph configurations never become operational again."""

import uuid

import pytest
from httpx import AsyncClient
from solus_api.models import GraphEdge, GraphEntity, SolusEntry, utcnow
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_lifecycle_phase3 import _connection, _save
from test_hardware_ownership import _create, _project, _url


@pytest.mark.parametrize("subject_kind", ["owner", "child"])
@pytest.mark.parametrize("fault", ["valid", "node", "edge", "missing_edge", "foreign_edge"])
async def test_runtime_refuses_retired_config_graph_without_writing(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    subject_kind: str,
    fault: str,
) -> None:
    project = await _project(client, alice_headers)
    robot = (await _create(client, alice_headers, project, kind="robot", name="Owner fixture"))[
        "entity"
    ]
    part = (
        await _create(
            client,
            alice_headers,
            project,
            kind="part",
            name="Child fixture",
            parent_id=robot["id"],
            category="sensors",
        )
    )["entity"]
    await _save(client, alice_headers, project, _connection(robot["id"], part["id"]))
    child_config = {
        "schema_version": 2,
        "entity_id": part["id"],
        "component": {"calibration": {"values": {"offset": 3}}},
        "provenance": {"component": {"by": "user"}},
    }
    await _save(client, alice_headers, project, child_config)
    subject = robot if subject_kind == "owner" else part
    entry = await db.scalar(
        select(SolusEntry).where(SolusEntry.configured_entity_id == uuid.UUID(subject["id"]))
    )
    assert entry is not None
    node = await db.get(GraphEntity, entry.entity_id)
    edge = await db.scalar(
        select(GraphEdge).where(
            GraphEdge.src_id == entry.entity_id, GraphEdge.relation_type == "configures"
        )
    )
    assert node is not None and edge is not None
    if fault == "node":
        node.deleted_at = utcnow()
    elif fault == "edge":
        edge.deleted_at = utcnow()
    elif fault == "missing_edge":
        await db.execute(delete(GraphEdge).where(GraphEdge.id == edge.id))
    elif fault == "foreign_edge":
        await db.commit()
        other = await _project(client, alice_headers)
        foreign = (
            await _create(client, alice_headers, other, kind="part", name="Foreign fixture")
        )["entity"]
        edge.dst_id = uuid.UUID(foreign["id"])
    await db.commit()
    before = (entry.id, entry.payload, entry.config_version, entry.updated_at)
    response = await client.get(
        _url(project, f"robots/{robot['id']}/config"), headers=alice_headers
    )
    assert response.status_code == (200 if fault == "valid" else 409), response.text
    direct = await client.get(
        _url(project, f"entities/{subject['id']}/config"), headers=alice_headers
    )
    assert direct.status_code == (200 if fault == "valid" else 409), direct.text
    await db.refresh(entry)
    assert (entry.id, entry.payload, entry.config_version, entry.updated_at) == before
    await db.commit()
    if fault != "valid":
        response = await client.put(
            _url(project, f"entities/{subject['id']}/config"),
            headers={**alice_headers, "If-Match": "1"},
            json={
                "config": _connection(robot["id"], part["id"])
                if subject_kind == "owner"
                else child_config
            },
        )
        assert response.status_code == 409, response.text


async def test_deleted_config_entry_reads_absent_and_preserves_history(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project = await _project(client, alice_headers)
    robot = (await _create(client, alice_headers, project, kind="robot", name="Historical owner"))[
        "entity"
    ]
    await _save(client, alice_headers, project, _connection(robot["id"]))
    entry = await db.scalar(
        select(SolusEntry).where(SolusEntry.configured_entity_id == uuid.UUID(robot["id"]))
    )
    assert entry is not None
    entry.deleted_at = utcnow()
    await db.commit()
    snapshot = (entry.id, entry.payload, entry.config_version, entry.updated_at, entry.deleted_at)
    for endpoint in (f"entities/{robot['id']}/config", f"robots/{robot['id']}/config"):
        response = await client.get(_url(project, endpoint), headers=alice_headers)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["entry_id"] is None
    rows = list(
        await db.scalars(
            select(SolusEntry).where(SolusEntry.configured_entity_id == uuid.UUID(robot["id"]))
        )
    )
    assert len(rows) == 1
    await db.refresh(entry)
    assert (
        entry.id,
        entry.payload,
        entry.config_version,
        entry.updated_at,
        entry.deleted_at,
    ) == snapshot
