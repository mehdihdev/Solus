"""GET/PATCH /api/v1/projects/{p}/bench/view (docs/api/bench-view.md §2–§3)."""

from __future__ import annotations

import uuid
from typing import Any

from conftest import BOB, add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient, Response
from solus_api.bridge.service import ConnectRateLimiter

DEV = "usb:5A7A/3"


def _url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/bench/view"


async def _project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return project["id"], team["id"]


def _pin(signal: str = "shoulder_lift.position", **patch: Any) -> dict[str, Any]:
    return {
        "kind": "set_display",
        "target": {"kind": "signal", "device_id": DEV, "signal": signal},
        "patch": patch or {"pinned": True},
    }


async def _patch(
    client: AsyncClient, headers: dict[str, str], project_id: str, body: dict[str, Any]
) -> Response:
    return await client.patch(_url(project_id), json=body, headers=headers)


async def test_get_returns_the_default_view(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    response = await client.get(_url(project_id), headers=alice_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "data": {"version": 0, "display": [], "derived": [], "updated_at": None}
    }


async def test_patch_happy_path_returns_version_view_and_inverse_ops(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    expression = f'abs(sig("{DEV}", "elbow.position"))'
    response = await _patch(
        client,
        alice_headers,
        project_id,
        {
            "version": 0,
            "ops": [
                _pin(unit="rad"),
                {"kind": "upsert_derived", "name": "Elbow", "expression": expression},
            ],
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["version"] == 1
    assert data["view"]["version"] == 1
    assert data["view"]["display"][0]["unit"] == "rad"
    derived = data["view"]["derived"][0]
    assert derived["node_count"] == 2
    assert derived["refs"] == [{"device_id": DEV, "signal": "elbow.position"}]
    assert data["inverse_ops"] == [
        {"kind": "delete_derived", "id": derived["id"]},
        _pin(unit=None),
    ]
    got = (await client.get(_url(project_id), headers=alice_headers)).json()["data"]
    assert got["version"] == 1 and got["display"] == data["view"]["display"]
    assert "updated_by" not in got

    undone = await _patch(
        client,
        alice_headers,
        project_id,
        {"version": 1, "ops": data["inverse_ops"], "undo": True},
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["data"]["view"]["display"] == []
    assert undone.json()["data"]["view"]["derived"] == []


async def test_unauthenticated_is_401(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    project_id, _ = await _project(client, alice_headers)
    assert (await client.get(_url(project_id))).status_code == 401
    response = await client.patch(_url(project_id), json={"version": 0, "ops": [_pin()]})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_viewer_reads_but_gets_403_on_patch_even_with_a_bad_body(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id, team_id = await _project(client, alice_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team_id, role="viewer")
    assert (await client.get(_url(project_id), headers=bob_headers)).status_code == 200
    for body in ({"version": 0, "ops": [_pin()]}, {"version": 0, "ops": [], "junk": 1}):
        response = await _patch(client, bob_headers, project_id, body)
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "forbidden"


async def test_member_can_write(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id, team_id = await _project(client, alice_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team_id)
    response = await _patch(client, bob_headers, project_id, {"version": 0, "ops": [_pin()]})
    assert response.status_code == 200, response.text


async def test_stale_version_is_409_with_current_version_and_writes_nothing(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    assert (
        await _patch(client, alice_headers, project_id, {"version": 0, "ops": [_pin()]})
    ).status_code == 200
    response = await _patch(
        client, alice_headers, project_id, {"version": 0, "ops": [_pin("other")]}
    )
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "conflict"
    assert error["details"] == [{"current_version": 1}]
    got = (await client.get(_url(project_id), headers=alice_headers)).json()["data"]
    assert got["version"] == 1 and len(got["display"]) == 1


async def test_validation_errors_are_422(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    bodies: list[Any] = [
        {"version": 0, "ops": [_pin()], "unknown": True},
        {"version": 0, "ops": [_pin()] * 33},
        {"version": 0, "ops": []},
        {"version": 0, "ops": [{**_pin(), "patch": {}}]},
        {"version": 0, "ops": [_pin(order=4096)]},
    ]
    for body in bodies:
        response = await _patch(client, alice_headers, project_id, body)
        assert response.status_code == 422, (body, response.text)
        assert response.json()["error"]["code"] == "validation_error"


async def test_non_finite_number_is_422_not_500(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    content = (
        '{"version": 0, "ops": [{"kind": "set_display", "target": {"kind": "signal", '
        '"device_id": "d", "signal": "s"}, "patch": {"limits": {"min": NaN, "max": 1}}}]}'
    )
    response = await client.patch(
        _url(project_id),
        content=content,
        headers={**alice_headers, "content-type": "application/json"},
    )
    assert response.status_code == 422, response.text


async def test_expression_error_is_422_with_detail(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    response = await _patch(
        client,
        alice_headers,
        project_id,
        {
            "version": 0,
            "ops": [{"kind": "upsert_derived", "name": "Bad", "expression": 'sig("a", "b") *'}],
        },
    )
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "expression_error"
    assert error["details"][0]["op_index"] == 0
    assert error["details"][0]["code"] == "syntax"


async def test_unknown_derived_id_is_404(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    response = await _patch(
        client,
        alice_headers,
        project_id,
        {"version": 0, "ops": [{"kind": "delete_derived", "id": str(uuid.uuid4())}]},
    )
    assert response.status_code == 404, response.text


async def test_patch_is_rate_limited_per_user(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    app.state.bench_view_limiter = ConnectRateLimiter(2)
    statuses = []
    for version in range(3):
        response = await _patch(
            client, alice_headers, project_id, {"version": version, "ops": [_pin(f"s{version}")]}
        )
        statuses.append(response.status_code)
    assert statuses == [200, 200, 429]
    assert response.json()["error"]["code"] == "rate_limited"
    assert (await client.get(_url(project_id), headers=alice_headers)).status_code == 200


def test_default_rate_limit_is_120_per_minute() -> None:
    from solus_api.livebench.view.router import PATCHES_PER_MINUTE

    assert PATCHES_PER_MINUTE == 120
