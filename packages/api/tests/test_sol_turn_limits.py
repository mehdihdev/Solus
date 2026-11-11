"""Server-owned action-mode ceilings and independent transport enforcement."""

from pathlib import Path
from typing import Any, cast

import pytest
from solus_api.agent.modes import ActionMode
from solus_api.agent.stream import AgentEventType
from solus_api.orchestration.providers import ToolUse, Usage
from test_sol_reasoner import _ctx, _run


@pytest.mark.parametrize(
    "mode,expected",
    [
        # model_rounds, tool_calls, timeout_seconds, max_input_tokens (the standard tier's
        # 24,000-token context budget + 15,000 fixed prompt + 1,000 per allowed tool call),
        # max_model_calls, web_searches, web_fetches (SOLUSDEV-321 P1-T3; P5 fix 1, M3;
        # SOLUSDEV-322 P8-T4 and the P10 merge of main).
        (ActionMode.GUIDE, (5, 8, 120, 47_000, 6, 1, 2)),
        (ActionMode.DO, (16, 24, 300, 63_000, 18, 1, 2)),
    ],
)
def test_server_owned_limits(mode: ActionMode, expected: tuple[int, ...]) -> None:
    from dataclasses import astuple

    from solus_api.agent.turn_limits import turn_limits

    assert astuple(turn_limits(mode)) == expected


def test_a_measured_fixed_part_replaces_the_default() -> None:
    """SOLUSDEV-321 P1-T3 F3: the runner measures the system prompt and tool specs it sends and
    passes them in, so the cap follows the real inventory; the default (14,000) is only for a
    caller that has not measured. Nothing but the input cap moves, and there is no floor."""
    from dataclasses import replace

    from solus_api.agent.turn_limits import turn_limits
    from solus_api.orchestration.enums import Complexity

    default = turn_limits(ActionMode.GUIDE, Complexity.STANDARD)
    assert default.max_input_tokens == 24_000 + 15_000 + 8 * 1_000
    big = turn_limits(ActionMode.GUIDE, Complexity.STANDARD, fixed_tokens=20_000)
    assert big.max_input_tokens == 24_000 + 20_000 + 8 * 1_000
    assert big == replace(default, max_input_tokens=big.max_input_tokens)
    none = turn_limits(ActionMode.GUIDE, Complexity.STANDARD, fixed_tokens=0)
    assert none.max_input_tokens == 24_000 + 8_000


def test_the_default_fixed_part_tracks_what_the_runner_measures(tmp_path: Path) -> None:
    """SOLUSDEV-321 P5 fix 1 (M3): the default fixed part is what a caller that has not measured
    is held to. Measured as the runner measures its own turn (`runtime.py`: the system prompt and
    the model-visible tool specs as text, both through the type estimator), over the fully bound
    registry `turn_limits.py` names, it must cover the measurement and stay within 2,000 tokens of
    it: a growing tool inventory cannot leave the default quietly stale."""
    import uuid

    from fixtures.fake_systems import FakeSolSystems
    from solus_api.agent import prompt
    from solus_api.agent.research import model_visible
    from solus_api.agent.runtime import build_sol_registry
    from solus_api.agent.turn_limits import FIXED_PROMPT_TOKENS
    from solus_api.connectors.registry import ConnectorRegistry
    from solus_api.connectors.secrets import InMemorySecretStore
    from solus_api.models import SolMode
    from solus_api.orchestration import gateway
    from solus_api.orchestration.type_estimator import estimate_tokens
    from solus_api.storage import LocalArtifactStore
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async def enqueue(*args: Any, **kwargs: Any) -> None:
        return None

    registry = build_sol_registry(
        async_sessionmaker(),
        uuid.uuid4(),
        user_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        secret_store=InMemorySecretStore(),
        connectors=ConnectorRegistry(),
        systems=FakeSolSystems(),
        artifact_store=LocalArtifactStore(str(tmp_path)),
        enqueue=enqueue,
        presence_service=object(),
        companion_deployment_service=object(),
        scene_enqueue=enqueue,
    )
    nonce = prompt.new_nonce()
    system = prompt.system_prompt(
        SolMode.GUIDE, None, None, with_screenshot=True, action_mode=ActionMode.DO, nonce=nonce
    )
    tools = prompt.tool_specs(model_visible(registry.list()), nonce=nonce)
    estimator = gateway.default_orchestration_config().type_estimator
    measured = estimate_tokens(system, config=estimator) + estimate_tokens(
        prompt.tools_text(tools), config=estimator
    )

    assert measured <= FIXED_PROMPT_TOKENS <= measured + 2_000


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
    # `_run` types its model as the sibling file's `_ScriptedModel`; this fake is duck-typed,
    # so the tests below hold it as `Any`.
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
    from collections.abc import AsyncGenerator
    from types import SimpleNamespace

    from solus_api.agent.runtime import AgentRunContext, AgentRunner
    from solus_api.agent.stream import AgentEvent
    from solus_api.agent.tools.shapes import ToolCall, ToolResult
    from solus_api.routers.sol import _run_and_persist
    from sqlalchemy.ext.asyncio import async_sessionmaker

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
        runner=cast(AgentRunner, Runner()),
        ctx=cast(AgentRunContext, SimpleNamespace(action_mode=ActionMode.DO)),
        sessionmaker=cast(async_sessionmaker[Any], None),
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
        assert isinstance(stream, AsyncGenerator)
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
    model: Any = _RepeatingModel()
    events = await _run(model, await _ctx(engine, "Inspect this assembly", action_mode=mode))
    assert len(model.seen) == rounds
    # SOLUSDEV-321 P0-T4: the tools stay listed (a cache-stable request) and are
    # withheld through tool_choice.
    assert model.seen[-1].tool_choice == "none"
    assert model.seen[-1].tools == model.seen[0].tools
    assert sum(event.type is AgentEventType.TOOL_CALL for event in events) == rounds - 1


@pytest.mark.parametrize("mode,cap", [(ActionMode.GUIDE, 8), (ActionMode.DO, 24)])
async def test_batched_model_requests_cannot_exceed_tool_cap(
    engine: Any, mode: ActionMode, cap: int
) -> None:
    model: Any = _RepeatingModel(batch=30)
    events = await _run(model, await _ctx(engine, "Inspect this assembly", action_mode=mode))
    assert sum(event.type is AgentEventType.TOOL_CALL for event in events) == cap
    assert len(model.seen) == 2
    assert model.seen[-1].tool_choice == "none"
    # The results turn, then the closing synthesis turn.
    assert len(model.seen[-1].messages[-2].tool_results) == 30
