"""Turn bookkeeping cannot authorize writes and releases only its own holds."""

import uuid
from unittest.mock import AsyncMock

import pytest
from solus_api.agent.execution_policy import BuildExecutionPolicy
from solus_api.agent.modes import ActionMode, build_mode_dispatch
from solus_api.agent.runtime import build_dispatch
from solus_api.agent.tools.shapes import ToolCall, ToolResult
from test_build_execution_policy import tool_fixture


@pytest.mark.parametrize(
    "mode,trusted,expected",
    [(ActionMode.GUIDE, True, 0), (ActionMode.DO, False, 0), (ActionMode.DO, True, 1)],
)
async def test_start_bookkeeping_only_after_real_policy_admission(mode, trusted, expected):
    _, registry, handler, preview = tool_fixture(trusted=trusted)

    async def started(call):
        assert preview.await_count == 2
        assert handler.await_count == 0

    start = AsyncMock(side_effect=started)
    policy = BuildExecutionPolicy(registry, mode)
    dispatch = build_mode_dispatch(
        mode,
        registry.list(),
        build_dispatch(registry, None, routine_policy=policy, routine_start=start),
    )
    await dispatch(ToolCall(tool="onshape.create_circle_sketch", args={"n": 1}))
    assert start.await_count == expected
    assert handler.await_count == expected


async def test_failed_hold_does_not_invoke_or_claim_execution():
    _, registry, handler, _ = tool_fixture()
    policy = BuildExecutionPolicy(registry, ActionMode.DO)
    dispatch = build_dispatch(
        registry,
        None,
        routine_policy=policy,
        routine_start=AsyncMock(side_effect=RuntimeError("private")),
    )
    result = await dispatch(ToolCall(tool="onshape.create_circle_sketch", args={"n": 1}))
    assert not result.ok and not result.error.retryable
    assert "private" not in result.error.message
    assert handler.await_count == 0 and not policy.executed_calls


async def test_cancelled_hold_never_invokes_or_claims_execution():
    import asyncio

    _, registry, handler, _ = tool_fixture()
    policy = BuildExecutionPolicy(registry, ActionMode.DO)
    dispatch = build_dispatch(
        registry,
        None,
        routine_policy=policy,
        routine_start=AsyncMock(side_effect=asyncio.CancelledError),
    )
    with pytest.raises(asyncio.CancelledError):
        await dispatch(ToolCall(tool="onshape.create_circle_sketch", args={"n": 1}))
    assert handler.await_count == 0 and not policy.executed_calls


async def test_two_writes_share_turn_owner_and_release_source_once(monkeypatch):
    from solus_api.agent.onshape_turn_sync import OnshapeTurnSync

    source = uuid.uuid4()
    hold = AsyncMock(return_value=source)
    release = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr("solus_api.services.onshape_write_sync.hold_onshape_write_sync", hold)
    monkeypatch.setattr("solus_api.services.onshape_write_sync.release_onshape_write_sync", release)
    coordinator = OnshapeTurnSync(
        None, project_id=uuid.uuid4(), team_id=uuid.uuid4(), store=None, enqueue=AsyncMock()
    )
    first = ToolCall(tool="onshape.create_circle_sketch", args={}, call_id="first")
    second = ToolCall(tool="onshape.create_circle_sketch", args={}, call_id="second")
    await coordinator.start(first)
    await coordinator.start(second)
    result = coordinator.outcome(first, ToolResult.success("first", {"changed": True}))
    assert result.value["graph_sync"]["status"] == "deferred"
    assert hold.call_args_list[0].kwargs["turn_id"] == hold.call_args_list[1].kwargs["turn_id"]
    assert (
        hold.call_args_list[0].kwargs["turn_deadline"]
        == hold.call_args_list[1].kwargs["turn_deadline"]
    )
    await coordinator.flush()
    await coordinator.flush()
    assert release.await_count == 1


@pytest.mark.parametrize("ending", ["normal", "error", "timeout", "cancel", "close"])
async def test_stream_termination_flushes_once_after_closing_runner(monkeypatch, ending):
    import asyncio
    from types import SimpleNamespace

    from solus_api.agent.stream import AgentEvent
    from solus_api.routers.sol import _run_and_persist

    events = []

    class Runner:
        async def run(self, ctx):
            try:
                yield AgentEvent.message("observed")
                if ending == "error":
                    raise RuntimeError("fixture")
                if ending == "timeout":
                    raise TimeoutError
                if ending == "cancel":
                    raise asyncio.CancelledError
            finally:
                events.append("closed")

    async def flush():
        events.append("flushed")

    monkeypatch.setattr("solus_api.routers.sol._persist_turn", AsyncMock(return_value=uuid.uuid4()))
    stream = _run_and_persist(
        runner=Runner(),
        ctx=SimpleNamespace(action_mode=ActionMode.DO),
        sessionmaker=None,
        conversation_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        sol_mode="guide",
        action_mode="do",
        parked=[],
        turn_sync=SimpleNamespace(flush=flush),
    )
    await anext(stream)
    if ending == "close":
        await stream.aclose()
    elif ending == "cancel":
        with pytest.raises(asyncio.CancelledError):
            _ = [item async for item in stream]
    else:
        _ = [item async for item in stream]
    assert events == ["closed", "flushed"]


async def test_fallback_enqueue_survives_caller_cancellation_and_runs_once(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from solus_api.agent.onshape_turn_sync import _FALLBACK_TASKS, create_turn_sync

    ready, release = asyncio.Event(), asyncio.Event()
    runs = []

    async def background():
        runs.append(True)
        ready.set()
        await release.wait()

    async def enqueue(session, ctx, source, request, tasks, settings, response):
        tasks.add_task(background)
        return uuid.uuid4()

    monkeypatch.setattr("solus_api.routers.sources.enqueue_sync", enqueue)
    scope = SimpleNamespace(
        project=SimpleNamespace(id=uuid.uuid4()), team=SimpleNamespace(id=uuid.uuid4())
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    settings = SimpleNamespace(model_copy=lambda **kwargs: None)
    coordinator = create_turn_sync(request, settings, scope, None)

    async def caller():
        await coordinator.enqueue(None, None)
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await caller()
    await asyncio.wait_for(ready.wait(), 1)
    assert len(runs) == 1 and len(_FALLBACK_TASKS) == 1
    task = next(iter(_FALLBACK_TASKS))
    release.set()
    await task
    await asyncio.sleep(0)
    assert not _FALLBACK_TASKS
