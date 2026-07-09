"""Model orchestration (ADR-026 / ADR-024): deterministic routing + per-call cost.

W0-03 ships the DESIGN + STUBS (see docs/contracts/model-orchestration.md).
Functional: the config contract (`models.yaml` + schema), the cost formula
(`compute_call_credits`), and the Step-1 complexity gateway (`derive_complexity`).
Stubbed for MO-01: `route`, `track_cost`, `has_sufficient_credits`.
"""

from solus_api.orchestration.choice import ModelChoice
from solus_api.orchestration.config import (
    CostConfig,
    ModelCatalogEntry,
    OrchestrationConfig,
    load_orchestration_config,
)
from solus_api.orchestration.cost import (
    compute_call_credits,
    has_sufficient_credits,
    track_cost,
)
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.router import (
    CONTEXT_COMPLEXITY_DEFAULTS,
    derive_complexity,
    route,
)

__all__ = [
    "CONTEXT_COMPLEXITY_DEFAULTS",
    "Complexity",
    "CostConfig",
    "InteractionContext",
    "ModelCatalogEntry",
    "ModelChoice",
    "OrchestrationConfig",
    "RouteType",
    "compute_call_credits",
    "derive_complexity",
    "has_sufficient_credits",
    "load_orchestration_config",
    "route",
    "track_cost",
]
