"""SOLUSDEV-326 P2: the detection routes' orchestration as services
(`hardware/detection_service.py`) that the routes and SOL's hardware tools both call. Each takes the
project and the acting member explicitly and reads as that member; it flushes and commits nothing,
and new hardware is in the graph with no onboarder unless a Solus caller says otherwise
(docs/api/hardware.md §1a, §4-5)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from conftest import BOB, add_member, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.core.errors import APIError
from solus_api.graph.read_scope import GraphReadScope, bind_scope
from solus_api.hardware import detection_service
from solus_api.hardware.detect import ConfirmIn, ProposeIn
from solus_api.hardware.links import LinkSuggestion, LinkTier, persist_suggestions
from solus_api.hardware.proposal_cache import PROPOSALS
from solus_api.models import Domain, GraphEntity, HardwareSuggestion, SuggestionStatus
from solus_api.services.physical_robots import PhysicalRobotService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_bind_refusal import _offered, _Runner
from test_hardware_detect import DEVICE_REF, _DetectLocal
from test_in_graph import _Team, _team
from test_mcu_connection import silent

STAMPED_KEYS = ("in_graph", "onboarded_by")


class _Connections:
    """The local runtime's connection coordinator, as a confirm uses it before writing."""

    async def ensure_owner(self) -> str:
        return "runtime-1"


class _Manager:
    """The bench session manager, recording what it is asked to start."""

    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []

    async def start(self, project_id: uuid.UUID, **kwargs: Any) -> Any:
        self.starts.append(kwargs)
        return SimpleNamespace(id=uuid.UUID(int=7))


def _bob(team: _Team) -> uuid.UUID:
    return uuid.UUID(team.bob["id"])


async def _hidden_robot(db: AsyncSession, team: _Team) -> GraphEntity:
    """Alice's robot she has not added to the graph: hers alone to see (§1a)."""
    robot = await PhysicalRobotService(db).create(
        team.project_id, "Private arm", in_graph=False, onboarded_by=team.alice_id
    )
    await db.commit()
    return robot


async def _offer(db: AsyncSession, team: _Team, robot_id: uuid.UUID) -> HardwareSuggestion:
    """A pending suggestion that the device on the wire is `robot_id`."""
    (row,) = await persist_suggestions(
        db,
        team.project_id,
        [
            LinkSuggestion(
                subject_ref=DEVICE_REF,
                subject_kind="device",
                candidate_robot_id=robot_id,
                confidence=0.8,
                tier=LinkTier.HIGH,
                evidence=[],
                reason="fixture",
            )
        ],
    )
    await db.commit()
    return row


def _confirm(target: dict[str, Any], *, start_session: bool = False) -> ConfirmIn:
    return ConfirmIn.model_validate(
        {
            "target": target,
            "accepted": [{"row_id": f"{DEVICE_REF}/1"}],
            "start_session": start_session,
        }
    )


# ---------------------------------------------------------------------------- propose


async def test_propose_keeps_the_proposal_for_its_member_and_names_only_robots_they_see(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    robot = await _hidden_robot(db, team)
    await _offer(db, team, robot.id)
    local = _DetectLocal()

    async def suggested(user_id: uuid.UUID) -> list[Any]:
        proposal = await detection_service.propose_detected(
            db,
            local,
            project_id=team.project_id,
            user_id=user_id,
            device_ref=DEVICE_REF,
            options=ProposeIn(),
        )
        assert [row.id for row in proposal.rows] == [f"{DEVICE_REF}/1", f"{DEVICE_REF}/2"]
        return [row["candidate_robot_id"] for row in proposal.suggestions]

    assert await suggested(_bob(team)) == []
    assert await suggested(team.alice_id) == [robot.id]
    kept = PROPOSALS.take((team.project_id, team.alice_id, DEVICE_REF, ""), [f"{DEVICE_REF}/1"])
    assert kept is not None and kept.device_ref == DEVICE_REF
    assert len(local.propose_calls) == 2


# ---------------------------------------------------------------------------- confirm


async def test_confirm_writes_new_hardware_out_of_the_graph_for_its_onboarder(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    confirmed = await detection_service.confirm_detected(
        db,
        _DetectLocal(),
        cast(Any, _Connections()),
        project_id=team.project_id,
        user_id=team.alice_id,
        device_ref=DEVICE_REF,
        body=_confirm({"kind": "new", "name": "Bench arm"}, start_session=True),
        in_graph=False,
        onboarded_by=team.alice_id,
    )
    await db.commit()

    robot = confirmed.result.robot
    assert confirmed.result.created_robot and not confirmed.proposal_reused
    assert confirmed.attempt_id is not None
    assert robot.attrs["connection"]["attempt_id"] == str(confirmed.attempt_id)
    assert robot.attrs["connection"]["runtime_id"] == "runtime-1"
    (part,) = await db.scalars(
        select(GraphEntity).where(GraphEntity.id.in_(confirmed.result.part_ids))
    )
    assert part.name == "Bench arm-Motor-1"
    stamped = {"in_graph": False, "onboarded_by": str(team.alice_id)}
    for entity in (robot, part):
        assert {key: entity.attrs.get(key) for key in STAMPED_KEYS} == stamped


async def test_confirm_defaults_to_the_graph_with_no_onboarder_and_no_connection(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    confirmed = await detection_service.confirm_detected(
        db,
        _DetectLocal(),
        cast(Any, None),  # no session to start: the coordinator is never asked
        project_id=team.project_id,
        user_id=team.alice_id,
        device_ref=DEVICE_REF,
        body=_confirm({"kind": "new", "name": "Bench arm"}),
    )
    await db.commit()

    assert confirmed.attempt_id is None
    robot = confirmed.result.robot
    assert "connection" not in robot.attrs
    assert not set(STAMPED_KEYS) & set(robot.attrs)


async def test_confirm_never_adds_parts_to_a_robot_its_member_cannot_see(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    robot = await _hidden_robot(db, team)
    bob = _bob(team)

    with (
        bind_scope(GraphReadScope(team.project_id, viewer_id=bob)),
        pytest.raises(APIError) as refused,
    ):
        await detection_service.confirm_detected(
            db,
            _DetectLocal(),
            cast(Any, _Connections()),
            project_id=team.project_id,
            user_id=bob,
            device_ref=DEVICE_REF,
            body=_confirm({"kind": "existing", "robot_id": str(robot.id)}),
        )

    assert (refused.value.status_code, refused.value.code) == (404, "not_found")
    await db.rollback()
    written = select(func.count()).where(GraphEntity.external_ref.like(f"{DEVICE_REF}/%"))
    assert await db.scalar(written) == 0


# ------------------------------------------------ refusals name only what their reader sees


def _connection(target: dict[str, Any]) -> ConfirmIn:
    return ConfirmIn.model_validate(
        {"target": target, "accepted": [], "connection_only": True, "start_session": False}
    )


async def _refusals(
    client: AsyncClient,
    db: AsyncSession,
    team: _Team,
    local: _DetectLocal,
    body: ConfirmIn,
    bob_headers: dict[str, str],
) -> tuple[str, str, str]:
    """The 409 a confirm of `body` gets: Bob's through the route, then Bob's and Alice's through
    the service, each with their own scope bound."""
    routed = await client.post(
        team.url("hardware", "detected", DEVICE_REF, "confirm"),
        headers=bob_headers,
        json=body.model_dump(mode="json"),
    )
    assert routed.status_code == 409, routed.text
    messages = [routed.json()["error"]["message"]]
    for viewer in (_bob(team), team.alice_id):
        with (
            bind_scope(GraphReadScope(team.project_id, viewer_id=viewer)),
            pytest.raises(APIError) as refused,
        ):
            await detection_service.confirm_detected(
                db,
                local,
                cast(Any, None),
                project_id=team.project_id,
                user_id=viewer,
                device_ref=DEVICE_REF,
                body=body,
            )
        assert refused.value.status_code == 409
        messages.append(refused.value.message)
        await db.rollback()
    routed_bob, service_bob, service_alice = messages
    return routed_bob, service_bob, service_alice


async def test_a_confirm_of_kept_rows_names_a_robot_out_of_the_graph_to_its_onboarder_only(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    """Alice's arm out of the graph keeps the device's rows: confirming them again is a 409 that
    tells Alice which robot, while Bob, through the route or the service, learns neither its id
    nor its name (§1a)."""
    team = await _team(client, alice_headers, bob_headers)
    local = _DetectLocal()
    app.state.bench_local = local
    confirmed = await detection_service.confirm_detected(
        db,
        local,
        cast(Any, None),
        project_id=team.project_id,
        user_id=team.alice_id,
        device_ref=DEVICE_REF,
        body=_confirm({"kind": "new", "name": "Bench arm"}),
        in_graph=False,
        onboarded_by=team.alice_id,
    )
    await db.commit()
    robot_id, name = str(confirmed.result.robot.id), confirmed.result.robot.name

    *bobs, alices = await _refusals(
        client, db, team, local, _confirm({"kind": "new", "name": "Second arm"}), bob_headers
    )

    for message in bobs:
        assert f"{DEVICE_REF}/1" in message
        assert robot_id not in message and name not in message
    assert robot_id in alices


async def test_a_connection_held_out_of_the_graph_is_named_to_its_onboarder_only(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    """The device is bound to Alice's board out of the graph: a connection-only confirm onto
    another robot is a 409 that tells Alice which board, while Bob, aiming at his own robot
    through the route or the service, learns neither its id nor its name (§1a)."""
    team = await _team(client, alice_headers, bob_headers)
    local = _DetectLocal()
    silent(local)
    app.state.bench_local = local
    confirmed = await detection_service.confirm_detected(
        db,
        local,
        cast(Any, None),
        project_id=team.project_id,
        user_id=team.alice_id,
        device_ref=DEVICE_REF,
        body=_connection({"kind": "new", "name": "Private board"}),
        in_graph=False,
        onboarded_by=team.alice_id,
    )
    board_id, name = str(confirmed.result.robot.id), confirmed.result.robot.name
    rover = await PhysicalRobotService(db).create(team.project_id, "Bench rover")
    await db.commit()

    *bobs, alices = await _refusals(
        client,
        db,
        team,
        local,
        _connection({"kind": "existing", "robot_id": str(rover.id)}),
        bob_headers,
    )

    for message in bobs:
        assert board_id not in message and name not in message
    assert board_id in alices


async def test_a_refused_bind_never_names_a_robot_its_member_cannot_see(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    """A part on Alice's robot out of the graph already keeps the row a device suggestion would
    key: Bob's accept is refused in `bind_error` without naming her robot (§1a, §5)."""
    project, _, _, url = await _offered(client, alice_headers, db, app, binding=None)
    alice = uuid.UUID((await me(client, alice_headers))["id"])
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, str(project.team_id))
    hidden = await PhysicalRobotService(db).create(
        project.id, "Private arm", in_graph=False, onboarded_by=alice
    )
    db.add(
        GraphEntity(
            project_id=project.id,
            kind="part",
            domain=Domain.PROJECT,
            origin="manual",
            name="Old joint",
            external_ref="usb:BBB/1",
            attrs={"robot_id": str(hidden.id), "in_graph": False, "onboarded_by": str(alice)},
        )
    )
    await db.commit()

    accepted = await client.post(url, headers=bob_headers)

    assert accepted.status_code == 200, accepted.text
    data = accepted.json()["data"]
    assert data["bound"] is False and "usb:BBB/1 is already part of" in data["bind_error"]
    assert str(hidden.id) not in data["bind_error"] and "Private arm" not in data["bind_error"]


# ----------------------------------------------------------------------------- decide


async def test_deciding_a_device_suggestion_binds_it_and_starts_the_robots_session(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, robot, joint, _ = await _offered(client, alice_headers, db, app, binding=None)
    robot_id, joint_id = robot.id, joint.id
    user = uuid.UUID((await me(client, alice_headers))["id"])
    row_id = await db.scalar(
        select(HardwareSuggestion.id).where(HardwareSuggestion.project_id == project.id)
    )
    assert row_id is not None
    opener = SimpleNamespace(label="Rover", device={"device_ref": "usb:BBB"}, open=object())

    async def plan(local: Any, session: Any, project_id: uuid.UUID, subject: Any) -> Any:
        assert subject.id == robot_id
        return SimpleNamespace()

    async def prepare(local: Any, plan: Any, account_id: uuid.UUID) -> Any:
        return opener

    monkeypatch.setattr(detection_service, "plan_session", plan)
    monkeypatch.setattr(detection_service, "prepare_session", prepare)
    manager = _Manager()

    decision = await detection_service.decide_and_link(
        db,
        _Runner(),
        cast(Any, manager),
        project_id=project.id,
        user_id=user,
        suggestion_id=row_id,
        accept=True,
        reason=None,
    )
    await db.commit()

    assert decision.row.status is SuggestionStatus.ACCEPTED and decision.device_bound
    assert decision.binding == {
        "bound": True,
        "robot_id": robot_id,
        "session_id": uuid.UUID(int=7),
        "session_error": None,
        "bind_error": None,
    }
    keyed = await db.get(GraphEntity, joint_id, populate_existing=True)
    assert keyed is not None and keyed.external_ref == "usb:BBB/1"
    (started,) = manager.starts
    assert (started["robot_entity_id"], started["owner_user_id"]) == (robot_id, user)
    assert started["open_conn"] is opener.open and started["device"] is opener.device


async def test_deciding_a_suggestion_naming_a_robot_its_member_cannot_see_is_404(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    row = await _offer(db, team, (await _hidden_robot(db, team)).id)
    row_id = row.id
    manager = _Manager()

    for accept in (True, False):
        with pytest.raises(APIError) as refused:
            await detection_service.decide_and_link(
                db,
                _Runner(),
                cast(Any, manager),
                project_id=team.project_id,
                user_id=_bob(team),
                suggestion_id=row_id,
                accept=accept,
                reason=None,
            )
        assert (refused.value.status_code, refused.value.code) == (404, "not_found")

    await db.rollback()
    status = await db.scalar(
        select(HardwareSuggestion.status)
        .where(HardwareSuggestion.id == row_id)
        .execution_options(populate_existing=True)
    )
    assert status is SuggestionStatus.PENDING and manager.starts == []
