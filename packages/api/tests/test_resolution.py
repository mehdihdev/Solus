"""MO-04 shared routing resolution: chains, sources, window fit, escalation policy."""

from solus_api.orchestration.config import (
    CostConfig,
    ModelCatalogEntry,
    OrchestrationConfig,
)
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.resolution import (
    ContextWindowExceededError,
    OverrideNotViableError,
    resolve_routing,
)
from solus_api.orchestration.type_estimator import AttachmentHint

assert ContextWindowExceededError is not None  # exported for the gateway guard
assert OverrideNotViableError is not None


def _windowed_config() -> OrchestrationConfig:
    """Three tiers with deliberately tiny/mid/big windows so fit and escalation
    are easy to trigger; every route type maps to the same role per tier."""
    all_types = {t: None for t in RouteType}

    def row(role: str) -> dict[str, str]:
        return {t.value: role for t in all_types}

    return OrchestrationConfig(
        version=1,
        catalog=[
            ModelCatalogEntry(
                provider="anthropic",
                name="tiny-model",
                price_in=1.0,
                price_out=2.0,
                context_window=1_000,
                roles=["r_trivial"],
            ),
            ModelCatalogEntry(
                provider="anthropic",
                name="mid-model",
                price_in=3.0,
                price_out=6.0,
                context_window=100_000,
                roles=["r_standard"],
            ),
            ModelCatalogEntry(
                provider="google",
                name="big-model",
                price_in=5.0,
                price_out=10.0,
                context_window=1_000_000,
                roles=["r_hard"],
            ),
        ],
        matrix={
            Complexity.TRIVIAL: row("r_trivial"),  # type: ignore[dict-item]
            Complexity.STANDARD: row("r_standard"),  # type: ignore[dict-item]
            Complexity.HARD: row("r_hard"),  # type: ignore[dict-item]
        },
        default_role="r_standard",
        cost=CostConfig(credits_per_dollar=100.0),
    )


def test_sources_reflect_each_rung_of_both_chains() -> None:
    config = _windowed_config()
    explicit = resolve_routing("hi", complexity=Complexity.HARD, type=RouteType.CODE, config=config)
    assert (explicit.complexity_source, explicit.type_source) == ("explicit", "explicit")
    assert explicit.choice.complexity is Complexity.HARD
    assert explicit.choice.route_type is RouteType.CODE

    contextual = resolve_routing("hi", context=InteractionContext.TELEMETRY_SUMMARY, config=config)
    assert (contextual.complexity_source, contextual.type_source) == ("context", "context")
    assert contextual.choice.complexity is Complexity.TRIVIAL  # derive_complexity
    assert contextual.choice.route_type is RouteType.VISUAL_LOG  # derive_type

    estimated = resolve_routing("hi", config=config)
    assert (estimated.complexity_source, estimated.type_source) == ("estimator", "estimator")


def test_fitting_request_reports_fits_and_no_escalation() -> None:
    resolved = resolve_routing("hi", complexity=Complexity.TRIVIAL, config=_windowed_config())
    assert resolved.fits is True
    assert resolved.reason is None
    assert resolved.escalated is False


def test_explicit_override_that_does_not_fit_is_refused_not_escalated() -> None:
    """User promise → the short factual reason, NEVER a silent escalation."""
    resolved = resolve_routing(
        "x" * 8_000,  # ~2K tokens > tiny-model's 1K window
        complexity=Complexity.TRIVIAL,
        config=_windowed_config(),
    )
    assert resolved.fits is False
    assert resolved.escalated is False
    assert resolved.choice.model_name == "tiny-model"  # the override result, unchanged
    assert resolved.reason == "Too many tokens for this tier (2K > 1K)"


def test_system_routed_misfit_escalates_within_the_role_family() -> None:
    """No override = no promise: the system's routing miss escalates to a model
    that fits, same route type, and says so."""
    config = _windowed_config()
    resolved = resolve_routing(
        "x" * 8_000,  # ~2K tokens
        context=InteractionContext.CODE_AUTOCOMPLETE,  # system-derived: trivial × code
        config=config,
    )
    assert resolved.fits is True
    assert resolved.escalated is True
    assert resolved.escalated_from_role == "r_trivial"
    assert resolved.choice.model_name == "mid-model"  # first tier up that fits
    assert resolved.choice.route_type is RouteType.CODE  # family preserved
    assert resolved.complexity_source == "context"  # source unchanged by escalation


def test_escalation_exhausted_reports_clear_limit() -> None:
    resolved = resolve_routing(
        "x" * 8_000_000,  # ~2M tokens: bigger than every window
        context=InteractionContext.CODE_AUTOCOMPLETE,
        config=_windowed_config(),
    )
    assert resolved.fits is False
    assert resolved.escalated is False
    assert resolved.reason is not None
    assert "exceeds every available model" in resolved.reason
    assert "1000K" in resolved.reason  # names the largest window in the family


def test_attachment_tokens_count_toward_the_window() -> None:
    resolved = resolve_routing(
        "tiny query",
        complexity=Complexity.TRIVIAL,
        attachments=(AttachmentHint(kind="file", tokens=5_000),),
        config=_windowed_config(),
    )
    assert resolved.fits is False
    assert resolved.reason is not None
    assert "5K > 1K" in resolved.reason


def test_estimator_long_context_path_routes_long_context_type() -> None:
    """A huge attachment with no explicit/context input flows through
    estimate_type → LONG_CONTEXT (uses the shipped-default type estimator only
    when configured; here the in-test config has default thresholds)."""
    resolved = resolve_routing(
        "summarize this",
        attachments=(AttachmentHint(kind="file", tokens=200_000),),
        config=_windowed_config(),
    )
    assert resolved.type_source == "estimator"
    assert resolved.choice.route_type is RouteType.LONG_CONTEXT


def test_resolution_is_deterministic() -> None:
    config = _windowed_config()
    results = {
        resolve_routing("why does init_pwm() fail", config=config).choice.model_name
        for _ in range(10)
    }
    assert len(results) == 1
