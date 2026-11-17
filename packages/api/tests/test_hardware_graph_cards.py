"""SOLUSDEV-326 P2-T5: SOL's card tools that write the graph around hardware
(agent/tools/hardware_graph_cards.py): `hardware.apply_evidence`, `hardware.link_part`,
`hardware.import_definition` and `hardware.set_in_graph`. Like every hardware card tool
(test_hardware_cards.py) each parks an offer card from its stored arguments, its preview never
reaches the local runner, and approval writes as the member: what they add stays theirs until
set_in_graph adds it, and only they take it out again.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.confirmations import ParkedCall, _diverged
from solus_api.agent.tools.hardware_cards import (
    APPLY_EVIDENCE,
    IMPORT_DEFINITION,
    LINK_PART,
    SET_IN_GRAPH,
)
from solus_api.agent.tools.hardware_onboarding import LIST_PARTS, READ_EVIDENCE
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.hardware.local_sources import LocalHardwareSources, LocalSourceError
from solus_api.models import (
    ConfirmationStatus,
    Domain,
    GraphEdge,
    GraphEntity,
    SolMode,
    ToolConfirmation,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from test_hardware_attach import _connector_parts
from test_hardware_cards import (
    _approve,
    _bob,
    _cards,
    _consent,
    _events,
    _offer,
    _park,
    _pure,
    _ran,
    _refused,
    _Runner,
    _value,
)
from test_in_graph import (
    _bobs_robot,
    _loose,
    _onboard,
    _onboarded,
    _out,
    _Team,
    _team,
    _wire,
)
from test_topology_proposals import setup as extraction_setup

# ---------------------------------------------------------------------------- apply_evidence


async def test_apply_evidence_adds_the_reviewed_rows_and_refuses_evidence_that_changed(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, team, robot, body, selected, _ = await extraction_setup(
        client, alice_headers, app, tmp_path, monkeypatch
    )
    await _consent(db)
    user = uuid.UUID((await me(client, alice_headers))["id"])
    runner = _Runner()
    alice = _cards(engine, uuid.UUID(project), user, runner)
    named = {key: body[key] for key in ("brain_id", "source_ref")}
    read = await _value(alice, READ_EVIDENCE, {"source": "host_config", "robot_id": robot, **named})
    args = {
        "source": "host_config",
        "robot_id": robot,
        **named,
        "proposal_digest": read["proposal_digest"],
        "rows": [{"row_index": 0, "name": " elbow "}],
    }

    parked = await _park(engine, alice, team, uuid.UUID(project), user, APPLY_EVIDENCE, args)

    card = _offer(parked)
    assert card["title"] == "Add 1 row of evidence to the robot" and "elbow" in card["body"]
    assert str(selected) not in json.dumps(parked.card) + json.dumps(parked.preview)

    def unreadable(*_: object) -> None:
        raise LocalSourceError("relink_required")

    with monkeypatch.context() as patched:  # the preview never reads the member's file
        patched.setattr(LocalHardwareSources, "read_source", unreadable)
        await _pure(alice, parked, runner)
    value = _ran(await _approve(engine, alice, parked, uuid.UUID(project), user))
    assert value["created"] == 1 and len(value["entity_ids"]) == 1
    evidence = await db.get(GraphEntity, uuid.UUID(value["entity_ids"][0]))
    assert evidence is not None and evidence.name == "elbow"
    [(_, payload)] = await _events(db, "hardware.extraction_confirmed")
    assert payload == {"robot_id": robot, "brain_id": body["brain_id"], "count": 1}

    read = await _value(alice, READ_EVIDENCE, {"source": "host_config", "robot_id": robot, **named})
    later = {**args, "proposal_digest": read["proposal_digest"]}
    later["rows"] = [{"row_index": 0, "name": "wrist"}]
    parked = await _park(engine, alice, team, uuid.UUID(project), user, APPLY_EVIDENCE, later)
    assert parked.confirmation_id is not None
    selected.write_text('{"parts":{"wrist":{"address":"07","model":"servo"}}}')
    await _pure(alice, parked, runner)  # a changed file never changes the card: the write refuses
    refused = await _approve(engine, alice, parked, uuid.UUID(project), user)
    assert refused.error is not None and refused.error.code is ToolErrorCode.UNAVAILABLE
    assert "changed" in refused.error.message  # the write read the file again and refused it
    status = await db.scalar(
        select(ToolConfirmation.status).where(ToolConfirmation.id == parked.confirmation_id)
    )
    assert status is ConfirmationStatus.APPROVED  # decided, then refused by the write: not STALE
    kept = await db.scalars(select(GraphEntity.name).where(GraphEntity.kind == "hardware_evidence"))
    assert list(kept) == ["elbow"]
    assert len(await _events(db, "hardware.extraction_confirmed")) == 1


async def test_apply_evidence_never_reaches_hardware_its_member_cannot_see(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    """Bob cannot name Alice's robot out of the graph, nor a part of hers on a robot of his own;
    Alice in project A cannot name a robot of another team's project: each reads as an unknown
    id, names nothing and parks nothing."""
    team = await _team(client, alice_headers, bob_headers)
    hidden = await _onboard(db, team)
    topology = await client.get(
        team.url("hardware", "robots", str(hidden.robot.id), "topology"), headers=alice_headers
    )
    brain = next(n["id"] for n in topology.json()["data"]["nodes"] if n["role"] == "brain")
    other_team = await create_team(client, alice_headers)
    other_project = await create_project(client, alice_headers, other_team["id"])
    foreign = await _onboard(
        db, _Team(other_project["id"], other_team["id"], team.alice, team.bob), in_graph=True
    )
    part = await db.get(GraphEntity, hidden.part_ids[0])
    assert part is not None
    runner = _Runner()
    bob = _cards(engine, team.project_id, _bob(team), runner)
    alice = _cards(engine, team.project_id, team.alice_id, runner)
    evidence = {
        "source": "host_config",
        "brain_id": brain,
        "source_ref": f"source:{uuid.uuid4()}",
        "proposal_digest": "0" * 64,
    }
    row = {"row_index": 0, "name": "elbow"}
    attempts = [
        (bob, _bob(team), str(hidden.robot.id), row, "Robot not found"),
        (
            bob,
            _bob(team),
            await _bobs_robot(client, team, bob_headers),
            {**row, "entity_id": str(part.id)},
            "A part a row names was not found.",
        ),
        (alice, team.alice_id, str(foreign.robot.id), row, "Robot not found"),
    ]
    for registry, user, robot, kept, expected in attempts:
        args = {**evidence, "robot_id": robot, "rows": [kept]}
        parked = await _park(
            engine, registry, team.team, team.project_id, user, APPLY_EVIDENCE, args
        )
        assert _refused(parked, ToolErrorCode.NOT_FOUND) == expected  # no name, no id
    assert runner.calls == []
    assert (await db.scalar(select(func.count()).select_from(ToolConfirmation))) == 0


async def test_apply_evidence_refuses_two_rows_of_one_name(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    """Two kept rows of one name would be two card rows of one label: refused before any read."""
    team = await _team(client, alice_headers, bob_headers)
    onboarded = await _onboard(db, team)
    alice = _cards(engine, team.project_id, team.alice_id, _Runner())
    args = {
        "source": "host_config",
        "robot_id": str(onboarded.robot.id),
        "brain_id": str(uuid.uuid4()),
        "source_ref": f"source:{uuid.uuid4()}",
        "proposal_digest": "0" * 64,
        "rows": [
            {"row_index": 0, "name": "elbow", "entity_id": str(onboarded.part_ids[0])},
            {"row_index": 1, "name": " Elbow "},
        ],
    }

    parked = await _park(
        engine, alice, team.team, team.project_id, team.alice_id, APPLY_EVIDENCE, args
    )

    message = _refused(parked, ToolErrorCode.INVALID_ARGS)
    assert message == "Keep each row once, each with a short name."
    assert (await db.scalar(select(func.count()).select_from(ToolConfirmation))) == 0


def test_rows_of_one_label_compare_whether_or_not_each_has_a_before() -> None:
    """The stale check sorts the rendered rows: two of one label, one with a `before` and one
    without, compare instead of raising, and still diverge only when a row differs."""
    rows: list[dict[str, Any]] = [
        {"label": "Robot", "before": None, "after": "arm"},
        {"label": "Robot", "before": "Elbow", "after": "servo at 6"},
        {"label": "Robot", "before": "Elbow", "after": None},
    ]

    assert _diverged(rows, rows[::-1]) is False
    assert _diverged(rows, [rows[0], {**rows[1], "before": None}, rows[2]]) is True
    assert _diverged(rows, [rows[0], rows[1], {**rows[2], "after": ""}]) is True


# ---------------------------------------------------------------------------- link_part


async def test_link_part_links_what_it_can_and_reports_the_rest(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    """Partial success: the CAD body is the same physical part and the sketch reads it; an id
    nobody has and a robot (hardware, not a design node) are named on the card and the result."""
    team = await _team(client, alice_headers, bob_headers)
    await _consent(db)
    onboarded = await _onboard(db, team)
    part = onboarded.part_ids[0]
    [cad] = await _connector_parts(db, team.project, team.team, ["Elbow bracket"])
    body = await db.get(GraphEntity, cad)
    assert body is not None
    sketch = GraphEntity(
        project_id=team.project_id,
        kind="code_file",
        domain=Domain.CODE,
        name="elbow.ino",
        origin="connector",
        source_id=body.source_id,
        external_ref="code:elbow.ino",
        attrs={},
    )
    db.add(sketch)
    await db.commit()
    nobody = str(uuid.uuid4())
    runner = _Runner()
    alice = _cards(engine, team.project_id, team.alice_id, runner)
    args = {
        "part_id": str(part),
        "targets": [
            {"entity_id": str(cad)},
            {"entity_id": str(sketch.id), "relation": "reads"},
            {"entity_id": nobody},
            {"entity_id": str(onboarded.robot.id)},
        ],
    }

    parked = await _park(engine, alice, team.team, team.project_id, team.alice_id, LINK_PART, args)

    card = _offer(parked)
    assert card["title"] == "Link this part to 2 design nodes" and card["primary"] == "Link"
    assert "2 more can't be linked" in card["body"]
    await _pure(alice, parked, runner)
    value = _ran(await _approve(engine, alice, parked, team.project_id, team.alice_id))

    assert {(row["entity_id"], row["relation"]) for row in value["linked"]} == {
        (str(cad), "same_as"),
        (str(sketch.id), "reads"),
    }
    assert {row["entity_id"] for row in value["skipped"]} == {nobody, str(onboarded.robot.id)}
    edges = await db.execute(
        select(GraphEdge.relation_type, GraphEdge.src_id, GraphEdge.dst_id, GraphEdge.origin).where(
            GraphEdge.project_id == team.project_id,
            GraphEdge.relation_type.in_(("same_as", "reads")),
            GraphEdge.deleted_at.is_(None),
        )
    )
    assert set(edges.tuples()) == {
        ("same_as", part, cad, "manual"),
        ("reads", sketch.id, part, "manual"),
    }
    [(_, payload)] = await _events(db, "hardware.part_linked")
    assert payload == {"part_id": str(part), "linked": 2, "skipped": 2}


async def test_link_part_reads_a_target_its_member_cannot_see_as_an_unknown_id(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    """Bob links his own part: Alice's part out of the graph and a part of another team's project
    are 'not found' by the id he sent — never named, on the refusal, the card or the preview."""
    team = await _team(client, alice_headers, bob_headers)
    hidden = await _onboard(db, team)
    other_team = await create_team(client, alice_headers)
    other_project = await create_project(client, alice_headers, other_team["id"])
    foreign = await _onboard(
        db, _Team(other_project["id"], other_team["id"], team.alice, team.bob), in_graph=True
    )
    unseen = [str(hidden.part_ids[0]), str(foreign.part_ids[0])]
    names = set(
        await db.scalars(
            select(GraphEntity.name).where(GraphEntity.id.in_([uuid.UUID(i) for i in unseen]))
        )
    )
    [cad] = await _connector_parts(db, team.project, team.team, ["Elbow bracket"])
    mine = await _loose(client, team, bob_headers, "Bobs servo")
    runner = _Runner()
    bob = _cards(engine, team.project_id, _bob(team), runner)

    async def park(*targets: str) -> ParkedCall:
        args = {"part_id": mine, "targets": [{"entity_id": target} for target in targets]}
        return await _park(engine, bob, team.team, team.project_id, _bob(team), LINK_PART, args)

    message = _refused(await park(*unseen), ToolErrorCode.INVALID_ARGS)
    assert message == f"Nothing to link: {unseen[0]}: not found; {unseen[1]}: not found"
    assert (await db.scalar(select(func.count()).select_from(ToolConfirmation))) == 0

    parked = await park(str(cad), unseen[0])

    assert parked.args["shown"]["targets"][1] == {
        "entity_id": unseen[0],
        "name": None,
        "relation": None,
        "reason": "not found",
    }
    assert {"label": unseen[0], "before": None, "after": "not linked: not found"} in parked.preview
    assert "1 more can't be linked" in _offer(parked)["body"]
    told = json.dumps([parked.card, parked.preview, parked.args])
    assert names and not any(name in told for name in {*names, "Private arm"})


# ---------------------------------------------------------------------------- import_definition


async def test_import_definition_adds_a_platform_out_of_the_graph_and_a_part_into_a_robot(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    await _consent(db)
    runner = _Runner()
    alice = _cards(engine, team.project_id, team.alice_id, runner)

    platform = await _park(
        engine,
        alice,
        team.team,
        team.project_id,
        team.alice_id,
        IMPORT_DEFINITION,
        {"definition_id": "so101-follower", "name": "Follower"},
    )

    card = _offer(platform)
    assert card["title"] == "Add a new robot from the library"
    assert card["field"] == {"label": "Robot name", "value": "Follower"}
    await _pure(alice, platform, runner)
    value = _ran(await _approve(engine, alice, platform, team.project_id, team.alice_id))
    robot = await db.get(GraphEntity, uuid.UUID(value["robot_id"]))
    assert robot is not None and robot.name == "Follower"
    assert (robot.attrs["in_graph"], robot.attrs["onboarded_by"]) == (False, str(team.alice_id))
    bob = _cards(engine, team.project_id, _bob(team), runner)
    assert (await _value(bob, LIST_PARTS, {}))["robots"] == []

    part = await _park(
        engine,
        alice,
        team.team,
        team.project_id,
        team.alice_id,
        IMPORT_DEFINITION,
        {"definition_id": "sts3215", "robot_id": value["robot_id"], "name": "spare"},
    )
    assert "Follower" in _offer(part)["body"]
    added = _ran(await _approve(engine, alice, part, team.project_id, team.alice_id))
    entity = await db.get(GraphEntity, uuid.UUID(added["part_id"]))
    assert entity is not None and entity.attrs["onboarded_by"] == str(team.alice_id)
    imported = [payload["parts"] for _, payload in await _events(db, "hardware.library_imported")]
    assert imported == [6, 1]

    lone = await _park(
        engine,
        alice,
        team.team,
        team.project_id,
        team.alice_id,
        IMPORT_DEFINITION,
        {"definition_id": "sts3215"},
    )
    assert "robot_id" in _refused(lone, ToolErrorCode.INVALID_ARGS)


# ---------------------------------------------------------------------------- set_in_graph


async def test_only_the_onboarder_takes_hardware_out_and_a_no_op_never_parks(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    robot = (await _onboard(db, team, in_graph=True)).robot
    runner = _Runner()
    alice = _cards(engine, team.project_id, team.alice_id, runner)
    bob = _cards(engine, team.project_id, _bob(team), runner)
    out = {"entity_id": str(robot.id), "in_graph": False}

    _refused(
        await _park(engine, bob, team.team, team.project_id, _bob(team), SET_IN_GRAPH, out),
        ToolErrorCode.UNAUTHORIZED,
    )
    already = {"entity_id": str(robot.id), "in_graph": True}
    assert "already" in _refused(
        await _park(
            engine, alice, team.team, team.project_id, team.alice_id, SET_IN_GRAPH, already
        ),
        ToolErrorCode.UNAVAILABLE,
    )
    parked = await _park(
        engine, alice, team.team, team.project_id, team.alice_id, SET_IN_GRAPH, out, SolMode.EXPERT
    )
    card = _offer(parked)
    assert card["title"] == "Take this robot out of the graph" and card["more"] is None
    assert card["primary"] == "Remove from graph" and "Only you" in card["body"]
    _ran(await _approve(engine, alice, parked, team.project_id, team.alice_id))
    assert (await _value(bob, LIST_PARTS, {}))["robots"] == []


async def test_the_set_in_graph_card_names_the_wired_parts_that_join_with_it(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    """Adding a robot adds the member's parts out of the graph its config wires (`admit_wired`):
    the card names them, a part wired after the card was shown makes it stale, and a wired part
    that is not the member's refuses before any card, naming nothing."""
    team = await _team(client, alice_headers, bob_headers)
    robot = str((await _onboard(db, team)).robot.id)
    part = await _loose(client, team, alice_headers, "Her encoder")
    await _onboarded(db, part, team.alice_id)
    assert (await _out(client, team, alice_headers, part)).status_code == 200
    runner = _Runner()
    alice = _cards(engine, team.project_id, team.alice_id, runner)
    bob = _cards(engine, team.project_id, _bob(team), runner)
    add = {"entity_id": robot, "in_graph": True}

    async def park() -> ParkedCall:
        return await _park(
            engine, alice, team.team, team.project_id, team.alice_id, SET_IN_GRAPH, add
        )

    before = await park()
    assert "Her encoder" not in json.dumps(before.card) + json.dumps(before.preview)
    await _wire(client, team, alice_headers, robot, part, "EEE")
    stale = await _approve(engine, alice, before, team.project_id, team.alice_id)
    assert stale.error is not None and "changed" in stale.error.message
    status = await db.scalar(
        select(ToolConfirmation.status).where(ToolConfirmation.id == before.confirmation_id)
    )
    assert status is ConfirmationStatus.STALE
    assert (await _value(bob, LIST_PARTS, {}))["parts"] == []

    parked = await park()
    assert parked.args["shown"]["wired"] == ["Her encoder"]
    assert "1 wired part on other hardware: `Her encoder`" in _offer(parked)["body"]
    assert any("Her encoder" in str(row["after"]) for row in parked.preview)
    await _pure(alice, parked, runner)
    _ran(await _approve(engine, alice, parked, team.project_id, team.alice_id))
    names = {row["name"] for row in (await _value(bob, LIST_PARTS, {}))["parts"]}
    assert "Her encoder" in names

    # Not the member's to add: the same closure refuses, and says nothing of what it found.
    assert (await _out(client, team, alice_headers, robot)).status_code == 200
    await _onboarded(db, part, _bob(team))
    hidden = await db.get(GraphEntity, uuid.UUID(part))
    assert hidden is not None
    hidden.attrs = {**hidden.attrs, "in_graph": False}
    await db.commit()
    message = _refused(await park(), ToolErrorCode.UNAVAILABLE)
    assert "Her encoder" not in message and "teammate" in message
