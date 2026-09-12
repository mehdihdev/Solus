"""R2 detection routes (docs/api/hardware.md §4): the Detected card lists devices at whichever
level is known; propose interrogates safely and asks when the repo matches twice; confirm
creates the robot, its parts (external_ref = <device ref>/<address>), the config with
provenance, and opens the session. Nothing is accepted that the body did not name."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from conftest import BOB, add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.models import DataEvent, GraphEdge, GraphEntity, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_bench_router import FakeLocal, TapConn

DEVICE_REF = "usb:5B42134331"


def _wire_device(ref: str | None = DEVICE_REF) -> dict[str, Any]:
    return {
        "transport": "usb_serial",
        "device_ref": ref,
        "identity": (
            {
                "kind": "usb_serial",
                "binding": "5B42134331",
                "vid": 0x1A86,
                "pid": 0x55D3,
                "last_seen_path": "/dev/serial/by-id/usb-1a86-5B42134331",
            }
            if ref
            else None
        ),
        "level": "transport",
        "board": "USB-serial bridge",
        "board_class": "usb_bridge",
        "mcu_known": False,
        "confidence": 0.3,
        "evidence": [],
        "ambiguous": ref is None,
        "last_seen_path": "/dev/serial/by-id/usb-1a86-5B42134331",
        "vid": 0x1A86,
        "pid": 0x55D3,
    }


def _bus_match(address: str) -> dict[str, Any]:
    return {
        "modality": "bus_enumeration",
        "source_ref": {
            "graph_entity_id": None,
            "source_connector": "demo-bus",
            "external_ref": f"{DEVICE_REF}/{address}",
        },
        "confidence": 0.92,
        "state": "matched",
        "evidence": {"matched_on": "model_register", "value": "M1"},
    }


def _wire_proposal(*, repo_matches: int = 0) -> dict[str, Any]:
    names = ["shoulder_pan", "gripper"]
    matches: list[dict[str, Any]] = [
        {
            "config_id": f"repo:cfg{i}",
            "parser_id": "test",
            "label": f"cfg{i}",
            "source": f"/repo/cfg{i}.py",
            "protocol_hint": "demo-bus",
            "parts": [
                {
                    "name": names[j],
                    "address": str(j + 1),
                    "model": "M1",
                    "calibration_mode": "degrees" if j == 0 else "range_0_100",
                    "calibration": {
                        "homing_offset": -2043 + i,
                        "range_min": 719,
                        "range_max": 3441,
                    },
                    "calibration_source": f"/cal/cfg{i}.json",
                }
                for j in range(2)
            ],
            "port_hint": None,
            "calibration_source": f"/cal/cfg{i}.json",
            "params": {},
        }
        for i in range(repo_matches)
    ]
    agreed = repo_matches >= 1
    return {
        "device_ref": DEVICE_REF,
        "identity": _wire_device()["identity"],
        "level": "protocol",
        "summary": "2 servos on a serial servo bus (ids 1–2, M1)",
        "driver_id": "demo-bus",
        "params": {"baud": 1_000_000, "protocol_version": 0},
        "rows": [
            {
                "id": f"{DEVICE_REF}/{address}",
                "subject": f"M1 at address {address}",
                "address": address,
                "model": "M1",
                "proposed_function": names[index] if agreed else None,
                "confidence": 0.92,
                "evidence": [_bus_match(address)],
                "provenance": "repo" if agreed else "bus",
            }
            for index, address in enumerate(("1", "2"))
        ],
        "repo_matches": matches,
        "disambiguation": (
            {
                "question": "Two configs in your repo match this device — which is it?",
                "options": [m["config_id"] for m in matches],
            }
            if repo_matches > 1
            else None
        ),
        "confidence": 0.92,
        "evidence": [_bus_match("1"), _bus_match("2")],
        "calibration_source": matches[0]["calibration_source"] if repo_matches == 1 else None,
    }


class _DetectLocal(FakeLocal):
    def __init__(self) -> None:
        super().__init__()
        self.devices: list[dict[str, Any]] = [_wire_device()]
        self.proposal: dict[str, Any] | None = _wire_proposal()
        self.proposals: dict[str, dict[str, Any]] = {}  # per device ref, consulted first
        self.propose_calls: list[dict[str, Any]] = []

    def detect_devices(self) -> list[dict[str, Any]]:
        return list(self.devices)

    def propose_device(
        self, device_ref: str, *, repo_root: str | None = None, budget_s: float = 0.5
    ) -> dict[str, Any] | None:
        self.propose_calls.append({"device_ref": device_ref, "repo_root": repo_root})
        if device_ref in self.proposals:
            return dict(self.proposals[device_ref])
        if self.proposal is None or self.proposal["device_ref"] != device_ref:
            return None
        return dict(self.proposal)

    async def open_robot(self, config: dict[str, Any], *, project_id: uuid.UUID) -> TapConn:
        return await self._open("robot", config=config, project_id=project_id)


@pytest.fixture
def detect_local(app: FastAPI, tmp_path: Path) -> _DetectLocal:
    fake = _DetectLocal()
    app.state.bench_local = fake
    if hasattr(app.state, "hardware_connections"):
        app.state.hardware_connections.local = fake
    return fake


async def _detect_project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return str(project["id"]), str(team["id"])


def _detect_url(project_id: str, *parts: str) -> str:
    return f"/api/v1/projects/{project_id}/hardware/" + "/".join(parts)


def _confirm_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "target": {"kind": "new", "name": "Follower"},
        "accepted": [
            {"row_id": f"{DEVICE_REF}/1", "function_name": "shoulder_pan", "category": "actuators"},
            {"row_id": f"{DEVICE_REF}/2", "function_name": "gripper", "category": "end_effectors"},
        ],
        "start_session": False,
    }
    body.update(overrides)
    return body


# -------------------------------------------------------------------- detected


async def test_detected_lists_devices_at_their_honest_level(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    resp = await client.get(_detect_url(project_id, "detected"), headers=alice_headers)
    assert resp.status_code == 200, resp.text
    [device] = resp.json()["data"]
    assert device["device_ref"] == DEVICE_REF
    assert device["level"] == "transport" and device["mcu_known"] is False
    assert device["identity"]["binding"] == "5B42134331"


async def test_detected_without_a_runner_is_honestly_unavailable(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    app.state.bench_local = None
    resp = await client.get(_detect_url(project_id, "detected"), headers=alice_headers)
    assert resp.status_code == 503, resp.text
    assert resp.json()["error"]["code"] == "source_unavailable"


# --------------------------------------------------------------------- propose


async def test_propose_returns_the_proposal_and_records_an_event(
    client: AsyncClient,
    alice_headers: dict[str, str],
    detect_local: _DetectLocal,
    db: AsyncSession,
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    user = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    user.data_collection_consent = True
    await db.commit()
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"), headers=alice_headers, json={}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["device_ref"] == DEVICE_REF and data["driver_id"] == "demo-bus"
    assert [r["address"] for r in data["rows"]] == ["1", "2"]
    assert data["disambiguation"] is None
    assert detect_local.propose_calls == [{"device_ref": DEVICE_REF, "repo_root": None}]
    events = list(
        await db.scalars(select(DataEvent).where(DataEvent.event_type == "hardware.proposal_built"))
    )
    assert len(events) == 1 and events[0].payload["rows"] == 2


async def test_propose_refuses_remote_paths_and_preserves_disambiguation(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal, tmp_path: Any
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    detect_local.proposal = _wire_proposal(repo_matches=2)
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"),
        headers=alice_headers,
        json={"repo_root": str(tmp_path)},
    )
    assert resp.status_code == 422, resp.text
    assert detect_local.propose_calls == []
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"),
        headers=alice_headers,
        json={},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["disambiguation"]["options"] == ["repo:cfg0", "repo:cfg1"]
    assert detect_local.propose_calls[0]["repo_root"] is None


async def test_propose_rejects_a_repo_root_that_is_not_a_directory(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    for bad in ("relative/path", "/definitely/not/here"):
        resp = await client.post(
            _detect_url(project_id, "detected", DEVICE_REF, "propose"),
            headers=alice_headers,
            json={"repo_root": bad},
        )
        assert resp.status_code == 422, resp.text


async def test_propose_for_an_unknown_device_is_404(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    resp = await client.post(
        _detect_url(project_id, "detected", "usb:NOPE", "propose"), headers=alice_headers, json={}
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "device_not_found"


# --------------------------------------------------------------------- confirm


async def test_confirm_creates_the_robot_parts_config_and_optionally_the_session(
    client: AsyncClient,
    alice_headers: dict[str, str],
    detect_local: _DetectLocal,
    db: AsyncSession,
    app: FastAPI,
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(start_session=True),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    robot = data["robot"]
    assert robot["type"] == "physical_robot" and robot["name"] == "Follower"
    assert robot["origin"] == "manual"
    assert len(data["part_ids"]) == 2
    assert data["session_id"] is None
    assert robot["properties"]["connection"]["status"] == "connecting"
    await app.state.hardware_connections.drain()
    assert detect_local.opened[0]["kind"] == "robot"

    parts = list(
        await db.scalars(
            select(GraphEntity).where(GraphEntity.id.in_([uuid.UUID(p) for p in data["part_ids"]]))
        )
    )
    by_ref = {p.external_ref: p for p in parts}
    assert set(by_ref) == {f"{DEVICE_REF}/1", f"{DEVICE_REF}/2"}
    assert by_ref[f"{DEVICE_REF}/1"].name == "shoulder_pan"
    assert by_ref[f"{DEVICE_REF}/1"].attrs["category"] == "actuators"
    assert by_ref[f"{DEVICE_REF}/2"].attrs["category"] == "end_effectors"
    assert all(p.origin == "manual" and p.source_id is None for p in parts)
    for part in parts:
        edge = await db.scalar(
            select(GraphEdge).where(
                GraphEdge.dst_id == part.id,
                GraphEdge.relation_type == "contains",
                GraphEdge.deleted_at.is_(None),
            )
        )
        assert edge is not None
        category = await db.get(GraphEntity, edge.src_id)
        assert category is not None and category.kind == "robot_category"
        assert category.attrs["category"] == part.attrs["category"]

    config_resp = await client.get(
        _detect_url(project_id, "robots", robot["id"], "config"), headers=alice_headers
    )
    config = config_resp.json()["data"]["config"]
    assert config["identity"]["binding"] == "5B42134331"
    assert config["identity"]["last_seen_path"] is None
    assert config["protocol"] == {
        "driver_id": "demo-bus",
        "params": {"baud": 1_000_000, "protocol_version": 0},
    }
    assert [e["address"] for e in config["bus_map"]] == ["1", "2"]
    assert {e["part_entity_id"] for e in config["bus_map"]} == set(data["part_ids"])
    assert set(config["parts"]) == set(data["part_ids"])
    part_1 = config["parts"][str(by_ref[f"{DEVICE_REF}/1"].id)]
    assert part_1["lifecycle"] == "live"
    assert part_1["telemetry"] == [{"name": "shoulder_pan.position", "unit": None}]
    for prefix in ("identity", "protocol", "bus_map"):
        assert _provenance_by(config, prefix) == {"detected"}
    assert config["disambiguated_by"] is None


def _provenance_by(config: dict[str, Any], prefix: str) -> set[str]:
    """Who set every valued leaf under `prefix` (provenance is recorded per leaf)."""
    return {
        record["by"]
        for key, record in config["provenance"].items()
        if key == prefix or key.startswith(f"{prefix}.")
    }


async def test_confirm_with_a_chosen_repo_config_imports_calibration_with_repo_provenance(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    detect_local.proposal = _wire_proposal(repo_matches=2)
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(repo_config_id="repo:cfg1"),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    config = (
        await client.get(
            _detect_url(project_id, "robots", data["robot"]["id"], "config"),
            headers=alice_headers,
        )
    ).json()["data"]["config"]
    assert config["disambiguated_by"] == "user"
    parts = config["parts"]
    shoulder = next(
        p for p in parts.values() if p["telemetry"][0]["name"] == "shoulder_pan.position"
    )
    assert shoulder["calibration"]["mode"] == "degrees"
    assert shoulder["calibration"]["values"]["homing_offset"] == -2042
    assert shoulder["calibration"]["owner"] == "repo"
    assert shoulder["calibration"]["source"] == "source:" + str(
        uuid.uuid5(uuid.UUID(project_id), "/cal/cfg1.json")
    )
    assert shoulder["telemetry"] == [{"name": "shoulder_pan.position", "unit": "deg"}]
    gripper = next(p for p in parts.values() if p["telemetry"][0]["name"] == "gripper.position")
    assert gripper["telemetry"] == [{"name": "gripper.position", "unit": "%"}]
    part_keys = [k for k in config["provenance"] if k.startswith("parts.")]
    assert any(config["provenance"][k]["by"] == "repo" for k in part_keys)


async def test_confirm_with_two_matches_and_no_choice_is_refused(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    detect_local.proposal = _wire_proposal(repo_matches=2)
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(),
    )
    assert resp.status_code == 422, resp.text
    assert "which" in resp.json()["error"]["message"].lower()


async def test_confirm_adds_to_an_existing_robot(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    created = await client.post(
        f"/api/v1/projects/{project_id}/entities",
        headers=alice_headers,
        json={"type": "physical_robot", "name": "Existing"},
    )
    robot_id = created.json()["data"]["id"]
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(target={"kind": "existing", "robot_id": robot_id}),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["robot"]["id"] == robot_id


@pytest.mark.parametrize(
    "body",
    [
        _confirm_body(accepted=[]),
        _confirm_body(accepted=[{"row_id": f"{DEVICE_REF}/9", "function_name": "x"}]),
        _confirm_body(accepted=[{"row_id": f"{DEVICE_REF}/1", "category": "not_a_category"}]),
        _confirm_body(target={"kind": "existing"}),
        {**_confirm_body(), "unexpected": True},
    ],
)
async def test_confirm_rejects_invalid_bodies(
    client: AsyncClient,
    alice_headers: dict[str, str],
    detect_local: _DetectLocal,
    body: dict[str, Any],
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=body,
    )
    assert resp.status_code == 422, resp.text


async def test_confirm_for_a_vanished_device_is_404(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    detect_local.proposal = None
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(),
    )
    assert resp.status_code == 404, resp.text


def _second_device(ref: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """A second, wire-identical device: same six-servo shape, different USB serial."""
    device = _wire_device(ref)
    device["identity"]["binding"] = ref.split(":", 1)[1]
    proposal = _wire_proposal(repo_matches=2)
    proposal["device_ref"] = ref
    proposal["identity"] = device["identity"]
    for row in proposal["rows"]:
        row["id"] = f"{ref}/{row['address']}"
        for match in row["evidence"]:
            match["source_ref"]["external_ref"] = row["id"]
    return device, proposal


async def test_the_second_arm_is_offered_only_the_remaining_repo_config(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    detect_local.proposal = _wire_proposal(repo_matches=2)
    first = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(repo_config_id="repo:cfg0"),
    )
    assert first.status_code == 201, first.text
    second_ref = "usb:5B42135040"
    device, proposal = _second_device(second_ref)
    detect_local.devices.append(device)
    detect_local.proposals[second_ref] = proposal
    resp = await client.post(
        _detect_url(project_id, "detected", second_ref, "propose"), headers=alice_headers, json={}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert [m["config_id"] for m in data["repo_matches"]] == ["repo:cfg1"]
    assert data["disambiguation"] is None  # one config left: no question
    assert [r["proposed_function"] for r in data["rows"]] == ["shoulder_pan", "gripper"]
    assert data["bound_repo_configs"] == ["repo:cfg0"]
    # and confirming the second arm with the already-bound config is refused
    taken = await client.post(
        _detect_url(project_id, "detected", second_ref, "confirm"),
        headers=alice_headers,
        json=_confirm_body(
            repo_config_id="repo:cfg0",
            accepted=[{"row_id": f"{second_ref}/1", "function_name": "shoulder_pan"}],
        ),
    )
    assert taken.status_code == 422, taken.text


async def test_propose_reports_port_repair_honestly(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    proposal = _wire_proposal(repo_matches=1)
    proposal["repo_matches"][0]["port_hint"] = "/dev/ttyACM0"
    detect_local.proposal = proposal
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"), headers=alice_headers, json={}
    )
    assert resp.status_code == 200, resp.text
    repair = resp.json()["data"]["port_repair"]
    assert repair["kind"] == "file"
    assert repair["configured"] == "/dev/ttyACM0"
    assert repair["actual"] == "/dev/serial/by-id/usb-1a86-5B42134331"
    assert repair["source"] == "/repo/cfg0.py"
    assert "not edit" in repair["note"]

    proposal["repo_matches"][0]["port_hint"] = None
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"), headers=alice_headers, json={}
    )
    repair = resp.json()["data"]["port_repair"]
    assert repair["kind"] == "command"
    assert "/dev/serial/by-id/usb-1a86-5B42134331" in repair["note"]

    proposal["repo_matches"][0]["port_hint"] = "/dev/serial/by-id/usb-1a86-5B42134331"
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"), headers=alice_headers, json={}
    )
    assert resp.json()["data"]["port_repair"] is None  # already right: nothing to repair


def _six_servo_proposal() -> dict[str, Any]:
    """The follower arm as the wire reports it: six servos, one model, no repo match."""
    proposal = _wire_proposal()
    proposal["driver_id"] = "feetech-sts"
    proposal["rows"] = [
        {
            "id": f"{DEVICE_REF}/{i}",
            "subject": f"STS3215 at address {i}",
            "address": str(i),
            "model": "STS3215",
            "proposed_function": None,
            "confidence": 0.92,
            "evidence": [_bus_match(str(i))],
            "provenance": "bus",
        }
        for i in range(1, 7)
    ]
    proposal["evidence"] = [_bus_match(str(i)) for i in range(1, 7)]
    proposal["summary"] = "6 servos on a serial servo bus (ids 1–6, STS3215)"
    return proposal


async def test_a_library_robot_and_the_same_machine_on_the_wire_reconcile_to_one_robot(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal, db: AsyncSession
) -> None:
    """The R4 trap at API level: import the platform, detect the arm → a suggestion against
    that robot (never a second robot); accept → identity bound, parts keyed, session opened."""
    project_id, _ = await _detect_project(client, alice_headers)
    imported = await client.post(
        f"/api/v1/projects/{project_id}/hardware/library/platforms/so101-follower/import",
        headers=alice_headers,
        json={},
    )
    assert imported.status_code == 201, imported.text
    robot_id = imported.json()["data"]["robot"]["id"]
    detect_local.proposal = _six_servo_proposal()

    proposed = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"), headers=alice_headers, json={}
    )
    assert proposed.status_code == 200, proposed.text
    suggestions = proposed.json()["data"]["suggestions"]
    assert [s["candidate_robot_id"] for s in suggestions] == [robot_id]
    assert suggestions[0]["tier"] == "high" and suggestions[0]["status"] == "pending"
    listed = await client.get(_detect_url(project_id, "suggestions"), headers=alice_headers)
    assert [s["id"] for s in listed.json()["data"]] == [suggestions[0]["id"]]

    accepted = await client.post(
        _detect_url(project_id, "suggestions", suggestions[0]["id"], "accept"),
        headers=alice_headers,
    )
    assert accepted.status_code == 200, accepted.text
    data = accepted.json()["data"]
    assert data["status"] == "accepted" and data["bound"] is True
    assert data["robot_id"] == robot_id and data["session_id"] is not None
    config = (
        await client.get(
            _detect_url(project_id, "robots", robot_id, "config"), headers=alice_headers
        )
    ).json()["data"]["config"]
    assert config["identity"]["binding"] == "5B42134331"
    assert config["protocol"] == {
        "driver_id": "feetech-sts",
        "params": {"baud": 1_000_000, "protocol_version": 0},
    }
    assert _provenance_by(config, "identity") == {"detected"}
    # the parts answered on the wire at their bus-map addresses: live, by detection
    assert {part["lifecycle"] for part in config["parts"].values()} == {"live"}
    assert all(
        _provenance_by(config, f"parts.{part_id}.lifecycle") == {"detected"}
        for part_id in config["parts"]
    )
    keyed = list(
        await db.scalars(
            select(GraphEntity).where(GraphEntity.external_ref.like(f"{DEVICE_REF}/%"))
        )
    )
    assert {p.external_ref for p in keyed} == {f"{DEVICE_REF}/{i}" for i in range(1, 7)}
    assert all(p.attrs.get("robot_id") == robot_id for p in keyed)

    # the machine is now bound: no second suggestion, and no second robot
    again = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"), headers=alice_headers, json={}
    )
    assert again.json()["data"]["suggestions"] == []
    second = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(
            accepted=[{"row_id": f"{DEVICE_REF}/1", "function_name": "shoulder_pan"}]
        ),
    )
    assert second.status_code == 409, second.text
    assert robot_id in second.json()["error"]["message"]


async def test_accepting_a_device_suggestion_without_a_runner_records_the_decision_only(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, app: Any
) -> None:
    from solus_api.hardware.links import LinkSuggestion, LinkTier, persist_suggestions

    project_id, _ = await _detect_project(client, alice_headers)
    created = await client.post(
        f"/api/v1/projects/{project_id}/entities",
        headers=alice_headers,
        json={"type": "physical_robot", "name": "Offline"},
    )
    robot_id = created.json()["data"]["id"]
    rows = await persist_suggestions(
        db,
        uuid.UUID(project_id),
        [
            LinkSuggestion(
                subject_ref=DEVICE_REF,
                subject_kind="device",
                candidate_robot_id=uuid.UUID(robot_id),
                confidence=0.8,
                tier=LinkTier.HIGH,
                evidence=[],
                reason="test",
            )
        ],
    )
    await db.commit()
    app.state.bench_local = None
    resp = await client.post(
        _detect_url(project_id, "suggestions", str(rows[0].id), "accept"), headers=alice_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "accepted" and data["bound"] is False
    assert "runner" in data["bind_error"].lower() or "livebench" in data["bind_error"].lower()


async def test_confirm_twice_reconciles_to_one_robot(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    first = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(),
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(),
    )
    assert second.status_code == 409, second.text
    assert first.json()["data"]["robot"]["id"] in second.json()["error"]["message"]


async def test_detection_routes_are_tenant_scoped(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    detect_local: _DetectLocal,
) -> None:
    project_id, team_id = await _detect_project(client, alice_headers)
    await me(client, bob_headers)
    listed = await client.get(_detect_url(project_id, "detected"), headers=bob_headers)
    assert listed.status_code == 404
    propose = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"), headers=bob_headers, json={}
    )
    assert propose.status_code == 404
    await add_member(client, alice_headers, bob_headers, BOB, team_id, role="viewer")
    confirm = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=bob_headers,
        json=_confirm_body(),
    )
    assert confirm.status_code == 403, confirm.text


# ── SOLUSDEV-250 Phase 2: headline, tone, stream, identity basis on the wire ────


def _wire_stream_proposal() -> dict[str, Any]:
    proposal = _wire_proposal()
    proposal.update(
        {
            "headline": "a board on USB",
            "tone": "probably",
            "stream": {
                "framing": "csv",
                "channel_count": 4,
                "update_hz": 49.6,
                "channel_names": ["motor_l", "motor_r", "dist", "batt"],
                "declared_hz": 50.0,
            },
            "identity_basis": "port_position",
        }
    )
    return proposal


async def test_propose_carries_headline_tone_stream_and_identity_basis(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    detect_local.proposal = _wire_stream_proposal()
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"), headers=alice_headers, json={}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["headline"] == "a board on USB" and data["tone"] == "probably"
    assert data["identity_basis"] == "port_position"
    assert data["stream"]["channel_names"] == ["motor_l", "motor_r", "dist", "batt"]
    assert data["stream"]["update_hz"] == pytest.approx(49.6)
    assert data["stream"]["declared_hz"] == pytest.approx(50.0)


async def test_a_pre_phase_2_wire_still_validates_with_defaults(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"), headers=alice_headers, json={}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["headline"] == "" and data["tone"] == "something"
    assert data["stream"] is None and data["identity_basis"] == "serial"
    listed = await client.get(_detect_url(project_id, "detected"), headers=alice_headers)
    [device] = listed.json()["data"]
    assert device["headline"] == "" and device["identity_basis"] == "serial"


async def test_detected_carries_headline_and_identity_basis(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    detect_local.devices = [
        {**_wire_device(), "headline": "something on USB", "identity_basis": "port_position"}
    ]
    resp = await client.get(_detect_url(project_id, "detected"), headers=alice_headers)
    assert resp.status_code == 200, resp.text
    [device] = resp.json()["data"]
    assert device["headline"] == "something on USB"
    assert device["identity_basis"] == "port_position"


def test_stream_wire_is_bounded() -> None:
    from pydantic import ValidationError
    from solus_api.hardware.detect import ProposalOut, StreamOut

    StreamOut.model_validate({"framing": "csv", "channel_count": 64, "update_hz": 0})
    with pytest.raises(ValidationError):
        StreamOut.model_validate({"framing": "csv", "channel_count": 65, "update_hz": 1})
    with pytest.raises(ValidationError):
        StreamOut.model_validate(
            {"framing": "csv", "channel_count": 1, "update_hz": 1, "channel_names": ["x" * 129]}
        )
    with pytest.raises(ValidationError):
        ProposalOut.model_validate({**_wire_stream_proposal(), "tone": "certainly"})


# ── Phase 2 review fixes: a stalled runner, repo_root confinement, wire bounds ──


async def test_a_stalled_runner_is_unavailable_not_a_hang(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from solus_api.core.errors import APIError
    from solus_api.hardware import detect

    class _Stalled(_DetectLocal):
        def propose_device(
            self, device_ref: str, *, repo_root: str | None = None, budget_s: float = 0.5
        ) -> dict[str, Any] | None:
            time.sleep(0.2)
            return super().propose_device(device_ref, repo_root=repo_root, budget_s=budget_s)

    monkeypatch.setattr(detect, "PROPOSE_TIMEOUT_S", 0.01)
    with pytest.raises(APIError) as excinfo:
        await detect.propose_via_local(_Stalled(), DEVICE_REF, repo_root=None, budget_s=0.5)
    assert excinfo.value.status_code == 503
    assert excinfo.value.code == "source_unavailable"


def _registry(path: Path, entries: dict[str, str]) -> Path:
    path.write_text(
        json.dumps({"schema_version": 1, "projects": {k: {"path": v} for k, v in entries.items()}})
    )
    return path


async def test_linked_directory_is_not_private_file_authorization(
    client: AsyncClient,
    alice_headers: dict[str, str],
    detect_local: _DetectLocal,
    app: FastAPI,
    tmp_path: Path,
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    linked, other, elsewhere = tmp_path / "linked", tmp_path / "other", tmp_path / "elsewhere"
    for folder in (linked / "sub", other, elsewhere):
        folder.mkdir(parents=True)
    _registry(tmp_path / "projects.json", {project_id: str(linked), str(uuid.uuid4()): str(other)})
    url = _detect_url(project_id, "detected", DEVICE_REF, "propose")
    for root in (linked, linked / "sub", elsewhere, other, tmp_path):
        resp = await client.post(url, headers=alice_headers, json={"repo_root": str(root)})
        assert resp.status_code == 422, resp.text
        assert "file picker" in resp.json()["error"]["message"]
    confirm = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(repo_root=str(other)),
    )
    assert confirm.status_code == 422, confirm.text
    assert detect_local.propose_calls == []


async def test_a_corrupt_registry_refuses_every_repo_root_with_a_clear_message(
    client: AsyncClient,
    alice_headers: dict[str, str],
    detect_local: _DetectLocal,
    app: FastAPI,
    tmp_path: Path,
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    registry = tmp_path / "projects.json"
    registry.write_text("{not json")
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"),
        headers=alice_headers,
        json={"repo_root": str(tmp_path)},
    )
    assert resp.status_code == 422, resp.text
    assert "file picker" in resp.json()["error"]["message"].lower()
    assert detect_local.propose_calls == []


async def test_without_a_registry_file_raw_directory_still_refused(
    client: AsyncClient,
    alice_headers: dict[str, str],
    detect_local: _DetectLocal,
    app: FastAPI,
    tmp_path: Path,
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"),
        headers=alice_headers,
        json={"repo_root": str(tmp_path)},
    )
    assert resp.status_code == 422, resp.text
    assert detect_local.propose_calls == []


async def test_an_over_long_summary_from_the_runner_is_refused(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    url = _detect_url(project_id, "detected", DEVICE_REF, "propose")
    detect_local.proposal = {**_wire_proposal(), "summary": "s" * 1024}
    resp = await client.post(url, headers=alice_headers, json={})
    assert resp.status_code == 200, resp.text
    detect_local.proposal = {**_wire_proposal(), "summary": "s" * 1025}
    resp = await client.post(url, headers=alice_headers, json={})
    assert resp.status_code == 503, resp.text
    assert resp.json()["error"]["code"] == "source_unavailable"


def test_the_remaining_wire_bounds_hold() -> None:
    from pydantic import ValidationError
    from solus_api.hardware.detect import DetectedDeviceOut, ProposalOut, RepoMatchOut, StreamOut

    match = _wire_proposal(repo_matches=1)["repo_matches"][0]
    RepoMatchOut.model_validate({**match, "label": "l" * 256, "source": "s" * 1024})
    for over in ({"label": "l" * 257}, {"source": "s" * 1025}, {"calibration_source": "c" * 1025}):
        with pytest.raises(ValidationError):
            RepoMatchOut.model_validate({**match, **over})
    part = match["parts"][0]
    with pytest.raises(ValidationError):
        RepoMatchOut.model_validate(
            {**match, "parts": [{**part, "calibration_source": "c" * 1025}]}
        )
    with pytest.raises(ValidationError):
        StreamOut.model_validate({"framing": "f" * 33, "channel_count": 1, "update_hz": 1})
    for over in ({"headline": "h" * 129}, {"calibration_source": "c" * 1025}):
        with pytest.raises(ValidationError):
            ProposalOut.model_validate({**_wire_proposal(), **over})
    with pytest.raises(ValidationError):
        DetectedDeviceOut.model_validate({**_wire_device(), "headline": "h" * 129})


# ── SOLUSDEV-250 Phase 6: confirm reuses the preceding proposal (≤ 60 s) ─────────


async def _propose_then_confirm(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    *,
    confirm_body: dict[str, Any] | None = None,
    between: Any = None,
) -> Any:
    resp = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "propose"), headers=headers, json={}
    )
    assert resp.status_code == 200, resp.text
    if between is not None:
        between()
    return await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=headers,
        json=confirm_body or _confirm_body(),
    )


async def test_confirm_reuses_the_proposal_the_propose_route_just_built(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    resp = await _propose_then_confirm(client, alice_headers, project_id)
    assert resp.status_code == 201, resp.text
    assert len(detect_local.propose_calls) == 1  # the runner was not asked twice
    assert len(resp.json()["data"]["part_ids"]) == 2


async def test_cached_proposal_cannot_confirm_a_disconnected_device(
    client: AsyncClient,
    alice_headers: dict[str, str],
    detect_local: _DetectLocal,
    db: AsyncSession,
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    response = await _propose_then_confirm(
        client, alice_headers, project_id, between=lambda: detect_local.devices.clear()
    )
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "device_not_found"
    assert len(detect_local.propose_calls) == 1
    assert (
        await db.scalar(
            select(GraphEntity.id).where(
                GraphEntity.project_id == uuid.UUID(project_id),
                GraphEntity.kind == "physical_robot",
            )
        )
        is None
    )


async def test_confirm_with_a_row_the_proposal_lacks_re_interrogates(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    body = _confirm_body(accepted=[{"row_id": f"{DEVICE_REF}/9", "function_name": "ghost"}])
    resp = await _propose_then_confirm(client, alice_headers, project_id, confirm_body=body)
    assert resp.status_code == 422, resp.text
    assert len(detect_local.propose_calls) == 2


async def test_a_proposal_older_than_the_ttl_is_re_interrogated(
    client: AsyncClient,
    alice_headers: dict[str, str],
    detect_local: _DetectLocal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.hardware import proposal_cache

    project_id, _ = await _detect_project(client, alice_headers)
    now = proposal_cache.PROPOSALS.clock()

    def _later() -> None:
        monkeypatch.setattr(
            proposal_cache.PROPOSALS, "clock", lambda: now + proposal_cache.TTL_S + 1
        )

    resp = await _propose_then_confirm(client, alice_headers, project_id, between=_later)
    assert resp.status_code == 201, resp.text
    assert len(detect_local.propose_calls) == 2


async def test_a_reused_proposal_is_consumed_by_the_confirm(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    first = await _propose_then_confirm(client, alice_headers, project_id)
    assert first.status_code == 201, first.text
    second = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(),
    )
    assert second.status_code == 409, second.text  # bound rows: the wire is asked again
    assert len(detect_local.propose_calls) == 2


async def test_a_proposal_never_crosses_projects(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    project_a, team_id = await _detect_project(client, alice_headers)
    project_b = str((await create_project(client, alice_headers, team_id))["id"])
    resp = await client.post(
        _detect_url(project_a, "detected", DEVICE_REF, "propose"), headers=alice_headers, json={}
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        _detect_url(project_b, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(),
    )
    assert resp.status_code == 201, resp.text
    assert len(detect_local.propose_calls) == 2  # project B's confirm never saw A's entry


async def test_a_reused_proposal_still_excludes_bound_configs(
    client: AsyncClient, alice_headers: dict[str, str], detect_local: _DetectLocal
) -> None:
    """The second arm's proposal is cached BEFORE the first arm binds cfg0; its confirm
    still runs `exclude_bound` against the bound set of the moment, not of the cache."""
    project_id, _ = await _detect_project(client, alice_headers)
    second_ref = "usb:5B42135040"
    device, proposal = _second_device(second_ref)
    detect_local.devices.append(device)
    detect_local.proposals[second_ref] = proposal
    detect_local.proposal = _wire_proposal(repo_matches=2)
    proposed = await client.post(
        _detect_url(project_id, "detected", second_ref, "propose"), headers=alice_headers, json={}
    )
    assert proposed.status_code == 200 and proposed.json()["data"]["disambiguation"] is not None
    first = await client.post(
        _detect_url(project_id, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(repo_config_id="repo:cfg0"),
    )
    assert first.status_code == 201, first.text
    calls_before = len(detect_local.propose_calls)
    second = await client.post(
        _detect_url(project_id, "detected", second_ref, "confirm"),
        headers=alice_headers,
        json=_confirm_body(
            accepted=[{"row_id": f"{second_ref}/1", "function_name": "shoulder_pan"}]
        ),
    )
    assert second.status_code == 201, second.text  # one config left → no question asked
    assert len(detect_local.propose_calls) == calls_before  # served from the cache
    config = (
        await client.get(
            _detect_url(project_id, "robots", second.json()["data"]["robot"]["id"], "config"),
            headers=alice_headers,
        )
    ).json()["data"]["config"]
    repo_sources = {r["source"] for r in config["provenance"].values() if r["by"] == "repo"}
    assert repo_sources == {"repo:cfg1"}  # cfg0 was bound by the first arm → excluded


async def test_confirm_logs_one_structured_timing_line(
    client: AsyncClient,
    alice_headers: dict[str, str],
    detect_local: _DetectLocal,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project_id, _ = await _detect_project(client, alice_headers)
    with caplog.at_level("INFO", logger="solus_api.hardware.hardware_router"):
        resp = await _propose_then_confirm(
            client, alice_headers, project_id, confirm_body=_confirm_body(start_session=True)
        )
    assert resp.status_code == 201, resp.text
    [record] = [r for r in caplog.records if r.getMessage() == "hardware.confirm timings"]
    fields = record.__dict__
    assert fields["device_ref"] == DEVICE_REF and fields["proposal_reused"] is True
    assert all(fields[phase] >= 0.0 for phase in ("propose_s", "write_s", "session_s"))
    assert "/dev/" not in caplog.text  # device_ref only, never a tty path


def test_the_proposal_cache_is_bounded_and_forgets_on_take() -> None:
    from solus_api.hardware.detect import ProposalOut
    from solus_api.hardware.proposal_cache import ProposalCache

    tick = [0.0]
    cache = ProposalCache(max_entries=2, ttl_s=60.0, clock=lambda: tick[0])
    proposal = ProposalOut.model_validate(_wire_proposal())
    keys = [(uuid.uuid4(), DEVICE_REF, None) for _ in range(3)]
    for key in keys:
        cache.put(key, proposal)
    rows = [f"{DEVICE_REF}/1"]
    assert cache.take(keys[0], rows) is None  # evicted: oldest of three, bound two
    assert cache.take(keys[1], rows) is proposal
    assert cache.take(keys[1], rows) is None  # consumed
    tick[0] = 61.0
    assert cache.take(keys[2], rows) is None  # expired
    cache.put(keys[2], proposal)
    assert cache.take(keys[2], [f"{DEVICE_REF}/1", f"{DEVICE_REF}/7"]) is None  # unknown row
