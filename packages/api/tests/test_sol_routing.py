"""SOLUSDEV-321 P0-T7: SOL routes by scope.

A turn anchored on code, or whose message reads as code, asks for the CODE role on its first
round, but only while the measured input leaves 20 % of that role's window spare: an explicit
type refuses on overflow where a system-routed one escalates. A turn about a real (non-info)
finding runs HARD. Both are decided by Solus code before round 1, with no model call; from
round 2 on the runner pins round 1's choice.

The routing spy wraps the REAL gateway.stream; a scripted adapter plays every provider.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import replace
from typing import Any

import pytest
from fixtures.fake_systems import FakeSolSystems
from solus_api.agent import runtime
from solus_api.agent.context import Context, build_context
from solus_api.agent.interfaces import ContextBudget
from solus_api.agent.sol_anchors import ResolvedAnchors
from solus_api.agent.stream import AgentEventType
from solus_api.checkers.interface import Severity
from solus_api.graph.findings import FindingSpec, raise_finding
from solus_api.models import Domain
from solus_api.orchestration import gateway
from solus_api.orchestration.config import OrchestrationConfig, load_orchestration_config
from solus_api.orchestration.enums import Complexity, RouteType
from solus_api.orchestration.type_estimator import chars_for_tokens, round_one_route_type
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from test_sol_reasoner import _CODE_FILE, _CodeScopeSystems, _ctx, _run, _ScriptedModel
from test_solus_layer import _part, _project, _ScopedGraph

#: models.yaml's (complexity x type) -> role table as P0-T7 found it: routing by scope picks a
#: cell, it never edits one.
_MATRIX = {
    Complexity.TRIVIAL: {
        RouteType.GENERAL: "openai_trivial",
        RouteType.CODE: "general_trivial",
        RouteType.VISUAL_LOG: "visual_trivial",
        RouteType.LONG_CONTEXT: "longctx_trivial",
    },
    Complexity.STANDARD: {
        RouteType.GENERAL: "openai_standard",
        RouteType.CODE: "code_standard",
        RouteType.VISUAL_LOG: "visual_standard",
        RouteType.LONG_CONTEXT: "longctx_standard",
    },
    Complexity.HARD: {
        RouteType.GENERAL: "general_hard",
        RouteType.CODE: "code_hard",
        RouteType.VISUAL_LOG: "visual_hard",
        RouteType.LONG_CONTEXT: "longctx_hard",
    },
}
_CODE_ROLES = frozenset(row[RouteType.CODE] for row in _MATRIX.values())
_SUBJECT = uuid.uuid4()
#: A part the turn mentions: `_CodeScopeSystems` puts the code file one hop from it.
_PART = uuid.uuid4()
_HEADLINE = "LM358 supply range unchecked"


def _routes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[dict[str, Any], Any]]:
    """Each REAL gateway stream the runner opens, with the routing kwargs it was handed."""
    opened: list[tuple[dict[str, Any], Any]] = []
    real = gateway.stream

    def spy(query: str, **kw: Any) -> Any:
        stream = real(query, **kw)
        opened.append((kw, stream))
        return stream

    monkeypatch.setattr(gateway, "stream", spy)  # the module object runtime imported
    return opened


def _windows(tokens: int, roles: Collection[str]) -> OrchestrationConfig:
    """The shipped config, with every model filling one of `roles` holding only `tokens`."""
    shipped = load_orchestration_config()
    catalog = [
        e.model_copy(update={"context_window": tokens}) if set(roles) & set(e.roles) else e
        for e in shipped.catalog
    ]
    # Validated afresh: a `model_copy` would keep the role index built from the old catalog.
    return OrchestrationConfig.model_validate({**shipped.model_dump(), "catalog": catalog})


@pytest.mark.parametrize(
    ("ctx_kw", "subjects", "severity", "routed", "budget_tier"),
    [
        # The turn names the finding: HARD before planning, so the budget is HARD's too.
        pytest.param(
            {"finding_id": uuid.uuid4()},
            (),
            None,
            Complexity.HARD,
            Complexity.HARD,
            id="finding_id",
        ),
        pytest.param(
            {}, (_SUBJECT,), None, Complexity.HARD, Complexity.HARD, id="finding_subject_anchor"
        ),
        pytest.param(
            {"finding_id": uuid.uuid4(), "think_harder": True},
            (),
            None,
            Complexity.HARD,
            Complexity.HARD,
            id="think_harder_too",
        ),
        # Only the findings read inside build_context finds it: round 1, never a re-pack, and
        # only a real finding: an info one renders but leaves the turn system-routed.
        pytest.param(
            {},
            (),
            Severity.WARNING,
            Complexity.HARD,
            Complexity.TRIVIAL,
            id="open_finding_on_a_scoped_part",
        ),
        pytest.param(
            {}, (), Severity.INFO, None, Complexity.TRIVIAL, id="open_info_finding_on_a_scoped_part"
        ),
    ],
)
async def test_finding_in_scope_routes_hard(
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    ctx_kw: dict[str, Any],
    subjects: tuple[uuid.UUID, ...],
    severity: Severity | None,
    routed: Complexity | None,
    budget_tier: Complexity,
) -> None:
    """R4/R6/F1: a turn about a finding runs round 1 HARD, explicitly. When the turn names the
    finding (its id, or the subjects that become `finding_subject` anchors) the tier is bumped
    before planning, so the context budget is HARD's as well: one tier feeds both. When only
    the findings read inside `build_context` finds an open warning or critical one on a part in
    scope, round 1 runs HARD on the context already packed: one `build_context`, at the planned
    tier. An open info finding renders in the findings layer and routes nothing."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id = await _project(maker)
    async with maker() as db:
        part = await _part(db, project_id, "LM358")
        if severity is not None:  # open, on the part in scope
            spec = FindingSpec(
                rule_id="power.supply_range",
                severity=severity,
                source="checker",
                headline=_HEADLINE,
                subjects=[part.id],
                evidence={"rail": "5V"},
                domain=Domain.ELECTRICAL,
            )
            await raise_finding(db, project_id, spec)
        await db.commit()
    if subjects:

        async def resolved(*_: Any, **__: Any) -> ResolvedAnchors:
            return ResolvedAnchors(finding_subjects=subjects)

        monkeypatch.setattr(runtime, "resolve_anchor_inputs", resolved)
    packs: list[tuple[ContextBudget | None, Context]] = []

    async def packed(*args: Any, **kw: Any) -> Context:
        context = await build_context(*args, **kw)
        packs.append((kw.get("budget"), context))
        return context

    monkeypatch.setattr(runtime, "build_context", packed)
    opened = _routes(monkeypatch)
    # "hi" estimates trivial: without a finding the turn would route, and pack, at trivial.
    ctx = replace(await _ctx(engine, "hi", **ctx_kw), project_id=project_id)
    events = await _run(_ScriptedModel(), replace(ctx, systems=_ScopedGraph(part)))

    assert [kw["complexity"] for kw, _ in opened] == [routed]
    ((budget, context),) = packs  # packed once: a finding found while packing never re-packs
    total = gateway.default_orchestration_config().context_budget.total_for(budget_tier)
    assert budget is not None and budget.max_tokens == total
    rendered = [section.text.split(" rule=")[0] for section in context.layers.findings.sections]
    assert rendered == ([f"{_HEADLINE} [severity={severity}"] if severity else [])
    manifest = next(e for e in events if e.type is AgentEventType.CONTEXT_USED)
    assert [a["reason"] for a in manifest.data["anchors"]] == ["finding_subject"] * len(subjects)


@pytest.mark.parametrize(
    ("systems", "mentions", "prompt_text", "explicit"),
    [
        pytest.param(
            _CodeScopeSystems(),
            (_CODE_FILE,),
            "what is I2C",
            RouteType.CODE,
            id="code_file_anchored",
        ),
        # Anchored on a part whose one-hop neighbourhood holds the code file: not code.
        pytest.param(_CodeScopeSystems(), (_PART,), "what is I2C", None, id="code_file_one_hop"),
        pytest.param(
            FakeSolSystems(),
            (),
            "fix the traceback in motor.py",
            RouteType.CODE,
            id="code_in_message",
        ),
        pytest.param(FakeSolSystems(), (), "what is I2C", None, id="neither"),
    ],
)
async def test_code_scope_routes_code_role(
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    systems: FakeSolSystems,
    mentions: tuple[uuid.UUID, ...],
    prompt_text: str,
    explicit: RouteType | None,
) -> None:
    """R1/R3/I2: a turn anchored on code, or whose message reads as code, asks for CODE on
    round 1 and lands on the matrix's CODE cell at the tier it routes at. Code one hop from the
    anchor does not make the turn code; with neither signal the type stays None and the context
    derives GENERAL, as before."""
    opened = _routes(monkeypatch)
    ctx = await _ctx(engine, prompt_text, mentions=mentions)
    await _run(_ScriptedModel(), replace(ctx, systems=systems))

    ((kw, stream),) = opened
    assert kw["type"] is explicit
    model = stream.completion.model
    assert model.route_type is (explicit or RouteType.GENERAL)
    assert model.role == _MATRIX[model.complexity][model.route_type]


async def test_explicit_type_withheld_when_input_would_overflow(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3: an explicit type REFUSES on window overflow (`resolution.resolve_routing`), so round 1
    asks for CODE only while the measured input fills at most 80 % of the CODE role's window.
    Past that the type stays None: the turn is system-routed and answered, never refused."""
    small = _windows(1_000, _CODE_ROLES)
    for tokens, expected in ((800, RouteType.CODE), (801, None)):  # 80 % of 1,000, then one over
        query = "x" * chars_for_tokens(tokens, config=small.type_estimator)
        # P1-T1: the scope planner's `type_hint` says the turn is code; the window decides.
        decided = round_one_route_type(
            RouteType.CODE, query=query, tier=Complexity.STANDARD, config=small
        )
        assert decided is expected, tokens
        assert (
            round_one_route_type(None, query=query, tier=Complexity.STANDARD, config=small) is None
        )

    monkeypatch.setattr(gateway, "_default_config", _windows(10, _CODE_ROLES))
    opened = _routes(monkeypatch)
    ctx = await _ctx(engine, "hi", mentions=(_CODE_FILE,))  # anchored on code: CODE is asked for
    events = await _run(_ScriptedModel(), replace(ctx, systems=_CodeScopeSystems()))

    ((kw, stream),) = opened
    assert kw["type"] is None
    assert stream.completion.model.route_type is RouteType.GENERAL
    assert [e.type for e in events].count(AgentEventType.MESSAGE) == 1  # answered, not refused


async def test_a_discovered_finding_measures_the_code_window_at_hard(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """m1 (D2): the window check measures the CODE role at the tier round 1 routes at. A finding
    found while packing turns a trivial turn HARD after its budget was set, so the check reads
    the HARD CODE cell; the planned trivial one, shrunk here, would have withheld CODE."""
    shrunk = _windows(10, {_MATRIX[Complexity.TRIVIAL][RouteType.CODE]})
    monkeypatch.setattr(gateway, "_default_config", shrunk)

    async def packed(*args: Any, **kw: Any) -> Context:
        context = await build_context(*args, **kw)
        return context.model_copy(update={"finding_in_scope": True})

    monkeypatch.setattr(runtime, "build_context", packed)
    opened = _routes(monkeypatch)
    ctx = await _ctx(engine, "hi", mentions=(_CODE_FILE,))
    await _run(_ScriptedModel(), replace(ctx, systems=_CodeScopeSystems()))

    ((kw, stream),) = opened
    assert (kw["complexity"], kw["type"]) == (Complexity.HARD, RouteType.CODE)
    assert stream.completion.model.role == _MATRIX[Complexity.HARD][RouteType.CODE]


def test_matrix_roles_unchanged() -> None:
    """Routing by scope picks a cell of the table; it never edits the table."""
    shipped = load_orchestration_config()
    assert shipped.matrix == _MATRIX
    assert shipped.default_role == "general_standard"
