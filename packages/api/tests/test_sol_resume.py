"""SOLUSDEV-317 §5.5: continuing a SOL turn after a decided command card.

`MessageCreate.resume_confirmation_id` starts a turn with no user turn stored;
it is owner/conversation scoped, once-only, capped at six consecutive resumes,
and goes through the same budget pre-flight as a typed message.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from conftest import BOB, add_member
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.runtime import AgentRunContext
from solus_api.agent.stream import AgentEvent
from solus_api.models import (
    ConfirmationStatus,
    Conversation,
    ConversationTurn,
    DataEvent,
    ToolConfirmation,
    TurnRole,
    User,
    utcnow,
)
from solus_api.routers.sol_resume import RESUME_PROMPT
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from test_sol import _create_conversation, _project


class _Capture:
    def __init__(self) -> None:
        self.seen: list[AgentRunContext] = []

    async def run(self, ctx: AgentRunContext) -> AsyncIterator[AgentEvent]:
        self.seen.append(ctx)
        yield AgentEvent.message("continued")


async def _seed(
    db: AsyncSession,
    *,
    project_id: str,
    conversation_id: str,
    tool: str = "code.exec",
    status: ConfirmationStatus = ConfirmationStatus.APPROVED,
    with_decision_turn: bool = True,
) -> uuid.UUID:
    convo = await db.get(Conversation, uuid.UUID(conversation_id))
    assert convo is not None
    row = ToolConfirmation(
        project_id=uuid.UUID(project_id),
        team_id=convo.team_id,
        user_id=convo.created_by,
        conversation_id=convo.id,
        tool=tool,
        args={"argv": ["make"]},
        summary="Run",
        expires_at=utcnow() + timedelta(minutes=30),
        status=status,
    )
    db.add(row)
    await db.flush()
    if with_decision_turn:
        db.add(
            ConversationTurn(
                conversation_id=convo.id,
                project_id=uuid.UUID(project_id),
                role=TurnRole.TOOL,
                content=f"{tool} → approved by you; the command exited 0",
                attrs={"confirmation_id": str(row.id)},
            )
        )
    await db.commit()
    return row.id


def _url(project_id: str, conversation_id: str) -> str:
    return f"/api/v1/projects/{project_id}/sol/conversations/{conversation_id}/messages"


@pytest.fixture
def capture(app: FastAPI) -> _Capture:
    runner = _Capture()
    app.state.agent_runner = runner
    return runner


async def _setup(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    _, project = await _project(client, headers)
    convo = await _create_conversation(client, headers, project["id"])
    return project["id"], convo["id"]


async def test_resume_runs_a_turn_without_a_user_turn_and_records_resume_of(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, capture: _Capture
) -> None:
    project, convo = await _setup(client, alice_headers)
    await db.execute(update(User).values(data_collection_consent=True))
    await db.commit()
    confirmation = await _seed(db, project_id=project, conversation_id=convo)

    resp = await client.post(
        _url(project, convo),
        json={"resume_confirmation_id": str(confirmation), "action_mode": "do"},
        headers=alice_headers,
    )

    assert resp.status_code == 200, resp.text
    assert capture.seen[0].prompt == RESUME_PROMPT
    turns = (
        await db.scalars(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == uuid.UUID(convo))
            .order_by(ConversationTurn.created_at)
        )
    ).all()
    assert [t.role for t in turns] == [TurnRole.TOOL, TurnRole.ASSISTANT]
    assert turns[1].attrs["resume_of"] == str(confirmation)
    events = (
        await db.scalars(select(DataEvent).where(DataEvent.event_type == "sol.turn_resumed"))
    ).all()
    assert [e.payload for e in events] == [
        {"confirmation_id": str(confirmation), "tool": "code.exec", "chain": 1}
    ]
    assert not (
        await db.scalars(select(DataEvent).where(DataEvent.event_type == "sol.message"))
    ).all()


async def test_a_confirmation_resumes_only_once(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, capture: _Capture
) -> None:
    project, convo = await _setup(client, alice_headers)
    confirmation = await _seed(db, project_id=project, conversation_id=convo)
    body = {"resume_confirmation_id": str(confirmation)}
    assert (
        await client.post(_url(project, convo), json=body, headers=alice_headers)
    ).status_code == 200
    again = await client.post(_url(project, convo), json=body, headers=alice_headers)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_resumed"
    assert len(capture.seen) == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"action_mode": "do"},
        {"content": "hi", "resume_confirmation_id": str(uuid.uuid4())},
        {"resume_confirmation_id": "not-a-uuid"},
        {"content": ""},
    ],
)
async def test_body_validation(
    client: AsyncClient, alice_headers: dict[str, str], capture: _Capture, body: dict[str, Any]
) -> None:
    project, convo = await _setup(client, alice_headers)
    resp = await client.post(_url(project, convo), json=body, headers=alice_headers)
    assert resp.status_code == 422, resp.text
    assert capture.seen == []


@pytest.mark.parametrize(
    ("tool", "status", "decided_turn"),
    [
        ("code.exec", ConfirmationStatus.PENDING, True),
        ("onshape.set_variable", ConfirmationStatus.APPROVED, True),
        ("code.exec", ConfirmationStatus.APPROVED, False),
    ],
)
async def test_only_decided_command_actions_resume(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    capture: _Capture,
    tool: str,
    status: ConfirmationStatus,
    decided_turn: bool,
) -> None:
    project, convo = await _setup(client, alice_headers)
    confirmation = await _seed(
        db,
        project_id=project,
        conversation_id=convo,
        tool=tool,
        status=status,
        with_decision_turn=decided_turn,
    )
    resp = await client.post(
        _url(project, convo),
        json={"resume_confirmation_id": str(confirmation)},
        headers=alice_headers,
    )
    assert resp.status_code == 422
    assert capture.seen == []


async def test_command_tools_that_resume(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, capture: _Capture
) -> None:
    project, convo = await _setup(client, alice_headers)
    for tool in (
        "code.run",
        "code.test",
        "code.install",
        "code.create_environment",
        "code.process_start",
        "code.profile_capture",
    ):
        confirmation = await _seed(db, project_id=project, conversation_id=convo, tool=tool)
        resp = await client.post(
            _url(project, convo),
            json={"resume_confirmation_id": str(confirmation)},
            headers=alice_headers,
        )
        assert resp.status_code == 200, (tool, resp.text)


async def test_another_conversation_or_user_cannot_resume(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    capture: _Capture,
) -> None:
    team, project = await _project(client, alice_headers)
    alice_convo = await _create_conversation(client, alice_headers, project["id"])
    other_convo = await _create_conversation(client, alice_headers, project["id"])
    confirmation = await _seed(db, project_id=project["id"], conversation_id=alice_convo["id"])
    body = {"resume_confirmation_id": str(confirmation)}

    wrong_convo = await client.post(
        _url(project["id"], other_convo["id"]), json=body, headers=alice_headers
    )
    assert wrong_convo.status_code == 404

    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    bob_convo = await _create_conversation(client, bob_headers, project["id"])
    teammate = await client.post(
        _url(project["id"], bob_convo["id"]), json=body, headers=bob_headers
    )
    assert teammate.status_code == 404
    assert capture.seen == []


async def test_cross_team_resume_is_404(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    capture: _Capture,
) -> None:
    project, convo = await _setup(client, alice_headers)
    confirmation = await _seed(db, project_id=project, conversation_id=convo)
    bob_project, bob_convo = await _setup(client, bob_headers)
    resp = await client.post(
        _url(bob_project, bob_convo),
        json={"resume_confirmation_id": str(confirmation)},
        headers=bob_headers,
    )
    assert resp.status_code == 404
    foreign = await client.post(
        _url(project, convo),
        json={"resume_confirmation_id": str(confirmation)},
        headers=bob_headers,
    )
    assert foreign.status_code == 404
    assert capture.seen == []


async def test_six_consecutive_resumes_then_wait_for_the_person(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, capture: _Capture
) -> None:
    project, convo = await _setup(client, alice_headers)
    for chain in range(1, 7):
        confirmation = await _seed(db, project_id=project, conversation_id=convo)
        resp = await client.post(
            _url(project, convo),
            json={"resume_confirmation_id": str(confirmation)},
            headers=alice_headers,
        )
        assert resp.status_code == 200, (chain, resp.text)
    seventh = await _seed(db, project_id=project, conversation_id=convo)
    body = {"resume_confirmation_id": str(seventh)}
    limited = await client.post(_url(project, convo), json=body, headers=alice_headers)
    assert limited.status_code == 409
    assert limited.json()["error"]["code"] == "resume_limit"
    typed = await client.post(
        _url(project, convo), json={"content": "go on"}, headers=alice_headers
    )
    assert typed.status_code == 200
    assert (
        await client.post(_url(project, convo), json=body, headers=alice_headers)
    ).status_code == 200


async def test_budget_preflight_applies_and_does_not_consume_the_resume(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    capture: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.routers import sol

    project, convo = await _setup(client, alice_headers)
    confirmation = await _seed(db, project_id=project, conversation_id=convo)
    body = {"resume_confirmation_id": str(confirmation)}

    async def broke(*_args: Any, **_kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(sol, "has_sufficient_credits", broke)
    refused = await client.post(_url(project, convo), json=body, headers=alice_headers)
    assert refused.status_code == 402
    monkeypatch.undo()
    resumed = await client.post(_url(project, convo), json=body, headers=alice_headers)
    assert resumed.status_code == 200
    assert json.dumps(capture.seen[0].prompt) == json.dumps(RESUME_PROMPT)


async def test_the_claim_is_atomic(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, engine: Any
) -> None:
    from solus_api.core.errors import APIError
    from solus_api.routers.sol_resume import ResumeTicket, claim_resume
    from sqlalchemy.ext.asyncio import async_sessionmaker

    project, convo = await _setup(client, alice_headers)
    confirmation = await _seed(db, project_id=project, conversation_id=convo)
    ticket = ResumeTicket(confirmation_id=confirmation, tool="code.exec", chain=1)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    scope = {"conversation_id": uuid.UUID(convo), "project_id": uuid.UUID(project)}
    async with maker() as first:
        await claim_resume(first, ticket, **scope)
        await first.commit()
    async with maker() as second:
        with pytest.raises(APIError) as caught:
            await claim_resume(second, ticket, **scope)
    assert caught.value.status_code == 409


async def test_concurrent_resumes_at_chain_five_respect_the_cap(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, engine: Any
) -> None:
    """§9 item 9: the chain check locks the conversation row, so two resumes that
    both read chain 5 cannot both start a turn (the sixth claim is visible to the
    second check before any assistant turn has been written)."""
    import asyncio

    from solus_api.core.errors import APIError
    from solus_api.routers.sol_resume import check_resume, claim_resume
    from sqlalchemy.ext.asyncio import async_sessionmaker

    project, convo = await _setup(client, alice_headers)
    owner = await db.get(Conversation, uuid.UUID(convo))
    assert owner is not None
    for _ in range(5):
        db.add(
            ConversationTurn(
                conversation_id=owner.id,
                project_id=uuid.UUID(project),
                role=TurnRole.ASSISTANT,
                content="continued",
                attrs={"resume_of": str(uuid.uuid4())},
            )
        )
    await db.commit()
    first = await _seed(db, project_id=project, conversation_id=convo)
    second = await _seed(db, project_id=project, conversation_id=convo)
    scope = {
        "conversation_id": owner.id,
        "project_id": uuid.UUID(project),
        "team_id": owner.team_id,
        "user_id": owner.created_by,
    }
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as a, maker() as b:
        ticket = await check_resume(a, confirmation_id=first, **scope)
        assert ticket.chain == 6
        racing = asyncio.create_task(check_resume(b, confirmation_id=second, **scope))
        await asyncio.sleep(0.3)
        assert not racing.done()  # blocked on the conversation row lock
        await claim_resume(
            a, ticket, conversation_id=owner.id, project_id=uuid.UUID(project)
        )
        await a.commit()
        with pytest.raises(APIError) as caught:
            await racing
    assert caught.value.status_code == 409
    assert caught.value.code == "resume_limit"
