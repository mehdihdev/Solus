"""Model orchestration (ADR-026 / ADR-024): deterministic routing + the gateway.

Every AI call in Solus flows through `complete()` / `stream()` (gateway.py):
route via the pure `route()` selector, dispatch to a provider adapter
(providers.py — the only module that may import provider SDKs), capture final
token usage, and invoke the `track_cost` cost-hook call site. Model identity
lives ONLY in `models.yaml`.

Complexity tiers resolve in a fixed order (MO-02): explicit `complexity` arg ->
`derive_complexity(context)` when an `InteractionContext` is supplied -> the
deterministic query-text estimator (`estimate_complexity`, knobs in
models.yaml) -> STANDARD as the estimator's own safe default.

MO-03 (complete): every identified call is gated pre-flight (Redis frequency
cap -> trial/balance spend gate), retried on transient provider errors, and
debited post-call — atomically and idempotently (`credit_ledger.call_id`
unique) — with failed debits deferred to the ARQ reconciliation job. See
gateway.py's identity-gating warning before exposing anything over HTTP.
"""

from solus_api.orchestration.choice import ModelChoice
from solus_api.orchestration.complexity import estimate_complexity
from solus_api.orchestration.config import (
    CostConfig,
    EstimatorConfig,
    EstimatorWeights,
    LimitsConfig,
    ModelCatalogEntry,
    OrchestrationConfig,
    TypeEstimatorConfig,
    load_orchestration_config,
)
from solus_api.orchestration.cost import (
    RECONCILE_JOB_NAME,
    account_spend,
    compute_call_credits,
    has_sufficient_credits,
    track_cost,
)
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.gates import (
    FrequencyCapExceededError,
    InsufficientCreditsError,
    TrialCapReachedError,
    assert_can_spend,
    check_frequency_cap,
)
from solus_api.orchestration.gateway import (
    Completion,
    CompletionStream,
    complete,
    stream,
)
from solus_api.orchestration.providers import (
    ANTHROPIC_API_KEY_NAME,
    GOOGLE_API_KEY_NAME,
    OPENAI_API_KEY_NAME,
    AnthropicAdapter,
    GeminiAdapter,
    OpenAIAdapter,
    ProviderAdapter,
    ProviderCredentialsMissingError,
    ProviderError,
    UnknownProviderError,
    Usage,
    build_adapter_registry,
)
from solus_api.orchestration.resolution import (
    ContextWindowExceededError,
    OverrideNotViableError,
    ResolvedRouting,
    resolve_routing,
)
from solus_api.orchestration.router import (
    CONTEXT_COMPLEXITY_DEFAULTS,
    derive_complexity,
    route,
)
from solus_api.orchestration.type_estimator import (
    CONTEXT_TYPE_DEFAULTS,
    AttachmentHint,
    derive_type,
    estimate_tokens,
    estimate_type,
)

__all__ = [
    "ANTHROPIC_API_KEY_NAME",
    "CONTEXT_COMPLEXITY_DEFAULTS",
    "GOOGLE_API_KEY_NAME",
    "OPENAI_API_KEY_NAME",
    "AnthropicAdapter",
    "Completion",
    "CompletionStream",
    "Complexity",
    "AttachmentHint",
    "CONTEXT_TYPE_DEFAULTS",
    "ContextWindowExceededError",
    "CostConfig",
    "EstimatorConfig",
    "EstimatorWeights",
    "FrequencyCapExceededError",
    "GeminiAdapter",
    "InsufficientCreditsError",
    "InteractionContext",
    "LimitsConfig",
    "OverrideNotViableError",
    "RECONCILE_JOB_NAME",
    "ResolvedRouting",
    "TrialCapReachedError",
    "TypeEstimatorConfig",
    "ModelCatalogEntry",
    "ModelChoice",
    "OpenAIAdapter",
    "OrchestrationConfig",
    "ProviderAdapter",
    "ProviderCredentialsMissingError",
    "ProviderError",
    "RouteType",
    "UnknownProviderError",
    "Usage",
    "account_spend",
    "assert_can_spend",
    "build_adapter_registry",
    "check_frequency_cap",
    "complete",
    "compute_call_credits",
    "derive_complexity",
    "derive_type",
    "estimate_complexity",
    "estimate_tokens",
    "estimate_type",
    "has_sufficient_credits",
    "load_orchestration_config",
    "resolve_routing",
    "route",
    "stream",
    "track_cost",
]
