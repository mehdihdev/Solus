"""SOLUSDEV-322 P2-T2 — the per-call confirmation hook (`agent/dynamic_gate.py`).

A tool's descriptor flag (`requires_confirmation`) is static: the same answer for every call.
Simulator tools need a per-call answer — an action inside a Solus-owned session needs no card,
the same action inside a user-started one does — so a tool may carry a duck-typed
`needs_confirmation(args)` hook. The hook is consulted by the fused dispatch (Build parks, the
no-park fallback refuses) and by the Guide mode layer (refuses). It fails closed: an exception
or a timeout is a card. The static flag still wins without consulting the hook.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from solus_api.agent import dynamic_gate
from solus_api.agent.confirmations import request_confirmation
from solus_api.agent.dynamic_gate import current_call_id, needs_card
from solus_api.agent.modes import ActionMode, build_mode_dispatch
from solus_api.agent.runtime import DispatchFn, build_dispatch
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool
from solus_api.models import Project, Team, ToolConfirmation, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

UNGATED = ToolDescriptor(
    name="sim.step",
    description="Advance one session.",
    params={"type": "object", "properties": {"session_id": {"type": "string"}}},
    returns={"type": "object"},
)
STATIC_GATED = UNGATED.model_copy(update={"name": "sim.save", "requires_confirmation": True})

Hook = Callable[[dict[str, Any]], Awaitable[bool]]


class HookedTool(InProcessTool):
    """A fake with the duck-typed per-call hook; records what ran."""

    def __init__(self, descriptor: ToolDescriptor, hook: Hook, executed: list[str]) -> None:
        async def handler(args: dict[str, Any]) -> dict[str, Any]:
            executed.append(descriptor.name)
            return {"ok": True, "call_id": current_call_id.get()}

        super().__init__(descriptor, handler)
        self.needs_confirmation = hook


def _answering(answer: bool, seen: list[dict[str, Any]] | None = None) -> Hook:
    async def hook(args: dict[str, Any]) -> bool:
        if seen is not None:
            seen.append(args)
        return answer

    return hook


async def _echo_args(args: dict[str, Any]) -> dict[str, Any]:
    return args


def _one_tool_registry(tool: InProcessTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool)
    return registry


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _gate_scope(
    maker: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with maker() as db:
        user = User(supabase_user_id=f"sub-{uuid.uuid4()}", email=f"{uuid.uuid4()}@e.test")
        team = Team(name="T")
        db.add_all([user, team])
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.commit()
        return project.id, team.id, user.id


def _parking_dispatch(
    mode: ActionMode,
    registry: ToolRegistry,
    maker: async_sessionmaker[AsyncSession],
    scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> DispatchFn:
    """The production shape: mode layer outside, real `request_confirmation` as the park."""
    project_id, team_id, user_id = scope

    async def park(call: ToolCall) -> Any:
        async with maker() as db:
            parked = await request_confirmation(
                db, registry, call, project_id=project_id, team_id=team_id, user_id=user_id
            )
            await db.commit()
            return parked

    return build_mode_dispatch(
        mode, registry.list(), build_dispatch(registry, park), registry=registry
    )


async def _confirmation_rows(maker: async_sessionmaker[AsyncSession]) -> list[ToolConfirmation]:
    async with maker() as db:
        return list(await db.scalars(select(ToolConfirmation)))


# ----------------------------------------------------------------- the hook itself


async def test_static_flag_wins_without_consulting_the_hook() -> None:
    seen: list[dict[str, Any]] = []
    executed: list[str] = []
    tool = HookedTool(STATIC_GATED, _answering(False, seen), executed)

    assert await needs_card(tool, {"session_id": "s"}) is True
    result = await build_dispatch(_one_tool_registry(tool), None)(
        ToolCall(tool=STATIC_GATED.name, args={"session_id": "s"})
    )

    assert not result.ok and result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED
    assert seen == [] and executed == []


async def test_hook_exception_or_timeout_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    async def raising(args: dict[str, Any]) -> bool:
        raise RuntimeError("ledger unreachable")

    async def hanging(args: dict[str, Any]) -> bool:
        await asyncio.sleep(5)
        return False

    monkeypatch.setattr(dynamic_gate, "HOOK_TIMEOUT_SECONDS", 0.02)
    assert await needs_card(HookedTool(UNGATED, raising, []), {}) is True
    assert await needs_card(HookedTool(UNGATED, hanging, []), {}) is True
    # Sanity: a plain tool with no hook and no flag is never carded.
    assert await needs_card(InProcessTool(UNGATED, _echo_args), {}) is False


# -------------------------------------------------------------- the fused dispatch


async def test_no_park_fallback_refuses_when_hook_says_card() -> None:
    executed: list[str] = []
    carded = _one_tool_registry(HookedTool(UNGATED, _answering(True), executed))
    free = _one_tool_registry(HookedTool(UNGATED, _answering(False), executed))
    call = ToolCall(tool=UNGATED.name, args={"session_id": "s"})

    refused = await build_dispatch(carded, None)(call)
    assert not refused.ok and refused.error is not None
    assert refused.error.code is ToolErrorCode.UNAUTHORIZED
    assert "confirmation flow is not yet available" in refused.error.message
    assert executed == []

    assert (await build_dispatch(free, None)(call)).ok
    assert executed == [UNGATED.name]


async def test_current_call_id_is_set_inside_the_dispatch_and_cleared_after() -> None:
    executed: list[str] = []
    seen: list[str | None] = []

    async def hook(args: dict[str, Any]) -> bool:
        seen.append(current_call_id.get())
        return False

    tool = HookedTool(UNGATED, hook, executed)
    result = await build_dispatch(_one_tool_registry(tool), None)(
        ToolCall(tool=UNGATED.name, args={}, call_id="call-42")
    )

    assert result.ok and result.value == {"ok": True, "call_id": "call-42"}
    assert seen == ["call-42"]
    assert current_call_id.get() is None


async def test_hook_false_dispatches_without_a_card_in_build_and_guide(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    scope = await _gate_scope(maker)
    executed: list[str] = []
    registry = _one_tool_registry(HookedTool(UNGATED, _answering(False), executed))
    call = ToolCall(tool=UNGATED.name, args={"session_id": "owned"})

    for mode in (ActionMode.DO, ActionMode.GUIDE):
        result = await _parking_dispatch(mode, registry, maker, scope)(call)
        assert result.ok, mode

    assert executed == [UNGATED.name, UNGATED.name]
    assert await _confirmation_rows(maker) == []


async def test_hook_true_parks_in_build_and_refuses_in_guide(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    scope = await _gate_scope(maker)
    executed: list[str] = []
    registry = _one_tool_registry(HookedTool(UNGATED, _answering(True), executed))
    call = ToolCall(tool=UNGATED.name, args={"session_id": "attached"})

    parked = await _parking_dispatch(ActionMode.DO, registry, maker, scope)(call)
    assert not parked.ok and parked.error is not None
    assert parked.error.code is ToolErrorCode.UNAUTHORIZED
    assert "waiting for the person to approve" in parked.error.message
    rows = await _confirmation_rows(maker)
    assert [(r.tool, r.args, r.project_id) for r in rows] == [
        (UNGATED.name, {"session_id": "attached"}, scope[0])
    ]

    refused = await _parking_dispatch(ActionMode.GUIDE, registry, maker, scope)(call)
    assert not refused.ok and refused.error is not None
    assert refused.error.code is ToolErrorCode.UNAUTHORIZED
    assert "Guide mode can explain" in refused.error.message
    assert len(await _confirmation_rows(maker)) == 1, "Guide never reaches the park"
    assert executed == []


async def test_guide_without_a_registry_keeps_the_static_semantics() -> None:
    """Existing callers pass three positional args; the hook is then not consulted."""
    executed: list[str] = []
    registry = _one_tool_registry(HookedTool(UNGATED, _answering(True), executed))
    dispatch = build_mode_dispatch(
        ActionMode.GUIDE, registry.list(), build_dispatch(registry, None)
    )

    result = await dispatch(ToolCall(tool=UNGATED.name, args={}))

    # The mode layer let it through; the no-park fallback inside still carded it.
    assert not result.ok and result.error is not None
    assert "confirmation flow is not yet available" in result.error.message
    assert executed == []


def test_approval_required_rows_are_recognised_by_label_only() -> None:
    """P10 item 22: a preview row labelled `APPROVAL_REQUIRED_LABEL` (ADR-040 §5) is what a sim
    hook honours; the label is one constant, shared with `execution_policy`."""
    from solus_api.agent import execution_policy
    from solus_api.agent.dynamic_gate import APPROVAL_REQUIRED_LABEL, approval_required

    assert execution_policy.APPROVAL_REQUIRED_LABEL is APPROVAL_REQUIRED_LABEL
    demanded = {"label": APPROVAL_REQUIRED_LABEL, "before": None, "after": "saves the world"}
    assert approval_required([{"label": "x", "before": 1, "after": 2}, demanded])
    assert not approval_required([{"label": "Approval required.", "before": 1, "after": 2}])
    assert not approval_required([{"after": APPROVAL_REQUIRED_LABEL}, "Approval required", None])
    assert not approval_required([])
