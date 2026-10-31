"""SOLUSDEV-321 P3-T4 fix 1 (R83) — the SOL turn a call runs in.

`LlmRunner.run` binds the turn's id around each call the model proposes (`with_turn`, R75). Every
model call made inside that call reads it (`current_turn_id`): a tool's own, and the shared page
extractor's (`agent/documents/extract.py`). Their ledger rows are therefore attributed to the turn
that asked; each also takes one of the turn's calls first (`PerceptionTurn.take_model_call`,
below — the page extractor and `label_motifs` too, M122), so it counts against its budget. The
turn's project is bound beside its id
(`current_project_id`, SOLUSDEV-321 P8, R148), so those rows also name the project whose usage lists
them. Outside a turn nothing is bound.

Beside the id, the runner binds the turn's perception (SOLUSDEV-321 P5, R125: `with_perception`):
the turn's own budget, which a tool's model call is noted on (`PerceptionTurn.take_model_call`, so
it counts against `max_model_calls` and never spends the closing round's call), and the reason
renders are off this turn, when the scope planner decided they are (connectivity and counting
come from the graph, never from pixels). It carries the person's `Code style` preference too
(SOLUSDEV-321 P6, R134), so a tool that writes code reads it from the turn, never from the model.

The module is neutral: it imports nothing from Solus at run time, so the runtime, the tools and
the documents layer all read the one variable.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from solus_api.agent.turn_budget import TurnBudget

_TURN: Final[ContextVar[uuid.UUID | None]] = ContextVar("sol_turn_id", default=None)
#: The turn's project, bound beside its id (SOLUSDEV-321 P8, R148): a tool's own model call names
#: it on its ledger row, so the turn's usage lists the call under its project.
_PROJECT: Final[ContextVar[uuid.UUID | None]] = ContextVar("sol_turn_project_id", default=None)

#: Why a turn looks at no render (P5, R104): the scope planner's `exclude_renders` and `counting`.
CONNECTIVITY_REFUSAL: Final = (
    "connectivity comes from the graph's wires, never from pixels: no render this turn"
)
COUNTING_REFUSAL: Final = "counts come from the graph, never from pixels: no render this turn"


@dataclass(frozen=True, slots=True)
class PerceptionTurn:
    """What a tool's perception may spend and look at in the turn it runs in (P5, R125): the
    turn's own budget, and why renders are off this turn, when they are."""

    budget: TurnBudget
    renders_refused: str | None = None
    #: The person's `Code style` preference for this turn (P6, R134); "" when they state none.
    code_style: str = ""

    def take_model_call(self) -> bool:
        """One model call for a tool, noted on the turn's budget so it counts against
        `max_model_calls`. Never the closing round's: False, with nothing noted, when that call
        is the only one left (the runner notes each round's call before it runs it)."""
        if self.budget.model_calls + 1 >= self.budget.limits.max_model_calls:
            return False
        self.budget.note_model_call()
        return True


_PERCEPTION: Final[ContextVar[PerceptionTurn | None]] = ContextVar(
    "sol_turn_perception", default=None
)


def current_turn_id() -> uuid.UUID | None:
    """The SOL turn a call is running in, or None outside one."""
    return _TURN.get()


def current_project_id() -> uuid.UUID | None:
    """The project of the SOL turn a call is running in, or None outside one (R148)."""
    return _PROJECT.get()


@contextmanager
def bind_turn_id(turn_id: uuid.UUID, project_id: uuid.UUID | None = None) -> Iterator[None]:
    """`turn_id` and the turn's `project_id` bound for the block (None names no project); the
    bindings before them come back after, even on a raise."""
    token, project = _TURN.set(turn_id), _PROJECT.set(project_id)
    try:
        yield
    finally:
        _PROJECT.reset(project)
        _TURN.reset(token)


def with_turn[T, R](
    dispatch: Callable[[T], Awaitable[R]], turn_id: uuid.UUID, project_id: uuid.UUID
) -> Callable[[T], Awaitable[R]]:
    """`dispatch`, with `turn_id` and the turn's `project_id` bound while each call runs (R75,
    R148)."""

    async def bound(call: T) -> R:
        with bind_turn_id(turn_id, project_id):
            return await dispatch(call)

    return bound


def current_perception() -> PerceptionTurn | None:
    """The perception of the SOL turn a call is running in, or None outside one."""
    return _PERCEPTION.get()


@contextmanager
def bind_perception(turn: PerceptionTurn) -> Iterator[None]:
    """`turn` bound for the block; the binding before it comes back after, even on a raise."""
    token = _PERCEPTION.set(turn)
    try:
        yield
    finally:
        _PERCEPTION.reset(token)


def with_perception[T, R](
    dispatch: Callable[[T], Awaitable[R]],
    budget: TurnBudget,
    *,
    connectivity: bool,
    counting: bool,
    code_style: str = "",
) -> Callable[[T], Awaitable[R]]:
    """`dispatch`, with the turn's perception bound while each call runs (R125). `connectivity`
    and `counting` are the scope planner's `exclude_renders` and `counting`; `code_style` is the
    person's preference (P6, R134)."""
    refused = CONNECTIVITY_REFUSAL if connectivity else COUNTING_REFUSAL if counting else None
    turn = PerceptionTurn(budget, refused, code_style)

    async def bound(call: T) -> R:
        with bind_perception(turn):
            return await dispatch(call)

    return bound
