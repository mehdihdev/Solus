"""SOLUSDEV-260: saved connection context survives compatibility-route mutations.

Regression evidence for REVIEW_SOLUSDEV-251_premerge.md §3.1, governed by the
hardware API, ownership architecture and hardware-config storage specification.
"""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.hardware.config import EntityHardwareConfig
from solus_api.hardware.library import Library, PartDefinition
from solus_api.hardware.store import read_entity_config
from solus_api.models import GraphEdge, GraphEntity
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_detect import DEVICE_REF, _DetectLocal, _wire_proposal
from test_hardware_router import _hw_get_config, _hw_project, _hw_url, _robot


async def _configured_robot(
    client: AsyncClient, headers: dict[str, str], *, firmware: bool = True
) -> tuple[str, str, str]:
    project_id, _ = await _hw_project(client, headers)
    robot_id = (await _robot(client, headers, project_id))["id"]
    created = await client.post(
        _hw_url(project_id, "robots", robot_id, "parts"),
        headers=headers,
        json={"name": "Existing sensor", "category": "sensors", "specs": {}},
    )
    assert created.status_code == 201, created.text
    part_id = created.json()["data"]["entity"]["id"]
    config = {
        "robot_entity_id": robot_id,
        "identity": {"kind": "usb_serial", "binding": DEVICE_REF.split(":")[1]},
        "protocol": {"driver_id": "demo-bus", "params": {"baud": 1_000_000}},
        "bus_map": [{"protocol": "demo-bus", "address": "9", "part_entity_id": part_id}],
        "parts": {part_id: {"lifecycle": "planned"}},
        "firmware": {"version": "1.2.3"} if firmware else {},
        "disambiguated_by": "user",
        "provenance": {
            key: {"by": "user"}
            for key in ("identity", "protocol", "bus_map", "parts", "firmware", "disambiguated_by")
        },
    }
    saved = await client.put(
        _hw_url(project_id, "robots", robot_id, "config"),
        headers=headers,
        json={"config": config},
    )
    assert saved.status_code == 200, saved.text
    return project_id, robot_id, part_id


async def _stored(db: AsyncSession, project_id: str, robot_id: str) -> dict[str, Any]:
    # Read the durable v2 document, not PUT's echo of its submitted v1 aggregate.
    db.expire_all()
    _, config = await read_entity_config(db, uuid.UUID(project_id), uuid.UUID(robot_id))
    assert config is not None
    result = config.model_dump(mode="json")
    await db.commit()
    return result


def _connection(config: dict[str, Any]) -> dict[str, Any]:
    return {key: config[key] for key in ("identity", "protocol", "bus_map", "disambiguated_by")}


@pytest.mark.parametrize("operation", ["promote", "put", "library"])
async def test_firmware_robot_connection_survives_compatibility_mutation(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    project_id, robot_id, part_id = await _configured_robot(client, alice_headers)
    before = await _stored(db, project_id, robot_id)
    assert before["component"]["firmware"] == {"version": "1.2.3"}
    assert all(_connection(before).values())

    if operation == "promote":
        response = await client.post(
            _hw_url(project_id, "robots", robot_id, "parts", part_id, "lifecycle"),
            headers=alice_headers,
            json={"state": "installed"},
        )
    elif operation == "put":
        current = await _hw_get_config(client, alice_headers, project_id, robot_id)
        response = await client.put(
            _hw_url(project_id, "robots", robot_id, "config"),
            headers=alice_headers,
            json={"config": current["config"]},
        )
    else:
        definition = PartDefinition(id="test-sensor", name="Test sensor", category="sensors")
        library = Library(parts={definition.id: definition}, platforms={})
        monkeypatch.setattr("solus_api.hardware.library_router.load_library", lambda: library)
        response = await client.post(
            _hw_url(project_id, "library", "parts", definition.id, "import"),
            headers=alice_headers,
            json={"robot_id": robot_id},
        )
    assert response.status_code == (201 if operation == "library" else 200), response.text
    after = await _stored(db, project_id, robot_id)
    assert _connection(after) == _connection(before)
    assert after["component"]["firmware"] == before["component"]["firmware"]


async def test_detect_confirm_preserves_existing_firmware_robot_context(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    project_id, robot_id, _ = await _configured_robot(client, alice_headers)
    before = await _stored(db, project_id, robot_id)
    local = _DetectLocal()
    proposal = _wire_proposal()
    proposal["identity"] = before["identity"]
    proposal["params"] = before["protocol"]["params"]
    local.proposal = proposal
    app.state.bench_local = local
    response = await client.post(
        _hw_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json={
            "target": {"kind": "existing", "robot_id": robot_id},
            "accepted": [{"row_id": f"{DEVICE_REF}/1", "function_name": "New actuator"}],
            "start_session": False,
        },
    )
    assert response.status_code == 201, response.text
    after = await _stored(db, project_id, robot_id)
    preserved = _connection(after)
    # Confirmation may append accepted bindings; existing bindings must remain.
    preserved["bus_map"] = [row for row in after["bus_map"] if row in before["bus_map"]]
    assert preserved == _connection(before)
    assert after["component"]["firmware"] == before["component"]["firmware"]
    assert len(after["bus_map"]) == len(before["bus_map"]) + 1
    assert after["bus_map"][-1]["part_entity_id"] == response.json()["data"]["part_ids"][0]
    old_config = EntityHardwareConfig.model_validate(before)
    new_config = EntityHardwareConfig.model_validate(after)
    for path in (
        "identity.binding",
        "protocol.driver_id",
        "protocol.params.baud",
        "bus_map.0.address",
        "component.firmware.version",
        "disambiguated_by",
    ):
        assert new_config.provenance_of(path) == old_config.provenance_of(path)


async def test_promote_without_owner_firmware_preserves_connection_control(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, robot_id, part_id = await _configured_robot(client, alice_headers, firmware=False)
    before = await _stored(db, project_id, robot_id)
    response = await client.post(
        _hw_url(project_id, "robots", robot_id, "parts", part_id, "lifecycle"),
        headers=alice_headers,
        json={"state": "installed"},
    )
    assert response.status_code == 200, response.text
    assert _connection(await _stored(db, project_id, robot_id)) == _connection(before)


@pytest.mark.parametrize(
    "conflict", ["identity", "driver", "parameter", "bus_address", "disabled_binding"]
)
async def test_detect_conflict_preserves_saved_config_and_graph(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    conflict: str,
) -> None:
    project_id, robot_id, _ = await _configured_robot(client, alice_headers)
    before = await _stored(db, project_id, robot_id)
    count_query = (
        select(func.count())
        .select_from(GraphEntity)
        .where(GraphEntity.project_id == uuid.UUID(project_id))
    )
    count_before = await db.scalar(count_query)
    if conflict == "disabled_binding":
        binding = await db.scalar(
            select(GraphEdge).where(
                GraphEdge.project_id == uuid.UUID(project_id),
                GraphEdge.relation_type == "binds",
                GraphEdge.dst_id == uuid.UUID(before["bus_map"][0]["part_entity_id"]),
            )
        )
        assert binding is not None
        binding.attrs = {**binding.attrs, "enabled": False, "disabled_reason": "ownership_changed"}
    await db.commit()
    proposal = _wire_proposal()
    proposal["identity"] = dict(before["identity"])
    proposal["params"] = dict(before["protocol"]["params"])
    if conflict == "identity":
        proposal["identity"]["binding"] = "different-serial"
    elif conflict == "driver":
        proposal["driver_id"] = "different-driver"
    elif conflict == "parameter":
        proposal["params"]["baud"] = 9600
    elif conflict == "bus_address":
        proposal["rows"][0]["address"] = "9"
    local = _DetectLocal()
    local.proposal = proposal
    app.state.bench_local = local
    response = await client.post(
        _hw_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json={
            "target": {"kind": "existing", "robot_id": robot_id},
            "accepted": [{"row_id": f"{DEVICE_REF}/1", "function_name": "New actuator"}],
            "start_session": False,
        },
    )
    assert response.status_code == 409, response.text
    expected_code = (
        "config_upgrade_required" if conflict == "disabled_binding" else "proposal_changed"
    )
    assert response.json()["error"]["code"] == expected_code
    assert await _stored(db, project_id, robot_id) == before
    assert await db.scalar(count_query) == count_before
