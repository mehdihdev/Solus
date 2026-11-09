# SOLUSDEV-321 (P0-T2) — every model call names WHY it ran (`purpose`), and the
# gateway threads `purpose` + `turn_id` onto the `model call start` log line and the
# credit-ledger attrs, so spend can be counted per purpose and per turn.
#
# The sweep is an AST walk over packages/api/src. Heuristic (documented because a
# static walk cannot resolve every call): a call is "the gateway's" when
#   * it is a bare name bound by `from solus_api.orchestration[.gateway] import
#     complete|stream [as x]` anywhere in the file (module level or inside a function),
#   * it is `<obj>.complete(` / `<obj>.stream(` with <obj> named gateway, llm or runner, or
#   * it is a bare `complete(` / `stream(` inside orchestration/gateway.py itself
#     (`complete()` delegates to `stream()`).
# Lookalikes (httpx `client.stream`, the CAD-refresh job's own `complete` in
# connectors/worker.py, a router's local `stream()`) are not bound to the gateway and
# are ignored. `**kwargs` does not count as naming the purpose.
from __future__ import annotations

import ast
import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import CreditLedger, PlanType, Subscription, SubscriptionStatus, User
from solus_api.orchestration.config import CostConfig, ModelCatalogEntry, OrchestrationConfig
from solus_api.orchestration.gateway import complete, stream
from solus_api.orchestration.providers import ImageBlock, ToolConversation, ToolUse, Usage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_SRC = Path(__file__).resolve().parents[1] / "src"
_GATEWAY_MODULES = frozenset({"solus_api.orchestration", "solus_api.orchestration.gateway"})
_CALLEES = frozenset({"complete", "stream"})
_GATEWAY_OBJECTS = frozenset({"gateway", "llm", "runner"})
#: One known site per way of reaching the gateway, so a broken heuristic cannot pass
#: the sweep vacuously.
_KNOWN_SITES = {
    "solus_api/agent/runtime.py",  # gateway.stream(…)
    "solus_api/agent/screen.py",  # gateway.complete(…)
    "solus_api/livebench/runs/narration.py",  # module-level `from … import complete`
    "solus_api/toolkb/ingest/visual.py",  # `from … import complete` inside a function
    "solus_api/orchestration/gateway.py",  # complete() → stream()
}


def _imported_callees(tree: ast.AST) -> set[str]:
    return {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module in _GATEWAY_MODULES
        for alias in node.names
        if alias.name in _CALLEES
    }


def _is_gateway_call(func: ast.expr, names: set[str]) -> bool:
    if isinstance(func, ast.Name):
        return func.id in names
    return (
        isinstance(func, ast.Attribute)
        and func.attr in _CALLEES
        and isinstance(func.value, ast.Name)
        and func.value.id in _GATEWAY_OBJECTS
    )


def gateway_calls(source: str, *, is_gateway_module: bool = False) -> list[ast.Call]:
    tree = ast.parse(source)
    names = _imported_callees(tree) | (_CALLEES if is_gateway_module else set())
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_gateway_call(node.func, names)
    ]


def _names_purpose(call: ast.Call) -> bool:
    return any(keyword.arg == "purpose" for keyword in call.keywords)


def _calls_by_file() -> dict[str, list[ast.Call]]:
    """Every gateway call under packages/api/src, keyed by file (relative to src)."""
    by_file: dict[str, list[ast.Call]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        is_gateway_module = path.name == "gateway.py" and path.parent.name == "orchestration"
        found = gateway_calls(path.read_text(), is_gateway_module=is_gateway_module)
        if found:
            by_file[str(path.relative_to(_SRC))] = found
    return by_file


def test_every_complete_or_stream_call_under_src_passes_purpose() -> None:
    by_file = _calls_by_file()
    assert _KNOWN_SITES <= by_file.keys()
    unnamed = [
        f"{path}:{call.lineno}"
        for path, calls in by_file.items()
        for call in calls
        if not _names_purpose(call)
    ]
    assert unnamed == [], f"gateway calls without an explicit purpose=: {unnamed}"


#: SOLUSDEV-321 P8 (R148): the rule this pin enforces — every gateway call under `agent/` names
#: `project_id=` explicitly: the runner's own `ctx.project_id`, a tool's own project, or the turn's
#: bound one (`turn_context.current_project_id()`, which `with_turn` binds beside the turn's id).
#: Each of them is a SOL call made for one project, so its usage row is listed under it.
_AGENT_PREFIX = "solus_api/agent/"


def test_every_gateway_call_under_agent_names_its_project() -> None:
    by_file = _calls_by_file()
    agent = {path: calls for path, calls in by_file.items() if path.startswith(_AGENT_PREFIX)}
    assert {"solus_api/agent/runtime.py", "solus_api/agent/screen.py"} <= agent.keys()
    unnamed = [
        f"{path}:{call.lineno}"
        for path, calls in agent.items()
        for call in calls
        if not any(keyword.arg == "project_id" for keyword in call.keywords)
    ]
    assert unnamed == [], f"agent gateway calls without an explicit project_id=: {unnamed}"


#: What each existing caller's call IS, so the ledger's `purpose` means something.
#: A new call site needs no entry here — the sweep above only requires that it names one.
_PURPOSE_OF = {
    "solus_api/agent/runtime.py": "answer",  # the SOL turn itself
    "solus_api/sourcing/engine.py": "answer",  # a user-requested sourcing question
    "solus_api/agent/screen.py": "vision",  # read a screenshot
    "solus_api/agent/vision/vision_extract.py": "vision",  # read one labelled render (P5)
    "solus_api/fingerprint/visual.py": "vision",  # read part markings off a photo
    "solus_api/toolkb/ingest/visual.py": "vision",  # read a tool photo
    "solus_api/agent/documents/extract.py": "extract",  # pull facts from a document page
    "solus_api/fingerprint/escalation.py": "extract",  # pull a base MPN out of a marking
    "solus_api/livebench/runs/narration.py": "narration",  # explain bench findings
    "solus_api/impact/consequences.py": "narration",  # explain impact consequences
}
#: A caller whose calls do more than one job (SOLUSDEV-321 P1-T1): the runner's closure that
#: puts a HARD turn's tied names to a model once, for the scope planner.
_ALSO_PURPOSE: dict[str, set[str]] = {"solus_api/agent/runtime.py": {"planner"}}


def test_each_existing_caller_names_the_purpose_of_its_job() -> None:
    by_file = _calls_by_file()
    named = {
        path: {
            keyword.value.value
            for call in by_file[path]
            for keyword in call.keywords
            if keyword.arg == "purpose" and isinstance(keyword.value, ast.Constant)
        }
        for path in _PURPOSE_OF
    }
    assert named == {
        path: {purpose, *_ALSO_PURPOSE.get(path, set())} for path, purpose in _PURPOSE_OF.items()
    }


def test_the_sweep_flags_a_call_without_purpose() -> None:
    source = (
        "from solus_api.orchestration.gateway import complete\n"
        "async def f(extra):\n"
        "    await complete('q', user_id=1)\n"
        "    await complete('q', purpose='vision')\n"
        "    await complete('q', **extra)\n"
    )
    flagged = [call.lineno for call in gateway_calls(source) if not _names_purpose(call)]
    assert flagged == [3, 5]


def test_the_sweep_resolves_aliases_and_ignores_lookalikes() -> None:
    source = (
        "from solus_api.orchestration import gateway, complete as ask\n"
        "from solus_api.livebench.scene.cad_refresh import stream\n"
        "ask('q')\n"
        "gateway.stream('q')\n"
        "llm.complete('q')\n"
        "stream()\n"
        "client.stream('GET')\n"
        "worker.complete(1)\n"
    )
    assert [call.lineno for call in gateway_calls(source)] == [3, 4, 5]


class _ScriptedAdapter:
    """A provider adapter that replays one canned answer with fixed usage — no network."""

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Sequence[ImageBlock] | None = None,
        conversation: ToolConversation | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[str | ToolUse | Usage]:
        yield "ok"
        yield Usage(tokens_in=7, tokens_out=9)


def _config() -> OrchestrationConfig:
    return OrchestrationConfig(
        version=1,
        catalog=[
            ModelCatalogEntry(
                provider="anthropic",
                name="scripted-model",
                price_in=1.0,
                price_out=2.0,
                context_window=100_000,
                roles=["only_role"],
            )
        ],
        matrix={},
        default_role="only_role",
        cost=CostConfig(credits_per_dollar=100.0),
    )


async def _funded_user(db: AsyncSession) -> uuid.UUID:
    tag = uuid.uuid4().hex[:10]
    user = User(supabase_user_id=f"sub-{tag}", email=f"{tag}@example.com")
    db.add(user)
    await db.flush()
    user_id = user.id
    db.add(Subscription(user_id=user_id, plan=PlanType.BASIC, status=SubscriptionStatus.TRIALING))
    await db.commit()
    return user_id


async def _ledger_attrs(db: AsyncSession, call_id: str) -> dict[str, Any]:
    row = await db.scalar(select(CreditLedger).where(CreditLedger.idempotency_key == call_id))
    assert row is not None, "the scripted call should have been debited"
    return dict(row.attrs)


async def test_purpose_and_turn_id_reach_track_cost_meta(db: AsyncSession) -> None:
    turn_id = uuid.uuid4()
    result = await complete(
        "hi",
        secret_store=InMemorySecretStore(),
        config=_config(),
        adapters={"anthropic": _ScriptedAdapter()},
        user_id=await _funded_user(db),
        session=db,
        purpose="planner",
        turn_id=turn_id,
    )
    attrs = await _ledger_attrs(db, result.call_id)
    assert attrs["purpose"] == "planner"
    assert attrs["turn_id"] == str(turn_id)
    # The billing keys are untouched.
    assert attrs["call_id"] == result.call_id
    assert (attrs["tokens_in"], attrs["tokens_out"]) == (7, 9)


async def test_an_unlabelled_call_is_an_answer_with_no_turn_id(db: AsyncSession) -> None:
    result = await complete(
        "hi",
        secret_store=InMemorySecretStore(),
        config=_config(),
        adapters={"anthropic": _ScriptedAdapter()},
        user_id=await _funded_user(db),
        session=db,
    )
    attrs = await _ledger_attrs(db, result.call_id)
    assert attrs["purpose"] == "answer"
    assert "turn_id" not in attrs


def _start_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        message
        for record in caplog.records
        if (message := record.getMessage()).startswith("model call start")
    ]


async def test_purpose_on_log_line(caplog: pytest.LogCaptureFixture) -> None:
    turn_id = uuid.uuid4()
    with caplog.at_level(logging.INFO, logger="solus.orchestration.gateway"):
        await complete(
            "hi",
            secret_store=InMemorySecretStore(),
            config=_config(),
            adapters={"anthropic": _ScriptedAdapter()},
            purpose="narration",
            turn_id=turn_id,
        )
    (line,) = _start_lines(caplog)
    assert "purpose=narration" in line
    assert f"turn_id={turn_id}" in line


async def test_stream_logs_purpose_and_the_defaults(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="solus.orchestration.gateway"):
        chunks = stream(
            "hi",
            secret_store=InMemorySecretStore(),
            config=_config(),
            adapters={"anthropic": _ScriptedAdapter()},
        )
        assert [chunk async for chunk in chunks] == ["ok"]
    (line,) = _start_lines(caplog)
    assert "purpose=answer" in line
    assert "turn_id=None" in line
