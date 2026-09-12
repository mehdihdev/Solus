"""S1-W3: the SOL runtime's routing — live-message estimator, "think harder",
provider replay items, and the output-token ceiling.

The routing spy wraps the REAL gateway.stream and records what the runner asked
for; a scripted adapter plays the provider so no key is ever needed.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from fixtures.fake_systems import FakeSolSystems
from fixtures.screenshot import screenshot_block
from solus_api.agent import runtime
from solus_api.agent.runtime import SOL_MAX_TOKENS, AgentRunContext, LlmRunner, build_dispatch
from solus_api.agent.stream import AgentEventType
from solus_api.agent.tools import InProcessTool, ToolDescriptor, ToolException, ToolRegistry
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import (
    CreditBalance,
    PlanType,
    Subscription,
    SubscriptionStatus,
    Team,
    User,
)
from solus_api.orchestration import gateway
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.providers import ToolConversation, ToolUse, Usage
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

READ = ToolDescriptor(
    name="onshape.get_variables",
    description="Variables in a Variable Studio.",
    params={"type": "object", "properties": {"d": {"type": "string"}}, "required": ["d"]},
    returns={"type": "object"},
)
REPLAY_ITEMS: tuple[dict[str, Any], ...] = ({"type": "reasoning", "id": "rs_1"},)
_MODEL_NAME = re.compile(r"(claude|gemini)-[\w.-]*\d|gpt-\d")


class _ScriptedModel:
    """Round 1: one tool call + replay items. Round 2: prose."""

    def __init__(self, *, tool_round: bool = False) -> None:
        self.tool_round = tool_round
        self.seen: list[ToolConversation] = []
        self.max_tokens: list[int] = []

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Any = None,
        conversation: ToolConversation | None = None,
        **_: Any,
    ) -> Any:
        self.max_tokens.append(max_tokens)
        if conversation is not None:
            self.seen.append(conversation)
        if self.tool_round and len(self.seen) == 1:
            yield ToolUse(id="tu_1", name="onshape__get_variables", args={"d": "x"})
            yield Usage(tokens_in=5, tokens_out=2, provider_items=REPLAY_ITEMS)
            return
        yield "The I2C bus uses two wires."
        yield Usage(tokens_in=5, tokens_out=2)


async def _funded_user(maker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        handle = uuid.uuid4().hex
        user = User(supabase_user_id=handle, email=f"{handle}@example.dev")
        db.add(user)
        await db.flush()
        db.add(CreditBalance(user_id=user.id, balance=10_000))
        db.add(Subscription(user_id=user.id, plan=PlanType.PRO, status=SubscriptionStatus.ACTIVE))
        await db.commit()
        return user.id


async def _ctx(engine: AsyncEngine, prompt_text: str, **kw: Any) -> AgentRunContext:
    async def run(args: dict[str, Any]) -> dict[str, Any]:
        return {"variables": []}

    registry = ToolRegistry()
    registry.register(InProcessTool(READ, run))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return AgentRunContext(
        prompt=prompt_text,
        tools=tuple(registry.list()),
        dispatch=build_dispatch(registry, None),
        systems=FakeSolSystems(),
        project_id=uuid.uuid4(),
        user_id=await _funded_user(maker),
        sessionmaker=maker,
        secret_store=InMemorySecretStore(),
        **kw,
    )


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record the routing kwargs the runner hands the REAL gateway.stream."""
    calls: list[dict[str, Any]] = []
    real = gateway.stream

    def spy(query: str, **kw: Any) -> Any:
        calls.append(kw)
        return real(query, **kw)

    monkeypatch.setattr(gateway, "stream", spy)  # the module object runtime imported
    return calls


async def _run(model: _ScriptedModel, ctx: AgentRunContext) -> list[Any]:
    adapters = {name: model for name in ("anthropic", "openai", "google")}
    return [event async for event in LlmRunner(adapters=adapters).run(ctx)]


async def test_complexity_comes_from_the_estimator_on_the_live_message(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gateway gets the flattened fenced conversation as `query` (token
    measurement) but the ESTIMATOR runs on the person's message: without this,
    SOL_OPEN_QUESTION's HARD default sends every "what is I2C" to the top tier."""
    calls = _spy(monkeypatch)
    ctx = await _ctx(engine, "what is I2C")
    await _run(_ScriptedModel(), ctx)
    assert len(calls) == 1
    assert calls[0]["estimate_from"] == "what is I2C"
    assert calls[0]["context"] is InteractionContext.SOL_OPEN_QUESTION
    assert calls[0]["complexity"] is None  # no override: the estimator decides


@pytest.mark.parametrize(
    ("prompt_text", "expected"),
    [
        ("hi", Complexity.STANDARD),  # trivial -> standard
        ("why is my SLAM drifting when the robot turns", Complexity.HARD),  # hard stays hard
    ],
)
async def test_think_harder_bumps_the_estimator_tier_and_passes_it_explicitly(
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    prompt_text: str,
    expected: Complexity,
) -> None:
    calls = _spy(monkeypatch)
    ctx = await _ctx(engine, prompt_text, think_harder=True)
    await _run(_ScriptedModel(), ctx)
    assert calls[0]["complexity"] is expected
    assert calls[0]["estimate_from"] == prompt_text


async def test_provider_items_replay_on_the_next_round_and_never_leave_the_runner(
    engine: AsyncEngine,
) -> None:
    model = _ScriptedModel(tool_round=True)
    events = await _run(model, await _ctx(engine, "check the variables"))
    assert len(model.seen) == 2
    assistant = [t for t in model.seen[1].messages if t.role == "assistant"][-1]
    assert assistant.provider_items == REPLAY_ITEMS
    assert assistant.tool_uses and assistant.tool_uses[0].id == "tu_1"
    # Transcript-bound events (what _persist_turn stores) never carry them.
    assert all("provider_items" not in str(e.model_dump()) for e in events)


async def test_output_ceiling_leaves_headroom_for_reasoning_tokens(engine: AsyncEngine) -> None:
    """Responses-style providers count reasoning tokens against max_output_tokens."""
    model = _ScriptedModel()
    await _run(model, await _ctx(engine, "hi"))
    assert SOL_MAX_TOKENS == 16384
    assert model.max_tokens == [SOL_MAX_TOKENS]


async def test_a_screenshot_keeps_the_reasoning_route_and_runs_the_extractor_on_visual_log(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sol-window.md §8: the extractor pass is THE VISUAL_LOG call; the turn's
    own route still derives from its context, so a screenshot can never flip a
    tool-calling SOL turn onto a provider that cannot carry tools."""
    calls = _spy(monkeypatch)  # `complete` drains `stream`, so both calls land here
    shot = screenshot_block()
    model = _ScriptedModel()
    events = await _run(model, await _ctx(engine, "what is this?", screenshot=shot))

    extractor = [c for c in calls if c.get("conversation") is None]
    reasoning = [c for c in calls if c.get("conversation") is not None]
    assert len(extractor) == 1 and len(reasoning) == 1
    assert extractor[0]["type"] is RouteType.VISUAL_LOG
    assert extractor[0]["images"] == [shot.image]
    assert reasoning[0]["type"] is None  # context-derived, exactly as without a screenshot
    assert reasoning[0]["context"] is InteractionContext.SOL_OPEN_QUESTION
    assert reasoning[0].get("images") is None  # pixels ride the Turn, not the call
    live = model.seen[0].messages[-1]
    assert live.role == "user" and live.images == (shot.image,)
    manifest = next(e for e in events if e.type is AgentEventType.CONTEXT_USED)
    screen = [s for s in manifest.data["sections"] if s["kind"] == "screen"]
    assert screen == [{"kind": "screen", "citation": None, "tokens": screen[0]["tokens"]}]
    assert screen[0]["tokens"] > 0


def test_runtime_source_names_no_model() -> None:
    assert _MODEL_NAME.search(runtime.__file__ and open(runtime.__file__).read()) is None


async def test_the_context_image_reaches_only_the_extractor_never_the_reasoning_turn(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sol-window.md §8: the context image is used ONLY by the extractor pass;
    the live Turn carries exactly the crop."""
    calls = _spy(monkeypatch)
    shot = screenshot_block(with_context=True)
    model = _ScriptedModel()
    await _run(model, await _ctx(engine, "what is this?", screenshot=shot))

    [extractor] = [c for c in calls if c.get("conversation") is None]
    assert extractor["images"] == [shot.image, shot.context]
    live = model.seen[0].messages[-1]
    assert live.images == (shot.image,)


# ----------------------------------------------- artifacts + Error logging (S5)


ARTIFACT_VALUE = {
    "artifact_id": "019f9a00-0000-7000-8000-000000000001",
    "uri": "/api/v1/projects/p/artifacts/a/content",
    "media_type": "image/svg+xml",
    "title": "Arm wiring",
    "unknown_pins": [],
    "summary": "wiring diagram: 3 nodes, 2 wires, 0 unknown pin(s).",
}
DIAGRAM = ToolDescriptor(
    name="make_diagram",
    description="Draw a diagram.",
    params={"type": "object"},
    returns={"type": "object"},
)
LOCAL_ACTION = ToolDescriptor(
    name="companion.run_command",
    description="Run a command.",
    params={"type": "object"},
    returns={"type": "object"},
    files_errors=True,
)


class _ToolCallingModel(_ScriptedModel):
    """Round 1: one call per (name, args) given. Round 2: prose."""

    def __init__(self, calls: list[tuple[str, dict[str, Any]]]) -> None:
        super().__init__()
        self.calls = calls

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Any = None,
        conversation: ToolConversation | None = None,
        **_: Any,
    ) -> Any:
        if conversation is not None:
            self.seen.append(conversation)
        if len(self.seen) == 1:
            offered = {spec.name for spec in (conversation.tools if conversation else ())}
            for i, (name, args) in enumerate(self.calls):
                # The model answers with the provider-safe name it was offered.
                safe = next(o for o in offered if o == re.sub(r"[^A-Za-z0-9_-]", "_", name))
                yield ToolUse(id=f"tu_{i}", name=safe, args=args)
            yield Usage(tokens_in=5, tokens_out=2)
            return
        yield "Done."
        yield Usage(tokens_in=5, tokens_out=2)


async def _project_for(maker: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> uuid.UUID:
    from solus_api.models import Project

    async with maker() as db:
        team = Team(name="P")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="Rover", created_by=user_id)
        db.add(project)
        await db.commit()
        return project.id


async def _action_ctx(engine: AsyncEngine, *, fail: bool) -> AgentRunContext:
    async def diagram(args: dict[str, Any]) -> dict[str, Any]:
        return dict(ARTIFACT_VALUE)

    async def run_command(args: dict[str, Any]) -> dict[str, Any]:
        if fail:
            raise ToolException("exit 1: no board found")
        return {"stdout": "ok"}

    registry = ToolRegistry()
    registry.register(InProcessTool(DIAGRAM, diagram))
    registry.register(InProcessTool(LOCAL_ACTION, run_command))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user_id = await _funded_user(maker)
    return AgentRunContext(
        prompt="draw it and build it",
        tools=tuple(registry.list()),
        dispatch=build_dispatch(registry, None),
        systems=FakeSolSystems(),
        project_id=await _project_for(maker, user_id),
        user_id=user_id,
        sessionmaker=maker,
        secret_store=InMemorySecretStore(),
    )


async def _errors_of(engine: AsyncEngine, project_id: uuid.UUID) -> list[str]:
    from solus_api.models import SolusEntry, SolusSection
    from sqlalchemy import select

    async with async_sessionmaker(engine)() as db:
        rows = await db.scalars(
            select(SolusEntry.text).where(
                SolusEntry.project_id == project_id, SolusEntry.section == SolusSection.ERRORS
            )
        )
        return [r or "" for r in rows]


async def test_runner_emits_an_artifact_event_right_after_the_producing_tool_result(
    engine: AsyncEngine,
) -> None:
    ctx = await _action_ctx(engine, fail=False)
    model = _ToolCallingModel([("make_diagram", {"focus_entity_ids": [str(uuid.uuid4())]})])
    events = await _run(model, ctx)
    types = [e.type for e in events]
    i = types.index(AgentEventType.TOOL_RESULT)
    assert types[i + 1] is AgentEventType.ARTIFACT
    assert events[i + 1].data == {
        "artifact_id": ARTIFACT_VALUE["artifact_id"],
        "uri": ARTIFACT_VALUE["uri"],
        "media_type": "image/svg+xml",
        "title": "Arm wiring",
        "source_tool": "make_diagram",
        "summary": ARTIFACT_VALUE["summary"],
    }
    assert types.count(AgentEventType.ARTIFACT) == 1
    assert await _errors_of(engine, ctx.project_id) == []  # nothing failed, nothing filed


async def test_a_failed_files_errors_tool_is_filed_once_and_the_turn_continues(
    engine: AsyncEngine,
) -> None:
    ctx = await _action_ctx(engine, fail=True)
    model = _ToolCallingModel(
        [("companion.run_command", {"command": ["pio", "run"], "token": "hunter2"})]
    )
    events = await _run(model, ctx)
    types = [e.type for e in events]
    assert AgentEventType.ARTIFACT not in types  # a failure never yields an artifact
    assert types[-1] is AgentEventType.MESSAGE and events[-1].data["content"] == "Done."
    [text] = await _errors_of(engine, ctx.project_id)
    assert "companion.run_command" in text and "exit 1: no board found" in text
    assert "pio" in text and "hunter2" not in text


async def test_a_succeeding_files_errors_tool_files_nothing(engine: AsyncEngine) -> None:
    ctx = await _action_ctx(engine, fail=False)
    model = _ToolCallingModel([("companion.run_command", {"command": ["pio", "run"]})])
    await _run(model, ctx)
    assert await _errors_of(engine, ctx.project_id) == []


# ------------------------------- S5 layer wiring (sol-context-layers.md §6)
#
# The layer machinery was complete and tested, but the RUNNER passed neither
# `sessionmaker` nor `preferences_tokens` to build_context and never called
# `with_screen`/`with_conversation` — so a live turn reported ".solus not
# loaded", 0 preference tokens (while the system prompt carried them), and no
# screen/conversation layer at all. Honest manifest or no manifest.


async def _project_with_solus(maker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    from solus_api.models import Project, SolusSection
    from solus_api.services.solus_config import add_text_entry

    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="Rover")
        db.add(project)
        await db.commit()
        project_id = project.id
    async with maker() as db:
        await add_text_entry(
            db,
            project_id,
            SolusSection.HARDWARE,
            "the IMU sits on I2C bus 1 at 0x68",
            author="user",
            created_by=None,
        )
        await db.commit()
    return project_id


async def test_a_live_turn_reports_the_solus_and_screen_layers(engine: AsyncEngine) -> None:
    import dataclasses

    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project_with_solus(maker)
    shot = screenshot_block()
    ctx = dataclasses.replace(
        await _ctx(engine, "what is on my screen?", screenshot=shot),
        project_id=project_id,
    )
    events = await _run(_ScriptedModel(), ctx)

    manifest = next(e for e in events if e.type is AgentEventType.CONTEXT_USED)
    kinds = [s["kind"] for s in manifest.data["sections"]]
    assert "solus" in kinds  # the project .solus entries actually loaded
    assert "screen" in kinds  # the screen read is IN the context, not bolted after it
    # The manifest stays labels-and-counts (test_reason.py holds the shape).
    for section in manifest.data["sections"]:
        assert set(section) == {"kind", "citation", "tokens"}


async def test_the_preferences_and_conversation_layers_report_what_the_turn_carries(
    engine: AsyncEngine,
) -> None:
    import dataclasses

    from solus_api.agent.runtime import TurnView

    model = _ScriptedModel()
    ctx = dataclasses.replace(
        await _ctx(engine, "why does the arm sag at rest?"),
        engineering_preferences={"units": "millimetres, never inches"},
        history=(TurnView(role="user", content="the arm sags"),),
    )
    await _run(model, ctx)

    live = model.seen[0].messages[-1].text or ""
    assert "carried in the system prompt" in live  # preferences layer, non-zero
    assert "carried as the surrounding turns" in live  # conversation layer, non-zero


async def test_the_screen_read_is_not_sent_twice(engine: AsyncEngine) -> None:
    """`with_screen` slots the already-fenced read into the screen LAYER; the
    old code also appended it after the context, which would now duplicate it."""
    model = _ScriptedModel()
    await _run(model, await _ctx(engine, "what is this?", screenshot=screenshot_block()))
    live = model.seen[0].messages[-1].text or ""
    assert live.count("context_screen") <= 1
    assert live.count("Layer 4/5") == 1
