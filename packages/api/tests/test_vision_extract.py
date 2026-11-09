"""SOLUSDEV-321 P5 (R103, R125) — `agent/vision/vision_extract.py`: one read of one render.

One VISUAL_LOG `gateway.complete` per render, as the requesting person (`user_id`, `session`,
`redis`) and attributed to the SOL turn it runs in (`turn_id`); the call is noted on the turn's own
budget, so it counts against `max_model_calls`, and it never spends the closing round's call.
Outside a turn nothing is called. Every failure is honest text, never an exception.
"""

from __future__ import annotations

import io
import logging
import uuid
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from fixtures.fake_systems import FakeSolSystems
from PIL import Image
from solus_api.agent import runtime
from solus_api.agent.modes import ActionMode
from solus_api.agent.runtime import AgentRunContext, LlmRunner, build_dispatch
from solus_api.agent.tools import InProcessTool, ToolDescriptor, ToolRegistry
from solus_api.agent.turn_budget import TurnBudget
from solus_api.agent.turn_context import PerceptionTurn, bind_perception, bind_turn_id
from solus_api.agent.turn_limits import turn_limits
from solus_api.agent.vision.vision_extract import (
    EXTRACT_MAX_TOKENS,
    MAX_READ_CHARS,
    VISION_UNAVAILABLE,
    RenderRead,
    vision_extract,
)
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.orchestration import gateway
from solus_api.orchestration.enums import Complexity, RouteType
from solus_api.orchestration.providers import ImageBlock, ToolUse, Usage
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from test_sol_reasoner import _funded_user

READ = "A front view of the fake arm: the base below, servo 2 above it, labelled."


def _render_png(width: int = 64, height: int = 48) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (240, 240, 240)).save(out, format="PNG")
    return out.getvalue()


def _turn_budget(max_model_calls: int) -> TurnBudget:
    return TurnBudget(replace(turn_limits(ActionMode.GUIDE), max_model_calls=max_model_calls))


def _refuse_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def never(query: str, **kwargs: Any) -> Any:
        raise AssertionError("no model call may run here")

    monkeypatch.setattr(gateway, "complete", never)


class _ReadsTheRender:
    """Round 1 proposes the probe; the probe's vision call (pixels, no conversation) is read; round
    2 answers."""

    def __init__(self) -> None:
        self.rounds = 0

    async def stream(self, model_name: str, query: str, **kw: Any) -> Any:
        if kw.get("images"):
            yield READ
        elif kw.get("conversation") is not None:
            self.rounds += 1
            if self.rounds == 1:
                yield ToolUse(id="tu_look", name="look", args={})
            else:
                yield "It is labelled."
        else:
            yield "unused"
        yield Usage(tokens_in=5, tokens_out=2)


async def test_counted_against_turn_budget(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inside a real turn: the tool's one vision read carries the turn's id and `purpose: vision`,
    and the turn's own budget counts it beside the two rounds — three calls, three counted."""
    budgets: list[TurnBudget] = []

    class _Recorded(TurnBudget):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            budgets.append(self)

    monkeypatch.setattr(runtime, "TurnBudget", _Recorded)
    calls: list[dict[str, Any]] = []
    real = gateway.stream

    def spy(query: str, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return real(query, **kwargs)

    monkeypatch.setattr(gateway, "stream", spy)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user_id = await _funded_user(maker)
    model = _ReadsTheRender()
    adapters: dict[str, Any] = {name: model for name in ("anthropic", "openai", "google")}
    reads: list[RenderRead] = []

    async def look(args: dict[str, Any]) -> dict[str, Any]:
        async with maker() as session:
            reads.append(
                await vision_extract(
                    _render_png(),
                    secret_store=InMemorySecretStore(),
                    user_id=user_id,
                    session=session,
                    adapters=adapters,
                )
            )
        return {"read": reads[-1].text}

    registry = ToolRegistry()
    registry.register(
        InProcessTool(
            ToolDescriptor(
                name="look",
                description="Read one render.",
                params={"type": "object", "properties": {}, "additionalProperties": False},
                returns={"type": "object"},
            ),
            look,
        )
    )
    ctx = AgentRunContext(
        prompt="what does the arm look like from the front?",
        tools=tuple(registry.list()),
        dispatch=build_dispatch(registry, None),
        systems=FakeSolSystems(),
        project_id=uuid.uuid4(),
        user_id=user_id,
        sessionmaker=maker,
        secret_store=InMemorySecretStore(),
    )

    [event async for event in LlmRunner(adapters=adapters).run(ctx)]

    assert reads == [RenderRead(READ, True)]
    assert [(c["purpose"], c["turn_id"]) for c in calls] == [
        ("answer", ctx.turn_id),
        ("vision", ctx.turn_id),
        ("answer", ctx.turn_id),
    ]
    (budget,) = budgets
    assert budget.model_calls == len(calls) == 3


async def test_one_read_as_the_requester_in_its_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one call: VISUAL_LOG at the standard tier, the render as its only image, the person's
    identity and the turn's id. The reply is model output: control characters go, and it is
    capped."""
    seen: list[dict[str, Any]] = []
    reply = "A side view\x07 of the arm.\x00" + "x" * (MAX_READ_CHARS + 50)

    async def complete(query: str, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return SimpleNamespace(text=reply)

    monkeypatch.setattr(gateway, "complete", complete)
    png, user_id, session, redis = _render_png(), uuid.uuid4(), object(), object()
    budget, turn_id, project_id = _turn_budget(6), uuid.uuid4(), uuid.uuid4()
    budget.note_model_call()

    with bind_turn_id(turn_id, project_id), bind_perception(PerceptionTurn(budget)):
        read = await vision_extract(
            png,
            secret_store=InMemorySecretStore(),
            user_id=user_id,
            session=session,  # type: ignore[arg-type]  # passed through, never used here
            redis=redis,
        )

    (call,) = seen
    assert call["type"] is RouteType.VISUAL_LOG and call["complexity"] is Complexity.STANDARD
    assert call["purpose"] == "vision" and call["turn_id"] == turn_id
    assert call["project_id"] == project_id  # the turn's project, bound beside its id (R148)
    assert (call["user_id"], call["session"], call["redis"]) == (user_id, session, redis)
    assert call["images"] == [ImageBlock(media_type="image/png", data=png)]
    assert call["max_tokens"] == EXTRACT_MAX_TOKENS
    assert read.read is True and len(read.text) == MAX_READ_CHARS
    assert read.text.startswith("A side view  of the arm.")
    assert budget.model_calls == 2


async def test_the_closing_rounds_call_and_a_turnless_call_are_never_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _refuse_calls(monkeypatch)
    secrets = InMemorySecretStore()

    outside = await vision_extract(
        _render_png(),
        secret_store=secrets,
        user_id=uuid.uuid4(),
        session=object(),  # type: ignore[arg-type]
    )
    assert outside.read is False and "only inside a SOL turn" in outside.text

    budget = _turn_budget(3)
    budget.note_model_call()
    budget.note_model_call()  # the next call would be the closing round's
    with bind_turn_id(uuid.uuid4()), bind_perception(PerceptionTurn(budget)):
        spent = await vision_extract(
            _render_png(),
            secret_store=secrets,
            user_id=uuid.uuid4(),
            session=object(),  # type: ignore[arg-type]
        )
    assert spent.read is False and "budget is spent" in spent.text
    assert budget.model_calls == 2


async def test_a_failed_read_is_honest_and_never_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A provider failure is the honest unavailable text. Its message can quote the request body
    (the pixels), so only the error's class is logged."""

    async def broken(query: str, **kwargs: Any) -> Any:
        raise RuntimeError("provider echoed iVBORw0KGgo the request")

    monkeypatch.setattr(gateway, "complete", broken)
    with (
        caplog.at_level(logging.WARNING, logger="solus.agent.vision"),
        bind_turn_id(uuid.uuid4()),
        bind_perception(PerceptionTurn(_turn_budget(6))),
    ):
        read = await vision_extract(
            _render_png(),
            secret_store=InMemorySecretStore(),
            user_id=uuid.uuid4(),
            session=object(),  # type: ignore[arg-type]
        )

    assert read == RenderRead(VISION_UNAVAILABLE, False)
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "RuntimeError" in logged and "iVBOR" not in logged
