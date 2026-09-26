"""Explicit transport-only acceptance never invents a protocol or opens hardware."""

from typing import Any

import pytest
from httpx import AsyncClient
from test_hardware_detect import (
    DEVICE_REF,
    _detect_project,
    _detect_url,
    _DetectLocal,
    detect_local,
)

__all__ = ["detect_local"]


def connection_body() -> dict[str, Any]:
    return {
        "target": {"kind": "new", "name": "Uno"},
        "accepted": [],
        "connection_only": True,
        "start_session": True,
    }


def silent(local: _DetectLocal) -> None:
    assert local.proposal is not None
    local.proposal.update(driver_id=None, rows=[], params={}, level="transport")


async def test_connection_only_replay_without_session(
    client: AsyncClient,
    alice_headers: dict[str, str],
    detect_local: _DetectLocal,
) -> None:
    project, _ = await _detect_project(client, alice_headers)
    silent(detect_local)
    url = _detect_url(project, "detected", DEVICE_REF, "confirm")
    first = await client.post(url, headers=alice_headers, json=connection_body())
    assert first.status_code == 201, first.text
    second = await client.post(url, headers=alice_headers, json=connection_body())
    assert second.status_code == 201, second.text
    assert first.json()["data"]["robot"]["id"] == second.json()["data"]["robot"]["id"]
    assert first.json()["data"]["part_ids"] == []
    assert "connection" not in first.json()["data"]["robot"]["properties"]
    assert first.json()["data"]["session_id"] is None
    config_response = await client.get(
        _detect_url(project, "robots", first.json()["data"]["robot"]["id"], "config"),
        headers=alice_headers,
    )
    config = config_response.json()["data"]["config"]
    assert config["identity"]["binding"] == "5B42134331"
    assert config["protocol"] is None
    assert config["parts"] == {} and config["bus_map"] == []
    assert not detect_local.opened


@pytest.mark.parametrize(
    "changes",
    [
        {"connection_only": False},
        {"connection_only": "true"},
        {"accepted": [{"row_id": "invented"}]},
    ],
)
async def test_connection_only_strict_request(
    client: AsyncClient,
    alice_headers: dict[str, str],
    detect_local: _DetectLocal,
    changes: dict[str, Any],
) -> None:
    project, _ = await _detect_project(client, alice_headers)
    silent(detect_local)
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=connection_body() | changes,
    )
    assert response.status_code == 422, response.text


async def test_recognized_driver_cannot_be_connection_only(
    client: AsyncClient,
    alice_headers: dict[str, str],
    detect_local: _DetectLocal,
) -> None:
    project, _ = await _detect_project(client, alice_headers)
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=connection_body(),
    )
    assert response.status_code == 422


async def test_connection_only_auth_and_project_isolation(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    detect_local: _DetectLocal,
) -> None:
    from conftest import BOB, add_member, me

    project, team = await _detect_project(client, alice_headers)
    silent(detect_local)
    url = _detect_url(project, "detected", DEVICE_REF, "confirm")
    assert (await client.post(url, json=connection_body())).status_code == 401
    await me(client, bob_headers)
    assert (await client.post(url, headers=bob_headers, json=connection_body())).status_code == 404
    await add_member(client, alice_headers, bob_headers, BOB, team, role="viewer")
    assert (await client.post(url, headers=bob_headers, json=connection_body())).status_code == 403
    assert not detect_local.opened


async def test_connection_only_rejects_operational_saved_robot(
    client: AsyncClient,
    alice_headers: dict[str, str],
    detect_local: _DetectLocal,
) -> None:
    from test_hardware_detect import _confirm_body

    project, _ = await _detect_project(client, alice_headers)
    url = _detect_url(project, "detected", DEVICE_REF, "confirm")
    saved = await client.post(url, headers=alice_headers, json=_confirm_body())
    assert saved.status_code == 201
    silent(detect_local)
    response = await client.post(url, headers=alice_headers, json=connection_body())
    assert response.status_code == 409, response.text
    assert not detect_local.opened


async def test_connection_only_foreign_target_and_fresh_identity(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    detect_local: _DetectLocal,
) -> None:
    first_project, _ = await _detect_project(client, alice_headers)
    second_project, _ = await _detect_project(client, bob_headers)
    silent(detect_local)
    first = await client.post(
        _detect_url(first_project, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=connection_body(),
    )
    robot_id = first.json()["data"]["robot"]["id"]
    url = _detect_url(second_project, "detected", DEVICE_REF, "confirm")
    foreign = await client.post(
        url,
        headers=bob_headers,
        json=connection_body() | {"target": {"kind": "existing", "robot_id": robot_id}},
    )
    assert foreign.status_code == 404
    detect_local.devices[0]["identity"]["pid"] = 123
    changed = await client.post(url, headers=bob_headers, json=connection_body())
    assert changed.status_code == 409, changed.text
    assert not detect_local.opened
