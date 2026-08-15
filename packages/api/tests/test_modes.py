# SOLUSDEV-200 (SOLX-01) — the Guide/Do action-mode layer. Guide explains and
# points; Do operates the tool. The property under test is structural: in Guide
# mode the dispatch closure a runner holds refuses mutating tools BEFORE the
# (already gated) dispatcher is even reached, so "Guide never dispatches a
# mutation" is unwritable rather than merely forbidden. Do mode passes through
# to the CTR-03 gate untouched — the mode layer composes OUTSIDE the gate and
# cannot weaken it.
from __future__ import annotations

import dataclasses
import logging
from typing import Any

import pytest
from solus_api.agent.modes import ActionMode, build_mode_dispatch
from solus_api.agent.runtime import AgentRunContext, build_dispatch
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import (
    ToolCall,
    ToolDescriptor,
    ToolErrorCode,
)
from solus_api.agent.tools.tool import InProcessTool

MUTATING = ToolDescriptor(
    name="onshape.set_variable",
    description="Change a Variable Studio value.",
    params={"type": "object", "properties": {"name": {"type": "string"}}},
    returns={"type": "object"},
    requires_confirmation=True,
)
READ_ONLY = ToolDescriptor(
    name="onshape.get_variables",
    description="Read variables.",
    params={"type": "object", "properties": {}},
    returns={"type": "object"},
)


def _registry(executed: list[str]) -> ToolRegistry:
    async def mutate(args: dict[str, Any]) -> dict[str, Any]:
        executed.append("mutate")
        return {"changed": True}

    async def read(args: dict[str, Any]) -> dict[str, Any]:
        executed.append("read")
        return {"variables": []}

    registry = ToolRegistry()
    registry.register(InProcessTool(MUTATING, mutate))
    registry.register(InProcessTool(READ_ONLY, read))
    return registry


def _mode_dispatch(mode: ActionMode, executed: list[str]):  # type: ignore[no-untyped-def]
    registry = _registry(executed)
    return build_mode_dispatch(mode, (MUTATING, READ_ONLY), build_dispatch(registry, None))


async def test_guide_never_dispatches_a_mutation() -> None:
    executed: list[str] = []
    dispatch = _mode_dispatch(ActionMode.GUIDE, executed)
    result = await dispatch(ToolCall(tool="onshape.set_variable", args={"name": "width"}))
    assert executed == []  # the acceptance line, verbatim
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED
    assert "guide" in result.error.message.lower()
    assert result.error.retryable is False


async def test_guide_dispatches_read_only_tools() -> None:
    executed: list[str] = []
    dispatch = _mode_dispatch(ActionMode.GUIDE, executed)
    result = await dispatch(ToolCall(tool="onshape.get_variables", args={}))
    assert executed == ["read"]
    assert result.ok is True


async def test_do_mode_still_hits_the_confirmation_gate() -> None:
    # Do mode is not a bypass: the mode layer wraps the ALREADY-gated dispatch,
    # so a mutating call in Do mode reaches the CTR-03 gate (flat refusal here,
    # park when a ParkFn is wired) and the tool still never runs unconfirmed.
    executed: list[str] = []
    dispatch = _mode_dispatch(ActionMode.DO, executed)
    result = await dispatch(ToolCall(tool="onshape.set_variable", args={"name": "width"}))
    assert executed == []
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED
    assert "confirmation" in result.error.message


async def test_do_mode_dispatches_read_only_tools() -> None:
    executed: list[str] = []
    dispatch = _mode_dispatch(ActionMode.DO, executed)
    result = await dispatch(ToolCall(tool="onshape.get_variables", args={}))
    assert executed == ["read"]
    assert result.ok is True


async def test_unknown_tool_falls_through_to_the_dispatcher() -> None:
    # A tool the mode layer has no descriptor for is not silently trusted as
    # read-only forever — it falls through to the gated dispatcher, whose
    # registry answers NOT_FOUND. Nothing runs.
    executed: list[str] = []
    dispatch = _mode_dispatch(ActionMode.GUIDE, executed)
    result = await dispatch(ToolCall(tool="no.such_tool", args={}))
    assert executed == []
    assert result.ok is False


async def test_every_action_is_logged_with_its_mode(caplog: pytest.LogCaptureFixture) -> None:
    # Acceptance: "the chosen mode is explicit and logged per action" — and the
    # agent-tool contract assigns `agent.tool_invoked` emission to the SOL loop.
    # §7: identifiers and outcomes only, never argument values.
    executed: list[str] = []
    dispatch = _mode_dispatch(ActionMode.GUIDE, executed)
    with caplog.at_level(logging.INFO, logger="solus.agent.modes"):
        await dispatch(ToolCall(tool="onshape.set_variable", args={"name": "SECRET-ARG"}))
        await dispatch(ToolCall(tool="onshape.get_variables", args={}))
    events = [r for r in caplog.records if r.message.startswith("agent.tool_invoked")]
    assert len(events) == 2
    refused, dispatched = events[0].message, events[1].message
    assert "mode=guide" in refused
    assert "tool=onshape.set_variable" in refused
    assert "mode_refused=True" in refused
    assert "mode_refused=False" in dispatched
    assert "SECRET-ARG" not in refused and "SECRET-ARG" not in dispatched


def test_run_context_carries_an_explicit_action_mode_defaulting_to_guide() -> None:
    fields = {f.name: f for f in dataclasses.fields(AgentRunContext)}
    assert "action_mode" in fields
    assert fields["action_mode"].default is ActionMode.GUIDE
    # The structural-gate invariants hold unchanged.
    assert "registry" not in fields
    assert {"tools", "dispatch"} <= set(fields)
