"""SOLUSDEV-321 P1-T3 — a turn runs inside server-owned ceilings, and stops with a frame.

`TurnLimits` (agent/turn_limits.py) is what a turn may spend and `TurnBudget`
(agent/turn_budget.py) what it has spent. The runner notes each unit, asks `check()` once a
round, and a hit becomes a `budget_reached` frame followed by the closing round with no tools —
never a silent end. The runner tests drive the real gateway on scripted adapters, so every count
here is of calls that really started.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import pytest
from fastapi import FastAPI
from fixtures.fake_arm import seed_fake_arm
from fixtures.screenshot import screenshot_block
from httpx import AsyncClient
from solus_api.agent import runtime
from solus_api.agent.context import Context, build_context
from solus_api.agent.deterministic_facts import GraphFactSources
from solus_api.agent.feeds import DbSolSystems
from solus_api.agent.layers import ContextSection
from solus_api.agent.modes import ActionMode
from solus_api.agent.prompt import DATA_CAP, TOOL_RESULT_CAP, tools_text
from solus_api.agent.reason import UUID_RE
from solus_api.agent.runtime import AgentRunContext, LlmRunner, build_dispatch
from solus_api.agent.sol_anchors import ResolvedAnchors
from solus_api.agent.stream import AgentEvent, AgentEventType
from solus_api.agent.tools import InProcessTool, ToolDescriptor, ToolRegistry
from solus_api.agent.turn_budget import BudgetHit, TurnBudget
from solus_api.agent.turn_limits import FIXED_PROMPT_TOKENS, TurnLimits, turn_limits
from solus_api.models import ConversationTurn, DataEvent, Domain, GraphEntity, TurnRole, User
from solus_api.orchestration import gateway
from solus_api.orchestration.enums import Complexity
from solus_api.orchestration.providers import ToolConversation, ToolUse, Usage
from solus_api.orchestration.type_estimator import estimate_tokens
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from test_deterministic import _NO_MODEL, _arm, _maker, _plumbing
from test_sol import _create_conversation, _parse_sse
from test_sol import _project as _api_project
from test_sol_reasoner import _ctx, _ScriptedModel, _spy
from test_sol_runtime import _factory, _seed_entity
from test_sol_turn_limits import _RepeatingModel


class _RecordedBudget(TurnBudget):
    """A TurnBudget that also remembers what each round noted (the counter itself is replaced
    every round)."""

    def __init__(self, limits: TurnLimits) -> None:
        super().__init__(limits)
        self.noted: list[int] = []

    def note_input_tokens(self, n: int) -> None:
        self.noted.append(n)
        super().note_input_tokens(n)


@pytest.fixture
def budgets(monkeypatch: pytest.MonkeyPatch) -> list[_RecordedBudget]:
    """Every TurnBudget the runner builds, in order."""
    made: list[_RecordedBudget] = []

    def build(limits: TurnLimits) -> _RecordedBudget:
        made.append(budget := _RecordedBudget(limits))
        return budget

    monkeypatch.setattr(runtime, "TurnBudget", build)
    return made


def _adapters(model: Any) -> dict[str, Any]:
    return {name: model for name in ("anthropic", "openai", "google")}


async def _events(model: Any, ctx: AgentRunContext) -> list[AgentEvent]:
    return [event async for event in LlmRunner(adapters=_adapters(model)).run(ctx)]


def _fixed_tokens(sent: ToolConversation) -> int:
    """The fixed part of a request, estimated here from the very system prompt and tool specs
    the model received — what the runner measures once per turn and sizes its cap from."""
    estimator = gateway.default_orchestration_config().type_estimator
    return estimate_tokens(sent.system, config=estimator) + estimate_tokens(
        tools_text(sent.tools), config=estimator
    )


# --------------------------------------------------------------------------- the limits


@pytest.mark.parametrize("tier", [None, *Complexity])
def test_guide_build_rounds_tools_timeouts_unchanged(tier: Complexity | None) -> None:
    """The three ceilings a turn has always had do not move with the tier, and the model-call
    cap is the round cap plus room for the planner's tie-break and a screen read."""
    guide, build = turn_limits(ActionMode.GUIDE, tier), turn_limits(ActionMode.DO, tier)
    assert (guide.model_rounds, guide.tool_calls, guide.timeout_seconds) == (5, 8, 120.0)
    assert (build.model_rounds, build.tool_calls, build.timeout_seconds) == (16, 24, 300.0)
    assert (guide.max_model_calls, build.max_model_calls) == (6, 18)
    assert (runtime.MAX_MODEL_ROUNDS, runtime.MAX_TOOL_CALLS) == (5, 8)


@pytest.mark.parametrize("mode", list(ActionMode))
def test_a_call_without_a_tier_is_the_standard_tier(mode: ActionMode) -> None:
    assert turn_limits(mode) == turn_limits(mode, Complexity.STANDARD)


@pytest.mark.parametrize("tier", ["fast", "hard", 3, object()])
def test_an_unknown_tier_is_refused(tier: Any) -> None:
    with pytest.raises(ValueError):
        turn_limits(ActionMode.GUIDE, tier)


@pytest.mark.parametrize("mode", list(ActionMode))
@pytest.mark.parametrize(
    ("tier", "caps"),
    [
        (None, (1, 2)),
        # A trivial turn gets the standard pair; whether it may spend it is P1-T5's gate.
        (Complexity.TRIVIAL, (1, 2)),
        (Complexity.STANDARD, (1, 2)),
        (Complexity.HARD, (3, 4)),
    ],
)
def test_web_caps_per_tier(
    mode: ActionMode, tier: Complexity | None, caps: tuple[int, int]
) -> None:
    limits = turn_limits(mode, tier)
    assert (limits.web_searches, limits.web_fetches) == caps


@pytest.mark.parametrize("mode", list(ActionMode))
@pytest.mark.parametrize("tier", list(Complexity))
def test_input_tokens_cap_is_per_round_budget_plus_headroom(
    mode: ActionMode, tier: Complexity
) -> None:
    """The cap on one round's whole request is the tier's context budget plus a headroom: the
    fixed system prompt and tool specs, and room for one default-size tool result (the
    4,000-character cap, 1,000 tokens) per tool call the mode allows. The counter is the
    round's alone."""
    config = gateway.default_orchestration_config()
    one_result = estimate_tokens("x" * TOOL_RESULT_CAP, config=config.type_estimator)
    limits = turn_limits(mode, tier)
    headroom = FIXED_PROMPT_TOKENS + limits.tool_calls * one_result
    assert (one_result, headroom) == (
        1_000,
        {ActionMode.GUIDE: 21_000, ActionMode.DO: 37_000}[mode],
    )
    assert limits.max_input_tokens == config.context_budget.total_for(tier) + headroom

    budget = TurnBudget(limits)
    budget.note_input_tokens(limits.max_input_tokens)  # exactly the cap still fits
    assert budget.check() is None
    budget.note_input_tokens(limits.max_input_tokens + 1)
    assert budget.check() == BudgetHit(
        "input_tokens", limits.max_input_tokens + 1, limits.max_input_tokens
    )
    budget.note_input_tokens(1)  # the next, smaller round replaces it; rounds never add up
    assert budget.check() is None


# ----------------------------------------------------------------------------- the counters


def test_a_fresh_budget_has_spent_nothing_and_hit_nothing() -> None:
    budget = TurnBudget(turn_limits(ActionMode.GUIDE))
    assert budget.check() is None
    spent = (budget.model_rounds, budget.tool_calls, budget.model_calls)
    assert spent + (budget.web_searches, budget.web_fetches, budget.input_tokens) == (0,) * 6


def test_an_allowance_is_a_hit_once_it_is_spent() -> None:
    """Tool calls, model calls and rounds are the runner's own to refuse: the allowance spent
    is the hit, `used` equal to `cap`."""
    limits = turn_limits(ActionMode.GUIDE)

    budget = TurnBudget(limits)
    budget.note_tool_calls(limits.tool_calls - 1)
    assert budget.check() is None
    budget.note_tool_calls(1)
    assert budget.check() == BudgetHit("tool_calls", 8, 8)

    budget = TurnBudget(limits)
    for _ in range(limits.max_model_calls - 1):
        budget.note_model_call()
    assert budget.check() is None
    budget.note_model_call()
    assert budget.check() == BudgetHit("model_calls", 6, 6)

    budget = TurnBudget(limits)
    for _ in range(limits.model_rounds - 1):
        budget.note_model_round()
    assert budget.check() is None
    budget.note_model_round()
    assert budget.check() == BudgetHit("model_rounds", 5, 5)


def test_web_calls_hit_only_past_their_cap() -> None:
    """The research tool meters its own searches and fetches, so spending the whole allowance
    is not a hit; only a call past it is."""
    limits = turn_limits(ActionMode.GUIDE, Complexity.HARD)
    budget = TurnBudget(limits)
    budget.note_web(searches=limits.web_searches, fetches=limits.web_fetches)
    assert budget.check() is None
    budget.note_web(fetches=1)
    assert budget.check() == BudgetHit("web_fetches", 5, 4)

    budget = TurnBudget(limits)
    budget.note_web(searches=limits.web_searches + 1)
    assert budget.check() == BudgetHit("web_searches", 4, 3)


def test_check_names_one_ceiling_in_a_fixed_order() -> None:
    limits = turn_limits(ActionMode.GUIDE)

    def hit(*, tools: bool = False, tokens: bool = False, rounds: bool = False) -> str | None:
        budget = TurnBudget(limits)
        budget.note_tool_calls(limits.tool_calls if tools else 0)
        budget.note_input_tokens(limits.max_input_tokens + 1 if tokens else 0)
        for _ in range(limits.model_rounds if rounds else 0):
            budget.note_model_round()
        found = budget.check()
        return found.limit if found else None

    assert hit(tools=True, tokens=True, rounds=True) == "tool_calls"
    assert hit(tokens=True, rounds=True) == "input_tokens"
    assert hit(rounds=True) == "model_rounds"
    assert hit() is None


# ----------------------------------------------------------------------------- the runner


@pytest.mark.parametrize(
    ("override", "limit", "rounds_before", "cap"),
    [
        ({}, "model_rounds", 4, 5),
        # The call about to be made counts against its own cap, so the cap-th call IS the
        # closing round: two calls in all, never three.
        ({"max_model_calls": 2}, "model_calls", 1, 2),
        ({"max_input_tokens": 1}, "input_tokens", 0, 1),
        ({"tool_calls": 1}, "tool_calls", 1, 1),
    ],
)
async def test_a_reached_ceiling_is_announced_before_the_closing_round(
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    override: dict[str, Any],
    limit: str,
    rounds_before: int,
    cap: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every ceiling the runner can hit ends the turn the same way: ONE `budget_reached` frame
    (and one log line naming the turn, with ids and counts only), then a closing round with
    `tool_choice="none"`, then the final message — never an error and never a silent stop, and
    the token ceiling is no refusal. Every round, the closing one included, carries the turn's
    id."""
    real = turn_limits
    monkeypatch.setattr(
        runtime,
        "turn_limits",
        lambda mode, tier=None, **measured: replace(real(mode, tier, **measured), **override),
    )
    calls = _spy(monkeypatch)
    model = _RepeatingModel()
    ctx = await _ctx(engine, "Inspect this assembly")

    events: list[Any] = []
    seen_at_frame: list[int] = []
    with caplog.at_level(logging.INFO, logger="solus.agent.runtime"):
        async for event in LlmRunner(adapters=_adapters(model)).run(ctx):
            if event.type is AgentEventType.BUDGET_REACHED:
                seen_at_frame.append(len(model.seen))
            events.append(event)

    (frame,) = [e for e in events if e.type is AgentEventType.BUDGET_REACHED]
    assert (frame.data["limit"], frame.data["cap"]) == (limit, cap)
    assert frame.data["used"] >= cap
    assert [r.getMessage() for r in caplog.records if "turn budget reached" in r.getMessage()] == [
        f"turn budget reached limit={limit} used={frame.data['used']} cap={cap} "
        f"turn_id={ctx.turn_id} user_id={ctx.user_id} project_id={ctx.project_id}"
    ]
    assert seen_at_frame == [rounds_before]  # the closing round had not been asked yet
    assert len(model.seen) == rounds_before + 1
    assert model.seen[-1].tool_choice == "none"
    assert events[-1].type is AgentEventType.MESSAGE
    assert AgentEventType.ERROR not in {e.type for e in events}
    assert [(c["purpose"], c["turn_id"]) for c in calls] == [("answer", ctx.turn_id)] * len(calls)
    assert len(calls) == rounds_before + 1


async def test_each_round_notes_the_whole_request_it_is_about_to_send(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, budgets: list[_RecordedBudget]
) -> None:
    """Per round and before the call: the fixed part of the request — the system prompt and the
    tool specs, measured once — plus `estimate_tokens` of the flattened turns, the measure the
    gateway routes on. The fixed part is the very `system` and `tools` every round sends, not a
    second rendering."""
    queries: list[str] = []
    real = gateway.stream

    def spy(query: str, **kwargs: Any) -> Any:
        queries.append(query)
        return real(query, **kwargs)

    monkeypatch.setattr(gateway, "stream", spy)
    model = _RepeatingModel()
    await _events(model, await _ctx(engine, "Inspect this assembly"))

    (budget,) = budgets
    estimator = gateway.default_orchestration_config().type_estimator
    sent = model.seen[0]
    fixed = _fixed_tokens(sent)
    assert len(queries) == 5
    assert all(c.system == sent.system and c.tools == sent.tools for c in model.seen)
    assert budget.noted == [fixed + estimate_tokens(query, config=estimator) for query in queries]


async def test_the_runner_resolves_the_tier_before_it_counts(
    engine: AsyncEngine, budgets: list[_RecordedBudget]
) -> None:
    """The budget is built at the tier the turn routes at, from the fixed part the turn sends
    (a Build turn's system prompt is longer than a Guide turn's, so the two caps differ by more
    than the tool allowance)."""
    guide_model, build_model = _RepeatingModel(), _RepeatingModel()
    await _events(guide_model, await _ctx(engine, "hi"))
    await _events(build_model, await _ctx(engine, "hi", action_mode=ActionMode.DO))
    guide, build = budgets
    assert guide.limits == turn_limits(
        ActionMode.GUIDE, Complexity.TRIVIAL, fixed_tokens=_fixed_tokens(guide_model.seen[0])
    )
    assert build.limits == turn_limits(
        ActionMode.DO, Complexity.TRIVIAL, fixed_tokens=_fixed_tokens(build_model.seen[0])
    )


class _ThreeKindsOfCall:
    """The planner's tie-break (no conversation, no pixels) picks the first id it was offered;
    the screen read (pixels) reads; each answer round (a conversation) asks for a tool while
    `tool_rounds` last and is prose from then on — and always on the closing round."""

    def __init__(self, tool_rounds: int = 0) -> None:
        self.tool_rounds = tool_rounds
        self.answers: list[Any] = []

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Any = None,
        conversation: Any = None,
        **_: Any,
    ) -> Any:
        if conversation is not None:
            self.answers.append(conversation)
            if conversation.tool_choice != "none" and len(self.answers) <= self.tool_rounds:
                yield ToolUse(
                    id=f"call_{len(self.answers)}", name="onshape_get_variables", args={"d": "x"}
                )
            else:
                yield "A bracket on a two-axis arm."
        elif images:
            yield "An Onshape window showing a bracket."
        else:
            yield UUID_RE.findall(query.split("kind=planner_candidates", 1)[1])[0]
        yield Usage(tokens_in=5, tokens_out=2)


async def _hard_turn_with_a_screenshot(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AgentRunContext:
    """A Guide turn that runs HARD (a finding's turn) over two entities tied for "servo 3", with
    a screenshot attached: the planner's tie-break and the screen read both come before round 1."""
    maker = _factory(engine)
    async with maker() as db:
        project_id, _ = await _seed_entity(db)
        db.add_all(
            GraphEntity(
                project_id=project_id, kind="component", domain=Domain.ELECTRICAL, name="servo 3"
            )
            for _ in range(2)
        )
        await db.commit()

    async def about_a_finding(*_: Any, **__: Any) -> ResolvedAnchors:
        return ResolvedAnchors(finding_subjects=(uuid.uuid4(),))  # a finding's turn runs HARD

    monkeypatch.setattr(runtime, "resolve_anchor_inputs", about_a_finding)
    return replace(
        await _ctx(engine, "why is servo 3 hot?", screenshot=screenshot_block()),
        project_id=project_id,
    )


async def test_model_calls_count_every_gateway_call_with_turn_id(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, budgets: list[_RecordedBudget]
) -> None:
    """A HARD turn with a screenshot makes three gateway calls — the planner's tie-break, the
    screen extractor and the answer — and the budget has counted all three, not just the rounds.
    All three carry the turn's id: the runner hands `read_screen` (agent/screen.py) its
    `turn_id`, so the screen read's ledger row names the turn too (M188)."""
    ctx = await _hard_turn_with_a_screenshot(engine, monkeypatch)
    calls = _spy(monkeypatch)  # `complete` drains `stream`, so all three land here

    model = _ThreeKindsOfCall()

    events = await _events(model, ctx)

    assert [c["purpose"] for c in calls] == ["planner", "vision", "answer"]
    (budget,) = budgets
    assert budget.model_calls == len(calls) == 3
    assert budget.limits == turn_limits(
        ctx.action_mode, Complexity.HARD, fixed_tokens=_fixed_tokens(model.answers[0])
    )
    assert [c["turn_id"] for c in calls] == [ctx.turn_id] * 3
    assert events[-1].type is AgentEventType.MESSAGE
    assert AgentEventType.BUDGET_REACHED not in {e.type for e in events}


async def test_the_model_call_cap_is_exact_with_a_planner_call_and_a_screen_read(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, budgets: list[_RecordedBudget]
) -> None:
    """Guide + HARD + a screenshot: the planner's tie-break and the screen read are calls 1 and
    2, rounds 1-3 are calls 3-5, and round 4 — the 6th call, the last the cap allows — is the
    closing round. Six gateway calls in all, never seven."""
    ctx = await _hard_turn_with_a_screenshot(engine, monkeypatch)
    calls = _spy(monkeypatch)
    model = _ThreeKindsOfCall(tool_rounds=99)

    events = await _events(model, ctx)

    (budget,) = budgets
    assert [c["purpose"] for c in calls] == ["planner", "vision", *["answer"] * 4]
    assert budget.model_calls == len(calls) == budget.limits.max_model_calls == 6
    assert [e.data for e in events if e.type is AgentEventType.BUDGET_REACHED] == [
        {"limit": "model_calls", "used": 6, "cap": 6}
    ]
    assert [c.tool_choice for c in model.answers] == ["auto", "auto", "auto", "none"]
    assert events[-1].type is AgentEventType.MESSAGE


async def test_tools_on_round_one_and_a_natural_answer_on_round_two_send_no_frame(
    engine: AsyncEngine,
) -> None:
    """Using a tool is not reaching a ceiling: a turn that calls one tool and then answers by
    itself streams no frame, and neither of its two rounds is a closing round."""
    model = _ScriptedModel(tool_round=True)

    events = await _events(model, await _ctx(engine, "check the variables"))

    kinds = {e.type for e in events}
    assert AgentEventType.TOOL_CALL in kinds and AgentEventType.BUDGET_REACHED not in kinds
    assert events[-1].type is AgentEventType.MESSAGE
    assert [c.tool_choice for c in model.seen] == ["auto", "auto"]


async def test_a_first_tier_answer_spends_nothing_and_announces_no_ceiling(
    engine: AsyncEngine, budgets: list[_RecordedBudget]
) -> None:
    """P1-T2's first tier returns before any model round: no tool, no gateway call, no round —
    every counter stays at zero and no ceiling is announced."""
    maker = _maker(engine)
    project_id, _ = await _arm(maker)
    plumbing = _plumbing(maker)
    ctx = await _ctx(engine, "what is the stall current of servo 3?")
    assert ctx.user_id is not None
    turn = replace(
        ctx,
        project_id=project_id,
        systems=DbSolSystems(maker, plumbing),
        facts=GraphFactSources(maker, project_id, ctx.user_id, telemetry=plumbing),
    )

    events = [e async for e in LlmRunner(adapters=_NO_MODEL).run(turn)]

    assert AgentEventType.ANSWER_SOURCE in {e.type for e in events}
    assert AgentEventType.BUDGET_REACHED not in {e.type for e in events}
    (budget,) = budgets
    counters = (budget.model_rounds, budget.tool_calls, budget.model_calls, budget.input_tokens)
    assert counters + (budget.web_searches, budget.web_fetches) == (0,) * 6
    assert budget.check() is None


def _blob_tool(name: str, *, size: int, result_cap: int | None = None) -> InProcessTool:
    """A read-only tool whose value is `size` characters, held to `result_cap` (None: the
    prompt's default 4,000) by the prompt layer."""

    async def read(args: dict[str, Any]) -> dict[str, Any]:
        return {"blob": "b" * size}

    descriptor = ToolDescriptor(
        name=name,
        description="Reads a blob.",
        params={"type": "object", "properties": {"n": {"type": "integer"}}},
        returns={"type": "object"},
        result_cap=result_cap,
    )
    return InProcessTool(descriptor, read)


def _pad_tool(chars: int) -> InProcessTool:
    """A tool never called, whose `chars`-long description pads the specs: 36,000 characters is
    about the weight of the 47 in-process tools (9,000 tokens), so a request weighs what a
    production one does; more is a bigger inventory (bridge and hosted tools)."""

    async def read(args: dict[str, Any]) -> dict[str, Any]:
        return {}

    descriptor = ToolDescriptor(
        name="pad_spec",
        description="A long description. " * (chars // 20),
        params={"type": "object"},
        returns={"type": "object"},
    )
    return InProcessTool(descriptor, read)


async def _build_turn(engine: AsyncEngine, *tools: InProcessTool) -> AgentRunContext:
    """A Build turn at the STANDARD tier whose only tools are `tools`."""
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    ctx = await _ctx(engine, "check the variables", action_mode=ActionMode.DO)
    return replace(ctx, tools=tuple(registry.list()), dispatch=build_dispatch(registry, None))


class _BlobCalls:
    """`per_round` calls to `tool` every round until the closing round, which answers."""

    def __init__(self, tool: str, per_round: int) -> None:
        self.tool = tool
        self.per_round = per_round
        self.seen: list[Any] = []

    async def stream(
        self, model_name: str, query: str, *, max_tokens: int, conversation: Any = None, **_: Any
    ) -> Any:
        self.seen.append(conversation)
        if conversation.tool_choice == "none":
            yield "Here is what I read."
        else:
            for index in range(self.per_round):
                yield ToolUse(
                    id=f"call_{len(self.seen)}_{index}", name=self.tool, args={"n": index}
                )
        yield Usage(tokens_in=5, tokens_out=2)


@pytest.mark.parametrize("pad_chars", [36_000, 100_000])
async def test_a_build_turn_with_24_default_cap_results_reaches_tool_calls_not_input_tokens(
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    budgets: list[_RecordedBudget],
    pad_chars: int,
) -> None:
    """The cap leaves room for the whole tool allowance at the default result size, whatever the
    tool inventory: a Build turn at the STANDARD tier, its context half packed (12,000 of 24,000
    tokens), reads 24 results of 4,000 characters (1,000 tokens each) — and what ends it is
    `tool_calls`. The tool specs are padded to about production weight (36,000 characters) and to
    well past it (100,000, some 25,000 tokens): the runner builds its cap from the fixed part the
    turn really sends, so the cap floats with the inventory — `budget.limits` is `turn_limits`
    with that measured part, `24,000 + fixed + 24,000`. The largest request it sent is under the
    cap too, so `check()`'s order is not what hid an `input_tokens` hit."""
    real = build_context

    async def half_packed(*args: Any, **kwargs: Any) -> Context:
        context = await real(*args, **kwargs)
        filler = ContextSection(kind="corpus", text="c" * DATA_CAP, tokens=2_000, score=0.5)
        return context.model_copy(update={"sections": (*context.sections, *[filler] * 6)})

    monkeypatch.setattr(runtime, "build_context", half_packed)
    ctx = await _build_turn(engine, _blob_tool("read_blob", size=6_000), _pad_tool(pad_chars))
    model = _BlobCalls("read_blob", per_round=3)

    events = await _events(model, ctx)

    (budget,) = budgets
    fixed = _fixed_tokens(model.seen[0])
    assert fixed > pad_chars // 4  # the padding really is in the request
    assert budget.limits == turn_limits(ActionMode.DO, Complexity.STANDARD, fixed_tokens=fixed)
    assert budget.limits.max_input_tokens == 24_000 + fixed + 24_000
    assert sum(e.type is AgentEventType.TOOL_RESULT for e in events) == 24
    assert [e.data for e in events if e.type is AgentEventType.BUDGET_REACHED] == [
        {"limit": "tool_calls", "used": 24, "cap": 24}
    ]
    assert {len(o.content) for o in model.seen[-1].messages[-2].tool_results} == {TOOL_RESULT_CAP}
    assert max(budget.noted) < budget.limits.max_input_tokens
    assert events[-1].type is AgentEventType.MESSAGE


async def test_large_result_tools_make_input_tokens_the_binding_ceiling(
    engine: AsyncEngine, budgets: list[_RecordedBudget]
) -> None:
    """A tool that raises its own result cap (24,000 characters, 6,000 tokens a read — what
    `read_code_file` does) fills the room faster than the tool allowance does: the turn ends on
    `input_tokens`, well short of 24 calls, with a closing answer from what it read — never an
    error. The cap is deliberately not sized for such tools."""
    ctx = await _build_turn(engine, _blob_tool("read_big", size=30_000, result_cap=24_000))

    events = await _events(_BlobCalls("read_big", per_round=1), ctx)

    (budget,) = budgets
    (frame,) = [e.data for e in events if e.type is AgentEventType.BUDGET_REACHED]
    assert frame["limit"] == "input_tokens"
    assert frame["used"] > frame["cap"] == budget.limits.max_input_tokens
    assert 0 < sum(e.type is AgentEventType.TOOL_RESULT for e in events) < 24
    assert events[-1].type is AgentEventType.MESSAGE
    assert AgentEventType.ERROR not in {e.type for e in events}


class _TwentyFiveCalls:
    """Round 1 asks for 25 tool calls at once; the closing round (no tools) answers."""

    def __init__(self) -> None:
        self.seen: list[Any] = []

    async def stream(
        self, model_name: str, query: str, *, max_tokens: int, conversation: Any = None, **_: Any
    ) -> Any:
        self.seen.append(conversation)
        if len(self.seen) == 1:
            for index in range(25):
                yield ToolUse(
                    id=f"call_{index}", name="get_entity", args={"entity_id": str(uuid.uuid4())}
                )
        else:
            yield "I used every tool call I was allowed."
        yield Usage(tokens_in=5, tokens_out=2)


async def _post_twenty_five_calls(
    app: FastAPI, client: AsyncClient, headers: dict[str, str], db: AsyncSession
) -> tuple[_TwentyFiveCalls, dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    """A Build turn through the real route whose model asks for 25 tool calls at once. The user
    has consented to data collection, so the turn's events are stored."""
    model = _TwentyFiveCalls()
    app.state.agent_runner = LlmRunner(adapters=_adapters(model))
    _, project = await _api_project(client, headers)
    await db.execute(update(User).values(data_collection_consent=True))
    await db.commit()
    conversation = await _create_conversation(client, headers, project["id"])
    reply = await client.post(
        f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/messages",
        json={"content": "go", "action_mode": "do"},
        headers=headers,
    )
    assert reply.status_code == 200, reply.text
    return model, conversation, _parse_sse(reply.text)


async def _assistant_turn(db: AsyncSession, conversation: dict[str, Any]) -> ConversationTurn:
    turns = (
        await db.scalars(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == uuid.UUID(conversation["id"]))
            .order_by(ConversationTurn.created_at)
        )
    ).all()
    (assistant,) = [turn for turn in turns if turn.role is TurnRole.ASSISTANT]
    return assistant


async def _completed_event(db: AsyncSession) -> DataEvent:
    rows = await db.scalars(select(DataEvent).where(DataEvent.event_type == "sol.turn.completed"))
    (event,) = rows.all()
    return event


async def test_build_turn_past_24_tool_calls_stops_on_tool_calls_with_budget_frame(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """P1 acceptance, through the route: a Build turn whose model asks for a 25th tool call
    runs 24, announces `tool_calls` (used 24 of 24) before its closing round, and answers. The
    transport's own `loop_limit` guard never fires — the runner stopped first — and the stored
    assistant turn is a clean one."""
    model, conversation, events = await _post_twenty_five_calls(app, client, alice_headers, db)

    kinds = [kind for kind, _ in events]
    assert kinds.count("tool_call") == kinds.count("tool_result") == 24
    assert "error" not in kinds
    assert [data for kind, data in events if kind == "budget_reached"] == [
        {"limit": "tool_calls", "used": 24, "cap": 24}
    ]
    last_result = len(kinds) - 1 - kinds[::-1].index("tool_result")
    assert last_result < kinds.index("budget_reached") < kinds.index("message")
    assert kinds[-2:] == ["message", "done"]
    # The model was asked twice: the 25 calls, then the closing round with no tools — and it
    # was told the 25th was not executed.
    assert [c.tool_choice for c in model.seen] == ["auto", "none"]
    assert len(model.seen[-1].messages[-2].tool_results) == 25

    assistant = await _assistant_turn(db, conversation)
    assert assistant.attrs["tool_calls"] == 24 and assistant.attrs["aborted"] is None
    assert assistant.content == "I used every tool call I was allowed."


async def test_a_budget_hit_is_stored_on_the_turn_and_sent_in_its_completed_event(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """CLAUDE.md §7: budget events reach the data collection system. The route stores the hit
    on the assistant turn (`attrs.budget_reached`), and the consent-gated `sol.turn.completed`
    event carries it beside `answer_source` (none here) — ids, counts and fixed names only."""
    _, conversation, _ = await _post_twenty_five_calls(app, client, alice_headers, db)

    hit = {"limit": "tool_calls", "used": 24, "cap": 24}
    assert (await _assistant_turn(db, conversation)).attrs["budget_reached"] == hit
    assert (await _completed_event(db)).payload == {
        "conversation_id": conversation["id"],
        "tool_calls": 24,
        "aborted": None,
        "answer_source": None,
        "budget_reached": hit,
    }


async def test_a_first_tier_turns_completed_event_carries_its_answer_source(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """The same event for a turn the first tier answered: `answer_source` is `graph`, and no
    budget was reached, so neither the turn's attrs nor the event name one."""
    _, project = await _api_project(client, alice_headers)
    await seed_fake_arm(db, uuid.UUID(project["id"]), user_id=None)
    await db.execute(update(User).values(data_collection_consent=True))
    await db.commit()
    app.state.agent_runner = LlmRunner(adapters=_NO_MODEL)
    conversation = await _create_conversation(client, alice_headers, project["id"])

    reply = await client.post(
        f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/messages",
        json={"content": "what is the stall current of servo 3?"},
        headers=alice_headers,
    )

    assert reply.status_code == 200, reply.text
    assistant = await _assistant_turn(db, conversation)
    assert assistant.attrs["answer_source"] == "graph" and "budget_reached" not in assistant.attrs
    assert (await _completed_event(db)).payload == {
        "conversation_id": conversation["id"],
        "tool_calls": 0,
        "aborted": None,
        "answer_source": "graph",
        "budget_reached": None,
    }


class _BothEnvelopes:
    """A runner that streams a first-tier envelope and then a budget frame. No real runner does
    both, so the route's fold is exercised on its own."""

    async def run(self, ctx: Any) -> AsyncIterator[AgentEvent]:
        yield AgentEvent.answer_source("graph", sources=("config",), citations=("[config:x]",))
        yield AgentEvent.budget_reached("model_rounds", 5, 5)
        yield AgentEvent.message("done")


async def test_the_route_keeps_every_envelope_a_turn_streams(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """The fold merges frames into the turn's attrs rather than replacing them: a later frame
    never erases an earlier one's."""
    app.state.agent_runner = _BothEnvelopes()
    _, project = await _api_project(client, alice_headers)
    conversation = await _create_conversation(client, alice_headers, project["id"])

    reply = await client.post(
        f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/messages",
        json={"content": "go"},
        headers=alice_headers,
    )

    assert reply.status_code == 200, reply.text
    attrs = (await _assistant_turn(db, conversation)).attrs
    assert attrs["answer_source"] == "graph" and attrs["citations"] == ["[config:x]"]
    assert attrs["budget_reached"] == {"limit": "model_rounds", "used": 5, "cap": 5}


_RESEARCH_FRAME: dict[str, Any] = {
    "call_id": "c1",
    "question": "OV9281 supply",
    "cached": False,
    "searches": 1,
    "pages": 2,
    "sources": [{"url": "https://docs.example.com/ov9281", "title": "OV9281", "fetched": True}],
}


class _ResearchFrames:
    """A runner that streams a turn's research sources, as the research step does."""

    async def run(self, ctx: Any) -> AsyncIterator[AgentEvent]:
        yield AgentEvent.research_sources(**_RESEARCH_FRAME)
        yield AgentEvent.message("done")


async def test_the_route_stores_a_turns_research_sources_and_leaves_its_completed_event_alone(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """SOLUSDEV-321 P1-T5: the `research_sources` frame reaches the client and is stored on the
    assistant turn (`attrs.research_sources`), so a reload shows the same pills. The consent-gated
    `sol.turn.completed` payload keeps its five keys: web calls are counted from the ledger."""
    app.state.agent_runner = _ResearchFrames()
    _, project = await _api_project(client, alice_headers)
    await db.execute(update(User).values(data_collection_consent=True))
    await db.commit()
    conversation = await _create_conversation(client, alice_headers, project["id"])

    reply = await client.post(
        f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/messages",
        json={"content": "go"},
        headers=alice_headers,
    )

    assert reply.status_code == 200, reply.text
    streamed = [data for kind, data in _parse_sse(reply.text) if kind == "research_sources"]
    assert streamed == [_RESEARCH_FRAME]
    assert (await _assistant_turn(db, conversation)).attrs["research_sources"] == _RESEARCH_FRAME
    assert set((await _completed_event(db)).payload) == {
        "conversation_id",
        "tool_calls",
        "aborted",
        "answer_source",
        "budget_reached",
    }
