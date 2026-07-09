"""ModelChoice — the resolved model config that `route()` returns (ADR-026).

Immutable value object carrying everything the caller needs to (a) make the model
call and (b) compute its cost afterward via `cost.compute_call_credits`. All model
identity (`provider`, `model_name`, prices, window) comes FROM CONFIG — there are
no hardcoded model strings in code.
"""

from pydantic import BaseModel, ConfigDict, Field

from solus_api.orchestration.enums import Complexity, RouteType


class ModelChoice(BaseModel):
    """A concrete, resolved model selection. Frozen: `route()` returns a fresh one
    per call; callers never mutate it. `protected_namespaces=()` allows the
    contract's `model_name` field without Pydantic's `model_`-prefix warning."""

    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    provider: str  # e.g. "anthropic", "google", "openai"
    model_name: str  # concrete model string, resolved from the catalog
    price_in: float = Field(ge=0)  # USD per 1M input tokens
    price_out: float = Field(ge=0)  # USD per 1M output tokens
    context_window: int = Field(gt=0)
    role: str  # the config role this choice resolved (for logging/debugging)
    complexity: Complexity  # routing metadata: the tier that selected it
    route_type: RouteType  # routing metadata: the resolved type (None → GENERAL)
    rationale: str | None = None  # optional human-readable "why this model"
