"""SOLUSDEV-326 P2-T5: SOL's hardware card tools (agent/tools/hardware_cards.py).

`hardware.add_parts`, `hardware.add_connection`, `hardware.apply_evidence`, `hardware.link_part`,
`hardware.import_definition` and `hardware.set_in_graph` register beside the hardware reads for a
person on a local API. Each is gated statically (a complete preview, `card_resumes`), is never an
owned routine and is on no auto-run list. Each parks an offer card built from its STORED arguments
(these write the graph, never the hardware). Its preview re-reads only Solus's own state — never the
local runner — so deciding never goes stale on a flaky read, and approval runs the stored call as
the member through the hardware services: nothing listens to a device again. Hardware SOL adds stays
out of the workspace graph, seen only by its onboarder, until set_in_graph adds it. The local runner
is a fake: no device is ever opened.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from conftest import create_project, create_team
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.cards import authored_card, working_line
from solus_api.agent.command_auto import AUTO_TOOLS
from solus_api.agent.command_gate import COMMAND_TOOLS
from solus_api.agent.confirmations import ParkedCall, decide_confirmation, request_confirmation
from solus_api.agent.dynamic_gate import registered_tool
from solus_api.agent.execution_policy import (
    _BRIDGE_SCHEMAS,
    _ONSHAPE,
    BuildExecutionPolicy,
    register_owned_routine,
)
from solus_api.agent.modes import DIRECT_WRITE_TOOLS, ActionMode
from solus_api.agent.runtime import build_sol_registry
from solus_api.agent.tools.hardware_cards import (
    ADD_CONNECTION,
    ADD_PARTS,
    APPLY_EVIDENCE,
    HARDWARE_CARDS,
    IMPORT_DEFINITION,
    LINK_PART,
    SET_IN_GRAPH,
)
from solus_api.agent.tools.hardware_onboarding import (
    INSPECT_DEVICE,
    LIST_PARTS,
    register_hardware_tools,
)
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolErrorCode, ToolResult
from solus_api.contracts.action_gate import Card
from solus_api.graph.live import LiveHub
from solus_api.hardware.detect import ProposalOut
from solus_api.hardware.inspections import INSPECTIONS
from solus_api.models import (
    ConfirmationStatus,
    DataEvent,
    GraphEntity,
    SolMode,
    SolusEntry,
    ToolConfirmation,
    User,
)
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_hardware_detect import DEVICE_REF, _DetectLocal, _wire_device, _wire_proposal
from test_in_graph import _onboard, _Team, _team

SECOND = "usb:SECOND"


class _Runner(_DetectLocal):
    """This computer as the card tools reach it: it enumerates and counts every call. A card tool
    never listens to a device, and its preview never reaches the runner at all."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def detect_devices(self) -> list[dict[str, Any]]:
        self.calls.append("detect_devices")
        return super().detect_devices()

    def propose_device(
        self, device_ref: str, *, repo_root: str | None = None, budget_s: float = 0.5
    ) -> dict[str, Any] | None:
        self.calls.append("propose_device")
        return super().propose_device(device_ref, repo_root=repo_root, budget_s=budget_s)

    def listen_restarts(self, device_ref: str) -> bool:
        self.calls.append("listen_restarts")
        return False


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _cards(
    engine: AsyncEngine, project: uuid.UUID, user: uuid.UUID, local: Any = None
) -> ToolRegistry:
    registry = ToolRegistry()
    register_hardware_tools(
        registry, _factory(engine), project, user_id=user, local=local, hub=LiveHub()
    )
    return registry


def _bob(team: _Team) -> uuid.UUID:
    return uuid.UUID(team.bob["id"])


def _inspected(team: _Team, proposal: dict[str, Any] | None = None) -> str:
    """Alice's inspection of a device, kept for her in this project (`inspect_device`'s store)."""
    found = ProposalOut.model_validate(proposal or _wire_proposal())
    return INSPECTIONS.put(team.project_id, team.alice_id, found).id


def _on(ref: str, proposal: dict[str, Any]) -> dict[str, Any]:
    """`proposal` as heard on another device: its ref and serial everywhere."""
    serial = ref.removeprefix("usb:")
    return dict(json.loads(json.dumps(proposal).replace("5B42134331", serial)))


def _line_board() -> dict[str, Any]:
    """A board printing four numbers a line; the evidence names its columns."""
    proposal = _wire_proposal()
    proposal.update(
        {
            "driver_id": "line-demo",
            "params": {"baud": 115200},
            "summary": "4 numbers per line",
            "headline": "a board on USB",
            "stream": {
                "framing": "csv",
                "channel_count": 4,
                "update_hz": 50.0,
                "channel_names": ["ax", "ay", "az", "temp"],
            },
            "rows": [
                {
                    "id": f"{DEVICE_REF}/{column}",
                    "subject": f"reading at address {column}",
                    "address": str(column),
                    "model": None,
                    "proposed_function": None,
                    "confidence": 0.9,
                    "evidence": [],
                    "provenance": "bus",
                }
                for column in range(4)
            ],
            "evidence": [],
        }
    )
    return proposal


def _unidentified() -> dict[str, Any]:
    proposal = _wire_proposal()
    proposal.update(
        {
            "level": "transport",
            "summary": "a USB serial device: no protocol recognised",
            "driver_id": None,
            "params": {},
            "rows": [],
            "evidence": [],
        }
    )
    return proposal


async def _park(
    engine: AsyncEngine,
    registry: ToolRegistry,
    team_id: str,
    project: uuid.UUID,
    user: uuid.UUID,
    tool: str,
    args: dict[str, Any],
    mode: SolMode = SolMode.GUIDE,
) -> ParkedCall:
    async with _factory(engine)() as session:
        parked = await request_confirmation(
            session,
            registry,
            ToolCall(tool=tool, args=args),
            project_id=project,
            team_id=uuid.UUID(team_id),
            user_id=user,
            sol_mode=mode,
        )
        await session.commit()
    assert parked is not None, f"{tool} must always park"
    return parked


async def _approve(
    engine: AsyncEngine,
    registry: ToolRegistry,
    parked: ParkedCall,
    project: uuid.UUID,
    user: uuid.UUID,
) -> ToolResult:
    assert parked.confirmation_id is not None, parked.result.error
    async with _factory(engine)() as session:
        result = await decide_confirmation(
            session,
            registry,
            parked.confirmation_id,
            approve=True,
            project_id=project,
            user_id=user,
        )
        await session.commit()
    return result


def _ran(result: ToolResult) -> dict[str, Any]:
    assert result.ok and result.value is not None, result.error
    return result.value


def _refused(parked: ParkedCall, code: ToolErrorCode) -> str:
    """Nothing was parked: the call was refused with `code`; its message."""
    error = parked.result.error
    assert parked.confirmation_id is None and error is not None
    assert error.code is code, error
    return error.message


def _offer(parked: ParkedCall) -> dict[str, Any]:
    """The card is an offer (these write the graph, never the hardware): the contract's shape,
    a one-line body, "Not now" and a receipt; SOL continues after any decision on it."""
    assert parked.card is not None, parked.result.error
    card = Card.model_validate(parked.card)
    assert card.kind == "offer" and card.secondary == "Not now" and card.resumes is True
    assert card.receipt and "\n" not in card.body and len(card.body) <= 240
    return dict(parked.card)


async def _pure(registry: ToolRegistry, parked: ParkedCall, runner: _Runner) -> None:
    """The preview reads Solus's own state alone: twice over the same stored arguments it is the
    card's rows again, and it never reaches the local runner."""
    preview: Any = getattr(registered_tool(registry, parked.tool), "preview", None)
    calls = list(runner.calls)
    again = [await preview(dict(parked.args)) for _ in range(2)]
    assert again == [parked.preview, parked.preview]
    assert runner.calls == calls


async def _value(registry: ToolRegistry, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return _ran(await registry.invoke(ToolCall(tool=tool, args=args)))


async def _consent(db: AsyncSession) -> None:
    await db.execute(update(User).values(data_collection_consent=True))
    await db.commit()


async def _events(db: AsyncSession, *names: str) -> list[tuple[str, dict[str, Any]]]:
    rows = await db.scalars(
        select(DataEvent).where(DataEvent.event_type.in_(names)).order_by(DataEvent.created_at)
    )
    return [(row.event_type, row.payload) for row in rows]


async def _robots(db: AsyncSession, project: uuid.UUID) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(GraphEntity)
        .where(GraphEntity.project_id == project, GraphEntity.kind == "physical_robot")
    )
    return int(count or 0)


# ---------------------------------------------------------------------------- registration


def test_the_card_tools_register_gated_beside_the_reads_with_the_apps_hub() -> None:
    project, person = uuid.uuid4(), uuid.uuid4()

    def tools(registry: ToolRegistry) -> dict[str, Any]:
        return {tool.descriptor.name: tool for tool in registry.tools()}

    local = _Runner()
    bound = tools(build_sol_registry(MagicMock(), project, user_id=person, hardware_local=local))
    assert not set(HARDWARE_CARDS) & set(bound)  # no hub to publish through: no writes
    registry = build_sol_registry(
        MagicMock(), project, user_id=person, hardware_local=local, graph_hub=LiveHub()
    )
    found = tools(registry)
    assert set(HARDWARE_CARDS) <= set(found)
    hosted = tools(build_sol_registry(MagicMock(), project, user_id=person, graph_hub=LiveHub()))
    assert not set(HARDWARE_CARDS) & set(hosted)
    for name in HARDWARE_CARDS:
        tool = found[name]
        assert tool.descriptor.requires_confirmation is True, name
        assert tool.descriptor.consent_summary, name  # Solus words the person approves
        assert getattr(tool, "requires_complete_preview", False) is True, name
        assert getattr(tool, "card_resumes", False) is True, name
        assert all(callable(getattr(tool, hook, None)) for hook in ("preview", "card", "working"))
        # Solus's own words: no model value reaches the working line.
        line = working_line(registry, ToolCall(tool=name, args={"inspection_id": "x`y"}))
        assert line is None or "x`y" not in line


async def test_no_card_tool_can_auto_run() -> None:
    """No card tool is on an auto-run list, no registry makes one an owned routine — not even a
    call to `register_owned_routine` for any family — and Build sends every call to the gate."""
    registry = build_sol_registry(
        MagicMock(),
        uuid.uuid4(),
        user_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        hardware_local=_Runner(),
        graph_hub=LiveHub(),
    )
    lists = (AUTO_TOOLS, _ONSHAPE, set(_BRIDGE_SCHEMAS), DIRECT_WRITE_TOOLS, COMMAND_TOOLS)
    assert not any(set(HARDWARE_CARDS) & set(names) for names in lists)
    policy = BuildExecutionPolicy(registry, ActionMode.DO)
    for name in HARDWARE_CARDS:
        tool = registered_tool(registry, name)
        assert tool is not None and getattr(tool, "_build_authority", None) is None, name
        for family in ("onshape", "machine", "command", "bridge"):
            register_owned_routine(tool, family=family)
        assert getattr(tool, "_build_authority", None) is None, name
        assert await policy.prepare(ToolCall(tool=name, args={})) is False, name


# ---------------------------------------------------------------------------- add_parts


async def test_add_parts_keeps_a_new_robot_out_of_the_graph_until_set_in_graph_adds_it(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    """The card stamps the whole inspection, so approval only re-checks the device is still
    here: nothing listens again. The robot and its parts are Alice's alone — Bob's reads show
    nothing — until her set_in_graph card adds them, saying what moves with the robot."""
    team = await _team(client, alice_headers, bob_headers)
    await _consent(db)
    runner = _Runner()
    alice = _cards(engine, team.project_id, team.alice_id, runner)
    args = {"inspection_id": _inspected(team), "target": {"kind": "new", "name": "  Rover arm "}}

    parked = await _park(engine, alice, team.team, team.project_id, team.alice_id, ADD_PARTS, args)

    card = _offer(parked)
    assert card["title"] == "Add 2 parts as a new robot" and card["primary"] == "Add"
    assert card["field"] == {"label": "Robot name", "value": "Rover arm"}
    assert DEVICE_REF in card["body"] and card["more"]  # Guide's sentence
    assert parked.args["proposal"]["device_ref"] == DEVICE_REF  # the whole inspection, stamped
    assert [row["row_id"] for row in parked.args["rows"]] == [f"{DEVICE_REF}/1", f"{DEVICE_REF}/2"]
    assert runner.calls == []
    await _pure(alice, parked, runner)

    value = _ran(await _approve(engine, alice, parked, team.project_id, team.alice_id))

    assert value["robot"] == "Rover arm" and value["created_robot"] is True
    assert len(value["part_ids"]) == 2 and value["in_graph"] is False
    assert runner.calls == ["detect_devices"]  # the device is still here; it was not listened to
    ids = [uuid.UUID(value["robot_id"]), *(uuid.UUID(part) for part in value["part_ids"])]
    written = list(await db.scalars(select(GraphEntity).where(GraphEntity.id.in_(ids))))
    assert {(row.attrs.get("in_graph"), row.attrs.get("onboarded_by")) for row in written} == {
        (False, str(team.alice_id))
    }
    bob = _cards(engine, team.project_id, _bob(team), runner)
    empty = {"robots": [], "parts": [], "complete": True, "more": 0}
    assert await _value(bob, LIST_PARTS, {}) == empty

    moved = await _park(
        engine,
        alice,
        team.team,
        team.project_id,
        team.alice_id,
        SET_IN_GRAPH,
        {"entity_id": value["robot_id"], "in_graph": True},
    )
    shown = _offer(moved)
    assert shown["title"] == "Add this robot to the workspace graph"
    assert shown["primary"] == "Add to workspace graph" and "2 parts" in shown["body"]
    await _pure(alice, moved, runner)
    assert _ran(await _approve(engine, alice, moved, team.project_id, team.alice_id))["updated"]

    listed = await _value(bob, LIST_PARTS, {})
    assert [robot["name"] for robot in listed["robots"]] == ["Rover arm"]
    assert len(listed["parts"]) == 2
    names = ("hardware.robot_confirmed", "hardware.added_to_graph")
    assert [name for name, _ in await _events(db, *names)] == list(names)


async def test_add_parts_shows_the_repo_config_whose_calibration_it_writes(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    engine: AsyncEngine,
) -> None:
    """Two repo configs name the same parts with different calibration: the choice is on the
    card and in its preview rows (so the STALE check covers it), and approval writes that one."""
    team = await _team(client, alice_headers, bob_headers)
    runner = _Runner()
    alice = _cards(engine, team.project_id, team.alice_id, runner)
    inspection = _inspected(team, _wire_proposal(repo_matches=2))
    args = {"inspection_id": inspection, "target": {"kind": "new", "name": "Rover arm"}}

    async def park(config: str) -> ParkedCall:
        call = {**args, "repo_config_id": config}
        return await _park(
            engine, alice, team.team, team.project_id, team.alice_id, ADD_PARTS, call
        )

    first, second = await park("repo:cfg0"), await park("repo:cfg1")

    assert first.preview != second.preview and first.card != second.card
    assert {"label": "Repo config", "before": None, "after": "cfg1 (/cal/cfg1.json)"} in (
        second.preview or []
    )
    assert "`cfg1`" in _offer(second)["body"] and "`cfg0`" in _offer(first)["body"]
    await _pure(alice, second, runner)
    value = _ran(await _approve(engine, alice, second, team.project_id, team.alice_id))
    config = await client.get(
        team.url("hardware", "robots", value["robot_id"], "config"), headers=alice_headers
    )
    offsets = {
        part["calibration"]["values"]["homing_offset"]
        for part in config.json()["data"]["config"]["parts"].values()
    }
    assert offsets == {-2042}  # cfg1's, the one the card named

    one = _inspected(team, _on(SECOND, _wire_proposal(repo_matches=1)))
    single = await _park(
        engine,
        alice,
        team.team,
        team.project_id,
        team.alice_id,
        ADD_PARTS,
        {"inspection_id": one, "target": {"kind": "new", "name": "Second arm"}},
    )
    assert "`cfg0`" in _offer(single)["body"]  # the only match is written too, so it is shown


async def test_add_parts_refuses_when_the_device_left_and_writes_nothing(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    runner = _Runner()
    alice = _cards(engine, team.project_id, team.alice_id, runner)
    args = {"inspection_id": _inspected(team), "target": {"kind": "new", "name": "Rover arm"}}
    parked = await _park(engine, alice, team.team, team.project_id, team.alice_id, ADD_PARTS, args)
    runner.devices = []  # unplugged before the person approved

    refused = await _approve(engine, alice, parked, team.project_id, team.alice_id)

    assert refused.error is not None and refused.error.code is ToolErrorCode.NOT_FOUND
    assert "propose_device" not in runner.calls and await _robots(db, team.project_id) == 0


async def test_add_parts_refuses_what_it_cannot_add_before_parking(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    engine: AsyncEngine,
) -> None:
    """An inspection another member made, a row it did not hear, a bus of parts with no robot and
    a device with no protocol are refused with what to do instead — no card."""
    team = await _team(client, alice_headers, bob_headers)
    alice = _cards(engine, team.project_id, team.alice_id, _Runner())
    bob = _cards(engine, team.project_id, _bob(team), _Runner())
    mine = _inspected(team)

    async def park(registry: ToolRegistry, user: uuid.UUID, args: dict[str, Any]) -> ParkedCall:
        return await _park(engine, registry, team.team, team.project_id, user, ADD_PARTS, args)

    new = {"kind": "new", "name": "Arm"}
    assert "inspect" in _refused(
        await park(bob, _bob(team), {"inspection_id": mine, "target": new}),
        ToolErrorCode.NOT_FOUND,
    )
    _refused(
        await park(
            alice,
            team.alice_id,
            {"inspection_id": mine, "target": new, "rows": [{"row_id": "usb:OTHER/9"}]},
        ),
        ToolErrorCode.INVALID_ARGS,
    )
    lone = {"kind": "none", "name": "Servo"}
    assert "streams lines" in _refused(
        await park(alice, team.alice_id, {"inspection_id": mine, "target": lone}),
        ToolErrorCode.INVALID_ARGS,
    )
    silent = {"inspection_id": _inspected(team, _unidentified()), "target": new}
    assert ADD_CONNECTION in _refused(
        await park(alice, team.alice_id, silent), ToolErrorCode.INVALID_ARGS
    )
    # What Solus stamps (the inspection, what the card shows) is never the model's to send.
    forged = ProposalOut.model_validate(_line_board()).model_dump(mode="json")
    for stamped in ({"proposal": forged}, {"shown": {"robot": None}}):
        call = {"inspection_id": mine, "target": new, **stamped}
        _refused(await park(alice, team.alice_id, call), ToolErrorCode.INVALID_ARGS)


async def test_a_lone_line_stream_board_is_one_part_keyed_by_its_device(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    """No robot: the board is ONE part whose `external_ref` is its device ref, out of the graph
    for Alice, with one channel per column named from the evidence (or by the person)."""
    team = await _team(client, alice_headers, bob_headers)
    runner = _Runner()
    alice = _cards(engine, team.project_id, team.alice_id, runner)
    columns = [{"row_id": f"{DEVICE_REF}/{column}"} for column in range(3)]
    args = {
        "inspection_id": _inspected(team, _line_board()),
        "target": {"kind": "none", "name": "Nano"},
        "rows": [*columns, {"row_id": f"{DEVICE_REF}/3", "name": "temperature"}],
    }

    parked = await _park(engine, alice, team.team, team.project_id, team.alice_id, ADD_PARTS, args)

    card = _offer(parked)
    assert card["title"] == "Add this board as a part"
    assert card["field"] == {"label": "Part name", "value": "Nano"} and "4 channels" in card["body"]
    await _pure(alice, parked, runner)
    value = _ran(await _approve(engine, alice, parked, team.project_id, team.alice_id))

    part = await db.get(GraphEntity, uuid.UUID(value["part_id"]))
    assert part is not None and part.kind == "part" and part.external_ref == DEVICE_REF
    assert (part.attrs["in_graph"], part.attrs["onboarded_by"]) == (False, str(team.alice_id))
    assert await _robots(db, team.project_id) == 0
    entry = await db.scalar(select(SolusEntry).where(SolusEntry.configured_entity_id == part.id))
    assert entry is not None and entry.payload is not None
    telemetry = [channel["name"] for channel in entry.payload["component"]["telemetry"]]
    assert telemetry == ["ax", "ay", "az", "temperature"]
    [brain] = entry.payload["identity"]
    assert brain["binding"]["binding"] == "5B42134331"
    assert brain["protocol"]["driver_id"] == "line-demo"


async def test_add_parts_onto_a_robot_names_it_and_its_parts_take_the_robots_keys(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    """A second device onto Alice's robot in the graph: the card names the robot it read as
    Alice, and the parts are seen by whoever sees the robot — Bob included."""
    team = await _team(client, alice_headers, bob_headers)
    robot = (await _onboard(db, team, in_graph=True)).robot
    runner = _Runner()
    runner.devices = [_wire_device(), _wire_device(SECOND)]
    alice = _cards(engine, team.project_id, team.alice_id, runner)
    args = {
        "inspection_id": _inspected(team, _on(SECOND, _wire_proposal())),
        "target": {"kind": "existing", "robot_id": str(robot.id)},
    }

    parked = await _park(engine, alice, team.team, team.project_id, team.alice_id, ADD_PARTS, args)

    card = _offer(parked)
    assert card["title"] == "Add 2 parts to your robot" and "Private arm" in card["body"]
    value = _ran(await _approve(engine, alice, parked, team.project_id, team.alice_id))
    assert value["created_robot"] is False and value["robot_id"] == str(robot.id)
    listed = await _value(_cards(engine, team.project_id, _bob(team), runner), LIST_PARTS, {})
    assert len(listed["parts"]) == 4

    renamed = await db.get(GraphEntity, robot.id)
    assert renamed is not None
    again = await _park(
        engine, alice, team.team, team.project_id, team.alice_id, ADD_PARTS, {**args}
    )
    renamed.name = "Renamed arm"
    await db.commit()
    stale = await _approve(engine, alice, again, team.project_id, team.alice_id)
    assert stale.error is not None and "changed" in stale.error.message
    status = await db.scalar(
        select(ToolConfirmation.status).where(ToolConfirmation.id == again.confirmation_id)
    )
    assert status is ConfirmationStatus.STALE


# ---------------------------------------------------------------------------- add_connection


async def test_add_connection_keeps_an_unidentified_device_as_a_plain_connection(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    runner = _Runner()
    alice = _cards(engine, team.project_id, team.alice_id, runner)
    args = {
        "inspection_id": _inspected(team, _unidentified()),
        "target": {"kind": "new", "name": "Mystery box"},
    }

    parked = await _park(
        engine, alice, team.team, team.project_id, team.alice_id, ADD_CONNECTION, args
    )

    card = _offer(parked)
    assert card["title"] == "Firmware and protocol are unknown"
    assert card["primary"] == "Add as a connection" and DEVICE_REF in card["body"]
    await _pure(alice, parked, runner)
    value = _ran(await _approve(engine, alice, parked, team.project_id, team.alice_id))
    assert value["part_ids"] == [] and value["created_robot"] is True
    robot = await db.get(GraphEntity, uuid.UUID(value["robot_id"]))
    assert robot is not None and robot.attrs["in_graph"] is False
    assert runner.calls == ["detect_devices"]

    heard = {"inspection_id": _inspected(team), "target": {"kind": "new", "name": "Arm"}}
    assert ADD_PARTS in _refused(
        await _park(
            engine, alice, team.team, team.project_id, team.alice_id, ADD_CONNECTION, heard
        ),
        ToolErrorCode.INVALID_ARGS,
    )


async def test_add_connection_refuses_a_device_other_hardware_already_holds(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    """The write would re-bind the device to its holder while the card said "a plain connection
    of a new robot": refused before anything parks. The holder is named only to someone who may
    see it (§1a); a teammate's hardware out of the graph is never named."""
    team = await _team(client, alice_headers, bob_headers)
    await _onboard(db, team)  # Alice's "Private arm", out of the graph, holds DEVICE_REF
    robots = await _robots(db, team.project_id)
    silent = ProposalOut.model_validate(_unidentified())
    said: dict[str, str] = {}
    for who, user in (("alice", team.alice_id), ("bob", _bob(team))):
        registry = _cards(engine, team.project_id, user, _Runner())
        args = {
            "inspection_id": INSPECTIONS.put(team.project_id, user, silent).id,
            "target": {"kind": "new", "name": "Mystery box"},
        }
        said[who] = _refused(
            await _park(engine, registry, team.team, team.project_id, user, ADD_CONNECTION, args),
            ToolErrorCode.UNAVAILABLE,
        )

    assert "already connected to Private arm" in said["alice"]
    assert "a teammate's hardware that isn't in the graph" in said["bob"]
    assert "Private arm" not in said["bob"]
    assert await db.scalar(select(func.count()).select_from(ToolConfirmation)) == 0
    assert await _robots(db, team.project_id) == robots


# ------------------------------------------------------------------- the longest cards

LONG_REF = "usb:" + "S" * 128


def _longest_proposal(base: dict[str, Any] | None = None) -> dict[str, Any]:
    """An inspection whose every card text is as long as it gets: the longest device ref, tied to
    its USB port (the port note), three rows, and a repo config with a long label."""
    proposal = _on(LONG_REF, base or _wire_proposal(repo_matches=1))
    proposal["identity_basis"] = "port_position"
    if proposal["rows"]:
        third = {**proposal["rows"][0], "id": f"{LONG_REF}/3", "address": "3"}
        proposal["rows"] = [*proposal["rows"], third]
    for match in proposal["repo_matches"]:
        match["label"] = "c" * 80
    return proposal


def _longest_stored() -> dict[str, tuple[str, dict[str, Any]]]:
    """Per card, the tool and the longest STORED arguments its card is written from."""
    heard, silent = _longest_proposal(), _longest_proposal(_unidentified())
    picks = [
        {"row_id": row["id"], "name": f"{index}" + "p" * 119}
        for index, row in enumerate(heard["rows"])
    ]
    new, onto = (
        {"kind": "new", "name": "N" * 120},
        {"kind": "existing", "robot_id": str(uuid.uuid4())},
    )
    robot = {"name": "R" * 200, "in_graph": True}
    parts = {"rows": picks, "proposal": heard, "repo_config_id": "repo:cfg0"}
    definition = {"name": "D" * 200, "platform": True, "parts": [["r" * 200, None, None]] * 5}
    moves = {"robot": True, "name": "N" * 200, "parts": 999, "wiring": 999, "runs": 999}
    return {
        "add_parts new": (ADD_PARTS, {**parts, "target": new, "shown": {"robot": None}}),
        "add_parts existing": (ADD_PARTS, {**parts, "target": onto, "shown": {"robot": robot}}),
        "add_connection": (
            ADD_CONNECTION,
            {"target": new, "proposal": silent, "shown": {"robot": None}},
        ),
        "apply_evidence": (
            APPLY_EVIDENCE,
            {
                "source": "host_config",
                "rows": [{"name": "n" * 120}] * 32,
                "shown": {"robot": "R" * 200},
            },
        ),
        "link_part": (
            LINK_PART,
            {
                "shown": {
                    "part": "P" * 200,
                    "targets": [{"name": "t" * 200, "relation": "reads"}] * 16,
                }
            },
        ),
        "import_definition platform": (
            IMPORT_DEFINITION,
            {"name": "N" * 120, "shown": {"definition": definition, "robot": None}},
        ),
        "import_definition part": (
            IMPORT_DEFINITION,
            {
                "name": "N" * 120,
                "shown": {"definition": {**definition, "platform": False}, "robot": robot},
            },
        ),
        "set_in_graph add": (
            SET_IN_GRAPH,
            {"in_graph": True, "shown": {**moves, "wired": ["w" * 200] * 9}},
        ),
        "set_in_graph take out": (
            SET_IN_GRAPH,
            {"in_graph": False, "shown": {**moves, "wired": []}},
        ),
        "inspect_device restart": (
            INSPECT_DEVICE,
            {"device_ref": LONG_REF, "restart_approved": True},
        ),
    }


@pytest.mark.parametrize("case", sorted(_longest_stored()))
def test_every_card_tool_authors_a_card_at_its_longest_inputs(
    engine: AsyncEngine, case: str
) -> None:
    """A card that failed the contract's bounds was dropped: the call parked with none, never
    reached the Hardware slot, and SOL waited until it expired."""
    name, stored = _longest_stored()[case]
    tool = registered_tool(_cards(engine, uuid.uuid4(), uuid.uuid4(), _Runner()), name)

    card = authored_card(tool, stored, guide=True)

    assert card is not None, case
    shown = Card.model_validate(card)
    assert shown.resumes is True
    for text in (shown.body, shown.receipt):
        assert text.count("`") % 2 == 0, text  # no chip is cut open


@pytest.mark.parametrize("case", ["add_parts new", "add_parts existing"])
def test_add_parts_at_its_longest_still_names_the_repo_config(
    engine: AsyncEngine, case: str
) -> None:
    """Two calls that differ only in the config show different cards, even when a 132-character
    ref, a 60-character robot name and three 40-character part names fill the body: the config
    chip is never the text the bound cuts."""
    name, stored = _longest_stored()[case]
    tool = registered_tool(_cards(engine, uuid.uuid4(), uuid.uuid4(), _Runner()), name)
    other = copy.deepcopy(stored)
    for match in other["proposal"]["repo_matches"]:
        match["label"] = "d" * 80

    first, second = (authored_card(tool, args, guide=True) for args in (stored, other))

    assert first is not None and second is not None
    assert f"`{'c' * 40}`" in first["body"] and f"`{'d' * 40}`" in second["body"]


async def test_add_parts_at_its_longest_parks_with_its_card(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    engine: AsyncEngine,
) -> None:
    """A 132-character device chip, three 40-character name chips, the calibration chip and the
    port note are past the body's bound together."""
    team = await _team(client, alice_headers, bob_headers)
    alice = _cards(engine, team.project_id, team.alice_id, _Runner())
    _, stored = _longest_stored()["add_parts new"]
    args = {
        "inspection_id": _inspected(team, stored["proposal"]),
        "target": stored["target"],
        "rows": stored["rows"],
        "repo_config_id": stored["repo_config_id"],
    }

    parked = await _park(engine, alice, team.team, team.project_id, team.alice_id, ADD_PARTS, args)

    assert parked.confirmation_id is not None, parked.result.error
    assert parked.card is not None
    body = Card.model_validate(parked.card).body
    assert LONG_REF in body and body.count("`") % 2 == 0


# ---------------------------------------------------------------------------- isolation


async def test_a_card_tool_never_reaches_hardware_its_member_cannot_see(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    """Bob's cards cannot name Alice's hardware out of the graph, and Alice's cards in project A
    cannot name hardware of another team's project (her own, B): each is refused like an unknown
    id, nothing parked."""
    team = await _team(client, alice_headers, bob_headers)
    hidden = await _onboard(db, team)
    other_team = await create_team(client, alice_headers)
    other_project = await create_project(client, alice_headers, other_team["id"])
    elsewhere = _Team(other_project["id"], other_team["id"], team.alice, team.bob)
    foreign = await _onboard(db, elsewhere, in_graph=True)
    runner = _Runner()
    bob = _cards(engine, team.project_id, _bob(team), runner)
    alice = _cards(engine, team.project_id, team.alice_id, runner)
    bob_inspection = INSPECTIONS.put(
        team.project_id, _bob(team), ProposalOut.model_validate(_on(SECOND, _wire_proposal()))
    ).id

    hidden_part = str(hidden.part_ids[0])
    attempts: list[tuple[ToolRegistry, uuid.UUID, str, dict[str, Any]]] = [
        (bob, _bob(team), SET_IN_GRAPH, {"entity_id": str(hidden.robot.id), "in_graph": True}),
        (
            bob,
            _bob(team),
            LINK_PART,
            {"part_id": hidden_part, "targets": [{"entity_id": str(foreign.part_ids[0])}]},
        ),
        (
            bob,
            _bob(team),
            ADD_PARTS,
            {
                "inspection_id": bob_inspection,
                "target": {"kind": "existing", "robot_id": str(hidden.robot.id)},
            },
        ),
        (
            alice,
            team.alice_id,
            SET_IN_GRAPH,
            {"entity_id": str(foreign.robot.id), "in_graph": False},
        ),
        (
            alice,
            team.alice_id,
            IMPORT_DEFINITION,
            {"definition_id": "sts3215", "robot_id": str(foreign.robot.id)},
        ),
    ]
    for registry, user, tool, args in attempts:
        parked = await _park(engine, registry, team.team, team.project_id, user, tool, args)
        message = _refused(parked, ToolErrorCode.NOT_FOUND)
        assert "Private arm" not in message and str(hidden.robot.id) not in message, tool
    assert (await db.scalar(select(func.count()).select_from(ToolConfirmation))) == 0


# ---------------------------------------------------------------------------- the decision route


async def test_an_edited_card_field_never_reaches_the_stored_call(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    """The card's field shows the robot name; an edit is the person's next turn, never arguments:
    a decision carrying a field, args or a card is 422 and leaves the card waiting, and approval
    writes exactly the stored name."""
    team = await _team(client, alice_headers, bob_headers)
    runner = _Runner()
    app.state.bench_local = runner
    alice = _cards(engine, team.project_id, team.alice_id, runner)
    args = {"inspection_id": _inspected(team), "target": {"kind": "new", "name": "Rover arm"}}
    parked = await _park(engine, alice, team.team, team.project_id, team.alice_id, ADD_PARTS, args)
    url = team.url("sol", "confirmations", str(parked.confirmation_id))
    edited = {"kind": "new", "name": "Edited arm"}

    for extra in (
        {"field": {"label": "Robot name", "value": "Edited arm"}},
        {"args": {**args, "target": edited}},
        {"card": {**(parked.card or {}), "field": {"label": "Robot name", "value": "Edited"}}},
    ):
        response = await client.post(
            url, headers=alice_headers, json={"decision": "approve", **extra}
        )
        assert response.status_code == 422, response.text
    row = await db.get(ToolConfirmation, parked.confirmation_id)
    assert row is not None and row.status is ConfirmationStatus.PENDING

    approved = await client.post(url, headers=alice_headers, json={"decision": "approve"})

    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["ok"] is True, approved.text
    names = await db.scalars(
        select(GraphEntity.name).where(
            GraphEntity.project_id == team.project_id, GraphEntity.kind == "physical_robot"
        )
    )
    assert list(names) == ["Rover arm"]
