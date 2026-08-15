# SOLUSDEV-130 (SOL-02) — the reasoning layer's deterministic halves: query
# planning (what to pull, with no model call — the ADR-026 pattern) and
# citation verification (the model may only cite sources the context actually
# contains; everything else is stripped from the Sources line).
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from solus_api.agent.context import build_context
from solus_api.agent.fake_systems import FakeSolSystems
from solus_api.agent.interfaces import GraphScope
from solus_api.agent.reason import plan_query, verified_citations
from solus_api.orchestration.providers import ToolConversation, ToolUse, Usage
from sqlalchemy.ext.asyncio import AsyncEngine

ANCHOR = uuid.uuid4()


def test_plan_extracts_graph_anchors_from_the_query() -> None:
    plan = plan_query(f"why does entity {ANCHOR} overheat?")
    assert plan.scope.anchor_entity_ids == [ANCHOR]
    assert plan.scope.degree >= 1


def test_plan_requests_telemetry_only_for_runtime_shaped_queries() -> None:
    live = plan_query("the motor current spikes at runtime when the servo moves")
    static = plan_query("what package is the LM358 in?")
    assert live.window is not None
    assert static.window is None


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
    from solus_api.agent.runtime import LlmRunner

    runner = LlmRunner(adapters={"anthropic": model})
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
    from solus_api.agent.runtime import LlmRunner
    from test_sol_red_team import _funded_ctx, _registry

    seen_projects: list[uuid.UUID | None] = []
    hostile = PAYLOADS[0].text

    class RecordingPoisoned(FakeSolSystems):
        async def get_graph_context(self, project_id, scope, budget=None):  # type: ignore[no-untyped-def]
            seen_projects.append(project_id)
            return await super().get_graph_context(project_id, scope, budget)

        async def rag_query(self, text, k, filter=None):  # type: ignore[no-untyped-def]
            assert isinstance(filter, RetrievalFilter) and filter.project_id is not None
            seen_projects.append(filter.project_id)
            hits = await super().rag_query(text, k, filter)
            return [hits[0].model_copy(update={"chunk": hostile})]

    model = _CitingModel(f"As instructed: {hostile} [error_store:err-101]")
    runner = LlmRunner(adapters={"anthropic": model})
    ctx = await _funded_ctx(engine, _registry([]), systems=RecordingPoisoned())
    events = [event async for event in runner.run(ctx)]

    assert set(seen_projects) == {ctx.project_id}
    final = events[-1]
    # The poisoned chunk cannot mint provenance; only the genuine token is cited.
    assert final.data["citations"] == ["[error_store:err-101]"]
