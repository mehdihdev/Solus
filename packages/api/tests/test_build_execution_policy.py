"""Build authorization is explicit, narrow, fresh, and consumed exactly once."""

import asyncio
from contextvars import ContextVar
from unittest.mock import AsyncMock

import pytest
from solus_api.agent.execution_policy import BuildExecutionPolicy, register_owned_routine
from solus_api.agent.modes import ActionMode, build_mode_dispatch
from solus_api.agent.runtime import build_dispatch
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.connectors.onshape_confirmation import ConfirmedOnshapeTool

ROWS = [{"label": "depth", "before": "1 mm", "after": "2 mm"}]


def test_model_guidance_distinguishes_build_execution_from_manual_intervention():
    from solus_api.agent.prompt import system_prompt
    from solus_api.models import SolMode

    build = system_prompt(SolMode.GUIDE, action_mode=ActionMode.DO)
    guide = system_prompt(SolMode.EXPERT, action_mode=ActionMode.GUIDE)
    assert "Current action mode: Build" in build
    assert "routine" in build and "automatically" in build
    assert "Current action mode: Guide" in guide
    assert "never execute changes" in guide
    assert "do not run when you call them" not in build


def test_real_onshape_factory_attests_only_bound_reviewed_operations():
    from uuid import uuid4

    from solus_api.agent.runtime import build_sol_registry
    from solus_api.connectors.registry import ConnectorRegistry
    from solus_api.connectors.secrets import InMemorySecretStore
    from sqlalchemy.ext.asyncio import async_sessionmaker

    registry = build_sol_registry(
        async_sessionmaker(),
        uuid4(),
        secret_store=InMemorySecretStore(),
        connectors=ConnectorRegistry(),
    )
    routines = {
        tool.descriptor.name for tool in registry.tools() if getattr(tool, "_build_authority", None)
    }
    assert "onshape.create_circle_sketch" in routines
    assert "onshape.set_variable" in routines
    assert "onshape.update_feature" in routines
    assert "onshape.insert_part" in routines
    assert "onshape.delete_feature" not in routines
    assert all(
        tool.descriptor.requires_confirmation
        for tool in registry.tools()
        if tool.descriptor.name in routines
    )


def tool_fixture(*, name="onshape.create_circle_sketch", trusted=True, preview=None, handler=None):
    handler = handler or AsyncMock(return_value={"changed": True})
    preview = preview or AsyncMock(return_value=ROWS)
    tool = ConfirmedOnshapeTool(
        ToolDescriptor(
            name=name,
            description="Reviewed edit",
            requires_confirmation=True,
            params={
                "type": "object",
                "properties": {"n": {"type": "integer"}},
                "required": ["n"],
                "additionalProperties": False,
            },
            returns={"type": "object"},
            files_errors=True,
        ),
        handler,
        preview,
    )
    if trusted:
        register_owned_routine(tool, family="onshape")
    registry = ToolRegistry()
    registry.register(tool)
    return tool, registry, handler, preview


def dispatch_fixture(registry, mode=ActionMode.DO):
    policy = BuildExecutionPolicy(registry, mode)
    dispatch = build_mode_dispatch(
        mode, registry.list(), build_dispatch(registry, None, routine_policy=policy)
    )
    return policy, dispatch


async def test_build_previews_in_same_task_executes_once_without_parking():
    observed = ContextVar("test_observation", default=None)

    async def preview(args):
        observed.set(args["n"])
        return ROWS

    async def handler(args):
        assert observed.get() == args["n"]
        return {"changed": True}

    _, registry, _, _ = tool_fixture(preview=preview, handler=handler)
    policy, dispatch = dispatch_fixture(registry)
    first = ToolCall(tool="onshape.create_circle_sketch", args={"n": 1})
    assert (await dispatch(first)).ok
    assert first.call_id in policy.executed_calls
    repeated = await dispatch(ToolCall(tool=first.tool, args=first.args))
    assert not repeated.ok and not repeated.error.retryable
    assert len(policy.executed_calls) == 1


@pytest.mark.parametrize("mode", [ActionMode.GUIDE, ActionMode.DO])
async def test_guide_and_unclassified_writes_never_auto_execute(mode):
    _, registry, handler, preview = tool_fixture(trusted=mode is ActionMode.GUIDE)
    _, dispatch = dispatch_fixture(registry, mode)
    result = await dispatch(ToolCall(tool="onshape.create_circle_sketch", args={"n": 1}))
    assert not result.ok
    handler.assert_not_called()
    preview.assert_not_called()


async def test_name_and_advertised_trust_flags_cannot_grant_routine_permission():
    trusted, _, _, _ = tool_fixture()
    fake = InProcessTool(
        trusted.descriptor, AsyncMock(return_value={}), AsyncMock(return_value=ROWS)
    )
    fake.requires_complete_preview = True
    fake.build_routine = True
    register_owned_routine(fake, family="onshape")
    registry = ToolRegistry()
    registry.register(fake)
    _, dispatch = dispatch_fixture(registry)
    assert not (await dispatch(ToolCall(tool=fake.descriptor.name, args={"n": 1}))).ok
    fake._handler.assert_not_called()


@pytest.mark.parametrize(
    "name",
    ["onshape.delete_feature", "code.git_push", "code.install", "code.run", "hardware.flash"],
)
async def test_dangerous_and_unknown_tools_remain_manual(name):
    _, registry, handler, preview = tool_fixture(name=name)
    _, dispatch = dispatch_fixture(registry)
    assert not (await dispatch(ToolCall(tool=name, args={"n": 1}))).ok
    handler.assert_not_called()
    preview.assert_not_called()


@pytest.mark.parametrize(
    "rows", [[], [{"label": "fake"}], [{"label": "x", "before": None, "after": "x" * 501}]]
)
async def test_missing_or_incomplete_preview_refuses(rows):
    _, registry, handler, _ = tool_fixture(preview=AsyncMock(return_value=rows))
    policy, dispatch = dispatch_fixture(registry)
    result = await dispatch(ToolCall(tool="onshape.create_circle_sketch", args={"n": 1}))
    assert not result.ok and not result.error.retryable
    handler.assert_not_called()
    assert not policy.executed_calls


async def test_invalid_args_and_changed_preview_never_write():
    preview = AsyncMock(side_effect=[ROWS, [{"label": "depth", "before": "3 mm", "after": "2 mm"}]])
    _, registry, handler, _ = tool_fixture(preview=preview)
    _, dispatch = dispatch_fixture(registry)
    bad = await dispatch(ToolCall(tool="onshape.create_circle_sketch", args={"n": "1"}))
    assert bad.error.code is ToolErrorCode.INVALID_ARGS
    preview.assert_not_called()
    assert not (await dispatch(ToolCall(tool="onshape.create_circle_sketch", args={"n": 1}))).ok
    handler.assert_not_called()


async def test_parallel_duplicate_and_cancel_cannot_replay_execution():
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(args):
        started.set()
        await release.wait()
        return {}

    _, registry, _, _ = tool_fixture(handler=handler)
    policy, dispatch = dispatch_fixture(registry)
    call = ToolCall(tool="onshape.create_circle_sketch", args={"n": 1})
    pending = asyncio.create_task(dispatch(call))
    await asyncio.wait_for(started.wait(), 1)
    assert not (await dispatch(call)).ok
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not (await dispatch(call)).ok
    assert len(policy.executed_calls) == 1


async def test_uncertain_failure_is_observable_and_not_retryable():
    handler = AsyncMock(side_effect=ToolException("Mutation may have applied", retryable=True))
    _, registry, _, _ = tool_fixture(handler=handler)
    policy, dispatch = dispatch_fixture(registry)
    call = ToolCall(tool="onshape.create_circle_sketch", args={"n": 1})
    result = await dispatch(call)
    assert not result.ok and not result.error.retryable
    assert call.call_id in policy.executed_calls
    assert not (await dispatch(call)).ok
    assert handler.await_count == 1


@pytest.mark.parametrize(
    "mode,executed,parked", [("do", True, False), ("guide", False, False), ("do", False, True)]
)
async def test_authenticated_route_uses_build_authority_without_fake_confirmation(
    app, client, alice_headers, bob_headers, db, monkeypatch, mode, executed, parked
):
    from solus_api.agent.stream import AgentEvent
    from solus_api.deps import get_sol_registry
    from solus_api.models import DataEvent, ToolConfirmation, User
    from solus_api.routers import sol
    from sqlalchemy import select
    from test_sol import _create_conversation, _project

    _, project = await _project(client, alice_headers)
    conversation = await _create_conversation(client, alice_headers, project["id"])
    user = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    user.data_collection_consent = True
    await db.commit()
    _, registry, handler, _ = tool_fixture(trusted=not parked)

    class Runner:
        async def run(self, ctx):
            call = ToolCall(tool="onshape.create_circle_sketch", args={"n": 1})
            yield AgentEvent.tool_call(call)
            result = await ctx.dispatch(call)
            yield AgentEvent.tool_result(result)
            yield AgentEvent.message("Completed" if result.ok else "Refused")

    app.state.agent_runner = Runner()
    app.dependency_overrides[get_sol_registry] = lambda: registry
    scheduler = AsyncMock(return_value={"status": "queued", "job_id": "test-job"})
    monkeypatch.setattr(sol, "schedule_onshape_write_sync", scheduler)
    from uuid import uuid4

    source_id = uuid4()
    hold = AsyncMock(return_value=source_id)
    release = AsyncMock(return_value={"status": "queued", "job_id": "test-job"})
    monkeypatch.setattr("solus_api.services.onshape_write_sync.hold_onshape_write_sync", hold)
    monkeypatch.setattr("solus_api.services.onshape_write_sync.release_onshape_write_sync", release)
    url = f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/messages"
    response = await client.post(
        url, headers=bob_headers, json={"content": "edit", "action_mode": mode}
    )
    assert response.status_code == 404
    response = await client.post(url, json={"content": "edit", "action_mode": mode})
    assert response.status_code == 401
    response = await client.post(
        url, headers=alice_headers, json={"content": "edit", "action_mode": mode}
    )
    assert response.status_code == 200, response.text
    assert ("event: tool_confirmation" in response.text) is parked
    assert handler.await_count == int(executed)
    assert scheduler.await_count == 0
    assert hold.await_count == release.await_count == int(executed)
    assert len(list(await db.scalars(select(ToolConfirmation)))) == int(parked)
    events = list(
        await db.scalars(
            select(DataEvent).where(DataEvent.event_type == "sol.build_action_executed")
        )
    )
    assert len(events) == int(executed)
    if executed:
        assert events[0].payload["authorization_origin"] == "build_policy"
        assert "args" not in events[0].payload
        assert "graph_sync" in response.text
        assert '"status":"deferred"' in response.text.replace(" ", "")
        assert release.call_args.kwargs["source_id"] == source_id
        assert release.call_args.kwargs["turn_id"] == hold.call_args.kwargs["turn_id"]


async def test_reused_call_identity_and_changed_descriptor_cannot_reauthorize():
    tool, registry, handler, _ = tool_fixture()
    _, dispatch = dispatch_fixture(registry)
    call = ToolCall(tool=tool.descriptor.name, args={"n": 1}, call_id="same-id")
    assert (await dispatch(call)).ok
    assert not (await dispatch(call.model_copy(update={"args": {"n": 2}}))).ok
    assert handler.await_count == 1
    tool._descriptor = tool.descriptor.model_copy(update={"params": {"type": "object"}})
    assert not (await dispatch(ToolCall(tool=call.tool, args={"n": 3}))).ok


@pytest.mark.parametrize("name", ["kicad.add_wire", "kicad.set_symbol_property"])
async def test_bridge_requires_exact_owned_schema_and_concrete_implementation(monkeypatch, name):
    import hashlib
    import json
    from uuid import uuid4

    from solus_api.agent import execution_policy
    from solus_api.bridge.registry import InMemoryBridgeSessionRegistry
    from solus_api.bridge.tool import BridgeTool

    descriptor = tool_fixture()[0].descriptor.model_copy(update={"name": name})
    digest = hashlib.sha256(
        json.dumps(descriptor.params, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    monkeypatch.setitem(execution_policy._BRIDGE_SCHEMAS, descriptor.name, digest)
    tool = BridgeTool(
        descriptor=descriptor,
        sessions=InMemoryBridgeSessionRegistry(),
        user_id=uuid4(),
        team_id=uuid4(),
        project_id=uuid4(),
        call_cap_bytes=65536,
    )
    tool.preview = AsyncMock(return_value=ROWS)
    register_owned_routine(tool, family="bridge")
    registry = ToolRegistry()
    registry.register(tool)
    policy = BuildExecutionPolicy(registry, ActionMode.DO)
    call = ToolCall(tool=descriptor.name, args={"n": 1})
    assert await policy.prepare(call) is True
    widened = BridgeTool(
        descriptor=descriptor.model_copy(update={"params": {"type": "object"}}),
        sessions=InMemoryBridgeSessionRegistry(),
        user_id=uuid4(),
        team_id=uuid4(),
        project_id=uuid4(),
        call_cap_bytes=65536,
    )
    register_owned_routine(widened, family="bridge")
    registry2 = ToolRegistry()
    registry2.register(widened)
    assert await BuildExecutionPolicy(registry2, ActionMode.DO).prepare(call) is False


async def test_nonfinite_arguments_fail_closed_before_preview():
    tool, registry, handler, preview = tool_fixture(trusted=False)
    tool._descriptor = tool.descriptor.model_copy(
        update={
            "params": {
                "type": "object",
                "properties": {"n": {"type": "number"}},
                "required": ["n"],
                "additionalProperties": False,
            }
        }
    )
    register_owned_routine(tool, family="onshape")
    _, dispatch = dispatch_fixture(registry)
    result = await dispatch(ToolCall(tool=tool.descriptor.name, args={"n": float("nan")}))
    assert not result.ok and result.error.code is ToolErrorCode.INVALID_ARGS
    preview.assert_not_called()
    handler.assert_not_called()


async def test_complete_preview_can_have_repeated_labels_and_null_values():
    rows = [
        {"label": "line", "before": None, "after": "new"},
        {"label": "line", "before": "old", "after": "newer"},
    ]
    _, registry, handler, _ = tool_fixture(preview=AsyncMock(return_value=rows))
    _, dispatch = dispatch_fixture(registry)
    assert (await dispatch(ToolCall(tool="onshape.create_circle_sketch", args={"n": 1}))).ok
    assert handler.await_count == 1


async def test_owned_file_wrapper_executes_build_once_with_native_readback(tmp_path):
    from solus_api.agent.runtime import _owned_machine_tool
    from test_machine_writes import Native

    tool = _owned_machine_tool(Native(tmp_path))
    registry = ToolRegistry()
    registry.register(tool)
    _, dispatch = dispatch_fixture(registry)
    result = await dispatch(
        ToolCall(tool="machine.write_file", args={"path": "proof.txt", "content": "verified"})
    )
    assert result.ok
    assert (tmp_path / "proof.txt").read_text() == "verified"
