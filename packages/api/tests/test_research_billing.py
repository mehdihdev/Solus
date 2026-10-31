"""SOLUSDEV-321 P1-T5 — what a turn's web research costs, and who may spend it.

The web call is a turn's FIRST paid action, so the server admits it the way the gateway admits a
model call: on a cache miss, before the call, through `assert_can_spend`. A trial at its cap, an
expired trial or an empty balance gets a failed `tool_result` and no web call, debit, cache write
or source frame; a cache hit costs nothing and needs no admission; a turn with no signed-in user
researches nothing. Each Brave call a live research makes writes one ledger row — a failed write
is deferred to the reconciliation sweep, never raised — and a repeat ask writes none.
"""

from __future__ import annotations

import logging
import string
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from solus_api.agent import research as research_module
from solus_api.agent.modes import ActionMode, DispatchFn
from solus_api.agent.research import ResearchCache, ResearchDigest, ResearchStep, debit_web_calls
from solus_api.agent.runtime import LlmRunner
from solus_api.agent.stream import AgentEventType
from solus_api.agent.tools import ToolCall, ToolResult
from solus_api.agent.turn_budget import TurnBudget
from solus_api.agent.turn_limits import turn_limits
from solus_api.billing import credits as billing_credits
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.models import (
    CreditBalance,
    DebitReconcileStatus,
    PendingCreditDebit,
    PlanType,
    Subscription,
    SubscriptionStatus,
    User,
)
from solus_api.orchestration import config as orchestration_config
from solus_api.orchestration import gateway
from solus_api.orchestration.enums import Complexity
from solus_api.orchestration.gates import TrialCapReachedError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from test_research import ScriptedTools
from test_research_gating import (
    ASK,
    LIMITS,
    QUERY,
    _ctx,
    _install_brave,
    _kinds,
    _one_source_digest,
    _queue_one_page,
    _run,
    _web_rows,
)
from test_sol_reasoner import _funded_user, _ScriptedModel


@pytest.fixture
def brave(monkeypatch: pytest.MonkeyPatch) -> ScriptedTools:
    return _install_brave(monkeypatch)


class _SpyDispatch:
    """A dispatcher that remembers every call it was asked to run."""

    def __init__(self, inner: DispatchFn) -> None:
        self.calls: list[ToolCall] = []
        self._inner = inner

    async def __call__(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return await self._inner(call)


async def _user(
    maker: async_sessionmaker[Any],
    status: SubscriptionStatus,
    *,
    spent: int = 0,
    balance: int = 0,
    expires_at: datetime | None = None,
) -> uuid.UUID:
    async with maker() as db:
        handle = uuid.uuid4().hex
        user = User(supabase_user_id=handle, email=f"{handle}@example.dev")
        db.add(user)
        await db.flush()
        db.add(CreditBalance(user_id=user.id, balance=balance, spent_total=spent))
        db.add(
            Subscription(user_id=user.id, plan=PlanType.BASIC, status=status, expires_at=expires_at)
        )
        await db.commit()
        return user.id


async def _unadmitted(maker: async_sessionmaker[Any], who: str) -> uuid.UUID:
    """The ways the gateway refuses a model call: the trial cap, an ended trial, no credits."""
    if who == "trial_cap":
        cap = LIMITS.trial_credit_cap
        return await _user(maker, SubscriptionStatus.TRIALING, spent=cap)
    if who == "expired_trial":
        gone = datetime.now(UTC) - timedelta(days=1)
        return await _user(maker, SubscriptionStatus.TRIALING, expires_at=gone)
    return await _user(maker, SubscriptionStatus.ACTIVE, balance=0)


def _standard_budget() -> TurnBudget:
    return TurnBudget(turn_limits(ActionMode.GUIDE, Complexity.STANDARD))


# ------------------------------------------------------------------ admission


@pytest.mark.parametrize("who", ["trial_cap", "expired_trial", "empty_balance"])
async def test_an_unadmitted_user_gets_no_web_call_no_debit_and_no_frame(
    engine: AsyncEngine, brave: ScriptedTools, who: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The gateway's own pre-flight runs before the first paid web call (a cache miss): the
    dispatcher is never reached, nothing is debited or cached, the client gets a failed result
    and no sources, and the turn goes on to the gateway, which refuses its model call."""
    _queue_one_page(brave)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    cache = ResearchCache(InMemoryCacheStore())
    base = await _ctx(engine, ASK, research_cache=cache)
    spy = _SpyDispatch(base.dispatch)
    ctx = replace(base, user_id=await _unadmitted(maker, who), dispatch=spy)
    budget = _standard_budget()
    step = ResearchStep(ctx, missing=(), budget=budget, limits=LIMITS, credits_per_call=2)

    with caplog.at_level(logging.INFO, logger="solus.agent.research"):
        events = [event async for event in step.events()]

    assert _kinds(events) == [AgentEventType.TOOL_CALL, AgentEventType.TOOL_RESULT]
    assert events[1].data["ok"] is False and events[1].data["error"]["code"] == "unauthorized"
    assert spy.calls == [] and brave.calls == []
    assert await _web_rows(engine) == []
    assert await cache.get(ctx.project_id, QUERY) is None
    assert step.digest is None
    assert (budget.tool_calls, budget.web_searches, budget.web_fetches) == (1, 0, 0)
    refused = [r.getMessage() for r in caplog.records if "web research refused" in r.getMessage()]
    assert len(refused) == 1 and f"turn_id={ctx.turn_id}" in refused[0]


async def test_the_turn_goes_on_and_the_gateway_refuses_the_model_call_as_before(
    engine: AsyncEngine, brave: ScriptedTools
) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    base = await _ctx(engine, ASK)
    spy = _SpyDispatch(base.dispatch)
    ctx = replace(base, user_id=await _unadmitted(maker, "trial_cap"), dispatch=spy)
    model = _ScriptedModel()
    adapters = {name: model for name in ("anthropic", "openai", "google")}
    seen: list[AgentEventType] = []

    with pytest.raises(TrialCapReachedError):
        async for event in LlmRunner(adapters=adapters).run(ctx):
            seen.append(event.type)

    # The refused research is a tool step, the context was packed, and the turn stopped where it
    # always stops for this user: at the model call. No web call, no model call, no spend.
    assert seen == [
        AgentEventType.TOOL_CALL,
        AgentEventType.TOOL_RESULT,
        AgentEventType.CONTEXT_USED,
    ]
    assert spy.calls == [] and brave.calls == [] and model.seen == []
    assert await _web_rows(engine) == []


async def test_a_cache_hit_serves_a_user_who_could_not_afford_the_call(
    engine: AsyncEngine, brave: ScriptedTools
) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    cache = ResearchCache(InMemoryCacheStore())
    base = await _ctx(engine, ASK, research_cache=cache)
    await cache.put(base.project_id, QUERY, _one_source_digest())
    spy = _SpyDispatch(base.dispatch)
    ctx = replace(base, user_id=await _unadmitted(maker, "trial_cap"), dispatch=spy)
    step = ResearchStep(
        ctx, missing=(), budget=_standard_budget(), limits=LIMITS, credits_per_call=2
    )

    events = [event async for event in step.events()]

    assert _kinds(events) == [
        AgentEventType.TOOL_CALL,
        AgentEventType.TOOL_RESULT,
        AgentEventType.RESEARCH_SOURCES,
    ]
    assert events[2].data["cached"] is True
    assert spy.calls == [] and brave.calls == [] and await _web_rows(engine) == []


@pytest.mark.parametrize("identity", ["user", "sessionmaker"])
async def test_a_turn_without_an_identity_does_not_research_and_says_so_once(
    engine: AsyncEngine, brave: ScriptedTools, identity: str, caplog: pytest.LogCaptureFixture
) -> None:
    _queue_one_page(brave)
    base = await _ctx(engine, ASK)
    spy = _SpyDispatch(base.dispatch)
    ctx = replace(base, dispatch=spy)
    ctx = replace(ctx, user_id=None) if identity == "user" else replace(ctx, sessionmaker=None)
    step = ResearchStep(
        ctx, missing=(), budget=_standard_budget(), limits=LIMITS, credits_per_call=2
    )

    with caplog.at_level(logging.INFO, logger="solus.agent.research"):
        events = [event async for event in step.events()]

    assert events == [] and step.digest is None  # no frames at all
    assert spy.calls == [] and brave.calls == [] and await _web_rows(engine) == []
    skipped = [r for r in caplog.records if "web research skipped" in r.getMessage()]
    assert len(skipped) == 1 and "no user identity" in skipped[0].getMessage()


# ------------------------------------------------------------------ the ledger


async def _debit(
    maker: async_sessionmaker[Any], user_id: uuid.UUID, digest: ResearchDigest, **kwargs: Any
) -> int:
    async with maker() as session:
        return await debit_web_calls(
            session,
            user_id,
            digest,
            call_id=kwargs.pop("call_id", "call-1"),
            turn_id=kwargs.pop("turn_id", uuid.uuid4()),
            project_id=kwargs.pop("project_id", uuid.uuid4()),
            credits_per_call=kwargs.pop("credits_per_call", 2),
        )


async def test_web_calls_debit_ledger(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user_id, project_id, turn_id = await _funded_user(maker), uuid.uuid4(), uuid.uuid4()

    # One row per Brave call: the first `searches_run` are searches, the rest context calls.
    digest = _one_source_digest(queries=3, searches=2)
    applied = await _debit(maker, user_id, digest, turn_id=turn_id, project_id=project_id)

    assert applied == 3
    rows = await _web_rows(engine)
    assert [r.idempotency_key for r in rows] == [f"web:call-1:{n}" for n in range(3)]
    assert [r.amount for r in rows] == [-2, -2, -2]
    assert [r.attrs["kind"] for r in rows] == ["search", "search", "context"]
    assert all(r.attrs["purpose"] == "web" for r in rows)
    assert all(r.attrs["turn_id"] == str(turn_id) for r in rows)
    assert all(r.attrs["project_id"] == str(project_id) for r in rows)

    # Replaying the turn's debits applies nothing twice.
    again = await _debit(maker, user_id, digest, turn_id=turn_id, project_id=project_id)
    assert again == 0 and len(await _web_rows(engine)) == 3

    # A free call still leaves its row — the data layer counts calls, not just credits.
    free_digest = _one_source_digest(queries=1, searches=1)
    free = await _debit(maker, user_id, free_digest, call_id="call-free", credits_per_call=0)
    assert free == 1
    assert [r.amount for r in await _web_rows(engine)][-1] == 0


async def test_a_turn_bills_each_brave_call_once_and_a_hit_bills_nothing(
    engine: AsyncEngine, brave: ScriptedTools
) -> None:
    _queue_one_page(brave)
    cache = ResearchCache(InMemoryCacheStore())
    base = await _ctx(engine, ASK, research_cache=cache)
    spy = _SpyDispatch(base.dispatch)
    ctx = replace(base, dispatch=spy)
    # The PROVISIONAL price is in the shipped yaml itself, not merely the field's default.
    raw = yaml.safe_load(Path(orchestration_config.__file__).with_name("models.yaml").read_text())
    assert raw["cost"]["web_call_credits"] == 2
    cost = gateway.default_orchestration_config().cost.web_call_credits
    assert cost == 2

    first = await _run(_ScriptedModel(), ctx)

    assert len(spy.calls) == 1  # an admitted user's miss is dispatched, once
    rows = await _web_rows(engine)
    assert len(rows) == 2 and [r.amount for r in rows] == [-cost, -cost]
    call_id = first[0].data["call_id"]
    assert {r.idempotency_key for r in rows} == {f"web:{call_id}:0", f"web:{call_id}:1"}
    assert {r.attrs["turn_id"] for r in rows} == {str(ctx.turn_id)}
    assert sorted(r.attrs["kind"] for r in rows) == ["context", "search"]

    await _run(_ScriptedModel(), replace(ctx, turn_id=uuid.uuid4()))  # a hit
    assert len(spy.calls) == 1 and len(await _web_rows(engine)) == 2


async def test_a_failed_debit_is_deferred_to_reconciliation_and_never_raised(
    engine: AsyncEngine, brave: ScriptedTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The calls were made and paid for, so a write that fails (here: the second) must neither
    fail the turn nor go missing: the first row is committed, the second is recorded as a pending
    debit for the sweep, and the sources still stream."""
    real = billing_credits.debit_credits

    async def flaky(
        session: Any, user_id: uuid.UUID, credits: int, *, idempotency_key: str, **kwargs: Any
    ) -> Any:
        if idempotency_key.endswith(":1"):
            raise RuntimeError("deadlock detected")
        return await real(session, user_id, credits, idempotency_key=idempotency_key, **kwargs)

    monkeypatch.setattr(research_module, "debit_credits", flaky)
    _queue_one_page(brave)

    events = await _run(_ScriptedModel(), await _ctx(engine, ASK))

    call_id = events[0].data["call_id"]
    assert AgentEventType.RESEARCH_SOURCES in _kinds(events)
    assert events[-1].type is AgentEventType.MESSAGE
    assert [r.idempotency_key for r in await _web_rows(engine)] == [f"web:{call_id}:0"]
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        pending = list(await db.scalars(select(PendingCreditDebit)))
    (deferred,) = pending
    assert deferred.idempotency_key == f"web:{call_id}:1" and deferred.credits == 2
    assert deferred.status is DebitReconcileStatus.PENDING
    assert deferred.attrs["purpose"] == "web" and deferred.attrs["kind"] == "context"


async def test_debit_web_calls_counts_what_it_applied_and_survives_a_dead_letter_failure(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user_id = await _funded_user(maker)
    real = billing_credits.debit_credits

    async def flaky(
        session: Any, user_id: uuid.UUID, credits: int, *, idempotency_key: str, **kwargs: Any
    ) -> Any:
        if idempotency_key.endswith(":1"):
            raise RuntimeError("deadlock detected")
        return await real(session, user_id, credits, idempotency_key=idempotency_key, **kwargs)

    monkeypatch.setattr(research_module, "debit_credits", flaky)
    digest = _one_source_digest(queries=2, searches=1)

    assert await _debit(maker, user_id, digest, call_id="c1") == 1  # the second was deferred

    async def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(research_module, "record_failed_debit", broken)
    with caplog.at_level(logging.ERROR, logger="solus.agent.research"):
        assert await _debit(maker, user_id, digest, call_id="c2") == 1  # still no raise
    lost = [r.getMessage() for r in caplog.records if "could not record" in r.getMessage()]
    assert len(lost) == 1 and "web:c2:1" in lost[0] and str(user_id) in lost[0]
    assert [r.idempotency_key for r in await _web_rows(engine)] == ["web:c1:0", "web:c2:0"]


# ------------------------------------------------------------------ turns that never spend


async def test_a_solus_authored_turn_never_researches_whatever_it_says(
    engine: AsyncEngine, brave: ScriptedTools
) -> None:
    """A wake or resume prompt embeds a ticket's program, not the person's words: the route marks
    it `research_allowed=False`, and neither "search" in it nor a `/web` query can reach the web."""
    program = "Resume ticket 7. Step 2: search the OV9281 errata, then flash the board."
    ctx = await _ctx(engine, program, research_allowed=False, research_query="OV9281 errata")

    events = await _run(_ScriptedModel(), ctx)

    assert brave.calls == [] and await _web_rows(engine) == []
    assert AgentEventType.TOOL_CALL not in _kinds(events)
    assert events[-1].type is AgentEventType.MESSAGE


async def test_a_query_that_is_only_a_key_is_not_searched_billed_or_shown(
    engine: AsyncEngine, brave: ScriptedTools
) -> None:
    key = "AKIA" + string.ascii_uppercase[:8] + string.digits[:8]
    ctx = await _ctx(engine, f"/web {key}", research_query=key)

    events = await _run(_ScriptedModel(), ctx)

    assert brave.calls == [] and await _web_rows(engine) == []
    assert not {AgentEventType.TOOL_CALL, AgentEventType.RESEARCH_SOURCES} & set(_kinds(events))
    assert events[-1].type is AgentEventType.MESSAGE
