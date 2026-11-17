"""SOLUSDEV-326 P1-T5: this machine's device memory and each member's "Not now".

The local API remembers what it saw plugged in on ITS machine node in the project
(`attrs.devices`: device ref, identity basis, headline, last seen — never a path). A device that
leaves keeps its row and when it was last seen. `attrs.dismissed` keeps each member's "Not now"
per device until they clear it. Both are the machine owner's alone to read; `GET
/hardware/detected` tells each caller only what is theirs: what binds a device (when they may
see it), whether THEY dismissed it, and — for the machine's owner — when it was last seen.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from conftest import BOB, add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.hardware.config import EntityHardwareConfig
from solus_api.hardware.detect import detected_devices_wire
from solus_api.hardware.device_memory import (
    MAX_DISMISSED,
    MAX_REMEMBERED,
    dismiss,
    remembered,
)
from solus_api.hardware.host_topology import LocalHostProvider
from solus_api.hardware.store import put_entity_config
from solus_api.models import DataEvent, Domain, GraphEdge, GraphEntity, User, utcnow
from solus_api.services.machines import MachineIn, find_machine, upsert_machine
from solus_api.services.physical_robots import PhysicalRobotService
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_bind_refusal import _holder
from test_hardware_detect import DEVICE_REF, _DetectLocal, _wire_device
from test_hardware_detect import detect_local as detect_local
from test_hardware_identity_list import _project_by_id

COMPANION = "0123456789abcdef0123456789abcdef"
USER = {"by": "user", "source": None}


def _usb_device(binding: str) -> dict[str, Any]:
    """An enumerated USB device whose ref and binding agree."""
    wire = _wire_device()
    return {
        **wire,
        "device_ref": f"usb:{binding}",
        "identity": {**wire["identity"], "binding": binding},
    }


def _dismissals_url(project: str) -> str:
    return f"/api/v1/projects/{project}/hardware/devices/dismissals"


def _detected_url(project: str) -> str:
    return f"/api/v1/projects/{project}/hardware/detected"


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """This API's companion identity as `LocalHostProvider` reads it; tests may change it."""
    identity: list[str | None] = [COMPANION]

    async def read(self: LocalHostProvider) -> str | None:
        return identity[0]

    monkeypatch.setattr(LocalHostProvider, "identity", read)
    return identity


async def _team(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    *,
    role: str = "member",
) -> tuple[str, str, str]:
    """A project with Alice (owner) and Bob (`role`): (project, alice id, bob id)."""
    alice = await me(client, alice_headers)
    bob = await me(client, bob_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role=role)
    return str(project["id"]), str(alice["id"]), str(bob["id"])


async def _machine(db: AsyncSession, project: str, owner: str) -> GraphEntity:
    """THIS machine, registered in the project by `owner`'s companion."""
    machine = await upsert_machine(
        db,
        uuid.UUID(project),
        uuid.UUID(owner),
        COMPANION,
        MachineIn(hostname="bench-01", os="linux", arch="arm64"),
    )
    await db.commit()
    return machine


async def _fresh_machine(app: FastAPI, project: str) -> dict[str, Any]:
    """The machine's attrs as a new session reads them (what survives an app restart)."""
    async with app.state.sessionmaker() as session:
        machine = await find_machine(session, uuid.UUID(project), COMPANION)
        assert machine is not None
        return dict(machine.attrs)


async def _annotations(
    client: AsyncClient, project: str, headers: dict[str, str]
) -> dict[str, dict[str, Any]]:
    response = await client.get(_detected_url(project), headers=headers)
    assert response.status_code == 200, response.text
    return {
        row["device_ref"]: {key: row[key] for key in ("bound_to", "dismissed", "last_seen")}
        for row in response.json()["data"]
    }


# ------------------------------------------------------------------------------- memory


def test_a_device_that_leaves_keeps_its_row_and_the_time_it_was_last_seen() -> None:
    a, b, anonymous = detected_devices_wire(
        [_usb_device("A"), _usb_device("B"), _wire_device(None)]
    )
    first = remembered([], [a, b, anonymous], (), "T1")
    row = {"identity_basis": "serial", "headline": "", "last_seen": "T1", "present": True}
    assert first == [{"device_ref": "usb:A", **row}, {"device_ref": "usb:B", **row}]
    # B is unplugged: it was seen until this change, and keeps its row — no longer present.
    second = remembered(first, [a], {"usb:B"}, "T2")
    assert {row["device_ref"]: row["last_seen"] for row in second} == {
        "usb:A": "T2",
        "usb:B": "T2",
    }
    assert {row["device_ref"]: row["present"] for row in second} == {"usb:A": True, "usb:B": False}
    third = remembered(second, [], {"usb:A"}, "T3")
    assert [(row["device_ref"], row["last_seen"], row["present"]) for row in third] == [
        ("usb:A", "T3", False),
        ("usb:B", "T2", False),
    ]
    keys = {"device_ref", "identity_basis", "headline", "last_seen", "present"}
    assert all(set(row) == keys for row in third)


def test_present_is_the_whole_current_list_even_with_nothing_seen_leaving() -> None:
    """SOLUSDEV-326: a device notice asks the memory what is plugged in NOW. After a restart the
    watcher tells the full list with nothing marked as leaving, so presence is the list itself,
    not the `gone` set: a device unplugged while the API was down is not present."""
    a, b = detected_devices_wire([_usb_device("A"), _usb_device("B")])
    before = remembered([], [a, b], (), "T1")
    after_restart = remembered(before, [a], (), "T2")
    assert {row["device_ref"]: row["present"] for row in after_restart} == {
        "usb:A": True,
        "usb:B": False,
    }
    # B keeps when it was last seen: nothing saw it leave.
    assert {row["device_ref"]: row["last_seen"] for row in after_restart}["usb:B"] == "T1"


def test_memory_is_bounded_most_recent_first() -> None:
    prior = [
        {"device_ref": f"usb:OLD{i}", "identity_basis": "serial", "headline": "", "last_seen": "T1"}
        for i in range(MAX_REMEMBERED)
    ]
    rows = remembered(prior, detected_devices_wire([_usb_device("NEW")]), (), "T2")
    assert len(rows) == MAX_REMEMBERED
    assert rows[0]["device_ref"] == "usb:NEW"


# --------------------------------------------------------------------------- not now


async def test_not_now_is_each_members_own_and_survives_restart_replug_and_reregistration(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    detect_local: _DetectLocal,
    host: list[str | None],
) -> None:
    project, alice, bob = await _team(client, alice_headers, bob_headers)
    await _machine(db, project, alice)
    await db.execute(update(User).values(data_collection_consent=True))
    await db.commit()
    detect_local.devices = [_wire_device(), _usb_device("OTHER")]
    url = _dismissals_url(project)

    mine = await client.post(url, headers=alice_headers, json={"device_ref": DEVICE_REF})
    assert mine.status_code == 200, mine.text
    assert mine.json()["data"] == {"dismissed": [DEVICE_REF]}
    theirs = await client.post(url, headers=bob_headers, json={"device_ref": "usb:OTHER"})
    assert theirs.json()["data"] == {"dismissed": ["usb:OTHER"]}

    async def dismissed(headers: dict[str, str]) -> dict[str, bool]:
        rows = await _annotations(client, project, headers)
        return {ref: row["dismissed"] for ref, row in rows.items()}

    assert await dismissed(alice_headers) == {DEVICE_REF: True, "usb:OTHER": False}
    assert await dismissed(bob_headers) == {DEVICE_REF: False, "usb:OTHER": True}
    # Unplugged and plugged back in: nothing about the dismissal changed.
    detect_local.devices = []
    assert await dismissed(alice_headers) == {}
    detect_local.devices = [_wire_device()]
    assert await dismissed(alice_headers) == {DEVICE_REF: True}
    # A fresh read (an app restart) and the companion registering the machine again keep it.
    await _machine(db, project, alice)
    assert (await _fresh_machine(app, project))["dismissed"] == {
        alice: [DEVICE_REF],
        bob: ["usb:OTHER"],
    }

    cleared = await client.delete(url, headers=alice_headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"] == {"dismissed": []}
    assert await dismissed(alice_headers) == {DEVICE_REF: False}
    assert (await _fresh_machine(app, project))["dismissed"] == {bob: ["usb:OTHER"]}

    events = list(
        await db.scalars(
            select(DataEvent)
            .where(DataEvent.event_type.like("hardware.d%"))
            .order_by(DataEvent.created_at)
            .execution_options(populate_existing=True)
        )
    )
    assert [(event.event_type, event.payload) for event in events] == [
        ("hardware.device_dismissed", {"device_ref": DEVICE_REF}),
        ("hardware.device_dismissed", {"device_ref": "usb:OTHER"}),
        ("hardware.dismissals_cleared", {"count": 1}),
    ]


async def test_a_members_dismissals_are_bounded_oldest_first_out(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    await _machine(db, project, alice)
    kept: list[str] = []
    for index in range(MAX_DISMISSED + 1):
        kept = await dismiss(db, uuid.UUID(project), COMPANION, uuid.UUID(alice), f"usb:D{index}")
    assert len(kept) == MAX_DISMISSED
    assert kept[0] == "usb:D1" and kept[-1] == f"usb:D{MAX_DISMISSED}"
    again = await dismiss(db, uuid.UUID(project), COMPANION, uuid.UUID(alice), "usb:D1")
    assert again[-1] == "usb:D1" and len(again) == MAX_DISMISSED


async def test_dismissal_routes_refuse_outsiders_viewers_anonymous_and_bad_bodies(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    detect_local: _DetectLocal,
    host: list[str | None],
) -> None:
    alice = await me(client, alice_headers)
    await me(client, bob_headers)
    team = await create_team(client, alice_headers)
    project = str((await create_project(client, alice_headers, team["id"]))["id"])
    await _machine(db, project, str(alice["id"]))
    url, body = _dismissals_url(project), {"device_ref": DEVICE_REF}

    # Bob belongs to no team of this project: the project does not exist for him.
    assert (await client.post(url, headers=bob_headers, json=body)).status_code == 404
    assert (await client.delete(url, headers=bob_headers)).status_code == 404
    assert (await client.post(url, json=body)).status_code == 401
    assert (await client.delete(url)).status_code == 401
    for bad in (
        {"device_ref": DEVICE_REF, "extra": 1},
        {"device_ref": "usb:a/b"},
        {"device_ref": "no-transport"},
        {"device_ref": "usb:" + "x" * 200},
        {},
    ):
        response = await client.post(url, headers=alice_headers, json=bad)
        assert response.status_code == 422, bad
    # A viewer may read the project but writes nothing to it.
    await add_member(client, alice_headers, bob_headers, BOB, team["id"], role="viewer")
    assert (await client.post(url, headers=bob_headers, json=body)).status_code == 403
    assert (await client.delete(url, headers=bob_headers)).status_code == 403
    db.expire_all()
    machine = await find_machine(db, uuid.UUID(project), COMPANION)
    assert machine is not None and not machine.attrs.get("dismissed")


async def test_a_dismissal_lives_on_this_machine_and_needs_one(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    detect_local: _DetectLocal,
    host: list[str | None],
) -> None:
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    url, body = _dismissals_url(project), {"device_ref": DEVICE_REF}
    # This project has never registered the machine this API runs on.
    unknown = await client.post(url, headers=alice_headers, json=body)
    assert unknown.status_code == 409, unknown.text
    assert unknown.json()["error"]["code"] == "machine_unknown"
    await _machine(db, project, alice)
    host[0] = None  # no companion identity on this host: which machine is this?
    nameless = await client.delete(url, headers=alice_headers)
    assert nameless.status_code == 409 and nameless.json()["error"]["code"] == "machine_unknown"
    host[0] = COMPANION
    app.state.bench_local = None  # a hosted API runs on no one's machine
    hosted = await client.post(url, headers=alice_headers, json=body)
    assert hosted.status_code == 503 and hosted.json()["error"]["code"] == "source_unavailable"


# ------------------------------------------------------------------------- annotations


async def _part(db: AsyncSession, project: str, name: str, **fields: Any) -> GraphEntity:
    part = GraphEntity(
        project_id=uuid.UUID(project),
        kind="part",
        domain=Domain.PROJECT,
        origin="manual",
        name=name,
        attrs={},
        **fields,
    )
    db.add(part)
    await db.flush()
    return part


def _brain_item(binding: str, driver: str | None) -> dict[str, Any]:
    return {
        "kind": "mcu",
        "binding": {"kind": "usb_serial", "binding": binding},
        "protocol": {"driver_id": driver, "params": {}} if driver else None,
    }


async def _configure(
    db: AsyncSession, project: str, subject: GraphEntity, *brains: dict[str, Any]
) -> None:
    config = EntityHardwareConfig.model_validate(
        {"entity_id": str(subject.id), "identity": list(brains), "provenance": {"identity": USER}}
    )
    await put_entity_config(
        db, uuid.UUID(project), subject, config, expected_version=0, created_by=None
    )


async def test_each_detected_device_says_what_binds_it(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    detect_local: _DetectLocal,
    host: list[str | None],
) -> None:
    """A robot's brain, a robot bound by its connection alone, a lone part's own board and a part
    keyed by the device's ref all bind it; an unknown device is bound to nothing."""
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    await _machine(db, project, alice)
    robots = PhysicalRobotService(db)
    arm = await robots.create(uuid.UUID(project), "Arm")
    await _configure(db, project, arm, _brain_item("AAA", "bus-driver"))
    bare = await robots.create(uuid.UUID(project), "Bare")
    await _configure(db, project, bare, _brain_item("BBB", None))
    board = await _part(db, project, "Board")
    await _configure(db, project, board, _brain_item("CCC", "lines"))
    keyed = await _part(db, project, "Keyed", external_ref="usb:DDD")
    await db.commit()
    detect_local.devices = [_usb_device(b) for b in ("AAA", "BBB", "CCC", "DDD", "EEE")]

    rows = await _annotations(client, project, alice_headers)

    assert {ref: row["bound_to"] for ref, row in rows.items()} == {
        "usb:AAA": str(arm.id),
        "usb:BBB": str(bare.id),
        "usb:CCC": str(board.id),
        "usb:DDD": str(keyed.id),
        "usb:EEE": None,
    }


async def _backfilled_robot(db: AsyncSession, project: str) -> GraphEntity:
    """`test_hardware_bind_refusal`'s backfilled holder: a robot whose stored brain binds usb:BBB
    with no binding edge, as revision a26000000002 leaves a config."""
    robot = await _holder(db, await _project_by_id(db, project), "physical_robot")
    await db.execute(
        update(GraphEdge)
        .where(GraphEdge.project_id == uuid.UUID(project), GraphEdge.relation_type == "binds")
        .values(deleted_at=utcnow())
    )
    await db.commit()
    return robot


async def test_a_robot_binds_what_its_stored_brains_name_with_no_binding_edge(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    detect_local: _DetectLocal,
    host: list[str | None],
) -> None:
    """The holders `bind_device` refuses (§5): a backfilled config has no binding edge, yet its
    robot holds the device, so the list must not offer that device as new hardware."""
    project, _, _ = await _team(client, alice_headers, bob_headers)
    robot = await _backfilled_robot(db, project)
    detect_local.devices = [_usb_device("BBB")]

    rows = await _annotations(client, project, alice_headers)

    assert rows["usb:BBB"]["bound_to"] == str(robot.id)


async def test_hardware_out_of_the_graph_binds_a_device_for_its_onboarder_alone(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    detect_local: _DetectLocal,
    host: list[str | None],
) -> None:
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    await _machine(db, project, alice)
    hidden = await PhysicalRobotService(db).create(
        uuid.UUID(project), "Hidden", in_graph=False, onboarded_by=uuid.UUID(alice)
    )
    await _configure(db, project, hidden, _brain_item("AAA", "bus-driver"))
    await db.commit()
    detect_local.devices = [_usb_device("AAA")]

    mine = await _annotations(client, project, alice_headers)
    assert mine["usb:AAA"]["bound_to"] == str(hidden.id)
    assert (await _annotations(client, project, bob_headers))["usb:AAA"]["bound_to"] is None


async def test_a_teammate_reads_neither_the_machines_memory_nor_anyone_elses_not_now(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    detect_local: _DetectLocal,
    host: list[str | None],
) -> None:
    project, alice, _ = await _team(client, alice_headers, bob_headers)
    machine = await _machine(db, project, alice)
    seen = "2026-11-13T10:00:00+00:00"
    row = {"device_ref": DEVICE_REF, "identity_basis": "serial", "headline": "", "last_seen": seen}
    machine.attrs = {**machine.attrs, "devices": [row], "dismissed": {alice: [DEVICE_REF]}}
    await db.commit()

    assert (await _annotations(client, project, alice_headers))[DEVICE_REF] == {
        "bound_to": None,
        "dismissed": True,
        "last_seen": seen,
    }
    assert (await _annotations(client, project, bob_headers))[DEVICE_REF] == {
        "bound_to": None,
        "dismissed": False,
        "last_seen": None,
    }
    listed = await client.get(
        f"/api/v1/projects/{project}/entities?type=machine", headers=bob_headers
    )
    (entity,) = listed.json()["data"]
    assert not {"devices", "dismissed"} & set(entity["properties"])


async def test_an_unknown_machine_annotates_without_memory(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    detect_local: _DetectLocal,
    host: list[str | None],
) -> None:
    project, _, _ = await _team(client, alice_headers, bob_headers)
    host[0] = None
    assert (await _annotations(client, project, alice_headers))[DEVICE_REF] == {
        "bound_to": None,
        "dismissed": False,
        "last_seen": None,
    }
