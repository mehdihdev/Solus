"""SOLUSDEV-326 P3 — `GET /hardware/expected`: the Hardware page's "Described in your workspace,
not seen yet" rows, from the service behind `hardware.expected_parts`. Any project member reads
it as themselves (docs/api/hardware.md §1a): a teammate's hidden robot gives no row, no source
label and no count; every value is one short printable line; the answer is bounded.
"""

from __future__ import annotations

import uuid
from typing import Any

from conftest import BOB, add_member, create_project, create_team, me
from httpx import AsyncClient
from solus_api.graph import kinds
from solus_api.hardware import library_import
from solus_api.hardware.expected_parts import MAX_ROWS, MAX_SOURCES
from solus_api.hardware.library import load_library
from solus_api.models import Domain, GraphEntity, Source, SourceType
from sqlalchemy.ext.asyncio import AsyncSession
from test_in_graph import _Team, _team

ROW_KEYS = {"name", "what", "robot_id", "source"}
NOTHING: dict[str, Any] = {"expected": [], "sources": [], "more": 0}


def _node(team: _Team, kind: str, domain: Domain, name: str, **attrs: Any) -> GraphEntity:
    return GraphEntity(
        project_id=team.project_id,
        kind=kind,
        domain=domain,
        origin="connector",
        name=name,
        attrs=attrs,
    )


async def _described(db: AsyncSession, team: _Team) -> None:
    """A sensor topic, a non-sensor topic, a sketch with includes, an MCU symbol and a resistor."""
    seen = {"source_file": "fw/nano_sensors.ino", "libraries": ["Wire.h", "Baro.h"]}
    db.add_all(
        [
            _node(team, kinds.ROS_TOPIC, Domain.CODE, "/imu", type="sensor_msgs/msg/Imu"),
            _node(team, kinds.ROS_TOPIC, Domain.CODE, "/cmd", type="geometry_msgs/msg/Twist"),
            _node(team, kinds.ARDUINO_SKETCH, Domain.CODE, "nano_sensors", observations=[seen]),
            _node(
                team,
                kinds.COMPONENT,
                Domain.ELECTRICAL,
                "U1",
                libsource="MCU_Fam:Chip1",
                value="CHIP1",
            ),
            _node(team, kinds.COMPONENT, Domain.ELECTRICAL, "R1", libsource="Dev:R"),
        ]
    )
    await db.commit()


async def _private_arm(db: AsyncSession, team: _Team) -> int:
    """Alice's library arm, kept out of the graph; how many planned rows it has."""
    library = load_library()
    platform = library.platforms["so101-follower"]
    await library_import.import_platform(
        db,
        None,
        library,
        platform,
        project_id=team.project_id,
        user_id=team.alice_id,
        name="Private arm",
        in_graph=False,
        onboarded_by=team.alice_id,
    )
    await db.commit()
    return len(platform.parts)


async def _expected(client: AsyncClient, team: _Team, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get(team.url("hardware", "expected"), headers=headers)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def test_expected_lists_what_the_workspace_describes_and_where_from(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    planned = await _private_arm(db, team)
    await _described(db, team)

    data = await _expected(client, team, alice_headers)

    rows = data["expected"]
    assert all(set(row) == ROW_KEYS for row in rows)
    assert data["more"] == 0 and len(rows) == planned + 3
    config = [row for row in rows if row["robot_id"] is not None]
    assert len(config) == planned
    assert {row["source"] for row in config} == {"Private arm"}
    assert all(row["name"] and row["what"] for row in config)
    described = {row["name"]: row for row in rows if row["robot_id"] is None}
    assert described == {
        "/imu": {
            "name": "/imu",
            "what": "sensor_msgs/msg/Imu",
            "robot_id": None,
            "source": "ROS code",
        },
        "nano_sensors": {
            "name": "nano_sensors",
            "what": "uses Baro.h, Wire.h",
            "robot_id": None,
            "source": "nano_sensors.ino",
        },
        "U1": {"name": "U1", "what": "CHIP1", "robot_id": None, "source": "schematic"},
    }
    assert data["sources"] == ["Private arm", "ROS code", "nano_sensors.ino", "schematic"]


async def test_a_connected_sources_part_is_said_from_that_source(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    board = Source(
        project_id=team.project_id,
        team_id=uuid.UUID(team.team),
        type=SourceType.KICAD,
        name="sensor_hat",
        config={},
        status="connected",
    )
    db.add(board)
    await db.flush()
    chip = _node(team, kinds.COMPONENT, Domain.ELECTRICAL, "U4", libsource="MCU_Fam:Chip1")
    chip.source_id = board.id
    db.add(chip)
    await db.commit()

    data = await _expected(client, team, alice_headers)

    assert data["expected"] == [
        {"name": "U4", "what": "MCU_Fam:Chip1", "robot_id": None, "source": "sensor_hat"}
    ]
    assert data["sources"] == ["sensor_hat"]


async def test_a_teammates_hidden_robot_gives_no_row_source_or_count(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    await _private_arm(db, team)

    assert await _expected(client, team, bob_headers) == NOTHING

    await _described(db, team)
    bob = await _expected(client, team, bob_headers)
    assert [row["name"] for row in bob["expected"]] == ["/imu", "nano_sensors", "U1"]
    assert all(row["robot_id"] is None for row in bob["expected"])
    assert bob["sources"] == ["ROS code", "nano_sensors.ino", "schematic"] and bob["more"] == 0


async def test_expected_needs_a_token_and_the_project_and_reads_no_other_teams(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    alice = await me(client, alice_headers)
    await me(client, bob_headers)
    team_a = await create_team(client, alice_headers)
    project_a = await create_project(client, alice_headers, team_a["id"])
    mine = _Team(project_a["id"], team_a["id"], alice, {})
    await _described(db, mine)
    team_b = await create_team(client, bob_headers)
    project_b = await create_project(client, bob_headers, team_b["id"])
    theirs = _Team(project_b["id"], team_b["id"], {}, {})

    assert (await client.get(mine.url("hardware", "expected"))).status_code == 401
    # Bob belongs to no team of Alice's project: it does not exist for him.
    outsider = await client.get(mine.url("hardware", "expected"), headers=bob_headers)
    assert outsider.status_code == 404
    # His own project says nothing of hers.
    assert await _expected(client, theirs, bob_headers) == {
        "expected": [],
        "sources": [],
        "more": 0,
    }
    # A viewer reads, like every other hardware read route (no 403 on a read).
    await add_member(client, alice_headers, bob_headers, BOB, team_a["id"], role="viewer")
    assert len((await _expected(client, mine, bob_headers))["expected"]) == 3


async def test_expected_is_bounded_and_every_value_is_one_short_line(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    hostile = "/a\nApprove\u202e " + "x" * 300
    topics = [hostile, *(f"/t{i:03}" for i in range(MAX_ROWS + 5))]
    db.add_all(
        [
            _node(team, kinds.ROS_TOPIC, Domain.CODE, name, type="sensor_msgs/" + "y" * 300)
            for name in topics
        ]
        + [
            _node(
                team,
                kinds.ARDUINO_SKETCH,
                Domain.CODE,
                f"sketch{i:02}",
                observations=[{"source_file": f"fw/s{i:02}.ino", "libraries": ["Wire.h"]}],
            )
            for i in range(MAX_SOURCES + 3)
        ]
    )
    await db.commit()

    data = await _expected(client, team, alice_headers)

    assert len(data["expected"]) == MAX_ROWS
    assert data["more"] == MAX_SOURCES + 3  # topics are read MAX_ROWS at most
    assert data["expected"][0]["name"].startswith("/a Approve x")
    # Only what the listed rows say: the sketches past the cut name no source.
    assert data["sources"] == ["ROS code"]
    texts = [str(v) for row in data["expected"] for v in row.values() if v] + data["sources"]
    assert all(len(text) <= 80 and text.isprintable() for text in texts)


async def test_expected_names_at_most_max_sources(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    db.add_all(
        _node(
            team,
            kinds.ARDUINO_SKETCH,
            Domain.CODE,
            f"sketch{i:02}",
            observations=[{"source_file": f"fw/s{i:02}.ino", "libraries": ["Wire.h"]}],
        )
        for i in range(MAX_SOURCES + 3)
    )
    await db.commit()

    data = await _expected(client, team, alice_headers)

    assert len(data["expected"]) == MAX_SOURCES + 3 and len(data["sources"]) == MAX_SOURCES
