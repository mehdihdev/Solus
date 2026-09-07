"""R5 hardware onboarding routes (docs/api/hardware.md §2-3, §7, §8).

`/api/v1/projects/{project_id}/hardware/...` — the config document (GET/PUT), authored
parts + lifecycle promotion, and the durable link-suggestion inbox (GET/accept/reject).
Detection (R2) and library (R4) routes are out of scope here.
"""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from conftest import BOB, add_member, create_project, create_team, me
from httpx import AsyncClient
from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef
from solus_api.hardware.links import LinkSuggestion, LinkTier, persist_suggestions
from solus_api.models import DataEvent, GraphEdge, GraphEntity, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

FIXTURES = Path(__file__).parent / "fixtures" / "hardware"


# --------------------------------------------------------------------- helpers


async def _hw_project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return project["id"], team["id"]


def _hw_url(project_id: str, *parts: str) -> str:
    suffix = "/".join(parts)
    return f"/api/v1/projects/{project_id}/hardware" + (f"/{suffix}" if suffix else "")


async def _robot(client: AsyncClient, headers: dict[str, str], project_id: str) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/entities",
        headers=headers,
        json={"type": "physical_robot"},
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json()["data"])


async def _hw_get_config(
    client: AsyncClient, headers: dict[str, str], project_id: str, robot_id: str
) -> dict[str, Any]:
    resp = await client.get(_hw_url(project_id, "robots", robot_id, "config"), headers=headers)
    assert resp.status_code == 200, resp.text
    return dict(resp.json()["data"])


async def _hw_category(db: AsyncSession, robot_id: str, category: str) -> uuid.UUID:
    node = await db.scalar(
        select(GraphEntity).where(
            GraphEntity.kind == "robot_category",
            GraphEntity.attrs["robot_id"].astext == robot_id,
            GraphEntity.attrs["category"].astext == category,
            GraphEntity.deleted_at.is_(None),
        )
    )
    assert node is not None
    return node.id


def _serial_arm_for(robot_id: str) -> dict[str, Any]:
    raw = json.loads((FIXTURES / "serial_arm.json").read_text())
    raw["robot_entity_id"] = robot_id
    return dict(raw)


def _link_suggestion(subject_ref: str, candidate_robot_id: uuid.UUID) -> LinkSuggestion:
    return LinkSuggestion(
        subject_ref=subject_ref,
        subject_kind="part",
        candidate_robot_id=candidate_robot_id,
        confidence=0.80,
        tier=LinkTier.HIGH,
        evidence=[
            ModalityMatch(
                modality=Modality.BUS_ENUMERATION,
                source_ref=SourceRef(source_connector="bench", external_ref=subject_ref),
                confidence=0.80,
                state=MatchState.MATCHED,
                evidence={"matched_on": "bus_enumeration"},
            )
        ],
        reason="bus enumeration matched a free slot",
    )


async def _consent(db: AsyncSession) -> None:
    user = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    user.data_collection_consent = True
    await db.commit()


# --------------------------------------------------------------------- config


async def test_get_config_on_a_fresh_robot_creates_an_empty_document_and_backfills_the_ref(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    data = await _hw_get_config(client, alice_headers, project_id, robot["id"])
    assert data["robot_entity_id"] == robot["id"]
    assert data["config"]["schema_version"] == 1
    assert data["config"]["parts"] == {}
    assert data["config"]["bus_map"] == []
    entry_id = data["entry_id"]

    refreshed = await client.get(
        f"/api/v1/projects/{project_id}/entities/{robot['id']}", headers=alice_headers
    )
    assert refreshed.json()["data"]["properties"]["hardware_config_ref"] == entry_id

    solus = await client.get(f"/api/v1/projects/{project_id}/solus", headers=alice_headers)
    hardware_entries = solus.json()["data"]["sections"]["hardware"]
    assert len(hardware_entries) == 1
    assert hardware_entries[0]["kind"] == "config"
    assert hardware_entries[0]["payload"] is not None
    assert hardware_entries[0]["entity_id"] is not None


async def test_get_config_is_idempotent_across_repeat_reads(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    first = await _hw_get_config(client, alice_headers, project_id, robot["id"])
    second = await _hw_get_config(client, alice_headers, project_id, robot["id"])
    assert first["entry_id"] == second["entry_id"]
    solus = await client.get(f"/api/v1/projects/{project_id}/solus", headers=alice_headers)
    assert len(solus.json()["data"]["sections"]["hardware"]) == 1


async def test_put_config_replaces_the_document(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    resp = await client.put(
        _hw_url(project_id, "robots", robot["id"], "config"),
        headers=alice_headers,
        json={"config": _serial_arm_for(robot["id"])},
    )
    assert resp.status_code == 200, resp.text
    fetched = await _hw_get_config(client, alice_headers, project_id, robot["id"])
    assert fetched["config"]["identity"]["binding"] == "5B42134331"
    assert fetched["config"]["protocol"]["driver_id"] == "feetech-sts"
    assert len(fetched["config"]["bus_map"]) == 6


async def test_put_config_rejects_a_mismatched_robot_entity_id(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    resp = await client.put(
        _hw_url(project_id, "robots", robot["id"], "config"),
        headers=alice_headers,
        json={"config": _serial_arm_for(str(uuid.uuid4()))},
    )
    assert resp.status_code == 422, resp.text


async def test_put_config_rejects_an_unknown_top_level_field(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    body = _serial_arm_for(robot["id"])
    body["unexpected"] = True
    resp = await client.put(
        _hw_url(project_id, "robots", robot["id"], "config"),
        headers=alice_headers,
        json={"config": body},
    )
    assert resp.status_code == 422, resp.text


async def test_put_config_rejects_missing_provenance(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    body = _serial_arm_for(robot["id"])
    body["provenance"] = {}
    resp = await client.put(
        _hw_url(project_id, "robots", robot["id"], "config"),
        headers=alice_headers,
        json={"config": body},
    )
    assert resp.status_code == 422, resp.text


async def test_put_config_rejects_a_schema_version_other_than_one(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    body = _serial_arm_for(robot["id"])
    body["schema_version"] = 2
    resp = await client.put(
        _hw_url(project_id, "robots", robot["id"], "config"),
        headers=alice_headers,
        json={"config": body},
    )
    assert resp.status_code == 422, resp.text


async def test_get_config_for_an_unknown_robot_is_404(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    resp = await client.get(
        _hw_url(project_id, "robots", str(uuid.uuid4()), "config"), headers=alice_headers
    )
    assert resp.status_code == 404, resp.text


async def test_get_config_for_a_robot_category_entity_is_404(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    category_id = await _hw_category(db, robot["id"], "sensors")
    resp = await client.get(
        _hw_url(project_id, "robots", str(category_id), "config"), headers=alice_headers
    )
    assert resp.status_code == 404, resp.text


async def test_get_config_without_a_bearer_token_is_401(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    resp = await client.get(_hw_url(project_id, "robots", robot["id"], "config"))
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------- parts


async def test_post_parts_creates_a_contained_planned_part_recorded_in_the_config(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    specs = {"interface": "I2C", "supply_v": 3.3, "range": "300-1250 hPa"}
    resp = await client.post(
        _hw_url(project_id, "robots", robot["id"], "parts"),
        headers=alice_headers,
        json={"name": "Bosch BMP390", "category": "sensors", "specs": specs},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    entity = data["entity"]
    assert entity["type"] == "part"
    assert entity["name"] == "Bosch BMP390"
    assert entity["properties"]["category"] == "sensors"
    assert entity["properties"]["specs"] == specs
    assert "config_entry_id" in data

    category_id = await _hw_category(db, robot["id"], "sensors")
    edge = await db.scalar(
        select(GraphEdge).where(
            GraphEdge.src_id == category_id,
            GraphEdge.dst_id == uuid.UUID(entity["id"]),
            GraphEdge.relation_type == "contains",
            GraphEdge.deleted_at.is_(None),
        )
    )
    assert edge is not None
    assert edge.origin == "manual" and edge.source_id is None

    config = await _hw_get_config(client, alice_headers, project_id, robot["id"])
    part_id = entity["id"]
    assert config["config"]["parts"][part_id]["lifecycle"] == "planned"
    provenance = config["config"]["provenance"]
    resolved = [
        key
        for key, record in provenance.items()
        if record["by"] == "user"
        and (f"parts.{part_id}" == key or f"parts.{part_id}".startswith(f"{key}."))
    ]
    assert resolved


async def test_post_parts_accepts_an_explicit_lifecycle_state(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    resp = await client.post(
        _hw_url(project_id, "robots", robot["id"], "parts"),
        headers=alice_headers,
        json={
            "name": "BLHeli_32 35A ESC",
            "category": "actuators",
            "specs": {"interface": "PWM", "supply_v": 16.0, "rated_output": "35 A"},
            "lifecycle": "ordered",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    config = await _hw_get_config(client, alice_headers, project_id, robot["id"])
    assert config["config"]["parts"][data["entity"]["id"]]["lifecycle"] == "ordered"


@pytest.mark.parametrize(
    "body",
    [
        {"name": "Thing", "category": "not_a_category", "specs": {}},
        {"name": "Thing", "category": "sensors", "specs": {f"k{i}": i for i in range(33)}},
        {"name": "Thing", "category": "sensors", "specs": {}, "unexpected": True},
        {"name": "  ", "category": "sensors", "specs": {}},
    ],
)
async def test_post_parts_rejects_invalid_bodies(
    client: AsyncClient, alice_headers: dict[str, str], body: dict[str, Any]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    resp = await client.post(
        _hw_url(project_id, "robots", robot["id"], "parts"), headers=alice_headers, json=body
    )
    assert resp.status_code == 422, resp.text


# ----------------------------------------------------------------- lifecycle


async def test_post_lifecycle_promotes_the_part_without_changing_its_entity_or_edge(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    created = (
        await client.post(
            _hw_url(project_id, "robots", robot["id"], "parts"),
            headers=alice_headers,
            json={"name": "Bosch BMP390", "category": "sensors", "specs": {"interface": "I2C"}},
        )
    ).json()["data"]
    part_id = created["entity"]["id"]
    edge_before = await db.scalar(
        select(GraphEdge).where(
            GraphEdge.dst_id == uuid.UUID(part_id), GraphEdge.relation_type == "contains"
        )
    )
    assert edge_before is not None

    resp = await client.post(
        _hw_url(project_id, "robots", robot["id"], "parts", part_id, "lifecycle"),
        headers=alice_headers,
        json={"state": "live"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["part_id"] == part_id
    assert data["config"]["lifecycle"] == "live"

    edge_after = await db.scalar(
        select(GraphEdge).where(GraphEdge.id == edge_before.id, GraphEdge.deleted_at.is_(None))
    )
    assert edge_after is not None

    entity_after = await client.get(
        f"/api/v1/projects/{project_id}/entities/{part_id}", headers=alice_headers
    )
    assert entity_after.json()["data"]["id"] == part_id


async def test_post_lifecycle_for_a_part_not_owned_by_this_robot_is_404(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    resp = await client.post(
        _hw_url(project_id, "robots", robot["id"], "parts", str(uuid.uuid4()), "lifecycle"),
        headers=alice_headers,
        json={"state": "live"},
    )
    assert resp.status_code == 404, resp.text


async def test_post_lifecycle_rejects_an_unknown_state(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    created = (
        await client.post(
            _hw_url(project_id, "robots", robot["id"], "parts"),
            headers=alice_headers,
            json={"name": "Bosch BMP390", "category": "sensors", "specs": {}},
        )
    ).json()["data"]
    resp = await client.post(
        _hw_url(project_id, "robots", robot["id"], "parts", created["entity"]["id"], "lifecycle"),
        headers=alice_headers,
        json={"state": "not_a_state"},
    )
    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------- suggestions


async def test_get_suggestions_is_empty_on_a_fresh_project(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    resp = await client.get(_hw_url(project_id, "suggestions"), headers=alice_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []


async def test_suggestions_lifecycle_across_get_accept_and_conflict(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot_a = await _robot(client, alice_headers, project_id)
    robot_b = await _robot(client, alice_headers, project_id)
    rows = await persist_suggestions(
        db,
        uuid.UUID(project_id),
        [
            _link_suggestion("usb:AAAA/6", uuid.UUID(robot_a["id"])),
            _link_suggestion("usb:AAAA/6", uuid.UUID(robot_b["id"])),
        ],
    )
    await db.commit()

    listed = await client.get(_hw_url(project_id, "suggestions"), headers=alice_headers)
    assert listed.status_code == 200, listed.text
    assert {row["id"] for row in listed.json()["data"]} == {str(row.id) for row in rows}

    accepted_none_yet = await client.get(
        _hw_url(project_id, "suggestions"), headers=alice_headers, params={"status": "accepted"}
    )
    assert accepted_none_yet.json()["data"] == []

    accept = await client.post(
        _hw_url(project_id, "suggestions", str(rows[0].id), "accept"), headers=alice_headers
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["data"]["status"] == "accepted"

    superseded = await client.get(
        _hw_url(project_id, "suggestions"),
        headers=alice_headers,
        params={"status": "superseded"},
    )
    assert [row["id"] for row in superseded.json()["data"]] == [str(rows[1].id)]

    accept_again = await client.post(
        _hw_url(project_id, "suggestions", str(rows[0].id), "accept"), headers=alice_headers
    )
    assert accept_again.status_code == 409, accept_again.text


async def test_reject_a_suggestion_records_the_reason(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    rows = await persist_suggestions(
        db, uuid.UUID(project_id), [_link_suggestion("usb:BBBB/1", uuid.UUID(robot["id"]))]
    )
    await db.commit()
    resp = await client.post(
        _hw_url(project_id, "suggestions", str(rows[0].id), "reject"),
        headers=alice_headers,
        json={"reason": "wrong arm"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "rejected"
    assert data["reason"] == "wrong arm"


async def test_accept_an_unknown_suggestion_is_404(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    resp = await client.post(
        _hw_url(project_id, "suggestions", str(uuid.uuid4()), "accept"), headers=alice_headers
    )
    assert resp.status_code == 404, resp.text


async def test_reject_an_unknown_suggestion_is_404(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    resp = await client.post(
        _hw_url(project_id, "suggestions", str(uuid.uuid4()), "reject"),
        headers=alice_headers,
        json={"reason": "nah"},
    )
    assert resp.status_code == 404, resp.text


# ------------------------------------------------------------------ authz


@pytest.mark.parametrize(
    "route",
    ["config_get", "config_put", "parts_post", "suggestions_get", "suggestions_accept"],
)
async def test_a_non_member_gets_404_on_every_hardware_route(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    route: str,
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    await me(client, bob_headers)
    rows = await persist_suggestions(
        db, uuid.UUID(project_id), [_link_suggestion("usb:CCCC/1", uuid.UUID(robot["id"]))]
    )
    await db.commit()
    suggestion_id = str(rows[0].id)

    if route == "config_get":
        resp = await client.get(
            _hw_url(project_id, "robots", robot["id"], "config"), headers=bob_headers
        )
    elif route == "config_put":
        resp = await client.put(
            _hw_url(project_id, "robots", robot["id"], "config"),
            headers=bob_headers,
            json={"config": _serial_arm_for(robot["id"])},
        )
    elif route == "parts_post":
        resp = await client.post(
            _hw_url(project_id, "robots", robot["id"], "parts"),
            headers=bob_headers,
            json={"name": "X", "category": "sensors", "specs": {}},
        )
    elif route == "suggestions_get":
        resp = await client.get(_hw_url(project_id, "suggestions"), headers=bob_headers)
    else:
        resp = await client.post(
            _hw_url(project_id, "suggestions", suggestion_id, "accept"), headers=bob_headers
        )
    assert resp.status_code == 404, resp.text


async def test_a_viewer_can_read_config_but_cannot_write(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_id, team_id = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team_id, role="viewer")
    created = (
        await client.post(
            _hw_url(project_id, "robots", robot["id"], "parts"),
            headers=alice_headers,
            json={"name": "Bosch BMP390", "category": "sensors", "specs": {}},
        )
    ).json()["data"]
    rows = await persist_suggestions(
        db, uuid.UUID(project_id), [_link_suggestion("usb:DDDD/1", uuid.UUID(robot["id"]))]
    )
    await db.commit()

    read = await client.get(
        _hw_url(project_id, "robots", robot["id"], "config"), headers=bob_headers
    )
    assert read.status_code == 200, read.text

    put = await client.put(
        _hw_url(project_id, "robots", robot["id"], "config"),
        headers=bob_headers,
        json={"config": _serial_arm_for(robot["id"])},
    )
    assert put.status_code == 403, put.text

    post_part = await client.post(
        _hw_url(project_id, "robots", robot["id"], "parts"),
        headers=bob_headers,
        json={"name": "X", "category": "sensors", "specs": {}},
    )
    assert post_part.status_code == 403, post_part.text

    lifecycle = await client.post(
        _hw_url(project_id, "robots", robot["id"], "parts", created["entity"]["id"], "lifecycle"),
        headers=bob_headers,
        json={"state": "live"},
    )
    assert lifecycle.status_code == 403, lifecycle.text

    accept = await client.post(
        _hw_url(project_id, "suggestions", str(rows[0].id), "accept"), headers=bob_headers
    )
    assert accept.status_code == 403, accept.text


# ------------------------------------------------------------------- events


async def test_write_routes_emit_data_events_when_consented(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    await _consent(db)

    put = await client.put(
        _hw_url(project_id, "robots", robot["id"], "config"),
        headers=alice_headers,
        json={"config": _serial_arm_for(robot["id"])},
    )
    assert put.status_code == 200, put.text

    part = (
        await client.post(
            _hw_url(project_id, "robots", robot["id"], "parts"),
            headers=alice_headers,
            json={"name": "Bosch BMP390", "category": "sensors", "specs": {}},
        )
    ).json()["data"]

    lifecycle = await client.post(
        _hw_url(project_id, "robots", robot["id"], "parts", part["entity"]["id"], "lifecycle"),
        headers=alice_headers,
        json={"state": "live"},
    )
    assert lifecycle.status_code == 200, lifecycle.text

    rows = await persist_suggestions(
        db, uuid.UUID(project_id), [_link_suggestion("usb:EEEE/1", uuid.UUID(robot["id"]))]
    )
    await db.commit()
    accept = await client.post(
        _hw_url(project_id, "suggestions", str(rows[0].id), "accept"), headers=alice_headers
    )
    assert accept.status_code == 200, accept.text

    events = list(
        await db.scalars(
            select(DataEvent)
            .where(DataEvent.event_type.like("hardware.%"))
            .execution_options(populate_existing=True)
        )
    )
    assert {event.event_type for event in events} == {
        "hardware.config_updated",
        "hardware.part_created",
        "hardware.lifecycle_promoted",
        "hardware.suggestion_decided",
    }
