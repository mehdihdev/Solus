"""A model refusal on a SOL turn (SOLUSDEV-319, approved in-chat 2026-11-09).

Live, `claude-fable-5-1` (the standard CODE cell) refused a benign "does the Makefile selftest
pass?" turn with `stop_reason: refusal`; the runtime turned that into a silent, billed, empty
answer. Now: a refusal in round 1, before anything reached the person, re-routes that round once
to the GENERAL cell of the same tier; any other refusal ends the turn with `model_refused`. A
refused call is never debited.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

import pytest
from solus_api.agent.runtime import AgentRunContext, LlmRunner
from solus_api.agent.stream import AgentEventType
from solus_api.models import CreditLedger
from solus_api.orchestration.enums import RouteType
from solus_api.orchestration.providers import ProviderRefusalError, ToolUse, Usage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine
from test_sol_reasoner import _CODE_FILE, _CodeScopeSystems, _ctx, _spy

ANSWER = "make selftest fails at 180 degrees."


class _RefusingModel:
    """Plays every provider. `refuse` lists the 1-based calls that refuse; `stream_first` makes a
    refusing call stream a token before it refuses; `tool_on` is the call that is a tool round."""

    def __init__(
        self, refuse: set[int], *, stream_first: bool = False, tool_on: int | None = None
    ) -> None:
        self.refuse = refuse
        self.stream_first = stream_first
        self.tool_on = tool_on
        self.calls = 0

    async def stream(self, *args: Any, conversation: Any = None, **kwargs: Any) -> Any:
        self.calls += 1
        if self.calls in self.refuse:
            if self.stream_first:
                yield "Partial "
            raise ProviderRefusalError("anthropic/claude-x refused the request", category="cyber")
        if self.calls == self.tool_on:
            yield ToolUse(id="tu_1", name="onshape__get_variables", args={"d": "x"})
            yield Usage(tokens_in=5, tokens_out=2)
            return
        yield ANSWER
        yield Usage(tokens_in=5, tokens_out=2)


async def _code_ctx(engine: AsyncEngine) -> AgentRunContext:
    ctx = await _ctx(engine, "does the selftest pass?", mentions=(_CODE_FILE,))
    return replace(ctx, systems=_CodeScopeSystems())


async def _collect(model: _RefusingModel, ctx: AgentRunContext) -> list[Any]:
    adapters = {name: model for name in ("anthropic", "openai", "google")}
    return [event async for event in LlmRunner(adapters=adapters).run(ctx)]


def _text(events: list[Any]) -> str:
    """The assistant's final message text."""
    messages = [event for event in events if event.type is AgentEventType.MESSAGE]
    return str(messages[-1].data.get("content", "")) if messages else ""


async def _ledger_rows(engine: AsyncEngine, user_id: uuid.UUID | None) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async with async_sessionmaker(engine)() as db:
        count = await db.scalar(
            select(func.count()).select_from(CreditLedger).where(CreditLedger.user_id == user_id)
        )
    return int(count or 0)


async def test_a_round_one_refusal_reroutes_once_to_general_and_is_not_debited(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy(monkeypatch)
    ctx = await _code_ctx(engine)
    before = await _ledger_rows(engine, ctx.user_id)

    events = await _collect(_RefusingModel({1}), ctx)

    assert [call["type"] for call in calls] == [RouteType.CODE, RouteType.GENERAL]
    assert ANSWER in _text(events)
    assert not any(event.type is AgentEventType.ERROR for event in events)
    # Only the answering call is debited; the refused one is not.
    assert await _ledger_rows(engine, ctx.user_id) == before + 1


async def test_the_fallback_is_pinned_for_the_rest_of_the_turn(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After the re-route, later rounds stay on the GENERAL choice (replay items are bound to the
    model that produced them)."""
    calls = _spy(monkeypatch)
    ctx = await _code_ctx(engine)

    # Call 1 refuses, call 2 (the fallback) is a tool round, call 3 answers.
    events = await _collect(_RefusingModel({1}, tool_on=2), ctx)

    assert [call["type"] for call in calls] == [
        RouteType.CODE,
        RouteType.GENERAL,
        RouteType.GENERAL,
    ]
    assert ANSWER in _text(events)


async def test_a_refusal_after_text_reached_the_person_is_not_rerouted(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy(monkeypatch)
    ctx = await _code_ctx(engine)

    with pytest.raises(ProviderRefusalError):
        await _collect(_RefusingModel({1}, stream_first=True), ctx)

    assert len(calls) == 1


async def test_a_refusal_in_a_later_round_is_not_rerouted(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy(monkeypatch)
    ctx = await _code_ctx(engine)

    with pytest.raises(ProviderRefusalError):
        await _collect(_RefusingModel({2}, tool_on=1), ctx)

    assert len(calls) == 2
    assert calls[1]["type"] is RouteType.CODE  # still pinned to round 1's choice


async def test_the_fallback_is_tried_only_once(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy(monkeypatch)
    ctx = await _code_ctx(engine)
    before = await _ledger_rows(engine, ctx.user_id)

    with pytest.raises(ProviderRefusalError):
        await _collect(_RefusingModel({1, 2}), ctx)

    assert [call["type"] for call in calls] == [RouteType.CODE, RouteType.GENERAL]
    assert await _ledger_rows(engine, ctx.user_id) == before


async def test_a_refusal_already_on_the_general_route_is_not_retried(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy(monkeypatch)
    ctx = await _ctx(engine, "what is I2C")

    with pytest.raises(ProviderRefusalError):
        await _collect(_RefusingModel({1}), ctx)

    assert len(calls) == 1


def test_a_refusal_becomes_a_model_refused_frame_without_provider_text() -> None:
    from solus_api.routers.sol import _turn_failure_sse

    exc = ProviderRefusalError("anthropic/claude-x refused the request", category="cyber")
    frame = _turn_failure_sse(exc, uuid.uuid4())

    assert "model_refused" in frame
    assert "The model declined to answer this. Try rephrasing." in frame
    assert "claude-x" not in frame and "cyber" not in frame


async def test_the_fallback_keeps_the_refused_calls_tier(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus_api.orchestration.enums import Complexity

    calls = _spy(monkeypatch)
    ctx = await _code_ctx(engine)

    await _collect(_RefusingModel({1}), ctx)

    assert isinstance(calls[1]["complexity"], Complexity)  # pinned explicitly, not re-estimated


async def test_a_refusal_after_only_the_budget_frame_reroutes_and_announces_once(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A one-round turn is its own closing round, so `budget_reached` precedes the model's
    output. That frame is not the model's text: the round still re-routes, and the frame is not
    announced twice."""
    from solus_api.agent import runtime
    from solus_api.agent.turn_limits import turn_limits

    def one_round(*args: Any, **kwargs: Any) -> Any:
        return replace(turn_limits(*args, **kwargs), model_rounds=1)

    monkeypatch.setattr(runtime, "turn_limits", one_round)
    calls = _spy(monkeypatch)
    ctx = await _code_ctx(engine)

    events = await _collect(_RefusingModel({1}), ctx)

    assert [call["type"] for call in calls] == [RouteType.CODE, RouteType.GENERAL]
    assert sum(event.type is AgentEventType.BUDGET_REACHED for event in events) == 1
    assert ANSWER in _text(events)
