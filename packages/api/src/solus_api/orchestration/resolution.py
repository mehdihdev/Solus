"""Shared routing resolution (MO-04) — the ONE brain behind preview and calls.

`resolve_routing` runs BOTH deterministic chains —

    complexity: explicit -> derive_complexity(context) -> estimate_complexity
    type:       explicit -> derive_type(context)       -> estimate_type

— then selects via the unchanged, pure `route()`, measures the request against
the chosen model's context window, and applies the window policy. The classify
endpoint AND the gateway both call THIS function, so the preview cannot lie by
construction: identical inputs produce identical `ModelChoice`s.

Window policy (the whose-decision-was-it split):
- EXPLICIT tier/type (user override) that doesn't fit -> `fits=False` with a
  short factual reason ("Too many tokens for this tier (340K > 200K)"); the
  gateway REFUSES (`OverrideNotViableError`) — never silently escalated, never
  truncated. The override would otherwise be a lie.
- SYSTEM-routed choice that doesn't fit -> escalate ascending complexity tiers
  within the SAME route type (the role family) to the first model that fits
  (`escalated=True` — preview shows the escalated model too); if none fits,
  `fits=False` with a clear reason naming the family's largest window and the
  gateway raises `ContextWindowExceededError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from solus_api.orchestration.choice import ModelChoice
from solus_api.orchestration.complexity import estimate_complexity
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.router import derive_complexity, route
from solus_api.orchestration.type_estimator import (
    AttachmentHint,
    derive_type,
    estimate_tokens,
    estimate_type,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from solus_api.orchestration.config import OrchestrationConfig

Source = Literal["explicit", "context", "estimator"]


class OverrideNotViableError(RuntimeError):
    """A user-chosen tier/type routes to a model that cannot hold the request."""


class ContextWindowExceededError(RuntimeError):
    """No model in the routed family can hold the request."""


class ResolvedRouting(BaseModel):
    """Everything the gateway and the classify preview need, from one source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    choice: ModelChoice
    complexity_source: Source
    type_source: Source
    tokens_estimate: int
    fits: bool
    reason: str | None = None
    escalated: bool = False
    escalated_from_role: str | None = None

    @property
    def explicit_override(self) -> bool:
        return self.complexity_source == "explicit" or self.type_source == "explicit"


def _k(tokens: int) -> str:
    return f"{max(1, round(tokens / 1000))}K" if tokens >= 1000 else str(tokens)


def _resolve_complexity(
    query: str,
    complexity: Complexity | None,
    context: InteractionContext | None,
    estimate_from: str | None,
    config: OrchestrationConfig,
) -> tuple[Complexity, Source]:
    """explicit -> estimator(estimate_from) -> context default -> estimator(query)."""
    if complexity is not None:
        return complexity, "explicit"
    if estimate_from is not None:
        return estimate_complexity(estimate_from, config=config.estimator), "estimator"
    if context is not None:
        return derive_complexity(context), "context"
    return estimate_complexity(query, config=config.estimator), "estimator"


def resolve_routing(
    query: str,
    *,
    complexity: Complexity | None = None,
    context: InteractionContext | None = None,
    type: RouteType | None = None,
    attachments: Sequence[AttachmentHint] | None = None,
    estimate_from: str | None = None,
    config: OrchestrationConfig,
) -> ResolvedRouting:
    """Pure and deterministic: same (inputs, config) -> same ResolvedRouting.

    `estimate_from` (S1): run the complexity ESTIMATOR on this text instead of
    `query`, ahead of the context default. A SOL turn hands the gateway a whole
    fenced conversation as `query` (right for token measurement) but only the
    person's live message says how hard the question is; the context default
    (SOL_OPEN_QUESTION -> HARD) would otherwise send every "what is I2C" to the
    top tier. Still SYSTEM-routed: the window policy escalates rather than refuses.
    """
    resolved_complexity, complexity_source = _resolve_complexity(
        query, complexity, context, estimate_from, config
    )
    if type is not None:
        resolved_type, type_source = type, "explicit"
    elif context is not None:
        resolved_type, type_source = derive_type(context), "context"
    else:
        resolved_type, type_source = (
            estimate_type(query, config=config.type_estimator, attachments=attachments),
            "estimator",
        )
    tokens = estimate_tokens(query, config=config.type_estimator) + sum(
        a.tokens for a in attachments or ()
    )
    choice = route(query, resolved_complexity, resolved_type, config=config)

    def _result(
        final: ModelChoice,
        *,
        fits: bool,
        reason: str | None = None,
        escalated: bool = False,
        escalated_from_role: str | None = None,
    ) -> ResolvedRouting:
        return ResolvedRouting(
            choice=final,
            complexity_source=complexity_source,
            type_source=type_source,  # type: ignore[arg-type]
            tokens_estimate=tokens,
            fits=fits,
            reason=reason,
            escalated=escalated,
            escalated_from_role=escalated_from_role,
        )

    if tokens <= choice.context_window:
        return _result(choice, fits=True)
    if complexity is not None or type is not None:
        # User promise: refuse plainly, never escalate behind their back.
        return _result(
            choice,
            fits=False,
            reason=f"Too many tokens for this tier ({_k(tokens)} > {_k(choice.context_window)})",
        )
    # System-routed miss: escalate within the role family (same route type).
    tiers = list(Complexity)
    largest = choice.context_window
    for tier in tiers[tiers.index(resolved_complexity) + 1 :]:
        candidate = route(query, tier, resolved_type, config=config)
        largest = max(largest, candidate.context_window)
        if tokens <= candidate.context_window:
            return _result(candidate, fits=True, escalated=True, escalated_from_role=choice.role)
    return _result(
        choice,
        fits=False,
        reason=(
            f"Request (~{_k(tokens)} tokens) exceeds every available model for "
            f"this request type (largest window {_k(largest)})"
        ),
    )
