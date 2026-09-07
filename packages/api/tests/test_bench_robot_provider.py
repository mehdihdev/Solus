"""Bench sessions from a robot's config (docs/api/hardware.md §6): provider "robot" opens
through the driver registry with the HardwareConfig as the only source of truth — transport
identity, driver id and parameters all come from the document, never from the request."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.livebench.sessions import DeviceNotFoundError
from test_bench_router import FakeLocal, TapConn

FIXTURES = Path(__file__).parent / "fixtures" / "hardware"


class _RobotLocal(FakeLocal):
    def __init__(self) -> None:
        super().__init__()
        self.robot_error: Exception | None = None

    async def open_robot(self, config: dict[str, Any], *, project_id: uuid.UUID) -> TapConn:
        if self.robot_error is not None:
            raise self.robot_error
        return await self._open("robot", config=config, project_id=project_id)


@pytest.fixture
def robot_local(app: FastAPI) -> _RobotLocal:
    fake = _RobotLocal()
    app.state.bench_local = fake
    return fake


async def _robot_project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/entities",
        headers=headers,
        json={"type": "physical_robot", "name": "Follower"},
    )
    assert resp.status_code == 201, resp.text
    return str(project["id"]), str(resp.json()["data"]["id"])


async def _configure(
    client: AsyncClient, headers: dict[str, str], project_id: str, robot_id: str
) -> None:
    raw = json.loads((FIXTURES / "serial_arm.json").read_text())
    raw["robot_entity_id"] = robot_id
    resp = await client.put(
        f"/api/v1/projects/{project_id}/hardware/robots/{robot_id}/config",
        headers=headers,
        json={"config": raw},
    )
    assert resp.status_code == 200, resp.text


def _robot_session_body(robot_id: str, mode: str = "real") -> dict[str, Any]:
    return {"mode": mode, "config": {"provider": "robot", "robot_entity_id": robot_id}}


async def test_robot_session_opens_from_the_config(
    client: AsyncClient, alice_headers: dict[str, str], robot_local: _RobotLocal
) -> None:
    project_id, robot_id = await _robot_project(client, alice_headers)
    await _configure(client, alice_headers, project_id, robot_id)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions",
        headers=alice_headers,
        json=_robot_session_body(robot_id),
    )
    assert resp.status_code == 201, resp.text
    record = resp.json()["data"]
    assert record["provider"] == "robot" and record["mode"] == "real"
    assert record["device"]["device_ref"] == "usb:5B42134331"
    assert record["device"]["driver_id"] == "feetech-sts"
    assert record["device"]["serial_number"] == "5B42134331"
    assert record["device"]["baud"] == 1_000_000
    assert "usb:5B42134331" in record["label"]
    opened = robot_local.opened[0]
    assert opened["kind"] == "robot"
    assert opened["config"]["identity"]["binding"] == "5B42134331"
    assert opened["config"]["protocol"]["driver_id"] == "feetech-sts"
    assert opened["project_id"] == uuid.UUID(project_id)


async def test_robot_session_needs_identity_and_protocol(
    client: AsyncClient, alice_headers: dict[str, str], robot_local: _RobotLocal
) -> None:
    project_id, robot_id = await _robot_project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions",
        headers=alice_headers,
        json=_robot_session_body(robot_id),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "validation_error"
    assert robot_local.opened == []


async def test_robot_session_for_an_unknown_robot_is_404(
    client: AsyncClient, alice_headers: dict[str, str], robot_local: _RobotLocal
) -> None:
    project_id, _ = await _robot_project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions",
        headers=alice_headers,
        json=_robot_session_body(str(uuid.uuid4())),
    )
    assert resp.status_code == 404, resp.text


async def test_robot_session_only_runs_in_real_mode(
    client: AsyncClient, alice_headers: dict[str, str], robot_local: _RobotLocal
) -> None:
    project_id, robot_id = await _robot_project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions",
        headers=alice_headers,
        json=_robot_session_body(robot_id, mode="sim"),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (DeviceNotFoundError("no device with serial '5B42134331'"), 404, "device_not_found"),
        (RuntimeError("usb:5B42134331: no transport"), 503, "source_unavailable"),
    ],
)
async def test_robot_session_maps_open_failures_honestly(
    client: AsyncClient,
    alice_headers: dict[str, str],
    robot_local: _RobotLocal,
    error: Exception,
    status: int,
    code: str,
) -> None:
    project_id, robot_id = await _robot_project(client, alice_headers)
    await _configure(client, alice_headers, project_id, robot_id)
    robot_local.robot_error = error
    resp = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions",
        headers=alice_headers,
        json=_robot_session_body(robot_id),
    )
    assert resp.status_code == status, resp.text
    assert resp.json()["error"]["code"] == code


async def test_serial_config_accepts_a_driver_id_and_generic_params(
    client: AsyncClient, alice_headers: dict[str, str], robot_local: _RobotLocal
) -> None:
    project_id, _ = await _robot_project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions",
        headers=alice_headers,
        json={
            "mode": "real",
            "config": {
                "provider": "serial",
                "serial_number": "5B42135040",
                "driver_id": "json-lines",
                "driver_params": {"timeout_s": 0.2},
            },
        },
    )
    assert resp.status_code == 201, resp.text
    opened = robot_local.opened[0]
    assert opened["kind"] == "serial"
    assert opened["driver_id"] == "json-lines"
    assert opened["driver_params"] == {"timeout_s": 0.2}
    assert resp.json()["data"]["device"]["driver_id"] == "json-lines"


async def test_serial_config_bounds_driver_params(
    client: AsyncClient, alice_headers: dict[str, str], robot_local: _RobotLocal
) -> None:
    project_id, _ = await _robot_project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions",
        headers=alice_headers,
        json={
            "mode": "real",
            "config": {
                "provider": "serial",
                "serial_number": "5B42135040",
                "driver_params": {f"k{i}": i for i in range(40)},
            },
        },
    )
    assert resp.status_code == 422, resp.text
