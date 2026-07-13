"""models.yaml config contract (ADR-026/024) — schema + deterministic-role checks."""

from typing import Any

import pytest
from pydantic import ValidationError
from solus_api.orchestration.config import (
    ModelCatalogEntry,
    OrchestrationConfig,
    load_orchestration_config,
)
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


def test_shipped_estimator_section_loads_with_real_keyword_lists() -> None:
    est = load_orchestration_config().estimator
    assert est.tool_keywords
    assert est.reasoning_keywords
    assert set(est.domain_keywords) >= {"code", "electrical", "mechanical"}
    assert est.hard_threshold >= est.standard_threshold


def test_estimator_defaults_apply_when_section_omitted() -> None:
    """Hand-built configs (tests) need no estimator section: numeric defaults
    kick in and keyword lists stay empty (length-only estimation)."""
    config = OrchestrationConfig.model_validate(_minimal("general_standard"))
    assert config.estimator.trivial_max_words > 0
    assert config.estimator.tool_keywords == []
    assert config.estimator.domain_keywords == {}


def test_estimator_negative_weight_is_rejected() -> None:
    data = _minimal("general_standard")
    data["estimator"] = {"weights": {"tool_signal": -1}}
    with pytest.raises(ValidationError):
        OrchestrationConfig.model_validate(data)


def test_estimator_swapped_thresholds_are_rejected() -> None:
    """hard < standard would silently route ordinary queries to the expensive
    tier — the exact typo the tune-without-code workflow invites."""
    data = _minimal("general_standard")
    data["estimator"] = {"standard_threshold": 4, "hard_threshold": 1}
    with pytest.raises(ValidationError):
        OrchestrationConfig.model_validate(data)


def test_estimator_unknown_knob_is_rejected() -> None:
    data = _minimal("general_standard")
    data["estimator"] = {"no_such_knob": 1}
    with pytest.raises(ValidationError):
        OrchestrationConfig.model_validate(data)


def test_every_long_context_cell_resolves_to_a_large_window_model() -> None:
    """MO-02b guard: LONG_CONTEXT exists because the input is huge — any model
    reachable from a long_context matrix cell must be able to HOLD it. Makes
    the 200K-window-behind-long_context trap impossible to reintroduce by a
    config edit."""
    config = load_orchestration_config()
    floor = 500_000
    for complexity, row in config.matrix.items():
        role = row.get(RouteType.LONG_CONTEXT)
        if role is None:
            continue
        entry = config.entry_for_role(role)
        assert entry.context_window >= floor, (
            f"matrix[{complexity}][long_context] -> {role!r} -> {entry.name!r} "
            f"({entry.context_window} tokens) is below the {floor} floor"
        )


def test_every_registered_provider_is_present_and_role_assignable() -> None:
    """MO-02b: anthropic, openai, and google each have >= 1 catalog entry, and
    pointing a role at any of them routes there with ZERO code change."""
    from solus_api.orchestration.router import route

    config = load_orchestration_config()
    by_provider: dict[str, ModelCatalogEntry] = {}
    for entry in config.catalog:
        by_provider.setdefault(entry.provider, entry)
    assert {"anthropic", "openai", "google"} <= set(by_provider)
    for provider, entry in by_provider.items():
        rerouted = OrchestrationConfig(
            version=config.version,
            catalog=config.catalog,
            matrix={},
            default_role=entry.roles[0],
            cost=config.cost,
        )
        choice = route("q", Complexity.STANDARD, None, config=rerouted)
        assert choice.provider == provider
        assert choice.model_name == entry.name


def test_long_context_pricing_is_all_or_nothing() -> None:
    data = _minimal("general_standard")
    data["catalog"][0]["long_context_threshold_tokens"] = 200_000
    with pytest.raises(ValidationError, match="set together"):
        OrchestrationConfig.model_validate(data)
    data["catalog"][0]["price_in_long"] = 4.0
    data["catalog"][0]["price_out_long"] = 18.0
    config = OrchestrationConfig.model_validate(data)
    assert config.catalog[0].long_context_threshold_tokens == 200_000


def test_long_prices_below_base_prices_are_rejected() -> None:
    """Security-review hardening: a long-rate typo BELOW the flat rate would
    silently under-bill exactly the above-threshold calls."""
    data = _minimal("general_standard")
    data["catalog"][0]["long_context_threshold_tokens"] = 200_000
    data["catalog"][0]["price_in_long"] = 0.5  # below price_in=1.0
    data["catalog"][0]["price_out_long"] = 18.0
    with pytest.raises(ValidationError, match="must be >= the base prices"):
        OrchestrationConfig.model_validate(data)


def test_shipped_catalog_carries_breakpoint_pricing_where_providers_charge_it() -> None:
    config = load_orchestration_config()
    by_name = {entry.name: entry for entry in config.catalog}
    # Gemini Pro-class and the GPT-5.6 family bill more above a threshold.
    assert by_name["gemini-3.1-pro-preview"].long_context_threshold_tokens == 200_000
    assert by_name["gpt-5.6-sol"].long_context_threshold_tokens == 272_000
    # Flat-priced models omit the fields entirely.
    assert by_name["claude-haiku-4-5"].long_context_threshold_tokens is None
    assert by_name["gemini-3.5-flash"].price_in_long is None


def test_shipped_limits_section_loads() -> None:
    limits = load_orchestration_config().limits
    assert limits.trial_credit_cap > 0
    assert limits.max_calls_per_minute > 0
    assert limits.frequency_window_seconds > 0
    assert limits.retry_max_attempts >= 1


def test_limits_defaults_apply_when_section_omitted() -> None:
    config = OrchestrationConfig.model_validate(_minimal("general_standard"))
    assert config.limits.trial_credit_cap == 1000
    assert config.limits.max_calls_per_minute == 20


def test_limits_bad_values_rejected() -> None:
    data = _minimal("general_standard")
    data["limits"] = {"max_calls_per_minute": 0}
    with pytest.raises(ValidationError):
        OrchestrationConfig.model_validate(data)


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
