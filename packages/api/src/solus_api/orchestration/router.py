"""Deterministic routing (ADR-026): the Step-1 complexity gateway + `route()`.

`derive_complexity` is the cheap, no-model-call Step-1 mapping (context → tier).
`route()` is the pure (complexity × type) → role → catalog-entry selector.
Both are pure functions of (inputs + config); model identity lives only in
`models.yaml`.
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
    """Select the concrete model for a call — PURE SELECTION ONLY (ADR-026).

    Deterministic: same (query, complexity, type, config) → same ModelChoice.
    No randomness, no time-dependence, no hidden state, NO model call. It does NOT
    check credits, call the model, or track cost — those are separate phases (see
    `cost.py`). `config` is an explicit parameter (not a hidden global) so the
    function stays a pure function of (inputs + config); editing config is the
    intended routing lever.

    `query` is reserved for future within-tier heuristics; v1 selection is by the
    (complexity, type) pair only.
    """
    resolved = type or RouteType.GENERAL
    role = config.matrix.get(complexity, {}).get(resolved) or config.default_role
    entry = config.entry_for_role(role)
    return ModelChoice(
        provider=entry.provider,
        model_name=entry.name,
        price_in=entry.price_in,
        price_out=entry.price_out,
        context_window=entry.context_window,
        role=role,
        complexity=complexity,
        route_type=resolved,
        rationale=f"matrix[{complexity}][{resolved}] -> {role}",
    )
