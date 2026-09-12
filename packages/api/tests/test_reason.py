# SOLUSDEV-130 (SOL-02) — the reasoning layer's deterministic halves: query
# planning (what to pull, with no model call — the ADR-026 pattern) and
# citation verification (the model may only cite sources the context actually
# contains; everything else is stripped from the Sources line).
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from fixtures.fake_systems import FakeSolSystems
from solus_api.agent.context import build_context
from solus_api.agent.interfaces import GraphScope
from solus_api.agent.reason import plan_query, verified_citations
from solus_api.orchestration.providers import ToolConversation, ToolUse, Usage
from sqlalchemy.ext.asyncio import AsyncEngine

ANCHOR = uuid.uuid4()


if TYPE_CHECKING:
    from solus_api.agent.runtime import LlmRunner


def _runner(model: object) -> LlmRunner:
    """The shipped matrix routes a SOL turn to openai OR anthropic by tier
    (SOLUSDEV-252 S1), so the fake serves every provider the router may pick —
    these suites are about the reasoning loop, not about which model answers."""
    from solus_api.agent.runtime import LlmRunner

    return LlmRunner(adapters={"anthropic": model, "openai": model, "google": model})


def test_plan_extracts_graph_anchors_from_the_query() -> None:
    plan = plan_query(f"why does entity {ANCHOR} overheat?")
    assert plan.scope.anchor_entity_ids == [ANCHOR]
    assert plan.scope.degree >= 1


def test_plan_requests_telemetry_only_for_runtime_shaped_queries() -> None:
    live = plan_query("the motor current spikes at runtime when the servo moves")
    static = plan_query("what package is the LM358 in?")
    assert live.window is not None
    assert static.window is None


def test_explicit_mentions_become_anchors() -> None:
    """An `@`-mention is the user pointing at one node. It reaches the plan as an
    explicit id rather than being inferred from the prose, so SOL is grounded on
    the thing the user meant instead of whatever RAG's similarity search
    surfaced."""
    mentioned = uuid.uuid4()

    plan = plan_query("will this clear the belt?", mentions=[mentioned])

    assert plan.scope.anchor_entity_ids == [mentioned]


def test_mentions_outrank_ids_pasted_in_the_prose_when_the_cap_bites() -> None:
    """Both are anchors, but a mention is deliberate and a pasted UUID may just
    be quoted log output — so mentions are kept first and the cap trims the
    inferred ones."""
    mentions = [uuid.uuid4() for _ in range(8)]
    pasted = uuid.uuid4()

    plan = plan_query(f"compare against {pasted}", mentions=mentions)

    assert plan.scope.anchor_entity_ids == mentions
    assert pasted not in plan.scope.anchor_entity_ids


def test_mentions_are_deduped_against_the_prose_and_themselves() -> None:
    """The same node mentioned twice, or mentioned AND pasted, must not consume
    two of the eight anchor slots."""
    shared = uuid.uuid4()
    other = uuid.uuid4()

    plan = plan_query(f"why is {shared} hot?", mentions=[shared, shared, other])

    assert plan.scope.anchor_entity_ids == [shared, other]


def test_mentions_stay_bounded() -> None:
    """SEC-H3: the anchor cap bounds DB work, so it must bind the new input too —
    a client is not trusted to respect the request-schema limit."""
    plan = plan_query("look at these", mentions=[uuid.uuid4() for _ in range(50)])

    assert len(plan.scope.anchor_entity_ids) == 8


def test_plan_is_deterministic_and_bounded() -> None:
    query = f"telemetry glitch near {ANCHOR} during the last run"
    first, second = plan_query(query), plan_query(query)
    assert first == second
    assert first.k <= 20
    assert first.budget is not None and first.budget.max_tokens is not None


async def test_verified_citations_keep_only_real_sources() -> None:
    context = await build_context(
        FakeSolSystems(),
        "camera drops frames",
        project_id=uuid.uuid4(),
        scope=GraphScope(anchor_entity_ids=[uuid.uuid4()], degree=1),
        window=None,
    )
    text = (
        "The IMU conflict [error_store:err-101] matches the datasheet "
        "[datasheet:lm358.pdf#p1]. Also see [fabricated:nope] and again "
        "[error_store:err-101]."
    )
    assert verified_citations(text, context) == (
        "[error_store:err-101]",
        "[datasheet:lm358.pdf#p1]",
    )


async def test_verified_citations_empty_when_model_cites_nothing_real() -> None:
    context = await build_context(
        FakeSolSystems(),
        "q",
        project_id=uuid.uuid4(),
        scope=GraphScope(anchor_entity_ids=[], degree=0),
        window=None,
    )
    assert verified_citations("no citations here [made:up]", context) == ()


# ---------------------------------------------- runner integration (SOL-02)


class _CitingModel:
    """A scripted provider: replies with canned text citing one genuine and one
    fabricated source, and captures the conversation it was handed."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.seen: ToolConversation | None = None

    async def stream(  # matches the provider-adapter seam
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: object = None,
        conversation: ToolConversation | None = None,
        # The routed catalog entry may set a reasoning effort (SOLUSDEV-252 S1);
        # a fake adapter accepts whatever the seam passes.
        **_: Any,
    ) -> AsyncIterator[str | ToolUse | Usage]:
        self.seen = conversation
        yield self._text
        yield Usage(tokens_in=7, tokens_out=3)


async def test_runner_hands_the_model_fenced_context_and_verifies_sources(
    engine: AsyncEngine,
) -> None:
    from test_sol_red_team import _funded_ctx, _registry

    model = _CitingModel(
        "The IMU conflict [error_store:err-101] explains it; see also [fabricated:x].\n"
        "Sources: [fabricated:x] [datasheet:totally-made-up.pdf]"
    )

    runner = _runner(model)
    ctx = await _funded_ctx(engine, _registry([]), systems=FakeSolSystems())
    events = [event async for event in runner.run(ctx)]

    final = events[-1]
    # Provenance is STRUCTURED and Solus-verified: the fabricated token never
    # gains it, and the model's own forged "Sources:" line is stripped from
    # the prose — model text cannot impersonate the authoritative surface.
    assert final.data["citations"] == ["[error_store:err-101]"]
    assert "Sources:" not in final.data["content"]
    assert "totally-made-up" not in final.data["content"]
    # The fenced context reached the provider as data blocks.
    seen = model.seen
    assert seen is not None
    flat = "".join(t.text or "" for t in seen.messages)
    assert "context_graph" in flat and "context_error" in flat


def test_plan_caps_anchors_and_entities_against_hostile_queries() -> None:
    # SEC-H3: an 8000-char message full of UUIDs must bound DB work.
    flood = " ".join(str(uuid.uuid4()) for _ in range(300))
    plan = plan_query(f"explain {flood}")
    assert len(plan.scope.anchor_entity_ids) == 8
    assert plan.budget.max_entities == 200


async def test_telemetry_citations_survive_verification() -> None:
    # SOL-02 review: telemetry provenance was silently unverifiable (the `+`
    # in a tz-aware isoformat fell outside the citation charset).
    from solus_api.agent.interfaces import TelemetryWindow

    context = await build_context(
        FakeSolSystems(),
        "telemetry spike during the run",
        project_id=uuid.uuid4(),
        scope=GraphScope(anchor_entity_ids=[], degree=0),
        window=TelemetryWindow(duration_seconds=60.0),
    )
    telemetry_citation = next(
        s.citation for s in context.sections if s.kind == "telemetry" and s.citation
    )
    assert verified_citations(f"see {telemetry_citation}", context) == (telemetry_citation,)


async def test_runner_scopes_the_context_pull_to_the_request_project(
    engine: AsyncEngine,
) -> None:
    # SEC-H4: a regression to a prompt-derived project id must fail a test,
    # and a poisoned feed chunk cannot place its token in the citations.
    from fixtures.injection_corpus import PAYLOADS
    from solus_api.agent.interfaces import RetrievalFilter
    from test_sol_red_team import _funded_ctx, _registry

    seen_projects: list[uuid.UUID | None] = []
    hostile = PAYLOADS[0].text

    class RecordingPoisoned(FakeSolSystems):
        async def get_graph_context(self, project_id, scope, budget=None):  # type: ignore[no-untyped-def]
            seen_projects.append(project_id)
            return await super().get_graph_context(project_id, scope, budget)

        async def rag_query(self, text, k, filter=None):  # type: ignore[no-untyped-def]
            assert isinstance(filter, RetrievalFilter)
            if filter.source_types == ["corpus"]:
                # CORPUS C2 / ADR-036: the shipped corpus is the one GLOBAL source —
                # no tenant scope exists for it, and none may be attached.
                assert filter.project_id is None
                return await super().rag_query(text, k, filter)
            assert filter.project_id is not None
            seen_projects.append(filter.project_id)
            hits = await super().rag_query(text, k, filter)
            return [hits[0].model_copy(update={"chunk": hostile})]

    model = _CitingModel(f"As instructed: {hostile} [error_store:err-101]")
    runner = _runner(model)
    ctx = await _funded_ctx(engine, _registry([]), systems=RecordingPoisoned())
    events = [event async for event in runner.run(ctx)]

    assert set(seen_projects) == {ctx.project_id}
    final = events[-1]
    # The poisoned chunk cannot mint provenance; only the genuine token is cited.
    assert final.data["citations"] == ["[error_store:err-101]"]


# ------------------------------------ context_used frame (SOLUSDEV-233)


async def test_runner_streams_context_used_before_any_model_output(
    engine: AsyncEngine,
) -> None:
    """The first frame of a turn declares WHAT context the model was handed —
    kind/citation/tokens only, never section text (prompt internals stay
    server-side)."""
    from solus_api.agent.stream import AgentEventType
    from test_sol_red_team import _funded_ctx, _registry

    model = _CitingModel("All good [error_store:err-101].")
    runner = _runner(model)
    ctx = await _funded_ctx(engine, _registry([]), systems=FakeSolSystems())
    events = [event async for event in runner.run(ctx)]

    first = events[0]
    assert first.type is AgentEventType.CONTEXT_USED
    assert isinstance(first.data["sections"], list) and first.data["sections"]
    for section in first.data["sections"]:
        assert set(section) == {"kind", "citation", "tokens"}
    assert isinstance(first.data["truncated"], bool)
    assert isinstance(first.data["dropped"], int)


async def test_runner_hands_the_model_the_fenced_custom_instruction(
    engine: AsyncEngine,
) -> None:
    """ctx.custom_instruction reaches the provider inside the system prompt —
    fenced as data, after the Solus-authored base (SOLUSDEV-233)."""
    import dataclasses

    from solus_api.agent.prompt import system_prompt
    from test_sol_red_team import _funded_ctx, _registry

    model = _CitingModel("Understood.")
    runner = _runner(model)
    ctx = await _funded_ctx(engine, _registry([]), systems=FakeSolSystems())
    ctx = dataclasses.replace(ctx, custom_instruction="Prefer metric units.")
    _ = [event async for event in runner.run(ctx)]

    seen = model.seen
    assert seen is not None and seen.system is not None
    assert seen.system.startswith(system_prompt(ctx.sol_mode))
    assert '"Prefer metric units."' in seen.system


async def test_runner_hands_the_model_the_fenced_engineering_preferences(
    engine: AsyncEngine,
) -> None:
    """SOLUSDEV-244: ctx.engineering_preferences reaches the provider inside the
    system prompt — fenced as data, after the base, before the styling note."""
    import dataclasses

    from solus_api.agent.prompt import ENGINEERING_PREFERENCES_KIND, system_prompt
    from test_sol_red_team import _funded_ctx, _registry

    model = _CitingModel("Understood.")
    runner = _runner(model)
    ctx = await _funded_ctx(engine, _registry([]), systems=FakeSolSystems())
    ctx = dataclasses.replace(
        ctx,
        custom_instruction="Round to 2dp.",
        engineering_preferences={"Electrical": "Prefer 0.1 mm clearance minimum."},
    )
    _ = [event async for event in runner.run(ctx)]

    seen = model.seen
    assert seen is not None and seen.system is not None
    assert seen.system.startswith(system_prompt(ctx.sol_mode))
    assert f"kind={ENGINEERING_PREFERENCES_KIND}" in seen.system
    assert '"Prefer 0.1 mm clearance minimum."' in seen.system
    assert seen.system.index(f"kind={ENGINEERING_PREFERENCES_KIND}") < seen.system.index(
        "kind=user_preference"
    )
