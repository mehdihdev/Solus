"""Model-orchestration config contract (ADR-026/024).

The model catalog, the `(complexity × type) → role` matrix, and the cost/margin
knobs all live in data (`models.yaml`) and are validated here. There are ZERO
hardcoded model strings in Python code — model identity lives only in the catalog.

This module is FUNCTIONAL (it is the config contract MO-01 builds on): it loads,
validates, and cross-checks the config. Only the routing/cost *logic* is stubbed
elsewhere (`router.route`, `cost.track_cost`).
"""

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from solus_api.orchestration.enums import Complexity, RouteType

_DEFAULT_CONFIG_PATH = Path(__file__).with_name("models.yaml")


class ModelCatalogEntry(BaseModel):
    """One concrete model and the role(s) it fills. Prices are USD per 1M tokens."""

    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    provider: str
    name: str
    price_in: float = Field(ge=0)
    price_out: float = Field(ge=0)
    context_window: int = Field(gt=0)
    roles: list[str] = Field(min_length=1)


class CostConfig(BaseModel):
    """Token→credit conversion knobs (ADR-024), all CALIBRATABLE post-pilot.

    `margin_multiplier` defaults to 2.0 (covers infra + failed calls + trial
    grants + profit — not pure profit, which is why it is 2.0 not ~1.25). Values
    shipped in models.yaml are provisional (no real cost-per-op data yet)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    margin_multiplier: float = Field(default=2.0, gt=0)
    credits_per_dollar: float = Field(gt=0)
    price_unit: Literal["usd_per_million_tokens"] = "usd_per_million_tokens"


class OrchestrationConfig(BaseModel):
    """The whole routing contract as data. The matrix may be partial — a missing
    `(complexity, type)` cell falls back to `default_role` in `route()`."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    catalog: list[ModelCatalogEntry] = Field(min_length=1)
    matrix: dict[Complexity, dict[RouteType, str]]
    default_role: str
    cost: CostConfig

    _role_index: dict[str, ModelCatalogEntry] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _index_and_validate_roles(self) -> Self:
        """Build the role→entry index and enforce that routing is deterministic:
        each referenced role is filled by exactly one catalog entry."""
        index: dict[str, ModelCatalogEntry] = {}
        for entry in self.catalog:
            for role in entry.roles:
                if role in index:
                    raise ValueError(
                        f"role {role!r} is filled by more than one catalog entry "
                        "(routing must be deterministic)"
                    )
                index[role] = entry
        referenced = {role for row in self.matrix.values() for role in row.values()}
        referenced.add(self.default_role)
        missing = sorted(referenced - index.keys())
        if missing:
            raise ValueError(f"matrix/default_role reference roles absent from catalog: {missing}")
        self._role_index = index
        return self

    def entry_for_role(self, role: str) -> ModelCatalogEntry:
        """Resolve a role to its concrete catalog entry (validated to exist)."""
        return self._role_index[role]


def load_orchestration_config(path: Path | None = None) -> OrchestrationConfig:
    """Load and validate the model catalog; defaults to the sibling `models.yaml`."""
    source = path or _DEFAULT_CONFIG_PATH
    data = yaml.safe_load(source.read_text())
    return OrchestrationConfig.model_validate(data)
