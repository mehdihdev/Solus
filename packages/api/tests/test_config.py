"""models.yaml config contract (ADR-026/024) — schema + deterministic-role checks."""

from typing import Any

import pytest
from pydantic import ValidationError
from solus_api.orchestration.config import OrchestrationConfig, load_orchestration_config
from solus_api.orchestration.enums import Complexity, RouteType


def test_shipped_models_yaml_validates() -> None:
    config = load_orchestration_config()
    assert config.catalog
    assert config.cost.margin_multiplier == 2.0
    # default_role and a hard/code matrix cell both resolve to real catalog entries.
    assert config.entry_for_role(config.default_role).name
    role = config.matrix[Complexity.HARD][RouteType.CODE]
    assert config.entry_for_role(role).provider


def _minimal(matrix_role: str) -> dict[str, Any]:
    return {
        "version": 1,
        "catalog": [
            {
                "provider": "anthropic",
                "name": "m",
                "price_in": 1.0,
                "price_out": 2.0,
                "context_window": 1000,
                "roles": ["general_standard"],
            }
        ],
        "matrix": {"standard": {"general": matrix_role}},
        "default_role": "general_standard",
        "cost": {"credits_per_dollar": 100.0},
    }


def test_valid_minimal_config_resolves_role() -> None:
    config = OrchestrationConfig.model_validate(_minimal("general_standard"))
    assert config.entry_for_role("general_standard").name == "m"


def test_matrix_role_absent_from_catalog_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OrchestrationConfig.model_validate(_minimal("does_not_exist"))


def test_duplicate_role_across_entries_is_rejected() -> None:
    data = _minimal("general_standard")
    data["catalog"].append(
        {
            "provider": "google",
            "name": "n",
            "price_in": 1.0,
            "price_out": 2.0,
            "context_window": 1000,
            "roles": ["general_standard"],
        }
    )
    with pytest.raises(ValidationError):
        OrchestrationConfig.model_validate(data)
