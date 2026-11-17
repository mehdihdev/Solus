"""SOLUSDEV-326 — the card a parked call shows, and a tool's "working" line.

A tool may author its card through a duck-typed `card(stored_args)` and say what it is doing
through `working(args)`; `card_resumes` says whether SOL continues after any decision on it. The
gate computes the card ONCE when the call parks, from the STORED arguments, validates it as the
contract's `Card`, sets `resumes` from the tool (never the model), keeps `more` only in Guide
mode, and stores it on the row. The card is presentation only: it never enters the consent or
the stale check, and never becomes a `DiffRow` (docs/contracts/action-gate.md §Cards).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from functools import partial
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.cards import authored_card, chip, single_line, working_line
from solus_api.agent.confirmations import decide_confirmation, request_confirmation
from solus_api.agent.runtime import AgentRunContext, LlmRunner
from solus_api.agent.stream import WORKING_CAP, AgentEvent, AgentEventType
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolDescriptor
from solus_api.contracts.action_gate import Card
from solus_api.deps import get_sol_registry
from solus_api.models import (
    ConfirmationStatus,
    Conversation,
    SolMode,
    ToolConfirmation,
    User,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_confirmations import _scope
from test_sol import _create_conversation, _parse_sse, _project
from test_sol_reasoner import _ctx, _ScriptedModel

NAME = "hw.add_robot"


def _drafted(**overrides: Any) -> Card:
    fields: dict[str, Any] = {
        "kind": "approval",
        "title": "Approve: add Rover arm",
        "body": "Three servos answer on `/dev/ttyUSB0`.",
        "more": "A robot groups the parts that move together.",
        "primary": "Approve",
        "secondary": "Not now",
        "receipt": "Rover arm added",
        "resumes": False,
    }
    return Card(**{**fields, **overrides})


class _CardAuthor:
    """A gated tool that authors its card from the arguments it is parked with."""

    card_resumes = True

    def __init__(self, *, resumes: bool = True, title: str | None = None) -> None:
        self.card_resumes = resumes
        self.title = title
        self.cards_built: list[dict[str, Any]] = []
        self.ran: list[dict[str, Any]] = []
        self.descriptor = ToolDescriptor(
            name=NAME,
            description="Add a robot.",
            params={"type": "object", "properties": {"name": {"type": "string"}}},
            returns={"type": "object"},
            requires_confirmation=True,
        )

    def stored_args(self, args: dict[str, Any]) -> dict[str, Any]:
        return {**args, "device_ref": "usb:SERIAL1"}

    def card(self, stored_args: dict[str, Any]) -> Card:
        self.cards_built.append(stored_args)
        title = self.title or f"Approve: add {stored_args['name']} {len(self.cards_built)}"
        return _drafted(title=title, body=f"It is `{stored_args['device_ref']}`.")

    def working(self, args: dict[str, Any]) -> str:
        return f"Adding {args.get('name')}\non the bench"

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        self.ran.append(args)
        return {"added": args["name"]}


class _ClaimingCardAuthor(_CardAuthor):
    """Its card says it resumes; whether it does is the tool's `card_resumes` alone."""

    def card(self, stored_args: dict[str, Any]) -> Card:
        self.cards_built.append(stored_args)
        return _drafted(resumes=True)


class _Plain:
    """A tool that authors neither a card nor a working line."""

    descriptor = ToolDescriptor(
        name="plain.read", description="Read.", params={"type": "object"}, returns={}
    )

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        return {}


# ------------------------------------------------------------------------------ authoring


def test_a_tool_that_authors_no_card_parks_without_one() -> None:
    assert authored_card(_Plain(), {"name": "x"}, guide=True) is None


def test_resumes_is_the_tools_and_more_is_guide_modes() -> None:
    tool = _CardAuthor(title="Approve: add Rover")  # its card says it does not resume
    guide = authored_card(tool, {"name": "Rover", "device_ref": "usb:A"}, guide=True)
    expert = authored_card(tool, {"name": "Rover", "device_ref": "usb:A"}, guide=False)
    assert guide is not None and expert is not None
    assert guide["resumes"] is True and expert["resumes"] is True
    assert guide["more"] == "A robot groups the parts that move together."
    assert expert["more"] is None
    assert Card.model_validate(guide) == Card.model_validate({**expert, "more": guide["more"]})
    # A card that says it resumes never resumes when its tool does not, or says nothing.
    quiet = _ClaimingCardAuthor(resumes=False)
    drafted = authored_card(quiet, {"name": "Rover", "device_ref": "usb:A"}, guide=True)
    assert drafted is not None and drafted["resumes"] is False
    unflagged = _Plain()
    unflagged.card = lambda args: _drafted(resumes=True)  # type: ignore[attr-defined]
    drafted = authored_card(unflagged, {}, guide=True)
    assert drafted is not None and drafted["resumes"] is False


def test_the_card_reads_a_copy_of_the_stored_arguments() -> None:
    tool = _CardAuthor()
    stored = {"name": "Rover", "device_ref": "usb:A"}
    authored_card(tool, stored, guide=True)
    assert tool.cards_built == [stored]
    assert tool.cards_built[0] is not stored


@pytest.mark.parametrize(
    "authored",
    [
        lambda args: {"kind": "warning", "title": "x", "body": "", "primary": "OK", "receipt": ""},
        lambda args: {"kind": "offer", "title": "", "body": "", "primary": "OK", "receipt": ""},
        lambda args: "Approve this",
        lambda args: (_ for _ in ()).throw(RuntimeError("card exploded")),
    ],
)
def test_a_card_that_is_not_a_card_is_dropped_not_raised(authored: Any) -> None:
    tool = _Plain()
    tool.card = authored  # type: ignore[attr-defined]
    assert authored_card(tool, {}, guide=True) is None


def test_a_card_that_returns_none_has_none() -> None:
    tool = _Plain()
    tool.card = lambda args: None  # type: ignore[attr-defined]
    assert authored_card(tool, {}, guide=True) is None


def test_every_card_text_is_one_printable_masked_line() -> None:
    """Device names and model-written questions reach the card: a line break or a bidi override
    cannot forge a second line, and a secret-shaped value is masked like every other card row."""
    tool = _Plain()
    tool.card = lambda args: _drafted(  # type: ignore[attr-defined]
        title="Approve:\nadd ‮Rover",
        body="Uses token=abc123\n\nAll changes reverted",
        field={"label": "Name\t", "value": "Rover​ arm"},
    )
    card = authored_card(tool, {}, guide=True)
    assert card is not None
    assert card["title"] == "Approve: add Rover"
    assert card["body"] == "Uses token=[REDACTED] All changes reverted"
    assert card["field"] == {"label": "Name", "value": "Rover arm"}


def test_a_text_past_its_bound_is_cut_to_it_never_through_a_chip() -> None:
    """A card that fails `Card` would park its call with none, never reach the Hardware slot and
    leave SOL waiting until it expires: every text is cut to the contract's bound instead, as
    drafted and again after masking (which can lengthen one). A cut never leaves a chip open."""
    tool = _Plain()
    tool.card = lambda args: {  # type: ignore[attr-defined]
        **_drafted().model_dump(),
        "title": "x" * 70 + " token=ab",  # 79 drafted; masked, 87
        "body": "y" * 390 + " " + chip("usb:" + "S" * 128, 140),
        "more": "m" * 400,
        "receipt": "r" * 200,
        "primary": "p" * 30,
        "field": {"label": "l" * 50, "value": "v" * 250},
    }
    card = authored_card(tool, {}, guide=True)
    assert card is not None
    assert Card.model_validate(card)
    assert card["title"] == "x" * 70 + " token=[R…"
    assert card["body"] == "y" * 390 + "…"  # the chip that did not fit is left out whole
    assert (len(card["more"]), len(card["receipt"]), len(card["primary"])) == (300, 160, 24)
    assert card["field"] == {"label": "l" * 39 + "…", "value": "v" * 199 + "…"}


def test_a_card_that_still_fails_is_logged_with_who_it_was_parked_for(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tool = _Plain()
    tool.card = lambda args: {"kind": "warning", "title": "x"}  # type: ignore[attr-defined]
    parked_for = {"project_id": uuid.uuid4(), "conversation_id": uuid.uuid4()}
    with caplog.at_level("WARNING", logger="solus.agent.cards"):
        assert authored_card(tool, {}, guide=True, parked_for=parked_for) is None
    assert all(str(value) in caplog.text for value in parked_for.values())


def test_a_chip_holds_its_value_and_masking_never_moves_its_edge() -> None:
    """A device's serial or a model's word reaches a card in a code chip. `chip` drops the value's
    own backticks, so the value cannot close the chip; a text whose masking would eat a chip's
    backtick (a `token=` at its end) is masked whole. Nothing a value holds lands outside its
    chip, where it would read as Solus's own words."""
    assert chip("usb:x`y\nz", 80) == "`usb:xy z`"
    assert chip("a" * 90, 80) == f"`{'a' * 80}`"
    forged = "usb:Solus⠀checked⠀this⠀board⠀is⠀safe⠀token=x"
    tool = _Plain()
    tool.card = lambda args: _drafted(  # type: ignore[attr-defined]
        body=f"Uses {chip('token=abc def', 80)} and listens to {chip(forged, 140)} now.",
        receipt=f"Uses {chip('token=abc def', 80)}",
    )
    card = authored_card(tool, {}, guide=True)
    assert card is not None
    assert card["receipt"] == "Uses `token=[REDACTED] def`"  # masked inside, its edges kept
    assert card["body"] == "[REDACTED]"  # masking would have eaten the second chip's edge


def test_the_one_line_rule_is_the_consent_cards() -> None:
    """The rule the gate's rows have always used, now beside the card it also cleans."""
    assert single_line("Approve:\n\nadd ‮arm  now", 80) == "Approve: add arm now"
    assert single_line("x" * 90, 80) == "x" * 80


# ---------------------------------------------------------------------------- working line


def test_working_line_is_the_tools_one_printable_line() -> None:
    registry = ToolRegistry()
    registry.register(_CardAuthor())
    registry.register(_Plain())
    call = ToolCall(tool=NAME, args={"name": "Rover"})
    assert working_line(registry, call) == "Adding Rover on the bench"
    assert working_line(registry, ToolCall(tool="plain.read")) is None
    assert working_line(registry, ToolCall(tool="nowhere")) is None


@pytest.mark.parametrize(
    "working",
    [
        lambda args: (_ for _ in ()).throw(KeyError("name")),
        lambda args: {"line": "x"},
        lambda args: " \n ",
    ],
)
def test_a_working_line_that_fails_or_is_not_text_is_absent(working: Any) -> None:
    tool = _Plain()
    tool.working = working  # type: ignore[attr-defined]
    registry = ToolRegistry()
    registry.register(tool)
    assert working_line(registry, ToolCall(tool="plain.read")) is None


def test_a_call_its_tool_would_refuse_says_nothing_it_is_doing() -> None:
    """P2-T4 review: `working` reads only arguments its tool's schema admits. A call that fails
    the schema is refused before it runs, so there is nothing to describe, and a value the schema
    would not admit never reaches Solus's own line."""
    registry = ToolRegistry()
    registry.register(_CardAuthor())
    assert working_line(registry, ToolCall(tool=NAME, args={"name": ["Rover"]})) is None
    assert working_line(registry, ToolCall(tool=NAME, args={"name": "Rover"})) is not None


def test_the_frame_cuts_the_working_line_to_its_bound() -> None:
    tool = _Plain()
    tool.working = lambda args: "w" * (WORKING_CAP + 50)  # type: ignore[attr-defined]
    registry = ToolRegistry()
    registry.register(tool)
    call = ToolCall(tool="plain.read")
    frame = AgentEvent.tool_call(call, working=working_line(registry, call))
    assert len(frame.data["working"]) == WORKING_CAP


# ---------------------------------------------------------------------------------- parking


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _conversation(
    maker: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    project, team, user = await _scope(maker)
    async with maker() as db:
        conversation = Conversation(project_id=project, team_id=team, created_by=user)
        db.add(conversation)
        await db.commit()
        return project, team, user, conversation.id


async def _park_card_call(
    maker: async_sessionmaker[AsyncSession],
    registry: ToolRegistry,
    scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    sol_mode: SolMode,
) -> Any:
    project, team, user, conversation = scope
    async with maker() as db:
        parked = await request_confirmation(
            db,
            registry,
            ToolCall(tool=NAME, args={"name": "Rover"}),
            project_id=project,
            team_id=team,
            user_id=user,
            conversation_id=conversation,
            sol_mode=sol_mode,
        )
        await db.commit()
        return parked


@pytest.mark.parametrize("sol_mode", [SolMode.GUIDE, SolMode.EXPERT])
async def test_a_parked_call_stores_its_card_from_the_stored_arguments(
    maker: async_sessionmaker[AsyncSession], sol_mode: SolMode
) -> None:
    tool = _CardAuthor()
    registry = ToolRegistry()
    registry.register(tool)
    parked = await _park_card_call(maker, registry, await _conversation(maker), sol_mode)

    assert parked.confirmation_id is not None
    # Computed once, from the stored arguments: the Solus-stamped device ref is on it.
    assert tool.cards_built == [{"name": "Rover", "device_ref": "usb:SERIAL1"}]
    assert parked.card["body"] == "It is `usb:SERIAL1`."
    assert parked.card["resumes"] is True
    assert (parked.card["more"] is not None) is (sol_mode is SolMode.GUIDE)
    async with maker() as db:
        row = await db.get(ToolConfirmation, parked.confirmation_id)
    assert row is not None and row.card == parked.card
    # Never a DiffRow: the card's words are not on the rows the person approves.
    assert all("Rover arm" not in json.dumps(preview) for preview in row.preview)


async def test_a_restored_duplicate_carries_the_card_it_parked_with(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    tool = _CardAuthor()
    registry = ToolRegistry()
    registry.register(tool)
    scope = await _conversation(maker)
    first = await _park_card_call(maker, registry, scope, SolMode.GUIDE)
    again = await _park_card_call(maker, registry, scope, SolMode.GUIDE)
    assert again.confirmation_id == first.confirmation_id
    assert again.card == first.card
    assert len(tool.cards_built) == 1  # the duplicate is restored, never re-authored


async def test_a_parked_card_resumes_only_when_its_tool_does(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The flag that admits up to 40 continuations is the tool's class attribute, never what its
    card, built from the stored arguments, says."""
    registry = ToolRegistry()
    registry.register(_ClaimingCardAuthor(resumes=False))
    parked = await _park_card_call(maker, registry, await _conversation(maker), SolMode.GUIDE)
    assert parked.card is not None and parked.card["resumes"] is False
    async with maker() as db:
        row = await db.get(ToolConfirmation, parked.confirmation_id)
    assert row is not None and row.card is not None and row.card["resumes"] is False


class _FailingCardAuthor(_CardAuthor):
    def card(self, stored_args: dict[str, Any]) -> Card:
        raise RuntimeError("no card today")


async def test_a_card_that_fails_still_parks_the_call_without_one(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    tool = _FailingCardAuthor()
    registry = ToolRegistry()
    registry.register(tool)
    parked = await _park_card_call(maker, registry, await _conversation(maker), SolMode.GUIDE)
    assert parked.confirmation_id is not None and parked.card is None
    async with maker() as db:
        stored = await db.scalar(
            select(ToolConfirmation.card).where(ToolConfirmation.id == parked.confirmation_id)
        )
        null_rows = await db.scalar(
            select(ToolConfirmation.id).where(
                ToolConfirmation.id == parked.confirmation_id, ToolConfirmation.card.is_(None)
            )
        )
    assert stored is None and null_rows == parked.confirmation_id  # SQL NULL, not JSON null


async def test_the_card_never_enters_the_stale_check(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """A card authored differently at decision time is never re-authored there: the approval
    replays the STORED arguments and runs."""
    tool = _CardAuthor()
    registry = ToolRegistry()
    registry.register(tool)
    project, team, user, conversation = await _conversation(maker)
    parked = await _park_card_call(
        maker, registry, (project, team, user, conversation), SolMode.GUIDE
    )
    tool.title = "Approve: something else entirely"
    async with maker() as db:
        result = await decide_confirmation(
            db, registry, parked.confirmation_id, approve=True, project_id=project, user_id=user
        )
        await db.commit()
    assert result.ok is True, result
    assert tool.ran == [{"name": "Rover", "device_ref": "usb:SERIAL1"}]
    assert len(tool.cards_built) == 1
    async with maker() as db:
        row = await db.get(ToolConfirmation, parked.confirmation_id)
    assert row is not None and row.status is ConfirmationStatus.APPROVED
    assert row.card == parked.card


# ------------------------------------------------------------------------------ the frames


class _ParkingRunner:
    """Proposes one call to the card tool, the way the shipped runners frame it."""

    def __init__(self) -> None:
        self.call = ToolCall(tool=NAME, args={"name": "Rover"}, call_id="c-card")

    async def run(self, ctx: AgentRunContext) -> AsyncIterator[AgentEvent]:
        yield AgentEvent.tool_call(self.call, working=ctx.working(self.call))
        yield AgentEvent.tool_result(await ctx.dispatch(self.call))
        yield AgentEvent.message("Waiting for you.")


async def _turn_frames(
    app: FastAPI, client: AsyncClient, headers: dict[str, str], tool: _CardAuthor
) -> tuple[str, str, list[tuple[str, dict[str, Any]]]]:
    registry = ToolRegistry()
    registry.register(tool)
    app.dependency_overrides[get_sol_registry] = lambda: registry
    app.state.agent_runner = _ParkingRunner()
    _, project = await _project(client, headers)
    conversation = await _create_conversation(client, headers, project["id"])
    url = f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/messages"
    response = await client.post(
        url, headers=headers, json={"content": "add it", "action_mode": "do"}
    )
    assert response.status_code == 200, response.text
    return project["id"], conversation["id"], _parse_sse(response.text)


@pytest.mark.parametrize("sol_mode", [SolMode.GUIDE, SolMode.EXPERT])
async def test_the_frames_and_the_restore_route_carry_the_card_and_the_working_line(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    sol_mode: SolMode,
) -> None:
    from conftest import me

    await me(client, alice_headers)
    await db.execute(update(User).values(sol_mode=sol_mode))
    await db.commit()
    project, conversation, frames = await _turn_frames(app, client, alice_headers, _CardAuthor())

    (call_frame,) = [data for kind, data in frames if kind == "tool_call"]
    assert call_frame["working"] == "Adding Rover on the bench"
    (parked,) = [data for kind, data in frames if kind == "tool_confirmation"]
    assert parked["card"]["title"] == "Approve: add Rover 1"
    assert parked["card"]["resumes"] is True
    assert (parked["card"]["more"] is not None) is (sol_mode is SolMode.GUIDE)

    restored = await client.get(
        f"/api/v1/projects/{project}/sol/conversations/{conversation}/confirmations",
        headers=alice_headers,
    )
    assert restored.status_code == 200, restored.text
    (row,) = restored.json()["data"]
    assert row["card"] == parked["card"]
    assert row["confirmation_id"] == parked["confirmation_id"]


async def test_a_tool_without_a_card_or_working_line_frames_as_before(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    tool = _CardAuthor()
    del tool.card_resumes
    plain = type("Plainer", (), {})()
    plain.descriptor = tool.descriptor
    plain.invoke = tool.invoke
    _, _, frames = await _turn_frames(app, client, alice_headers, plain)
    (call_frame,) = [data for kind, data in frames if kind == "tool_call"]
    assert "working" not in call_frame
    (parked,) = [data for kind, data in frames if kind == "tool_confirmation"]
    assert parked["card"] is None


#: A GitHub-token shape (36 characters after `ghp_`), assembled so no scanner reads it as one.
_KEY = "ghp_" + "aB3dE5fG7hJ9" * 3


class _PushingCardAuthor(_CardAuthor):
    """Its working line carries a token that crosses the frame's cut (it starts at 141)."""

    def working(self, args: dict[str, Any]) -> str:
        return "Uploading the sketch to the board " * 4 + "with " + _KEY


async def test_a_secret_crossing_the_cut_is_masked_on_the_frame_and_the_stored_turn(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """The line is masked BEFORE it is cut, like `args` (contract §Cards 6): cut first, the token
    loses the length its shape needs and its first part goes out in the clear — on the frame and
    in the tool turn `/turns` serves back (SOLUS-RUN-01)."""
    tool = _PushingCardAuthor()
    project, conversation, frames = await _turn_frames(app, client, alice_headers, tool)
    (call_frame,) = [data for kind, data in frames if kind == "tool_call"]
    turns = await client.get(
        f"/api/v1/projects/{project}/sol/conversations/{conversation}/turns",
        headers=alice_headers,
    )
    assert turns.status_code == 200, turns.text
    (stored,) = [
        turn["attrs"]["call"]["working"] for turn in turns.json()["data"] if turn["role"] == "tool"
    ]
    for line in (call_frame["working"], stored):
        assert line.endswith("with [REDACTED]"), line
        assert "ghp_" not in line


async def test_the_shipped_runner_frames_the_working_line(engine: AsyncEngine) -> None:
    """LlmRunner, on a scripted model (no provider call): each `tool_call` frame carries the line
    the route bound for that call."""
    ctx = await _ctx(engine, "what are the variables?")
    seen: list[ToolCall] = []

    def line(call: ToolCall) -> str | None:
        seen.append(call)
        return "Reading the variables"

    model = _ScriptedModel(tool_round=True)
    adapters = {name: model for name in ("anthropic", "openai", "google")}
    events = [e async for e in LlmRunner(adapters=adapters).run(replace(ctx, working=line))]
    (call_frame,) = [e.data for e in events if e.type is AgentEventType.TOOL_CALL]
    assert call_frame["working"] == "Reading the variables"
    assert [call.tool for call in seen] == [call_frame["tool"]]


def test_the_route_binds_the_working_line_to_its_own_registry() -> None:
    registry = ToolRegistry()
    registry.register(_CardAuthor())
    bound = partial(working_line, registry)
    assert bound(ToolCall(tool=NAME, args={"name": "Rover"})) == "Adding Rover on the bench"
