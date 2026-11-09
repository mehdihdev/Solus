"""What one turn has spent against its ceilings (SOLUSDEV-321 P1-T3).

Pure: no I/O, no model, no clock. The runner notes each unit it spends and asks `check()` once a
round; what a hit means — announce it, then run the closing round without tools — is the runner's.
The ceilings are `TurnLimits` (agent/turn_limits.py), chosen by the server; nothing here is ever
read from the request.
"""

from dataclasses import dataclass
from typing import Literal

from solus_api.agent.turn_limits import TurnLimits

#: The ceilings a turn can reach, in the order `check()` reports them.
BudgetLimit = Literal[
    "tool_calls", "model_calls", "web_searches", "web_fetches", "input_tokens", "model_rounds"
]


@dataclass(frozen=True, slots=True)
class BudgetHit:
    """The ceiling a turn has reached: what it used against what it was allowed."""

    limit: BudgetLimit
    used: int
    cap: int


class TurnBudget:
    """One turn's counters. Rounds, tool calls, model calls and web calls only grow;
    `input_tokens` is the round in hand's alone and is replaced every round."""

    def __init__(self, limits: TurnLimits) -> None:
        self.limits = limits
        self.model_rounds = 0
        self.tool_calls = 0
        self.model_calls = 0
        self.web_searches = 0
        self.web_fetches = 0
        self.input_tokens = 0

    def note_model_round(self) -> None:
        """The round about to run. Noted before `check()`, so it counts against its own cap."""
        self.model_rounds += 1

    def note_model_call(self) -> None:
        """One gateway call carrying this turn's id: a round, the planner's tie-break, a screen
        read — noted where the call is made, before it starts. A round's call is noted before
        `check()`, so the call about to be made counts against its own cap."""
        self.model_calls += 1

    def note_tool_calls(self, n: int) -> None:
        self.tool_calls += n

    def note_web(self, searches: int = 0, fetches: int = 0) -> None:
        self.web_searches += searches
        self.web_fetches += fetches

    def note_input_tokens(self, n: int) -> None:
        """The input of the round about to be sent. It replaces the last round's, never adds."""
        self.input_tokens = n

    def check(self) -> BudgetHit | None:
        """The first ceiling the turn has reached, in the order of `BudgetLimit`, or None.

        What the runner refuses for itself — tool calls, model calls, rounds — is reached once
        the allowance is spent. For tool calls that is after the last allowed one ran; for model
        calls and rounds the runner notes the one about to run first, so `used == cap` means it
        IS the last allowed — it becomes the closing round and the cap holds exactly (only a
        cap already spent before round 1 can be passed, by that one closing call). What is
        spent elsewhere — web calls, which the research tool meters, and the input tokens of
        the call about to be made — is reached only when over its cap."""
        limits = self.limits
        counters: tuple[tuple[BudgetLimit, int, int, bool], ...] = (
            ("tool_calls", self.tool_calls, limits.tool_calls, True),
            ("model_calls", self.model_calls, limits.max_model_calls, True),
            ("web_searches", self.web_searches, limits.web_searches, False),
            ("web_fetches", self.web_fetches, limits.web_fetches, False),
            ("input_tokens", self.input_tokens, limits.max_input_tokens, False),
            ("model_rounds", self.model_rounds, limits.model_rounds, True),
        )
        for limit, used, cap, spent_is_hit in counters:
            if used > cap or (spent_is_hit and used == cap):
                return BudgetHit(limit, used, cap)
        return None
