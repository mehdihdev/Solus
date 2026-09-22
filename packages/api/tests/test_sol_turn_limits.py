"""Server-owned action-mode ceilings and independent transport enforcement."""

from typing import Any

import pytest
from solus_api.agent.modes import ActionMode
from solus_api.agent.stream import AgentEventType
from solus_api.orchestration.providers import ToolUse, Usage
from test_sol_reasoner import _ctx, _run


@pytest.mark.parametrize(
    "mode,expected", [(ActionMode.GUIDE, (5, 8, 120)), (ActionMode.DO, (16, 24, 300))]
)
def test_server_owned_limits(mode: ActionMode, expected: tuple[int, int, int]) -> None:
    from solus_api.agent.turn_limits import turn_limits

    limits = turn_limits(mode)
    assert (limits.model_rounds, limits.tool_calls, limits.timeout_seconds) == expected


@pytest.mark.parametrize("value", ["do", "build", {"model_rounds": 999}, None])
def test_unvalidated_inputs_cannot_select_build_limits(value: Any) -> None:
    from solus_api.agent.turn_limits import turn_limits

    with pytest.raises(ValueError):
        turn_limits(value)


def test_request_cannot_supply_numeric_limits() -> None:
    from pydantic import ValidationError
    from solus_api.routers.sol import MessageCreate

    with pytest.raises(ValidationError):
        MessageCreate.model_validate({"content": "go", "action_mode": "do", "model_rounds": 999})


class _RepeatingModel:
    def __init__(self, batch: int = 1) -> None:
        self.seen: list[Any] = []
        self.batch = batch

    async def stream(self, *args: Any, conversation: Any, **kwargs: Any) -> Any:
        self.seen.append(conversation)
        for index in range(self.batch):
            yield ToolUse(
                id=f"call_{len(self.seen)}_{index}", name="onshape__get_variables", args={"d": "x"}
            )
        yield Usage(tokens_in=5, tokens_out=2)


@pytest.mark.parametrize("consumer_close", [False, True])
async def test_cancellation_closes_runner_and_persists_completed_work(
    monkeypatch: Any, consumer_close: bool
) -> None:
    import asyncio
    import uuid
    from types import SimpleNamespace

    from solus_api.agent.stream import AgentEvent
    from solus_api.agent.tools.shapes import ToolCall, ToolResult
    from solus_api.routers.sol import _run_and_persist

    persisted: list[Any] = []
    closed: list[bool] = []

    async def persist(**kwargs: Any) -> Any:
        persisted.append(kwargs)
        return uuid.uuid4()

    class Runner:
        async def run(self, ctx: Any) -> Any:
            try:
                yield AgentEvent.tool_call(ToolCall(tool="get_entity", args={}, call_id="done"))
                yield AgentEvent.tool_result(ToolResult.success("done", {"observed": True}))
                raise asyncio.CancelledError
            finally:
                closed.append(True)

    monkeypatch.setattr("solus_api.routers.sol._persist_turn", persist)
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
    )
    if consumer_close:
        assert "tool_call" in await anext(stream)
        assert "tool_result" in await anext(stream)
        await stream.aclose()
    else:
        with pytest.raises(asyncio.CancelledError):
            _ = [event async for event in stream]
    assert closed == [True]
    assert len(persisted) == 1
    assert len(persisted[0]["tool_turns"]) == 1
    assert persisted[0]["aborted"] == "cancelled"


async def test_stalled_runner_cleanup_is_bounded() -> None:
    import asyncio

    from solus_api.routers.sol import _close_runner

    async def stalled() -> Any:
        try:
            yield None
        finally:
            await asyncio.Event().wait()

    stream = stalled()
    await anext(stream)
    await asyncio.wait_for(_close_runner(stream), timeout=6)


async def test_timeout_does_not_wait_for_stalled_generator_finally() -> None:
    import asyncio

    from solus_api.routers.sol import _bounded_events

    release = asyncio.Event()

    async def stalled() -> Any:
        try:
            await asyncio.Event().wait()
            yield None
        finally:
            await release.wait()

    stream = _bounded_events(stalled(), 0.01)
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(anext(stream), timeout=0.5)
    finally:
        release.set()


@pytest.mark.parametrize("mode,rounds", [(ActionMode.GUIDE, 5), (ActionMode.DO, 16)])
async def test_final_round_is_tool_free_and_rogue_requests_never_dispatch(
    engine: Any, mode: ActionMode, rounds: int
) -> None:
    model = _RepeatingModel()
    events = await _run(model, await _ctx(engine, "Inspect this assembly", action_mode=mode))
    assert len(model.seen) == rounds
    assert not model.seen[-1].tools
    assert sum(event.type is AgentEventType.TOOL_CALL for event in events) == rounds - 1


@pytest.mark.parametrize("mode,cap", [(ActionMode.GUIDE, 8), (ActionMode.DO, 24)])
async def test_batched_model_requests_cannot_exceed_tool_cap(
    engine: Any, mode: ActionMode, cap: int
) -> None:
    model = _RepeatingModel(batch=30)
    events = await _run(model, await _ctx(engine, "Inspect this assembly", action_mode=mode))
    assert sum(event.type is AgentEventType.TOOL_CALL for event in events) == cap
    assert len(model.seen) == 2
    assert not model.seen[-1].tools
    assert len(model.seen[-1].messages[-1].tool_results) == 30
