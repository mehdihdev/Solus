"""SOLUSDEV-321 P8 — outcomes as data: every decision on a SOL proposal is one `proposal_outcomes`
row, recorded by the router that saw it, with the project's design signals of that moment.

A card the person approves is `accepted` and one they reject `rejected`; a card that ran out of
time is `expired` and one whose effect moved while it waited is `stale`; an owned routine Build ran
by itself is `accepted_auto`. A second click on a settled card decides nothing and writes nothing.
A row holds identifiers and digests only, and is read back per project, newest first, by the
project's members and nobody else.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from conftest import BOB, add_member
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.confirmations import _cleaned_rows, request_confirmation
from solus_api.agent.execution_policy import register_owned_routine
from solus_api.agent.runtime import AgentRunContext
from solus_api.agent.stream import AgentEvent
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolDescriptor
from solus_api.agent.tools.tool import InProcessTool
from solus_api.agent.tools.untrusted import call_display_paths
from solus_api.bridge.command_previews import command_rows, plan_fingerprint
from solus_api.connectors.onshape_confirmation import ConfirmedOnshapeTool
from solus_api.deps import get_sol_registry
from solus_api.models import (
    ConfirmationStatus,
    ConversationTurn,
    DataEvent,
    Domain,
    GraphEntity,
    Project,
    ProposalOutcome,
    Source,
    SourceType,
    Team,
    ToolConfirmation,
    TurnRole,
    User,
    utcnow,
)
from solus_api.services.machines import MachineIn, upsert_machine
from solus_api.services.outcomes import proposal_digest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_command_previews import _EXEC_ARGS, _plan
from test_project_card import _companion_session
from test_sol import _create_conversation, _project

CARD = ToolDescriptor(
    name="demo.set_width",
    description="Change one width.",
    params={
        "type": "object",
        "properties": {"name": {"type": "string"}, "entity_id": {"type": "string"}},
    },
    returns={"type": "object"},
    requires_confirmation=True,
)
#: Build's owned routine (`tool_fixture`'s default), auto-run by the turn below.
ROUTINE = "onshape.create_circle_sketch"
COMMIT = "a" * 40


def _sha256(args: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(args, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _with_owned_routine() -> ToolRegistry:
    """A registry holding Build's owned routine (test_build_execution_policy's `tool_fixture`)."""

    async def sketch(args: dict[str, Any]) -> dict[str, Any]:
        return {"changed": True}

    async def rows(args: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"label": "depth", "before": "1 mm", "after": "2 mm"}]

    params = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
        "additionalProperties": False,
    }
    descriptor = ToolDescriptor(
        name=ROUTINE,
        description="Reviewed edit",
        requires_confirmation=True,
        params=params,
        returns={"type": "object"},
    )
    routine = ConfirmedOnshapeTool(descriptor, sketch, rows)
    register_owned_routine(routine, family="onshape")
    registry = ToolRegistry()
    registry.register(routine)
    return registry


async def _auto_run(
    app: FastAPI,
    client: AsyncClient,
    headers: dict[str, str],
    url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One Build turn whose model calls the owned routine: it runs with no card
    (test_build_execution_policy's route precedent, the CAD sync seams stubbed)."""
    from solus_api.routers import sol

    synced = {"status": "queued", "job_id": "test-job"}
    monkeypatch.setattr(sol, "schedule_onshape_write_sync", AsyncMock(return_value=synced))
    held = "solus_api.services.onshape_write_sync.hold_onshape_write_sync"
    monkeypatch.setattr(held, AsyncMock(return_value=uuid.uuid4()))
    released = "solus_api.services.onshape_write_sync.release_onshape_write_sync"
    monkeypatch.setattr(released, AsyncMock(return_value=synced))

    class Runner:
        async def run(self, ctx: AgentRunContext) -> AsyncIterator[AgentEvent]:
            call = ToolCall(tool=ROUTINE, args={"n": 1})
            yield AgentEvent.tool_call(call)
            yield AgentEvent.tool_result(await ctx.dispatch(call))
            yield AgentEvent.message("Done")

    app.state.agent_runner = Runner()
    turn = await client.post(
        url, headers=headers, json={"content": "sketch it", "action_mode": "do"}
    )
    assert turn.status_code == 200, turn.text
    assert "event: tool_confirmation" not in turn.text


async def test_approve_reject_expired_stale_and_auto_write_rows_with_signals(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team, project = await _project(client, alice_headers)
    team_id, project_id = uuid.UUID(team["id"]), uuid.UUID(project["id"])
    alice = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert alice is not None
    alice.data_collection_consent = True
    code = Source(
        project_id=project_id,
        team_id=team_id,
        type=SourceType.GITHUB,
        name="firmware",
        cursor={"branch": "main", "sha": COMMIT},
    )
    db.add(code)
    await db.flush()
    db.add(
        Source(
            project_id=project_id,
            team_id=team_id,
            type=SourceType.GITHUB,
            name="firmware at an older commit",
            cursor={"sha": "b" * 40},
            revision_base_source_id=code.id,
        )
    )
    part = GraphEntity(
        project_id=project_id,
        kind="component",
        domain=Domain.ELECTRICAL,
        origin="connector",
        name="R1",
    )
    db.add(part)
    await db.commit()
    machine = await upsert_machine(
        db, project_id, alice.id, "bench-01", MachineIn(hostname="bench", os="linux", arch="arm64")
    )
    await db.commit()
    # The person's own companion is live in the project: the decisions come from that machine.
    app.state.bridge_sessions.bind(_companion_session(alice.id, team_id, project_id, "bench-01"))

    drift: dict[str, str] = {}

    async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
        after = drift.get(args["name"], "120 mm")
        return [{"label": args["name"], "before": "100 mm", "after": after}]

    async def apply(args: dict[str, Any]) -> dict[str, Any]:
        return {"applied": args["name"]}

    registry = _with_owned_routine()
    registry.register(InProcessTool(CARD, apply, preview))
    app.dependency_overrides[get_sol_registry] = lambda: registry
    conversation = await _create_conversation(client, alice_headers, project["id"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    cards: dict[str, uuid.UUID] = {}
    for name in ("width", "height", "length", "depth"):
        call = ToolCall(tool=CARD.name, args={"name": name, "entity_id": str(part.id)})
        async with maker() as session:
            parked = await request_confirmation(
                session,
                registry,
                call,
                project_id=project_id,
                team_id=team_id,
                user_id=alice.id,
                conversation_id=uuid.UUID(conversation["id"]),
            )
            await session.commit()
        assert parked is not None and parked.confirmation_id is not None
        cards[name] = parked.confirmation_id
    late = await db.get(ToolConfirmation, cards["length"])
    assert late is not None
    late.expires_at = utcnow() - timedelta(minutes=1)  # it ran out of time
    await db.commit()
    drift["depth"] = "999 mm"  # its effect moved while the card waited

    decide = f"/api/v1/projects/{project_id}/sol/confirmations"
    for name, decision in (
        ("width", "approve"),
        ("height", "reject"),
        ("length", "approve"),
        ("depth", "approve"),
    ):
        response = await client.post(
            f"{decide}/{cards[name]}", headers=alice_headers, json={"decision": decision}
        )
        assert response.status_code == 200, response.text
    again = await client.post(
        f"{decide}/{cards['width']}", headers=alice_headers, json={"decision": "approve"}
    )
    assert again.status_code == 200 and again.json()["data"]["ok"] is False  # already settled
    messages = f"/api/v1/projects/{project_id}/sol/conversations/{conversation['id']}/messages"
    await _auto_run(app, client, alice_headers, messages, monkeypatch)

    rows = list(
        await db.scalars(
            select(ProposalOutcome).order_by(ProposalOutcome.created_at, ProposalOutcome.id)
        )
    )
    assert [row.decision for row in rows] == [
        "accepted",
        "rejected",
        "expired",
        "stale",
        "accepted_auto",
    ]
    assert {row.project_id for row in rows} == {project_id}
    # M190: the stale row says why the gate refused it; no other decision carries a reason.
    assert [row.stale_reason for row in rows] == [None, None, None, "diverged", None]
    # The design as it stood: the base source's commit. The revision snapshot is no signal.
    assert all(row.design_signals == {str(code.id): COMMIT} for row in rows)
    assert all(row.machine_id == machine.id and row.user_id == alice.id for row in rows)
    accepted, rejected, auto = rows[0], rows[1], rows[4]
    assert accepted.tool == CARD.name
    assert accepted.proposal_digest == _sha256({"entity_id": str(part.id), "name": "width"})
    assert accepted.proposal_digest != rejected.proposal_digest
    assert accepted.entity_ids == [str(part.id)]
    for row in rows[:4]:  # each decision links the tool turn that records it
        assert row.conversation_turn_id is not None
        recorded = await db.get(ConversationTurn, row.conversation_turn_id)
        assert recorded is not None and recorded.content.startswith(f"{CARD.name} →")
    assert auto.tool == ROUTINE and auto.proposal_digest == _sha256({"n": 1})
    assert auto.entity_ids == []
    assert auto.conversation_turn_id is None  # its tool turn is written when the stream ends
    events = list(
        await db.scalars(select(DataEvent).where(DataEvent.event_type == "sol.proposal_outcome"))
    )
    assert sorted(event.payload["decision"] for event in events) == sorted(
        row.decision for row in rows
    )
    assert all(
        set(event.payload) == {"outcome_id", "tool", "decision", "proposal_digest"}
        for event in events
    )

    url = f"/api/v1/projects/{project_id}/outcomes"
    listed = await client.get(url, headers=alice_headers)
    assert listed.status_code == 200, listed.text
    newest = listed.json()["data"]
    assert [item["decision"] for item in newest] == [row.decision for row in reversed(rows)]
    assert [item["stale_reason"] for item in newest] == [None, "diverged", None, None, None]
    assert newest[0]["design_signals"] == {str(code.id): COMMIT}
    assert newest[0]["machine_id"] == str(machine.id)
    first = await client.get(url, headers=alice_headers, params={"limit": 2})
    meta = first.json()["meta"]
    assert meta["has_next"] is True and len(first.json()["data"]) == 2
    rest = await client.get(
        url, headers=alice_headers, params={"limit": 2, "cursor": meta["next_cursor"]}
    )
    assert [item["decision"] for item in rest.json()["data"]] == ["expired", "rejected"]


async def test_cross_team_isolation_404(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    _, project = await _project(client, alice_headers)
    _, theirs = await _project(client, bob_headers)
    mine_id, theirs_id = uuid.UUID(project["id"]), uuid.UUID(theirs["id"])
    for project_id, tool in ((mine_id, "demo.mine"), (theirs_id, "demo.theirs")):
        db.add(
            ProposalOutcome(
                project_id=project_id, tool=tool, proposal_digest="0" * 64, decision="rejected"
            )
        )
    db.add(  # older than any read reaches back
        ProposalOutcome(
            project_id=mine_id,
            tool="demo.old",
            proposal_digest="1" * 64,
            decision="accepted",
            created_at=utcnow() - timedelta(days=100),
        )
    )
    await db.commit()

    url = f"/api/v1/projects/{mine_id}/outcomes"
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=bob_headers)).status_code == 404
    unknown = await client.get(f"/api/v1/projects/{uuid.uuid4()}/outcomes", headers=alice_headers)
    assert unknown.status_code == 404
    since = (utcnow() - timedelta(days=200)).isoformat()
    mine = await client.get(url, headers=alice_headers, params={"since": since})
    assert mine.status_code == 200, mine.text
    assert [item["tool"] for item in mine.json()["data"]] == ["demo.mine"]
    other = await client.get(f"/api/v1/projects/{theirs_id}/outcomes", headers=bob_headers)
    assert [item["tool"] for item in other.json()["data"]] == ["demo.theirs"]


async def test_a_teammate_lists_an_outcome_without_the_deciders_machine_or_turn(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """R146: outcomes are team data, so a member lists every row of the project; a row's machine
    and decision turn are the decider's own, and a teammate reads both as null."""
    team, project = await _project(client, alice_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    conversation = await _create_conversation(client, alice_headers, project["id"])
    project_id = uuid.UUID(project["id"])
    turn = ConversationTurn(
        conversation_id=uuid.UUID(conversation["id"]),
        project_id=project_id,
        role=TurnRole.TOOL,
        content=f"{CARD.name} → approved by you and applied ok",
    )
    db.add(turn)
    await db.flush()
    machines: dict[str, uuid.UUID] = {}
    for email, tool in (("alice@example.com", "demo.alices"), (BOB["email"], "demo.bobs")):
        decider = await db.scalar(select(User).where(User.email == email))
        assert decider is not None
        machines[tool] = uuid.uuid4()
        db.add(
            ProposalOutcome(
                project_id=project_id,
                user_id=decider.id,
                conversation_turn_id=turn.id,
                tool=tool,
                proposal_digest="0" * 64,
                decision="accepted",
                machine_id=machines[tool],
            )
        )
    await db.commit()

    url = f"/api/v1/projects/{project_id}/outcomes"
    for headers, own, theirs in (
        (bob_headers, "demo.bobs", "demo.alices"),
        (alice_headers, "demo.alices", "demo.bobs"),
    ):
        response = await client.get(url, headers=headers)
        assert response.status_code == 200, response.text
        listed = {item["tool"]: item for item in response.json()["data"]}
        assert set(listed) == {own, theirs}
        # M6: the digest is unkeyed, so it is the decider's alone as well.
        shown = ("machine_id", "conversation_turn_id", "proposal_digest")
        assert tuple(listed[own][key] for key in shown) == (
            str(machines[own]),
            str(turn.id),
            "0" * 64,
        )
        assert tuple(listed[theirs][key] for key in shown) == (None, None, None)


def test_a_code_commands_digest_is_its_plan_fingerprint() -> None:
    """A code command's card shows the plan fingerprint the person approved; the digest is that
    (its 64 hex digits). Anything else is the sha256 of the call's redacted canonical arguments."""
    fingerprint = ":".join(digit * 16 for digit in "abcd")
    shown = [
        {"label": "program", "before": None, "after": "/usr/bin/make"},
        {"label": "plan fingerprint", "before": None, "after": fingerprint},
    ]
    args = {"argv": ["make", "test"]}
    assert proposal_digest("code.exec", args, shown) == fingerprint.replace(":", "")
    assert proposal_digest("code.exec", args) == _sha256(args)
    unshaped = [{"label": "plan fingerprint", "after": "nope"}]
    assert proposal_digest("code.exec", args, unshaped) == _sha256(args)


def test_a_real_code_cards_stored_preview_keeps_its_fingerprint() -> None:
    """M8: a `code.exec` card is the server's `code.plan` rows, cleaned as the gate stores them;
    the grouped fingerprint survives the cleaning, so the row's digest is the plan's own."""
    rows = command_rows(_plan(), _EXEC_ARGS)
    allowed = call_display_paths("code.exec", _EXEC_ARGS)
    stored = _cleaned_rows(rows, required=True, allowed_paths=allowed)
    expected = plan_fingerprint(_plan()).replace(":", "")
    assert proposal_digest("code.exec", _EXEC_ARGS, stored) == expected


def test_a_fingerprint_row_on_another_tools_card_is_ignored() -> None:
    """I2: only a code command's card is composed by the server. Another card's labels can come from
    model-proposed or ingested text (a datasheet's spec name, a path, a variable name), and a
    colon-grouped hex value survives the card's cleaning, so a `plan fingerprint` row there never
    sets the digest: it stays the redacted arguments'."""
    forged = ":".join(digit * 16 for digit in "0f1e")
    stored = _cleaned_rows(
        [{"label": "plan fingerprint", "before": None, "after": forged}],
        required=False,
        allowed_paths=frozenset(),
    )
    assert stored[0]["after"] == forged  # the reviewer's probe: the forged row is stored as shown
    args = {"name": "XY-1234"}
    for tool in ("read_document", "onshape.set_variable", CARD.name):
        assert proposal_digest(tool, args, stored) == _sha256(args)
    assert proposal_digest("code.exec", args, stored) == forged.replace(":", "")


def test_the_digest_hashes_the_redacted_arguments_in_any_key_order() -> None:
    """R147: the digest is over the arguments as error filing redacts them, so a secret-named
    argument's value is never what is hashed, and identical redacted arguments digest alike
    whatever their key order."""
    first = {"name": "width", "api_key": "first-value", "dims": {"x": 1, "y": 2}}
    second = {"dims": {"y": 2, "x": 1}, "api_key": "second-value", "name": "width"}
    assert proposal_digest(CARD.name, first) == proposal_digest(CARD.name, second)
    redacted = {"api_key": "[REDACTED]", "dims": {"x": 1, "y": 2}, "name": "width"}
    assert proposal_digest(CARD.name, first) == _sha256(redacted)
    width, height = {"name": "width"}, {"name": "height"}
    assert proposal_digest(CARD.name, width) != proposal_digest(CARD.name, height)


async def test_a_failed_recording_never_fails_the_decision(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The recording runs in a savepoint of the decision's transaction: when it fails, the decision
    and its tool turn still land, and no outcome row is left behind."""
    from solus_api.services import outcomes

    async def unavailable(*_: object) -> list[str]:
        raise RuntimeError("entity check unavailable")

    monkeypatch.setattr(outcomes, "_project_entity_ids", unavailable)
    team, project = await _project(client, alice_headers)
    conversation = await _create_conversation(client, alice_headers, project["id"])
    alice = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert alice is not None
    card = ToolConfirmation(
        project_id=uuid.UUID(project["id"]),
        team_id=uuid.UUID(team["id"]),
        user_id=alice.id,
        conversation_id=uuid.UUID(conversation["id"]),
        tool=CARD.name,
        args={"name": "width"},
        summary="Change one width",
        expires_at=utcnow() + timedelta(minutes=10),
    )
    db.add(card)
    await db.commit()

    response = await client.post(
        f"/api/v1/projects/{project['id']}/sol/confirmations/{card.id}",
        headers=alice_headers,
        json={"decision": "reject"},
    )

    assert response.status_code == 200, response.text
    await db.refresh(card)
    assert card.status is ConfirmationStatus.REJECTED
    assert list(await db.scalars(select(ProposalOutcome))) == []
    turns = await db.scalars(
        select(ConversationTurn.content).where(
            ConversationTurn.conversation_id == card.conversation_id
        )
    )
    assert any(content.startswith(f"{CARD.name} → rejected by you") for content in turns)


@pytest.mark.parametrize(
    ("live", "complete", "reason"),
    [
        ("quota", False, "quota"),  # the live preview was refused (UNAVAILABLE)
        ("empty", True, "no_preview"),  # a tool that needs a complete preview produced none
        ("moved", False, "diverged"),  # what it would do moved while the card waited
    ],
)
async def test_each_stale_card_records_why_the_gate_refused_it(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    live: str,
    complete: bool,
    reason: str,
) -> None:
    """M190: each of the gate's three stale refusals is recorded under its own `stale_reason`;
    deleting any branch of `stale_reason()` or of the gate's messages turns one case red."""
    from solus_api.agent.preview_refusal import PreviewRefusal

    shown = [{"label": "width", "before": "100 mm", "after": "120 mm"}]

    async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
        if live == "quota":
            raise PreviewRefusal("The provider's quota is used up; try again later.")
        if live == "empty":
            return []
        return [{"label": "width", "before": "100 mm", "after": "999 mm"}]

    async def apply(args: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("a stale card never runs")

    tool = InProcessTool(CARD, apply, preview)
    if complete:
        tool.requires_complete_preview = True  # type: ignore[attr-defined]
    registry = ToolRegistry()
    registry.register(tool)
    app.dependency_overrides[get_sol_registry] = lambda: registry
    team, project = await _project(client, alice_headers)
    conversation = await _create_conversation(client, alice_headers, project["id"])
    alice = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert alice is not None
    card = ToolConfirmation(
        project_id=uuid.UUID(project["id"]),
        team_id=uuid.UUID(team["id"]),
        user_id=alice.id,
        conversation_id=uuid.UUID(conversation["id"]),
        tool=CARD.name,
        args={"name": "width"},
        summary="Change one width",
        preview=shown,
        expires_at=utcnow() + timedelta(minutes=10),
    )
    db.add(card)
    await db.commit()

    response = await client.post(
        f"/api/v1/projects/{project['id']}/sol/confirmations/{card.id}",
        headers=alice_headers,
        json={"decision": "approve"},
    )

    assert response.status_code == 200, response.text
    (row,) = await db.scalars(select(ProposalOutcome))
    assert (row.decision, row.stale_reason) == ("stale", reason)


async def test_entity_ids_are_every_verified_project_id_the_arguments_name(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """M191: `entity_ids` holds every id the call names under `entity_id`, `focus_entity_ids`,
    `robot_entity_id`, `source_entity_id` and `part_entity_id` that is this project's own — once
    each, in the order named — never only the first; a foreign, unknown or malformed id is left
    out."""
    team, project = await _project(client, alice_headers)
    project_id = uuid.UUID(project["id"])
    conversation = await _create_conversation(client, alice_headers, project["id"])
    alice = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert alice is not None
    elsewhere = Team(name="Elsewhere")
    db.add(elsewhere)
    await db.flush()
    stranger_project = Project(team_id=elsewhere.id, name="Theirs")
    db.add(stranger_project)
    await db.flush()

    def entity(pid: uuid.UUID, name: str) -> GraphEntity:
        row = GraphEntity(project_id=pid, kind="component", domain=Domain.ELECTRICAL, name=name)
        db.add(row)
        return row

    part, focus, robot, foreign = (
        entity(project_id, "R1"),
        entity(project_id, "U1"),
        entity(project_id, "arm"),
        entity(stranger_project.id, "theirs"),
    )
    await db.flush()
    card = ToolConfirmation(
        project_id=project_id,
        team_id=uuid.UUID(team["id"]),
        user_id=alice.id,
        conversation_id=uuid.UUID(conversation["id"]),
        tool=CARD.name,
        args={
            "name": "width",
            "entity_id": str(part.id),
            "focus_entity_ids": [str(focus.id), str(foreign.id), "not-a-uuid", str(part.id)],
            "robot_entity_id": str(robot.id),
            "source_entity_id": str(uuid.uuid4()),
            "part_entity_id": str(focus.id),
        },
        summary="Change one width",
        expires_at=utcnow() + timedelta(minutes=10),
    )
    db.add(card)
    await db.commit()

    response = await client.post(
        f"/api/v1/projects/{project_id}/sol/confirmations/{card.id}",
        headers=alice_headers,
        json={"decision": "reject"},
    )

    assert response.status_code == 200, response.text
    (row,) = await db.scalars(select(ProposalOutcome))
    assert row.entity_ids == [str(part.id), str(focus.id), str(robot.id)]
    assert row.stale_reason is None


async def test_the_design_signals_are_read_at_the_click_not_after_the_tool(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    """M5 (R1): the signals are the design as it stood when the person clicked. A sync that moves a
    source's cursor while the approved tool runs does not change what the row records."""
    team, project = await _project(client, alice_headers)
    team_id, project_id = uuid.UUID(team["id"]), uuid.UUID(project["id"])
    alice = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert alice is not None
    code = Source(
        project_id=project_id,
        team_id=team_id,
        type=SourceType.GITHUB,
        name="firmware",
        cursor={"sha": COMMIT},
    )
    db.add(code)
    await db.commit()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    moved = {"sha": "c" * 40}

    async def apply(args: dict[str, Any]) -> dict[str, Any]:
        async with maker() as session:  # a sync lands while the approved tool runs
            await session.execute(update(Source).where(Source.id == code.id).values(cursor=moved))
            await session.commit()
        return {"applied": args["name"]}

    registry = ToolRegistry()
    registry.register(InProcessTool(CARD, apply))
    app.dependency_overrides[get_sol_registry] = lambda: registry
    conversation = await _create_conversation(client, alice_headers, project["id"])
    async with maker() as session:
        parked = await request_confirmation(
            session,
            registry,
            ToolCall(tool=CARD.name, args={"name": "width"}),
            project_id=project_id,
            team_id=team_id,
            user_id=alice.id,
            conversation_id=uuid.UUID(conversation["id"]),
        )
        await session.commit()
    assert parked is not None and parked.confirmation_id is not None

    response = await client.post(
        f"/api/v1/projects/{project_id}/sol/confirmations/{parked.confirmation_id}",
        headers=alice_headers,
        json={"decision": "approve"},
    )

    assert response.status_code == 200 and response.json()["data"]["ok"] is True
    (row,) = list(await db.scalars(select(ProposalOutcome)))
    assert row.decision == "accepted" and row.design_signals == {str(code.id): COMMIT}
    assert await db.scalar(select(Source.cursor).where(Source.id == code.id)) == moved


@pytest.mark.parametrize("route", ["outcomes", "usage/turns"])
async def test_a_page_past_200_rows_or_a_malformed_cursor_is_refused(
    client: AsyncClient, alice_headers: dict[str, str], route: str
) -> None:
    """M8: both routes bound a page at 200 rows (422 past it) and refuse a cursor they did not
    issue (400 `invalid_cursor`)."""
    _, project = await _project(client, alice_headers)
    url = f"/api/v1/projects/{project['id']}/{route}"
    assert (await client.get(url, headers=alice_headers, params={"limit": 200})).status_code == 200
    assert (await client.get(url, headers=alice_headers, params={"limit": 201})).status_code == 422
    malformed = await client.get(url, headers=alice_headers, params={"cursor": "not-a-cursor"})
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "invalid_cursor"


async def test_an_unread_design_snapshot_never_fails_the_decision(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """N2: the click-time signals are read in a savepoint of their own, before the decision. A
    failed read is one warning line naming the card; the row records empty signals, and the
    decision still lands."""
    from solus_api.services import outcomes

    async def unreadable(*_: object) -> dict[str, str]:
        raise RuntimeError("sources unreadable")

    monkeypatch.setattr(outcomes, "snapshot_signals", unreadable)
    team, project = await _project(client, alice_headers)
    team_id, project_id = uuid.UUID(team["id"]), uuid.UUID(project["id"])
    alice = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert alice is not None
    db.add(
        Source(
            project_id=project_id,
            team_id=team_id,
            type=SourceType.GITHUB,
            name="firmware",
            cursor={"sha": COMMIT},
        )
    )
    card = ToolConfirmation(
        project_id=project_id,
        team_id=team_id,
        user_id=alice.id,
        tool=CARD.name,
        args={"name": "width"},
        summary="Change one width",
        expires_at=utcnow() + timedelta(minutes=10),
    )
    db.add(card)
    await db.commit()

    with caplog.at_level(logging.WARNING, logger="solus.services.outcomes"):
        response = await client.post(
            f"/api/v1/projects/{project_id}/sol/confirmations/{card.id}",
            headers=alice_headers,
            json={"decision": "reject"},
        )

    assert response.status_code == 200, response.text
    await db.refresh(card)
    assert card.status is ConfirmationStatus.REJECTED
    (row,) = list(await db.scalars(select(ProposalOutcome)))
    assert (row.decision, row.design_signals) == ("rejected", {})
    assert f"confirmation={card.id}" in caplog.text and "RuntimeError" in caplog.text
