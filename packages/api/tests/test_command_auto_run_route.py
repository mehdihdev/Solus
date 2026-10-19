"""SOLUSDEV-317 §10.1 end to end: an auto-run `code.exec` through the real
message route (no ToolConfirmation row, `sol.command.completed` with
`auto: true`) and through the real LLM runner (the SSE tool_result carries the
desktop's command fields; the model reads the outcome in the same turn)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fixtures.fake_systems import FakeSolSystems
from solus_api.agent.execution_policy import BuildExecutionPolicy
from solus_api.agent.modes import ActionMode
from solus_api.agent.runtime import AgentRunContext, build_dispatch
from solus_api.agent.stream import AgentEvent, AgentEventType
from solus_api.agent.tools.shapes import ToolCall
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.orchestration.providers import ToolUse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from test_command_auto_run import _LS, _registry, _system_plan
from test_command_gate import _Machine

_RESULT = {
    "ok": True,
    "argv": ["/bin/ls", "-la"],
    "cwd": ".",
    "exit_code": 0,
    "stdout_tail": "README.md\n",
    "stderr_tail": "",
    "timed_out": False,
    "duration_ms": 12,
    "sandbox": "sandbox-exec",
    "git_metadata_changed": False,
}


class _ExecRunner:
    def __init__(self, argv: list[str]) -> None:
        self.argv = argv

    async def run(self, ctx: Any) -> Any:
        call = ToolCall(tool="code.exec", args={"argv": self.argv})
        yield AgentEvent.tool_call(call)
        result = await ctx.dispatch(call)
        yield AgentEvent.tool_result(result)
        yield AgentEvent.message("done" if result.ok else "waiting")


@pytest.mark.parametrize(
    ("argv", "auto"), [(_LS, True), (["rm", "-rf", "build"], False)], ids=["no-risk", "risky"]
)
async def test_the_message_route_auto_runs_only_a_no_risk_exec(
    app: Any,
    client: Any,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: Any,
    argv: list[str],
    auto: bool,
) -> None:
    from solus_api.deps import get_sol_registry
    from solus_api.models import DataEvent, ToolConfirmation, User
    from test_sol import _create_conversation, _project

    _, project = await _project(client, alice_headers)
    conversation = await _create_conversation(client, alice_headers, project["id"])
    user = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    user.data_collection_consent = True
    await db.commit()
    plan_argv = ["/bin/ls", "-la"] if auto else ["/bin/rm", "-rf", "build"]
    machine = _Machine(_system_plan(plan_argv), dict(_RESULT, argv=plan_argv))
    app.state.agent_runner = _ExecRunner(argv)
    app.dependency_overrides[get_sol_registry] = lambda: _registry(machine)
    url = f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/messages"
    body = {"content": "list the folder", "action_mode": "do"}

    # Cross-team isolation is unaffected: Bob cannot reach Alice's project at all.
    assert (await client.post(url, headers=bob_headers, json=body)).status_code == 404
    assert machine.executed == [] and machine.plans == []

    response = await client.post(url, headers=alice_headers, json=body)
    assert response.status_code == 200, response.text
    assert ("event: tool_confirmation" in response.text) is not auto
    assert len(machine.executed) == int(auto)
    assert len(list(await db.scalars(select(ToolConfirmation)))) == int(not auto)
    completed = [
        row.payload
        for row in await db.scalars(
            select(DataEvent).where(DataEvent.event_type == "sol.command.completed")
        )
    ]
    if auto:
        assert completed == [
            {
                "tool": "code.exec",
                "program": "ls",
                "exit_code": 0,
                "timed_out": False,
                "duration_ms": 12,
                "sandbox": "sandbox-exec",
                "git_metadata_changed": False,
                "auto": True,
            }
        ]
        executed = list(
            await db.scalars(
                select(DataEvent).where(DataEvent.event_type == "sol.build_action_executed")
            )
        )
        assert [row.payload["tool"] for row in executed] == ["code.exec"]
    else:
        assert completed == []


# ------------------------------------------------------------- the real runner


async def test_the_runner_streams_the_command_fields_and_feeds_the_outcome_back(
    engine: AsyncEngine,
) -> None:
    from test_sol_red_team import _CompliantModel, _funded_user, _runner

    machine = _Machine(
        _system_plan(), dict(_RESULT, exit_code=3, stdout_tail="boom\n", stderr_tail="bad\n")
    )
    registry = _registry(machine)
    policy = BuildExecutionPolicy(registry, ActionMode.DO)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    ctx = AgentRunContext(
        prompt="list the folder",
        tools=tuple(registry.list()),
        dispatch=build_dispatch(registry, None, routine_policy=policy),
        executed_build_calls=policy.executed_calls,
        action_mode=ActionMode.DO,
        project_id=uuid.uuid4(),
        user_id=await _funded_user(maker),
        sessionmaker=maker,
        secret_store=InMemorySecretStore(),
        systems=FakeSolSystems(),
    )
    model = _CompliantModel((ToolUse(id="t1", name="code.exec", args={"argv": _LS}),), ())

    events = [event async for event in _runner(model).run(ctx)]

    assert machine.executed == [{"argv": _LS}]
    result = next(e for e in events if e.type is AgentEventType.TOOL_RESULT)
    assert {k: result.data[k] for k in ("tool", "auto", "program", "status")} == {
        "tool": "code.exec",
        "auto": True,
        "program": "ls",
        "status": "exited 3",
    }
    assert result.data["stdout_tail"] == "boom\n"
    assert result.data["stderr_tail"] == "bad\n"
    assert result.data["call_id"] == "t1" and result.data["ok"] is True
    second = model.seen[1]
    fed = [r.content for turn in second.messages for r in turn.tool_results]
    assert any("ran automatically in Build" in text and "exited 3" in text for text in fed)
    assert all("stdout_tail" not in text for text in fed)


async def test_a_parked_exec_result_carries_no_command_fields(engine: AsyncEngine) -> None:
    from test_sol_red_team import _CompliantModel, _funded_user, _runner

    machine = _Machine(_system_plan(["/bin/rm", "-rf", "build"]))
    registry = _registry(machine)
    policy = BuildExecutionPolicy(registry, ActionMode.DO)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    ctx = AgentRunContext(
        prompt="clean",
        tools=tuple(registry.list()),
        dispatch=build_dispatch(registry, None, routine_policy=policy),
        executed_build_calls=policy.executed_calls,
        action_mode=ActionMode.DO,
        project_id=uuid.uuid4(),
        user_id=await _funded_user(maker),
        sessionmaker=maker,
        secret_store=InMemorySecretStore(),
        systems=FakeSolSystems(),
    )
    use = ToolUse(id="t1", name="code.exec", args={"argv": ["rm", "-rf", "build"]})
    model = _CompliantModel((use,), ())

    events = [event async for event in _runner(model).run(ctx)]

    result = next(e for e in events if e.type is AgentEventType.TOOL_RESULT)
    assert result.data["ok"] is False and "auto" not in result.data
    assert machine.executed == []
