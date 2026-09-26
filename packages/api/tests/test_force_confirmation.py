"""A review-only Build request cannot authorize a routine file write."""

import pytest
from pydantic import ValidationError
from solus_api.agent.execution_policy import register_owned_routine
from solus_api.agent.stream import AgentEvent
from solus_api.agent.tools.machine_writes import build_machine_write_tool
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall
from solus_api.deps import get_sol_registry
from solus_api.models import ToolConfirmation
from solus_api.routers.sol import MessageCreate
from sqlalchemy import select
from test_machine_writes import Native
from test_sol import _create_conversation, _project


@pytest.mark.parametrize("invalid", ["true", "false", 1, 0, None])
def test_force_confirmation_requires_a_real_boolean(invalid):
    with pytest.raises(ValidationError):
        MessageCreate(content="Review this edit", force_confirmation=invalid)


def test_force_confirmation_defaults_off():
    assert MessageCreate(content="Normal Build request").force_confirmation is False


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_review_only_build_parks_owned_machine_write_until_explicit_decision(
    app, client, alice_headers, bob_headers, db, tmp_path, decision
):
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
        async def run(self, ctx):
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
