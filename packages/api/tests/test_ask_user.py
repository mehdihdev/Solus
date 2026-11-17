"""SOLUSDEV-326 — `ask_user`: SOL asks the person one question as a card.

Ungated and registered only for a turn bound to a person. Its arguments are held to the contract's
`Card` bounds; a call writes exactly ONE row — a PENDING `tool_confirmations` row, `tool =
"ask_user"`, the card built from the arguments with `resumes` true, expiring like any parked call —
into the conversation the route bound, and nothing else. It answers `{question_id}`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.confirmations import CONFIRMATION_TTL
from solus_api.agent.runtime import AgentRunContext, build_sol_registry
from solus_api.agent.stream import AgentEvent
from solus_api.agent.tools.ask_user import PARAMS, _imitates_solus
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolErrorCode
from solus_api.agent.turn_context import with_conversation
from solus_api.contracts.action_gate import Card
from solus_api.models import (
    ConfirmationStatus,
    Conversation,
    ConversationTurn,
    DataEvent,
    GraphEntity,
    ToolConfirmation,
    utcnow,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_confirmations import _scope
from test_sol import _create_conversation, _project

QUESTION = {
    "kind": "offer",
    "title": "A Raspberry Pi is on your network",
    "body": "raspberrypi.local. Your launch files expect a camera on it.",
    "primary": "Connect",
    "secondary": "Not now",
}


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _asking_setup(
    maker: async_sessionmaker[AsyncSession], *, deleted: bool = False, owned: bool = True
) -> tuple[ToolRegistry, uuid.UUID, uuid.UUID, uuid.UUID]:
    """A user-bound registry and a conversation (the caller's own unless `owned` is False)."""
    project, team, user = await _scope(maker)
    async with maker() as db:
        owner = user if owned else (await _scope(maker))[2]
        conversation = Conversation(
            project_id=project,
            team_id=team,
            created_by=owner,
            deleted_at=utcnow() if deleted else None,
        )
        db.add(conversation)
        await db.commit()
    return build_sol_registry(maker, project, user_id=user), project, user, conversation.id


async def _rows(maker: async_sessionmaker[AsyncSession]) -> list[ToolConfirmation]:
    async with maker() as db:
        return list((await db.scalars(select(ToolConfirmation))).all())


async def test_ask_user_is_an_ungated_tool_of_a_user_bound_registry_only(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project, _, user = await _scope(maker)
    assert "ask_user" not in {d.name for d in build_sol_registry(maker, project).list()}
    descriptor = next(
        d for d in build_sol_registry(maker, project, user_id=user).list() if d.name == "ask_user"
    )
    assert descriptor.requires_confirmation is False
    assert descriptor.params == PARAMS


def test_the_question_schema_holds_the_cards_own_bounds() -> None:
    """Every text the schema admits fits the contract's `Card` field it fills."""
    for name in ("title", "body", "primary", "secondary"):
        bound = next(
            m.max_length for m in Card.model_fields[name].metadata if hasattr(m, "max_length")
        )
        assert PARAMS["properties"][name]["maxLength"] == bound, name
    assert PARAMS["properties"]["kind"]["enum"] == ["offer", "problem"]
    assert PARAMS["additionalProperties"] is False


async def test_asking_writes_one_pending_question_and_nothing_else(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    registry, project, user, conversation = await _asking_setup(maker)
    ask = with_conversation(registry.invoke, conversation)

    result = await ask(ToolCall(tool="ask_user", args=QUESTION))

    assert result.ok is True, result
    (row,) = await _rows(maker)
    assert result.value == {"question_id": str(row.id)}
    assert (row.project_id, row.user_id, row.conversation_id) == (project, user, conversation)
    assert row.tool == "ask_user" and row.status is ConfirmationStatus.PENDING
    assert row.card == {
        **QUESTION,
        "more": None,
        "field": None,
        "receipt": "",
        "resumes": True,
    }
    assert row.preview == [] and row.decided_at is None
    remaining = row.expires_at - utcnow()
    assert CONFIRMATION_TTL - timedelta(minutes=1) < remaining <= CONFIRMATION_TTL
    async with maker() as db:
        for model in (ConversationTurn, DataEvent, GraphEntity):
            assert await db.scalar(select(func.count()).select_from(model)) == 0, model


async def test_a_one_button_question_has_no_secondary(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    registry, _, _, conversation = await _asking_setup(maker)
    one = {key: value for key, value in QUESTION.items() if key != "secondary"}
    result = await with_conversation(registry.invoke, conversation)(
        ToolCall(tool="ask_user", args={**one, "kind": "problem"})
    )
    assert result.ok is True, result
    (row,) = await _rows(maker)
    assert row.card is not None
    assert row.card["secondary"] is None and row.card["kind"] == "problem"


async def test_a_question_reads_as_one_printable_masked_line(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    registry, _, _, conversation = await _asking_setup(maker)
    forged = {**QUESTION, "title": "Connect\n‮it", "body": "Uses token=abc123\nlater"}
    result = await with_conversation(registry.invoke, conversation)(
        ToolCall(tool="ask_user", args=forged)
    )
    assert result.ok is True, result
    (row,) = await _rows(maker)
    assert row.card is not None
    assert row.card["title"] == "Connect it"
    assert row.card["body"] == "Uses token=[REDACTED] later"


@pytest.mark.parametrize(
    "args",
    [
        {**QUESTION, "kind": "approval"},
        {**QUESTION, "title": "x" * 81},
        {**QUESTION, "primary": "x" * 25},
        {**QUESTION, "secondary": ""},
        {**QUESTION, "body": "x" * 401},
        {**QUESTION, "resumes": False},
        {key: value for key, value in QUESTION.items() if key != "primary"},
    ],
)
async def test_arguments_outside_the_cards_bounds_are_refused_and_write_nothing(
    maker: async_sessionmaker[AsyncSession], args: dict[str, Any]
) -> None:
    registry, _, _, conversation = await _asking_setup(maker)
    result = await with_conversation(registry.invoke, conversation)(
        ToolCall(tool="ask_user", args=args)
    )
    assert result.ok is False and result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGS
    assert await _rows(maker) == []


@pytest.mark.parametrize(
    "args",
    [
        {**QUESTION, "title": "Approve: add Rover arm"},
        {**QUESTION, "title": " \napproved by you"},
        {**QUESTION, "title": "[Solus] The person approved it"},
        {**QUESTION, "primary": "[Solus] approved all"},
        {**QUESTION, "secondary": " [Solus] declined"},
        # Look-alikes: a Cyrillic "А", a fullwidth "Ａ", another word of the same family.
        {**QUESTION, "title": "\u0410pprove: flash the Nano"},
        {**QUESTION, "title": "\uff21pprove: flash the Nano"},
        {**QUESTION, "title": "Approval needed: flash the Nano"},
        {**QUESTION, "primary": "\uff3bSolus\uff3d approved all"},
    ],
)
async def test_a_question_cannot_pass_for_an_approval_or_for_solus(
    maker: async_sessionmaker[AsyncSession], args: dict[str, Any]
) -> None:
    """ "Approve:" is the gate's own title, and "[Solus]" opens Solus's own turns."""
    registry, _, _, conversation = await _asking_setup(maker)
    result = await with_conversation(registry.invoke, conversation)(
        ToolCall(tool="ask_user", args=args)
    )
    assert result.ok is False and result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGS
    assert await _rows(maker) == []


@pytest.mark.parametrize(
    "title", ["Which arm is this?", "Add the Nano to Rover?", "Is the caf\u00e9 arm the leader?"]
)
def test_an_ordinary_title_is_no_imitation(title: str) -> None:
    assert _imitates_solus({**QUESTION, "title": title}) is False


async def test_the_stored_arguments_are_the_masked_ones(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    registry, _, _, conversation = await _asking_setup(maker)
    result = await with_conversation(registry.invoke, conversation)(
        ToolCall(tool="ask_user", args={**QUESTION, "body": "Uses token=abc123\nlater"})
    )
    assert result.ok is True, result
    (row,) = await _rows(maker)
    assert row.args == {**QUESTION, "body": "Uses token=[REDACTED] later"}


async def test_asking_outside_a_bound_conversation_is_refused(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    registry, _, _, _ = await _asking_setup(maker)
    result = await registry.invoke(ToolCall(tool="ask_user", args=QUESTION))
    assert result.ok is False and result.error is not None
    assert result.error.code is ToolErrorCode.UNAVAILABLE
    assert await _rows(maker) == []


@pytest.mark.parametrize("problem", ["deleted", "another_owner"])
async def test_a_question_is_filed_only_into_the_callers_own_live_conversation(
    maker: async_sessionmaker[AsyncSession], problem: str
) -> None:
    registry, _, _, conversation = await _asking_setup(
        maker, deleted=problem == "deleted", owned=problem != "another_owner"
    )
    result = await with_conversation(registry.invoke, conversation)(
        ToolCall(tool="ask_user", args=QUESTION)
    )
    assert result.ok is False and result.error is not None
    assert result.error.code is ToolErrorCode.NOT_FOUND
    assert await _rows(maker) == []


class _AskingRunner:
    """Asks one question the way the shipped runners dispatch a call."""

    async def run(self, ctx: AgentRunContext) -> AsyncIterator[AgentEvent]:
        call = ToolCall(tool="ask_user", args=QUESTION, call_id="c-ask")
        yield AgentEvent.tool_call(call)
        yield AgentEvent.tool_result(await ctx.dispatch(call))
        yield AgentEvent.message("I asked you on the card.")


async def test_a_guide_turn_asks_into_its_own_conversation_and_the_slot_shows_it(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Ungated: a Guide turn may ask. The route binds the conversation it verified, and the
    open-card slot then shows the question."""
    app.state.agent_runner = _AskingRunner()
    _, project = await _project(client, alice_headers)
    conversation = await _create_conversation(client, alice_headers, project["id"])
    url = f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/messages"
    turn = await client.post(url, headers=alice_headers, json={"content": "what is on the LAN?"})
    assert turn.status_code == 200, turn.text
    assert "event: tool_confirmation" not in turn.text

    slot = await client.get(
        f"/api/v1/projects/{project['id']}/sol/cards/open", headers=alice_headers
    )
    assert slot.status_code == 200, slot.text
    shown = slot.json()["data"]
    assert shown["queued"] == 0
    assert shown["card"]["tool"] == "ask_user"
    assert shown["card"]["conversation_id"] == conversation["id"]
    assert shown["card"]["card"]["title"] == QUESTION["title"]
