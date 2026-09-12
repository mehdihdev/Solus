"""Hardware and CODE configuration identities coexist without sharing semantics."""

import uuid

from httpx import AsyncClient
from solus_api.hardware.config import EntityHardwareConfig
from solus_api.hardware.store import put_entity_config, read_entity_config
from solus_api.models import GraphEdge, GraphEntity, SolusSection
from solus_api.services.physical_robots import PhysicalRobotService
from solus_api.services.solus_config import validate_config_payload
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_code_env import _env, _project


def test_hardware_payload_validation_uses_per_entity_schema() -> None:
    subject = uuid.uuid4()
    result = validate_config_payload(
        SolusSection.HARDWARE,
        {"schema_version": 2, "entity_id": str(subject), "provenance": {}},
    )
    assert isinstance(result, EntityHardwareConfig)
    assert result.entity_id == subject


async def test_code_config_lifecycle_does_not_change_hardware_config(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, user = await _project(client, alice_headers)
    robot = await PhysicalRobotService(db).create(project, "Retained hardware")
    config = EntityHardwareConfig.model_validate(
        {"schema_version": 2, "entity_id": str(robot.id), "provenance": {}}
    )
    hardware_entry = await put_entity_config(
        db, project, robot, config, expected_version=0, created_by=user
    )
    await db.commit()
    hardware_id = hardware_entry.id
    hardware_node_id = hardware_entry.entity_id
    payload_before = hardware_entry.payload
    version_before = hardware_entry.config_version
    url = f"/api/v1/projects/{project}/solus/code/entries"
    created = await client.post(
        url, headers=alice_headers, json={"kind": "config", "payload": _env()}
    )
    assert created.status_code == 201, created.text
    entry = created.json()["data"]
    node = await db.get(GraphEntity, uuid.UUID(entry["entity_id"]))
    assert node is not None and node.kind == "solus_note"
    assert node.attrs["section"] == "code"
    assert node.attrs["solus_entry_id"] == entry["id"]
    edges = list(await db.scalars(select(GraphEdge).where(GraphEdge.src_id == node.id)))
    assert all(edge.relation_type != "configures" for edge in edges)
    updated = await client.post(
        url,
        headers=alice_headers,
        json={"kind": "config", "payload": _env(packages=[{"name": "numpy", "version": "2.2.0"}])},
    )
    assert updated.status_code == 201
    assert updated.json()["data"]["id"] == entry["id"]
    removed = await client.delete(
        f"/api/v1/projects/{project}/solus/entries/{entry['id']}", headers=alice_headers
    )
    assert removed.status_code == 204, removed.text
    robot_id = robot.id
    db.expire_all()
    saved_entry, saved_config = await read_entity_config(db, project, robot_id)
    assert saved_entry is not None and saved_config is not None
    assert saved_entry.id == hardware_id
    assert saved_entry.entity_id == hardware_node_id
    assert saved_entry.payload == payload_before
    assert saved_entry.config_version == version_before
