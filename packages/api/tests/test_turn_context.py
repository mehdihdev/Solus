"""SOLUSDEV-321 P3-T4 fix 1 (R83) — `agent/turn_context.py`: the SOL turn a call runs in.

`LlmRunner.run` binds the turn's id around each call the model proposes. A tool's own model call,
and the shared page extractor's, read it, so their ledger rows are attributed to that turn. Outside
a turn nothing is bound.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace

import pytest
from solus_api.agent.modes import ActionMode
from solus_api.agent.turn_budget import TurnBudget
from solus_api.agent.turn_context import (
    CONNECTIVITY_REFUSAL,
    COUNTING_REFUSAL,
    PerceptionTurn,
    bind_perception,
    bind_turn_id,
    current_perception,
    current_project_id,
    current_turn_id,
    with_perception,
    with_turn,
)
from solus_api.agent.turn_limits import turn_limits


def _budget(max_model_calls: int) -> TurnBudget:
    return TurnBudget(replace(turn_limits(ActionMode.GUIDE), max_model_calls=max_model_calls))


async def test_a_call_sees_the_turns_perception_only_while_it_runs() -> None:
    """SOLUSDEV-321 P5 (R125): beside the turn's id, the runner binds what a tool's perception may
    spend — the turn's own budget — and whether renders are off this turn."""
    budget = _budget(6)
    seen: list[PerceptionTurn | None] = []

    async def dispatch(call: str) -> str:
        seen.append(current_perception())
        return call

    bound = with_perception(dispatch, budget, connectivity=False, counting=False)

    assert await bound("the call") == "the call"
    (turn,) = seen
    assert turn is not None and turn.budget is budget and turn.renders_refused is None
    assert current_perception() is None


@pytest.mark.parametrize(
    ("connectivity", "counting", "reason"),
    [
        (True, False, CONNECTIVITY_REFUSAL),
        (False, True, COUNTING_REFUSAL),
        (True, True, CONNECTIVITY_REFUSAL),
        (False, False, None),
    ],
)
async def test_the_planners_flags_say_why_renders_are_off(
    connectivity: bool, counting: bool, reason: str | None
) -> None:
    """Connectivity never comes from pixels and counts come from the graph: the scope planner's
    `exclude_renders` and `counting` become the reason the turn looks at no render."""
    seen: list[str | None] = []

    async def dispatch(call: str) -> None:
        turn = current_perception()
        seen.append(turn.renders_refused if turn is not None else "unbound")

    await with_perception(dispatch, _budget(6), connectivity=connectivity, counting=counting)("c")
    assert seen == [reason]


async def test_with_perception_binds_the_turns_code_style() -> None:
    """SOLUSDEV-321 P6 (R134): the person's `Code style` preference rides with the turn, so a tool
    that writes code (`firmware_recipe`) reads it from the turn and never from the model."""
    seen: list[str] = []

    async def dispatch(call: str) -> None:
        turn = current_perception()
        seen.append(turn.code_style if turn is not None else "unbound")

    styled = with_perception(
        dispatch, _budget(6), connectivity=False, counting=False, code_style="tabs, no macros"
    )
    await styled("c")
    await with_perception(dispatch, _budget(6), connectivity=False, counting=False)("c")
    assert seen == ["tabs, no macros", ""] and PerceptionTurn(_budget(6)).code_style == ""


def test_a_tools_model_call_counts_and_never_takes_the_closing_rounds() -> None:
    """A tool's call is noted on the turn's own budget, so it counts against `max_model_calls`;
    the closing round's call is never the tool's to spend."""
    budget = _budget(3)
    budget.note_model_call()  # round 1, noted by the runner before it ran
    turn = PerceptionTurn(budget)

    assert turn.take_model_call() is True
    assert budget.model_calls == 2
    # Only the closing round's call is left: refused, and nothing noted.
    assert turn.take_model_call() is False
    assert budget.model_calls == 2


def test_perception_is_unbound_outside_a_turn_and_after_its_block() -> None:
    assert current_perception() is None
    turn = PerceptionTurn(_budget(6))
    with bind_perception(turn):
        assert current_perception() is turn
    assert current_perception() is None


def test_nothing_is_bound_outside_a_turn() -> None:
    assert current_turn_id() is None


def test_a_bound_turn_reads_inside_its_block_and_unbinds_after() -> None:
    outer, inner = uuid.uuid4(), uuid.uuid4()
    with bind_turn_id(outer):
        assert current_turn_id() == outer
        with bind_turn_id(inner):
            assert current_turn_id() == inner
        assert current_turn_id() == outer
    assert current_turn_id() is None


def test_a_block_that_raises_still_unbinds() -> None:
    with pytest.raises(RuntimeError), bind_turn_id(uuid.uuid4()):
        raise RuntimeError("the call failed")
    assert current_turn_id() is None


async def test_with_turn_binds_the_id_and_the_project_only_while_each_call_runs() -> None:
    """Beside the turn's id, the turn's project (SOLUSDEV-321 P8, R148): a tool's own model call
    names both on its ledger row, so the turn's usage lists it under its project. A binding that
    names no project leaves none bound."""
    turn_id, project_id = uuid.uuid4(), uuid.uuid4()
    seen: list[tuple[uuid.UUID | None, uuid.UUID | None]] = []

    async def dispatch(call: str) -> str:
        seen.append((current_turn_id(), current_project_id()))
        return call

    assert await with_turn(dispatch, turn_id, project_id)("the call") == "the call"
    with bind_turn_id(turn_id):
        seen.append((current_turn_id(), current_project_id()))
    assert seen == [(turn_id, project_id), (turn_id, None)]
    assert (current_turn_id(), current_project_id()) == (None, None)


async def test_two_turns_running_at_once_each_read_their_own_id() -> None:
    """A context variable is per task, so one person's turn never attributes a call to another's
    turn or project."""
    first, second = uuid.uuid4(), uuid.uuid4()
    seen: dict[str, tuple[uuid.UUID | None, uuid.UUID | None]] = {}

    async def dispatch(name: str) -> None:
        await asyncio.sleep(0)
        seen[name] = (current_turn_id(), current_project_id())

    await asyncio.gather(
        with_turn(dispatch, first, second)("first"), with_turn(dispatch, second, first)("second")
    )
    assert seen == {"first": (first, second), "second": (second, first)}
