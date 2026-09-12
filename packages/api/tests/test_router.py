"""Step-1 gateway + route() selection algorithm (ADR-026, implemented in MO-01)."""

import pytest
from solus_api.orchestration.config import (
    CostConfig,
    ModelCatalogEntry,
    OrchestrationConfig,
    load_orchestration_config,
)
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.router import derive_complexity, route


def test_derive_complexity_maps_starter_contexts() -> None:
    assert derive_complexity(InteractionContext.CODE_AUTOCOMPLETE) is Complexity.TRIVIAL
    assert derive_complexity(InteractionContext.SOL_OPEN_QUESTION) is Complexity.HARD
    assert derive_complexity(InteractionContext.COMPATIBILITY_RESEARCH) is Complexity.STANDARD


# Golden (complexity × type) → (role, provider) table for the SHIPPED models.yaml.
# ADR-026: CODE → Claude-class, VISUAL_LOG / LONG_CONTEXT → Gemini-class.
# MO-02b: trivial visual/long-context route to the cheap LARGE-WINDOW model
# (Flash-Lite class) — trivial.long_context on a 200K model was a hard failure
# for long-but-simple inputs. A deliberate models.yaml change updates these.
_MATRIX_GOLDENS = [
    (Complexity.TRIVIAL, RouteType.GENERAL, "openai_trivial", "openai"),
    (Complexity.TRIVIAL, RouteType.CODE, "general_trivial", "anthropic"),
    (Complexity.TRIVIAL, RouteType.VISUAL_LOG, "visual_trivial", "google"),
    (Complexity.TRIVIAL, RouteType.LONG_CONTEXT, "longctx_trivial", "google"),
    (Complexity.STANDARD, RouteType.GENERAL, "openai_standard", "openai"),
    (Complexity.STANDARD, RouteType.CODE, "code_standard", "anthropic"),
    (Complexity.STANDARD, RouteType.VISUAL_LOG, "visual_standard", "google"),
    (Complexity.STANDARD, RouteType.LONG_CONTEXT, "longctx_standard", "google"),
    (Complexity.HARD, RouteType.GENERAL, "general_hard", "openai"),
    (Complexity.HARD, RouteType.CODE, "code_hard", "openai"),
    (Complexity.HARD, RouteType.VISUAL_LOG, "visual_hard", "google"),
    (Complexity.HARD, RouteType.LONG_CONTEXT, "longctx_hard", "google"),
]


@pytest.mark.parametrize(("complexity", "route_type", "role", "provider"), _MATRIX_GOLDENS)
def test_route_full_matrix(
    complexity: Complexity, route_type: RouteType, role: str, provider: str
) -> None:
    config = load_orchestration_config()
    choice = route("q", complexity, route_type, config=config)
    entry = config.entry_for_role(role)
    assert choice.role == role
    assert choice.provider == provider
    assert choice.model_name == entry.name
    assert choice.price_in == entry.price_in
    assert choice.price_out == entry.price_out
    assert choice.context_window == entry.context_window
    assert choice.complexity is complexity
    assert choice.route_type is route_type


def test_route_type_none_resolves_to_general() -> None:
    config = load_orchestration_config()
    choice = route("q", Complexity.STANDARD, None, config=config)
    assert choice.route_type is RouteType.GENERAL
    assert choice.role == "openai_standard"


def _partial_matrix_config() -> OrchestrationConfig:
    """A config whose matrix is missing the (STANDARD, CODE) cell entirely."""
    return OrchestrationConfig(
        version=1,
        catalog=[
            ModelCatalogEntry(
                provider="anthropic",
                name="model-a",
                price_in=1.0,
                price_out=2.0,
                context_window=100_000,
                roles=["fallback_role"],
            ),
            ModelCatalogEntry(
                provider="google",
                name="model-b",
                price_in=1.0,
                price_out=2.0,
                context_window=100_000,
                roles=["visual_role"],
            ),
        ],
        matrix={Complexity.STANDARD: {RouteType.VISUAL_LOG: "visual_role"}},
        default_role="fallback_role",
        cost=CostConfig(credits_per_dollar=100.0),
    )


def test_route_missing_cell_falls_back_to_default_role() -> None:
    config = _partial_matrix_config()
    # Missing type cell within a present complexity row.
    choice = route("q", Complexity.STANDARD, RouteType.CODE, config=config)
    assert choice.role == "fallback_role"
    assert choice.provider == "anthropic"
    # Missing complexity row entirely.
    choice = route("q", Complexity.HARD, RouteType.VISUAL_LOG, config=config)
    assert choice.role == "fallback_role"


def test_route_deterministic_across_runs() -> None:
    config = load_orchestration_config()
    choices = [
        route("same query", Complexity.HARD, RouteType.CODE, config=config) for _ in range(50)
    ]
    assert all(choice == choices[0] for choice in choices)


def test_route_ignores_query_in_v1() -> None:
    config = load_orchestration_config()
    a = route("short", Complexity.STANDARD, RouteType.VISUAL_LOG, config=config)
    b = route(
        "a completely different and much longer query " * 50,
        Complexity.STANDARD,
        RouteType.VISUAL_LOG,
        config=config,
    )
    assert a == b


def test_route_rationale_names_the_role() -> None:
    config = load_orchestration_config()
    choice = route("q", Complexity.STANDARD, RouteType.CODE, config=config)
    assert choice.rationale is not None
    assert "code_standard" in choice.rationale
