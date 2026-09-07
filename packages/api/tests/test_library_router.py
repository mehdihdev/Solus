"""R4 library routes (docs/api/hardware.md §5): search and preview definitions, import a
platform into a new robot (parts under their categories, a LIBRARY-provenance config, a
reconciliation pass against detected devices), import one part into a robot. Scoped through
`ProjectCtx` (non-member → 404), MEMBER on writes, an event on every mutation."""

import uuid
from typing import Any

import pytest
from conftest import BOB, add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.hardware import library_router
from solus_api.models import DataEvent, GraphEntity, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_detect import _wire_device

SO101_ROLES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
DRONE_ADDRESSES = [
    "1:1",
    "servo:1",
    "servo:2",
    "servo:3",
    "servo:4",
    "1:1:imu",
    "1:1:gps",
    "1:1:baro",
]


class _Runner:
    """A local runtime that sees devices but has interrogated none of them."""

    def __init__(self, devices: list[dict[str, Any]]) -> None:
        self.devices = devices
        self.calls = 0

    def detect_devices(self) -> list[dict[str, Any]]:
        self.calls += 1
        return list(self.devices)


@pytest.fixture(autouse=True)
def _library_app(app: FastAPI) -> None:
    """Mount the router until main.py includes it; a real runner must never probe USB here."""
    if not any(getattr(route, "path", "") == library_router.router.prefix for route in app.routes):
        app.include_router(library_router.router)
    app.state.bench_local = None


# --------------------------------------------------------------------- helpers


async def _project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return str(project["id"]), str(team["id"])


def _url(project_id: str, *parts: str) -> str:
    suffix = "/".join(parts)
    return f"/api/v1/projects/{project_id}/hardware/library" + (f"/{suffix}" if suffix else "")


async def _import_platform(
    client: AsyncClient, headers: dict[str, str], project_id: str, definition_id: str, **body: Any
) -> dict[str, Any]:
    resp = await client.post(
        _url(project_id, "platforms", definition_id, "import"), headers=headers, json=body
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json()["data"])


async def _config(
    client: AsyncClient, headers: dict[str, str], project_id: str, robot_id: str
) -> dict[str, Any]:
    resp = await client.get(
        f"/api/v1/projects/{project_id}/hardware/robots/{robot_id}/config", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return dict(resp.json()["data"]["config"])


async def _parts_of(db: AsyncSession, robot_id: str) -> list[GraphEntity]:
    rows = await db.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.kind == "part",
            GraphEntity.attrs["robot_id"].astext == robot_id,
            GraphEntity.deleted_at.is_(None),
        )
        .order_by(GraphEntity.id)
    )
    return list(rows)


async def _consent(db: AsyncSession) -> None:
    user = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    user.data_collection_consent = True
    await db.commit()


# ------------------------------------------------------------------ list / get


async def test_list_without_a_query_lists_every_definition(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    resp = await client.get(_url(project_id), headers=alice_headers)
    assert resp.status_code == 200, resp.text
    hits = resp.json()["data"]
    assert len(hits) >= 20
    assert set(hits[0]) == {
        "kind",
        "id",
        "name",
        "manufacturer",
        "category",
        "machine_class",
        "summary",
    }
    assert {h["kind"] for h in hits} == {"part", "platform"}


async def test_search_finds_the_part_and_both_platforms_that_use_it(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    resp = await client.get(_url(project_id), headers=alice_headers, params={"q": "sts3215"})
    assert resp.status_code == 200, resp.text
    ids = {h["id"] for h in resp.json()["data"]}
    assert {"sts3215", "so101-follower", "so101-leader"} <= ids


async def test_list_filters_by_kind_and_bounds_limit(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    platforms = await client.get(
        _url(project_id), headers=alice_headers, params={"kind": "platform"}
    )
    assert platforms.status_code == 200, platforms.text
    assert {h["id"] for h in platforms.json()["data"]} == {
        "so101-follower",
        "so101-leader",
        "px4-quadrotor",
        "odrive-diff-base",
        "unitree-go2",
        "ur5e",
    }
    assert all(h["machine_class"] and h["category"] is None for h in platforms.json()["data"])
    two = await client.get(_url(project_id), headers=alice_headers, params={"limit": 2})
    assert len(two.json()["data"]) == 2
    for bad in ({"limit": 101}, {"limit": 0}, {"kind": "robot"}):
        resp = await client.get(_url(project_id), headers=alice_headers, params=bad)
        assert resp.status_code == 422, resp.text


async def test_get_returns_the_full_definition_and_404s_the_rest(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    part = await client.get(_url(project_id, "part", "sts3215"), headers=alice_headers)
    assert part.status_code == 200, part.text
    data = part.json()["data"]
    assert data["kind"] == "part" and data["driver_id"] == "feetech-sts"
    assert data["register_map"]["present_position"] == {"address": 56, "size": 2}
    platform = await client.get(
        _url(project_id, "platform", "so101-follower"), headers=alice_headers
    )
    assert platform.status_code == 200, platform.text
    assert [p["role"] for p in platform.json()["data"]["parts"]] == SO101_ROLES
    for kind, definition_id in (
        ("part", "nope"),
        ("platform", "sts3215"),
        ("part", "so101-follower"),
    ):
        resp = await client.get(_url(project_id, kind, definition_id), headers=alice_headers)
        assert resp.status_code == 404, resp.text
    bad_kind = await client.get(_url(project_id, "robot", "sts3215"), headers=alice_headers)
    assert bad_kind.status_code == 422, bad_kind.text
    bad_id = await client.get(_url(project_id, "part", "NOT AN ID"), headers=alice_headers)
    assert bad_id.status_code == 422, bad_id.text


# ------------------------------------------------------------- import platform


async def test_import_platform_creates_the_robot_its_parts_and_a_library_config(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    data = await _import_platform(client, alice_headers, project_id, "so101-follower")
    robot = data["robot"]
    assert robot["type"] == "physical_robot" and robot["name"] == "SO-101 follower arm"
    assert robot["properties"]["hardware_config_ref"] == data["config_entry_id"]
    assert len(data["part_ids"]) == 6 and data["suggestion_ids"] == []

    parts = await _parts_of(db, robot["id"])
    assert {str(p.id) for p in parts} == set(data["part_ids"])
    by_category: dict[str, list[GraphEntity]] = {}
    for part in parts:
        by_category.setdefault(part.attrs["category"], []).append(part)
    assert len(by_category["actuators"]) == 5 and len(by_category["end_effectors"]) == 1
    assert by_category["end_effectors"][0].attrs["role"] == "gripper"
    for part in parts:
        assert part.external_ref is None and part.origin == "manual"
        assert part.attrs["provenance"] == "library"
        assert part.attrs["definition_id"] == "sts3215"
        assert part.attrs["model"] == "Feetech STS3215"
        assert part.attrs["gear_ratio"] == "1/345"
        assert part.attrs["role"] in SO101_ROLES and part.name == part.attrs["role"]
        assert part.attrs["specs"]["resolution_steps"] == 4096

    config = await _config(client, alice_headers, project_id, robot["id"])
    assert config["identity"] is None
    assert config["protocol"] == {
        "driver_id": "feetech-sts",
        "params": {"baud": 1_000_000, "protocol_version": 0},
    }
    assert [e["address"] for e in config["bus_map"]] == [str(i) for i in range(1, 7)]
    assert [e["part_entity_id"] for e in config["bus_map"]] == data["part_ids"]
    channels = [config["parts"][e["part_entity_id"]]["telemetry"][0] for e in config["bus_map"]]
    assert [c["name"] for c in channels] == [f"{role}.position" for role in SO101_ROLES]
    assert [c["unit"] for c in channels] == ["deg"] * 5 + ["%"]
    assert {r["by"] for r in config["provenance"].values()} == {"library"}
    assert {r["source"] for r in config["provenance"].values()} == {"platform:so101-follower"}


async def test_import_platform_honours_a_name_and_validates_the_body(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    data = await _import_platform(
        client, alice_headers, project_id, "so101-leader", name="Bench leader"
    )
    assert data["robot"]["name"] == "Bench leader"
    for body in ({"name": ""}, {"name": 3}, {"colour": "red"}):
        resp = await client.post(
            _url(project_id, "platforms", "so101-leader", "import"),
            headers=alice_headers,
            json=body,
        )
        assert resp.status_code == 422, resp.text
    missing = await client.post(
        _url(project_id, "platforms", "nope", "import"), headers=alice_headers, json={}
    )
    assert missing.status_code == 404, missing.text


async def test_import_drone_places_parts_under_their_categories_on_one_bus(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    data = await _import_platform(client, alice_headers, project_id, "px4-quadrotor")
    parts = await _parts_of(db, data["robot"]["id"])
    categories = sorted(p.attrs["category"] for p in parts)
    assert categories == ["actuators"] * 4 + ["controllers"] + ["sensors"] * 3
    config = await _config(client, alice_headers, project_id, data["robot"]["id"])
    assert config["protocol"]["driver_id"] == "mavlink"
    assert [e["address"] for e in config["bus_map"]] == DRONE_ADDRESSES
    assert {e["protocol"] for e in config["bus_map"]} == {"mavlink"}
    names = {c["name"]: c["unit"] for part in config["parts"].values() for c in part["telemetry"]}
    assert names["motor_4.output"] == "us" and names["autopilot.attitude"] == "rad"


async def test_import_platform_without_a_driver_has_no_protocol(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    data = await _import_platform(client, alice_headers, project_id, "unitree-go2")
    assert len(data["part_ids"]) == 12
    config = await _config(client, alice_headers, project_id, data["robot"]["id"])
    assert config["protocol"] is None
    assert {e["protocol"] for e in config["bus_map"]} == {"ethernet"}


# ----------------------------------------------------------------- import part


async def test_import_part_into_a_robot(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    robot = await _import_platform(client, alice_headers, project_id, "ur5e")
    robot_id = robot["robot"]["id"]
    resp = await client.post(
        _url(project_id, "parts", "bmp390", "import"),
        headers=alice_headers,
        json={"robot_id": robot_id},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    entity = data["entity"]
    assert entity["type"] == "part" and entity["name"] == "Bosch BMP390"
    assert entity["properties"]["category"] == "sensors"
    assert entity["properties"]["definition_id"] == "bmp390"
    assert entity["properties"]["provenance"] == "library"
    assert entity["properties"]["manufacturer"] == "Bosch"
    assert data["config_entry_id"] == robot["config_entry_id"]

    config = await _config(client, alice_headers, project_id, robot_id)
    slot = config["parts"][entity["id"]]
    assert slot["lifecycle"] == "planned"
    assert {c["name"] for c in slot["telemetry"]} == {"bmp390.pressure", "bmp390.temperature"}
    assert config["provenance"][f"parts.{entity['id']}"] == {
        "by": "library",
        "source": "part:bmp390",
    }
    assert len(config["bus_map"]) == 6  # the platform's bus map is untouched

    overridden = await client.post(
        _url(project_id, "parts", "lipo-4s", "import"),
        headers=alice_headers,
        json={"robot_id": robot_id, "category": "structure"},
    )
    assert overridden.status_code == 201, overridden.text
    assert overridden.json()["data"]["entity"]["properties"]["category"] == "structure"
    parts = await _parts_of(db, robot_id)
    assert len(parts) == 8


async def test_import_part_404s_and_422s(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    robot = await _import_platform(client, alice_headers, project_id, "ur5e")
    robot_id = robot["robot"]["id"]
    unknown_part = await client.post(
        _url(project_id, "parts", "nope", "import"),
        headers=alice_headers,
        json={"robot_id": robot_id},
    )
    assert unknown_part.status_code == 404, unknown_part.text
    unknown_robot = await client.post(
        _url(project_id, "parts", "bmp390", "import"),
        headers=alice_headers,
        json={"robot_id": str(uuid.uuid4())},
    )
    assert unknown_robot.status_code == 404, unknown_robot.text
    for body in ({}, {"robot_id": robot_id, "category": "engines"}, {"robot_id": robot_id, "x": 1}):
        resp = await client.post(
            _url(project_id, "parts", "bmp390", "import"), headers=alice_headers, json=body
        )
        assert resp.status_code == 422, resp.text


async def test_import_part_cannot_reach_another_projects_robot(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_a, _ = await _project(client, alice_headers)
    team_b = await create_team(client, alice_headers, name="Other team")
    project_b = str((await create_project(client, alice_headers, team_b["id"]))["id"])
    robot_b = await _import_platform(client, alice_headers, project_b, "ur5e")
    resp = await client.post(
        _url(project_a, "parts", "bmp390", "import"),
        headers=alice_headers,
        json={"robot_id": robot_b["robot"]["id"]},
    )
    assert resp.status_code == 404, resp.text


# ----------------------------------------------------------------------- authz


@pytest.mark.parametrize("route", ["list", "get", "import_platform", "import_part"])
async def test_a_non_member_gets_404_on_every_library_route(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str], route: str
) -> None:
    project_id, _ = await _project(client, alice_headers)
    robot = await _import_platform(client, alice_headers, project_id, "ur5e")
    await me(client, bob_headers)
    if route == "list":
        resp = await client.get(_url(project_id), headers=bob_headers)
    elif route == "get":
        resp = await client.get(_url(project_id, "part", "sts3215"), headers=bob_headers)
    elif route == "import_platform":
        resp = await client.post(
            _url(project_id, "platforms", "so101-follower", "import"), headers=bob_headers, json={}
        )
    else:
        resp = await client.post(
            _url(project_id, "parts", "bmp390", "import"),
            headers=bob_headers,
            json={"robot_id": robot["robot"]["id"]},
        )
    assert resp.status_code == 404, resp.text


async def test_a_viewer_can_browse_but_cannot_import(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id, team_id = await _project(client, alice_headers)
    robot = await _import_platform(client, alice_headers, project_id, "ur5e")
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team_id, role="viewer")
    listed = await client.get(_url(project_id), headers=bob_headers, params={"q": "servo"})
    assert listed.status_code == 200, listed.text
    fetched = await client.get(_url(project_id, "platform", "ur5e"), headers=bob_headers)
    assert fetched.status_code == 200, fetched.text
    platform = await client.post(
        _url(project_id, "platforms", "so101-follower", "import"), headers=bob_headers, json={}
    )
    assert platform.status_code == 403, platform.text
    part = await client.post(
        _url(project_id, "parts", "bmp390", "import"),
        headers=bob_headers,
        json={"robot_id": robot["robot"]["id"]},
    )
    assert part.status_code == 403, part.text


async def test_a_member_can_import(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id, team_id = await _project(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team_id, role="member")
    data = await _import_platform(client, bob_headers, project_id, "odrive-diff-base")
    assert len(data["part_ids"]) == 4


# ---------------------------------------------------------------------- events


async def test_imports_emit_library_events_with_consent(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    silent = await _import_platform(client, alice_headers, project_id, "ur5e")
    await _consent(db)
    loud = await _import_platform(client, alice_headers, project_id, "so101-follower")
    resp = await client.post(
        _url(project_id, "parts", "bmp390", "import"),
        headers=alice_headers,
        json={"robot_id": loud["robot"]["id"]},
    )
    assert resp.status_code == 201, resp.text
    events = list(
        await db.scalars(
            select(DataEvent)
            .where(DataEvent.event_type == "hardware.library_imported")
            .order_by(DataEvent.created_at)
        )
    )
    assert [e.payload for e in events] == [
        {"definition_id": "so101-follower", "robot_id": loud["robot"]["id"], "parts": 6},
        {"definition_id": "bmp390", "robot_id": loud["robot"]["id"], "parts": 1},
    ]
    assert all(e.payload["robot_id"] != silent["robot"]["id"] for e in events)
    assert all(str(e.project_id) == project_id for e in events)


# -------------------------------------------------------------- reconciliation


async def test_import_with_a_runner_that_saw_a_device_without_bus_evidence_is_honestly_empty(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    project_id, _ = await _project(client, alice_headers)
    runner = _Runner([_wire_device(), _wire_device(None)])
    app.state.bench_local = runner
    data = await _import_platform(client, alice_headers, project_id, "so101-follower")
    assert runner.calls == 1
    assert data["suggestion_ids"] == []
    inbox = await client.get(
        f"/api/v1/projects/{project_id}/hardware/suggestions", headers=alice_headers
    )
    assert inbox.status_code == 200 and inbox.json()["data"] == []
