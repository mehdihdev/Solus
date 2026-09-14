"""models.yaml config contract (ADR-026/024) — schema + deterministic-role checks.

Also pins the `Settings` env surface (core/config.py) where a field's
presence/absence is itself the contract."""

from typing import Any

import pytest
from pydantic import ValidationError
from solus_api.core.config import Settings
from solus_api.orchestration.config import (
    ModelCatalogEntry,
    OrchestrationConfig,
    load_orchestration_config,
)
from solus_api.orchestration.enums import Complexity, RouteType


def test_settings_has_no_dead_stripe_secret_key_field() -> None:
    """SOLUSDEV-152: `stripe_secret_key` was never read anywhere (webhook trust
    comes from `stripe_webhook_secret` HMAC verification, and no checkout /
    Stripe-client code exists this cycle) — the dead field is removed and
    Settings still validates without it."""
    assert "stripe_secret_key" not in Settings.model_fields
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]  # hermetic: ignore local .env (matches CI)
        supabase_jwt_secret="dummy-jwt-signing-value-tests-only",
        database_url="sqlite+aiosqlite://",
    )
    # The consumed Stripe fields survive the removal.
    assert settings.stripe_webhook_secret is None
    assert settings.stripe_pack_credits == {}


def test_stripe_checkout_settings_defaults_and_shape() -> None:
    """SOLUSDEV-83 follow-up: the checkout settings default safely and the plan
    price map is a dict. The Stripe SECRET key is deliberately NOT a setting (it
    lives in the SecretStore under 'stripe_api_key')."""
    s = Settings(_env_file=None, supabase_jwt_secret="dummy", database_url="sqlite+aiosqlite://")  # type: ignore[call-arg]
    assert s.stripe_plan_prices == {}
    assert s.stripe_trial_days == 14
    assert s.stripe_checkout_success_url.endswith("checkout=success")
    assert "stripe_api_key" not in Settings.model_fields
    assert "stripe_secret_key" not in Settings.model_fields

    configured = Settings(
        _env_file=None,  # type: ignore[call-arg]
        supabase_jwt_secret="dummy",
        database_url="sqlite+aiosqlite://",
        stripe_plan_prices={"basic:month": "price_bm", "pro:year": "price_py"},
    )
    assert configured.stripe_plan_prices["pro:year"] == "price_py"


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


# --- SOLUSDEV-252 S3 review M2: routing must not be modality-blind ------------


def test_shipped_catalog_is_vision_capable_everywhere_a_screenshot_can_land() -> None:
    config = load_orchestration_config()
    assert all(entry.accepts_images for entry in config.catalog)
    for row in config.matrix.values():
        for route_type in (RouteType.GENERAL, RouteType.CODE):
            assert config.entry_for_role(row[route_type]).accepts_images is True


def test_a_text_only_model_on_a_general_cell_fails_at_load_naming_the_cell() -> None:
    data = _minimal("general_standard")
    data["catalog"][0]["accepts_images"] = False
    with pytest.raises(ValidationError, match="standard/general") as info:
        OrchestrationConfig.model_validate(data)
    assert "accepts_images" in str(info.value) and "'m'" in str(info.value)


def test_a_text_only_model_on_a_code_cell_fails_at_load() -> None:
    data = _minimal("general_standard")
    data["catalog"].append(
        {
            "provider": "openai",
            "name": "text-only",
            "price_in": 1.0,
            "price_out": 2.0,
            "context_window": 1000,
            "roles": ["code_hard"],
            "accepts_images": False,
        }
    )
    data["matrix"]["hard"] = {"code": "code_hard"}
    with pytest.raises(ValidationError, match="hard/code"):
        OrchestrationConfig.model_validate(data)


def test_a_text_only_model_on_a_long_context_only_role_is_fine() -> None:
    data = _minimal("general_standard")
    data["catalog"].append(
        {
            "provider": "google",
            "name": "longctx-text",
            "price_in": 1.0,
            "price_out": 2.0,
            "context_window": 2_000_000,
            "roles": ["longctx_standard"],
            "accepts_images": False,
        }
    )
    data["matrix"]["standard"]["long_context"] = "longctx_standard"
    config = OrchestrationConfig.model_validate(data)
    assert config.entry_for_role("longctx_standard").accepts_images is False
    assert config.entry_for_role("general_standard").accepts_images is True  # the default


def test_a_text_only_model_on_a_visual_log_cell_fails_at_load() -> None:
    """VISUAL_LOG is exactly where the extractor sends pixels (security re-check M2)."""
    data = _minimal("general_standard")
    data["catalog"].append(
        {
            "provider": "google",
            "name": "visual-text",
            "price_in": 1.0,
            "price_out": 2.0,
            "context_window": 2_000_000,
            "roles": ["visual_standard"],
            "accepts_images": False,
        }
    )
    data["matrix"]["standard"]["visual_log"] = "visual_standard"
    with pytest.raises(ValueError, match="standard/visual_log"):
        OrchestrationConfig.model_validate(data)


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


# --- SOLUSDEV-252 S1: the new matrix, cached pricing, reasoning effort, azure --


def test_shipped_matrix_fills_the_s1_cells() -> None:
    """Human-decided matrix (SOLUSDEV-252): astra fills BOTH hard cells, fable
    fills code_standard, the GPT-5.6 ladder fills standard/trivial general;
    Gemini rows unchanged (ADR-029); default_role stays a Sonnet fallback."""
    config = load_orchestration_config()

    def name(complexity: Complexity, route_type: RouteType) -> str:
        return config.entry_for_role(config.matrix[complexity][route_type]).name

    assert name(Complexity.HARD, RouteType.GENERAL) == "gpt-6-astra"
    assert name(Complexity.HARD, RouteType.CODE) == "gpt-6-astra"
    assert name(Complexity.STANDARD, RouteType.CODE) == "claude-fable-5-1"
    assert name(Complexity.STANDARD, RouteType.GENERAL) == "gpt-5.6-sol"
    assert name(Complexity.TRIVIAL, RouteType.GENERAL) == "gpt-5.6-luna"
    assert name(Complexity.TRIVIAL, RouteType.CODE) == "claude-haiku-4-5"
    for complexity in Complexity:
        assert config.entry_for_role(config.matrix[complexity][RouteType.VISUAL_LOG]).provider == (
            "google"
        )
        assert (
            config.entry_for_role(config.matrix[complexity][RouteType.LONG_CONTEXT]).provider
            == "google"
        )
    assert config.default_role == "general_standard"
    assert config.entry_for_role(config.default_role).name == "claude-sonnet-5"
    # Bench-only entries stay in the catalog, unreferenced by the matrix.
    referenced = {role for row in config.matrix.values() for role in row.values()}
    by_name = {entry.name: entry for entry in config.catalog}
    assert not referenced & set(by_name["claude-opus-4-8"].roles)
    assert not referenced & set(by_name["gpt-5.6-terra"].roles)


def test_shipped_catalog_cached_prices_and_reasoning_effort() -> None:
    config = load_orchestration_config()
    by_name = {entry.name: entry for entry in config.catalog}
    astra = by_name["gpt-6-astra"]
    assert (astra.price_in, astra.price_cached_in, astra.price_out) == (10.0, 1.0, 50.0)
    assert astra.long_context_threshold_tokens == 272_000
    assert (astra.price_in_long, astra.price_out_long) == (20.0, 75.0)
    assert astra.reasoning_effort == "medium"
    assert by_name["gpt-5.6-sol"].reasoning_effort == "medium"
    assert by_name["gpt-5.6-terra"].reasoning_effort == "low"
    assert by_name["gpt-5.6-luna"].reasoning_effort == "low"
    for entry in config.catalog:
        if entry.provider == "openai":
            assert entry.price_cached_in is not None
        else:
            assert entry.reasoning_effort is None
    # Anthropic cache reads: 0.1x input (0.025x on Fable 5.1) — verified 2026-09-07.
    assert by_name["claude-haiku-4-5"].price_cached_in == 0.1
    assert by_name["claude-fable-5-1"].price_cached_in == 0.25
    assert by_name["claude-fable-5-1"].price_in == 10.0


def test_cached_price_above_input_price_is_rejected() -> None:
    data = _minimal("general_standard")
    data["catalog"][0]["price_cached_in"] = 1.5  # price_in is 1.0
    with pytest.raises(ValidationError, match="price_cached_in"):
        OrchestrationConfig.model_validate(data)


def test_shipped_providers_stanza_loads() -> None:
    """The azure stanza is config-only (no adapter): production wiring is
    fill endpoint/deployments + register one adapter."""
    providers = load_orchestration_config().providers
    azure = providers["azure"]
    assert azure.kind == "openai_compatible"
    assert azure.api_key_ref == "azure_openai_api_key"
    assert azure.deployments == {}


def test_providers_stanza_defaults_and_rejects_unknowns() -> None:
    data = _minimal("general_standard")
    assert OrchestrationConfig.model_validate(data).providers == {}
    data["providers"] = {
        "azure": {"kind": "openai_compatible", "api_version": "v1", "api_key_ref": "k"}
    }
    stanza = OrchestrationConfig.model_validate(data).providers["azure"]
    assert stanza.endpoint == ""
    assert stanza.deployments == {}
    data["providers"]["azure"]["kind"] = "grpc"
    with pytest.raises(ValidationError):
        OrchestrationConfig.model_validate(data)
    data["providers"]["azure"] = {
        "kind": "openai_compatible",
        "api_version": "v1",
        "api_key_ref": "k",
        "region": "eastus",
    }
    with pytest.raises(ValidationError):
        OrchestrationConfig.model_validate(data)


def test_catalog_entry_may_name_a_stanza_only_provider() -> None:
    """A catalog entry on `azure` LOADS (the stanza is the contract) — the
    missing adapter surfaces at dispatch, not at config load (test_gateway)."""
    data = _minimal("general_standard")
    data["catalog"][0]["provider"] = "azure"
    data["providers"] = {
        "azure": {
            "kind": "openai_compatible",
            "api_version": "v1",
            "api_key_ref": "azure_openai_api_key",
            "deployments": {"m": "m-deployment"},
        }
    }
    config = OrchestrationConfig.model_validate(data)
    assert config.entry_for_role("general_standard").provider == "azure"
    assert config.providers["azure"].deployments["m"] == "m-deployment"


def test_hosted_mcp_does_not_advertise_an_unwired_annual_entitlement():
    assert "onshape_fs_annual_call_allowance" not in Settings.model_fields
    # The separately governed non-exempt REST policy is not this allocation.
    assert "onshape_annual_call_allowance" in Settings.model_fields
