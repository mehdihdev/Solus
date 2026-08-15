# SOLUSDEV-130 (SOL-02) — the retrieval-quality eval. Scores the tuned pull
# plan (plan_query: k=5, degree=2, telemetry-when-runtime-shaped) against a
# naive baseline (k=1, degree=0, no telemetry) on the labeled cross-domain
# cases, as recall@k over expected citations. Deterministic corpus, exact
# pinned scores — the recorded numbers the ticket requires.
#
# SCOPE NOTE: until SYS-04/ERR-02 land, this measures the reasoning layer's
# planning + packing against a controlled corpus (EvalSystems), not real
# pgvector retrieval. The harness re-runs unchanged against the real impl.
from __future__ import annotations

import uuid

from fixtures.sol_eval_cases import CASES, EvalSystems
from solus_api.agent.context import Context, build_context
from solus_api.agent.interfaces import ContextBudget, GraphScope
from solus_api.agent.reason import plan_query


async def _baseline_context(query: str) -> Context:
    # The naive dump: one hit, no traversal, no telemetry, no plan.
    return await build_context(
        EvalSystems(),
        query,
        project_id=uuid.uuid4(),
        scope=GraphScope(anchor_entity_ids=[], degree=0),
        window=None,
        budget=ContextBudget(max_tokens=4000),
        k=1,
    )


async def _tuned_context(query: str) -> Context:
    plan = plan_query(query)
    return await build_context(
        EvalSystems(),
        query,
        project_id=uuid.uuid4(),
        scope=plan.scope,
        window=plan.window,
        budget=plan.budget,
        k=plan.k,
    )


def _recall(context: Context, expected: frozenset[str]) -> float:
    present = {s.citation for s in context.sections if s.citation}
    return len(expected & present) / len(expected)


async def _mean_recall(tuned: bool) -> float:
    scores = []
    for case in CASES:
        context = await (_tuned_context if tuned else _baseline_context)(case.query)
        scores.append(_recall(context, case.expected_citations))
    return sum(scores) / len(scores)


async def test_tuned_plan_beats_the_naive_baseline() -> None:
    baseline = await _mean_recall(tuned=False)
    tuned = await _mean_recall(tuned=True)
    # THE RECORDED SCORES (mean recall@k over the labeled cases). Change the
    # knobs in reason.py or the corpus, and re-pin these deliberately:
    assert tuned == 1.0
    assert baseline == 0.9
    assert tuned > baseline


async def test_every_case_hits_full_recall_under_the_tuned_plan() -> None:
    for case in CASES:
        context = await _tuned_context(case.query)
        assert _recall(context, case.expected_citations) == 1.0, case.case_id


async def test_runtime_shaped_case_pulls_telemetry_only_when_planned() -> None:
    runtime_case = next(c for c in CASES if c.case_id == "eval-runtime-ripple")
    tuned = await _tuned_context(runtime_case.query)
    baseline = await _baseline_context(runtime_case.query)
    assert any(s.kind == "telemetry" for s in tuned.sections)
    assert not any(s.kind == "telemetry" for s in baseline.sections)
