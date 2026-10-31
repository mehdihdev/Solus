"""Hard server-owned ceilings, selected only from a validated action mode and routing tier."""

from dataclasses import KW_ONLY, dataclass
from typing import Final

from solus_api.agent.modes import ActionMode
from solus_api.agent.prompt import TOOL_RESULT_CAP
from solus_api.orchestration import gateway
from solus_api.orchestration.enums import Complexity
from solus_api.orchestration.type_estimator import estimate_tokens

#: Guide's rounds and tool calls, readable without the orchestration config: the runner's
#: `MAX_MODEL_ROUNDS` and `MAX_TOOL_CALLS` are these.
GUIDE_MODEL_ROUNDS: Final = 5
GUIDE_TOOL_CALLS: Final = 8

#: What every round re-sends whatever the turns hold — the system prompt and the tool specs — for a
#: caller that has not measured it: the transport's mode-only `turn_limits(mode)` and tests. The
#: runner always measures its own turn's (`fixed_tokens=`), so its cap follows the tool inventory
#: it really sends and this default is never what a model turn is held to. It is the part as
#: re-measured in SOLUSDEV-321 P5 fix 1 (M3) from packages/api with `uv run python`:
#: `build_sol_registry(async_sessionmaker(), project_id, user_id=…, team_id=…,
#: secret_store=InMemorySecretStore(), connectors=ConnectorRegistry(), systems=<a SolSystems>,
#: artifact_store, enqueue, presence_service, companion_deployment_service and scene_enqueue
#: bound)` for the 60 in-process tools, then, as the runner counts them,
#: `estimate_tokens(system_prompt(SolMode.GUIDE, None, None, with_screenshot=True,
#: action_mode=ActionMode.DO, nonce=…))` = 1,482 plus
#: `estimate_tokens(tools_text(tool_specs(model_visible(registry.list()), nonce=…)))` = 10,924:
#: 12,406, rounded up to the next 1,000. `tests/test_sol_turn_limits.py` re-measures it and fails
#: when the default no longer covers the measurement or sits more than 2,000 tokens above it.
FIXED_PROMPT_TOKENS: Final = 13_000


@dataclass(frozen=True, slots=True)
class TurnLimits:
    """What one turn may spend. `max_input_tokens` caps each round's whole request, not the turn's
    sum; `max_model_calls` counts every gateway call carrying the turn's id (the rounds, the
    planner's tie-break, a screen read); the web caps are the research tool's (P1-T5)."""

    model_rounds: int
    tool_calls: int
    timeout_seconds: float
    _: KW_ONLY
    max_input_tokens: int
    max_model_calls: int
    web_searches: int
    web_fetches: int


#: Model rounds, tool calls, wall-clock seconds and model calls (the rounds plus room for the
#: planner's tie-break and a screen read), by action mode.
_MODE_CEILINGS: Final = {
    ActionMode.GUIDE: (GUIDE_MODEL_ROUNDS, GUIDE_TOOL_CALLS, 120.0, 6),
    ActionMode.DO: (16, 24, 300.0, 18),
}
#: (searches, fetches) by tier. A trivial turn gets the standard pair; whether it may spend them
#: is the research gate's call (P1-T5: an explicit ask, `/web`, or an MPN-shaped missing term).
_WEB_CAPS: Final = {
    Complexity.TRIVIAL: (1, 2),
    Complexity.STANDARD: (1, 2),
    Complexity.HARD: (3, 4),
}


def turn_limits(
    mode: ActionMode, tier: Complexity | None = None, *, fixed_tokens: int | None = None
) -> TurnLimits:
    """The ceilings for `mode` at `tier`. No tier means the standard one: the transport, which
    reads only the timeout and the tool cap, asks before any tier is known.

    A round's request may reach the tier's context budget plus the fixed part of the request
    plus one default-size tool result (`TOOL_RESULT_CAP` characters) per tool call the mode
    allows. The fixed part — the system prompt and the tool specs — is `fixed_tokens` when the
    caller measured it (the runner always does, so a larger tool inventory raises its cap with
    it) and `FIXED_PROMPT_TOKENS` when not. The result term is NOT sized from the largest
    `result_cap` a tool may raise: a turn dominated by `read_code_file`, `read_document` or
    `rail_current` results fills the room faster, and for such a turn `input_tokens` is the
    ceiling that binds."""
    if not isinstance(mode, ActionMode):
        raise ValueError("A validated action mode is required")
    if tier is not None and not isinstance(tier, Complexity):
        raise ValueError("A routing tier is required")
    tier = tier or Complexity.STANDARD
    rounds, tools, seconds, model_calls = _MODE_CEILINGS[mode]
    searches, fetches = _WEB_CAPS[tier]
    config = gateway.default_orchestration_config()
    one_result = estimate_tokens("x" * TOOL_RESULT_CAP, config=config.type_estimator)
    return TurnLimits(
        rounds,
        tools,
        seconds,
        max_input_tokens=config.context_budget.total_for(tier)
        + (FIXED_PROMPT_TOKENS if fixed_tokens is None else fixed_tokens)
        + tools * one_result,
        max_model_calls=model_calls,
        web_searches=searches,
        web_fetches=fetches,
    )
