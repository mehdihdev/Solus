"""A review-only Build request cannot authorize a routine file write."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from conftest import me
from pydantic import ValidationError
from solus_api.agent.execution_policy import register_owned_routine
from solus_api.agent.stream import AgentEvent
from solus_api.agent.tools.machine_writes import build_machine_write_tool
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall
from solus_api.deps import get_sol_registry
from solus_api.models import ConfirmationStatus, ToolConfirmation
from solus_api.routers import sol_notice
from solus_api.routers.sol import MessageCreate
from sqlalchemy import select
from test_machine_writes import Native
from test_sol import _create_conversation, _project
from test_sol_notice import _notice, _remembering_machine, _seen
from test_sol_resume import _seed_card


@pytest.mark.parametrize("invalid", ["true", "false", 1, 0, None])
def test_force_confirmation_requires_a_real_boolean(invalid: Any) -> None:
    with pytest.raises(ValidationError):
        MessageCreate(content="Review this edit", force_confirmation=invalid)


def test_force_confirmation_defaults_off() -> None:
    assert MessageCreate(content="Normal Build request").force_confirmation is False


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_review_only_build_parks_owned_machine_write_until_explicit_decision(
    app: Any,
    client: Any,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: Any,
    tmp_path: Path,
    decision: str,
) -> None:
    _, project = await _project(client, alice_headers)
    conversation = await _create_conversation(client, alice_headers, project["id"])
    target = tmp_path / "control.py"
    before, after = "robot.connect()\n", "robot.connect()\n# reviewed observation shim\n"
    target.write_text(before)
    native = Native(tmp_path)
    writer = build_machine_write_tool(native)
    register_owned_routine(writer, family="machine")
    assert getattr(writer, "_build_authority", None) is not None
    registry = ToolRegistry()
    registry.register(writer)
    app.dependency_overrides[get_sol_registry] = lambda: registry

    class Runner:
        async def run(self, ctx: Any) -> AsyncIterator[AgentEvent]:
            # Even a model that insists on writing cannot override the HTTP policy.
            call = ToolCall(
                tool="machine.write_file",
                args={"path": "control.py", "content": after, "create_dirs": False},
            )
            yield AgentEvent.tool_call(call)
            yield AgentEvent.tool_result(await ctx.dispatch(call))
            yield AgentEvent.message("Review requested")

    app.state.agent_runner = Runner()
    url = f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/messages"
    body = {"content": "Review only", "action_mode": "do", "force_confirmation": True}
    assert (await client.post(url, json=body)).status_code == 401
    assert (await client.post(url, headers=bob_headers, json=body)).status_code == 404
    response = await client.post(url, headers=alice_headers, json=body)
    assert response.status_code == 200, response.text
    assert "event: tool_confirmation" in response.text
    assert target.read_text() == before
    # M184: the saved transcript tells the next turn the call is parked, not unauthorized.
    turns = await client.get(
        f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/turns",
        headers=alice_headers,
    )
    contents = [str(turn["content"]) for turn in turns.json()["data"]]
    assert "machine.write_file → parked, awaiting your approval" in contents, contents
    assert native.calls and all(call.get("dry_run") is True for call in native.calls)
    confirmation = await db.scalar(select(ToolConfirmation))
    assert confirmation is not None
    decision_url = f"/api/v1/projects/{project['id']}/sol/confirmations/{confirmation.id}"
    assert (
        await client.post(decision_url, headers=bob_headers, json={"decision": "approve"})
    ).status_code == 404
    assert target.read_text() == before
    outcome = await client.post(decision_url, headers=alice_headers, json={"decision": decision})
    assert outcome.status_code == 200, outcome.text
    assert target.read_text() == (after if decision == "approve" else before)
    assert sum("expected_fingerprint" in call for call in native.calls) == int(
        decision == "approve"
    )


# --- SOLUSDEV-326 P2 follow-up: a turn the person did not type always asks -----------------------


@pytest.mark.parametrize("started_by", ["notice", "card_resume", "typed"])
async def test_only_a_notice_or_a_card_resume_forces_the_card_on_the_server(
    app: Any,
    client: Any,
    alice_headers: dict[str, str],
    db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    started_by: str,
) -> None:
    """A device notice (started by a plug-in, carrying a device-chosen serial) and a resume after
    a card park an owned routine in "do" whatever the client's `force_confirmation` says; a typed
    message in "do" keeps running it."""
    monkeypatch.setattr(sol_notice, "_last_notice", {})
    user = await me(client, alice_headers)
    _, project = await _project(client, alice_headers)
    conversation = await _create_conversation(client, alice_headers, project["id"])
    target = tmp_path / "control.py"
    before, after = "robot.connect()\n", "robot.connect()\n# device said so\n"
    target.write_text(before)
    writer = build_machine_write_tool(Native(tmp_path))
    register_owned_routine(writer, family="machine")
    registry = ToolRegistry()
    registry.register(writer)
    app.dependency_overrides[get_sol_registry] = lambda: registry

    class Runner:
        async def run(self, ctx: Any) -> AsyncIterator[AgentEvent]:
            call = ToolCall(
                tool="machine.write_file",
                args={"path": "control.py", "content": after, "create_dirs": False},
            )
            yield AgentEvent.tool_call(call)
            yield AgentEvent.tool_result(await ctx.dispatch(call))
            yield AgentEvent.message("Done")

    app.state.agent_runner = Runner()
    body: dict[str, Any] = {"action_mode": "do"}
    if started_by == "notice":
        await _remembering_machine(db, project["id"], user["id"], [_seen()])
        body |= _notice()
    elif started_by == "card_resume":
        card = await _seed_card(db, project_id=project["id"], conversation_id=conversation["id"])
        body |= {"resume_confirmation_id": str(card)}
    else:
        body |= {"content": "Add the shim"}
    url = f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/messages"

    response = await client.post(url, headers=alice_headers, json=body)

    assert response.status_code == 200, response.text
    pending = (
        await db.scalars(
            select(ToolConfirmation).where(
                ToolConfirmation.tool == "machine.write_file",
                ToolConfirmation.status == ConfirmationStatus.PENDING,
            )
        )
    ).all()
    if started_by == "typed":
        assert target.read_text() == after
        assert "event: tool_confirmation" not in response.text and not pending
    else:
        assert target.read_text() == before
        assert "event: tool_confirmation" in response.text and len(pending) == 1
