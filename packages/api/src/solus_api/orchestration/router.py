"""Deterministic routing (ADR-026): the Step-1 complexity gateway + `route()`.

`derive_complexity` (the gateway) IS functional — it is the cheap, no-model-call
Step-1 mapping. `route()` is a STUB; its selection algorithm is implemented in
MO-01 (W0-03 is design + stubs). The `route()` contract is documented in full so
MO-01 can implement it and callers can rely on it.
"""

from solus_api.orchestration.choice import ModelChoice
from solus_api.orchestration.config import OrchestrationConfig
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType

# Step-1 gateway: interaction context → complexity tier, with NO model call.
# Extensible — add a row as new callers appear. The end user never sees this;
# calling code looks up its tier here and passes it to route().
CONTEXT_COMPLEXITY_DEFAULTS: dict[InteractionContext, Complexity] = {
    InteractionContext.CODE_AUTOCOMPLETE: Complexity.TRIVIAL,
    InteractionContext.TELEMETRY_SUMMARY: Complexity.TRIVIAL,
    InteractionContext.SOL_OPEN_QUESTION: Complexity.HARD,
    InteractionContext.COMPATIBILITY_RESEARCH: Complexity.STANDARD,
}

_DEFAULT_COMPLEXITY = Complexity.STANDARD


def derive_complexity(context: InteractionContext) -> Complexity:
    """Step-1 gateway: map an interaction context → complexity tier, deterministically
    and with NO model call (keeps routing cost near zero). The end user never sees or
    supplies complexity — the calling code passes what this returns into `route()`.
    Unknown contexts fall back to STANDARD."""
    return CONTEXT_COMPLEXITY_DEFAULTS.get(context, _DEFAULT_COMPLEXITY)


def route(
    query: str,
    complexity: Complexity,
    type: RouteType | None,
    *,
    config: OrchestrationConfig,
) -> ModelChoice:
    """Select the concrete model for a call — PURE SELECTION ONLY (STUB → MO-01).

    Deterministic: same (query, complexity, type, config) → same ModelChoice.
    No randomness, no time-dependence, no hidden state, NO model call. It does NOT
    check credits, call the model, or track cost — those are separate phases (see
    `cost.py`). `config` is an explicit parameter (not a hidden global) so the
    function stays a pure function of (inputs + config); editing config is the
    intended routing lever.

    Intended algorithm (MO-01 implements):
      1. resolved = type or RouteType.GENERAL                       # None → GENERAL
      2. role = config.matrix.get(complexity, {}).get(resolved) or config.default_role
      3. entry = config.entry_for_role(role)
      4. return ModelChoice(provider=entry.provider, model_name=entry.name,
             price_in=entry.price_in, price_out=entry.price_out,
             context_window=entry.context_window, role=role,
             complexity=complexity, route_type=resolved, rationale=...)

    `query` is reserved for future within-tier heuristics; v1 selection is by the
    (complexity, type) pair only.
    """
    raise NotImplementedError("route() is implemented in MO-01 (W0-03 ships design + stubs)")
