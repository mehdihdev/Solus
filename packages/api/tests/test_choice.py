"""ModelChoice — frozen, validated value object route() returns (ADR-026)."""

import pytest
from pydantic import ValidationError
from solus_api.orchestration.choice import ModelChoice
from solus_api.orchestration.enums import Complexity, RouteType


def _choice(price_in: float = 3.0) -> ModelChoice:
    return ModelChoice(
        provider="anthropic",
        model_name="claude-x",
        price_in=price_in,
        price_out=15.0,
        context_window=200_000,
        role="general_standard",
        complexity=Complexity.STANDARD,
        route_type=RouteType.GENERAL,
    )


def test_carries_resolved_config() -> None:
    choice = _choice()
    assert choice.model_name == "claude-x"
    assert choice.route_type is RouteType.GENERAL
    assert choice.rationale is None


def test_is_frozen() -> None:
    choice = _choice()
    with pytest.raises(ValidationError):
        choice.price_in = 1.0  # frozen — Pydantic raises at runtime


def test_rejects_negative_price() -> None:
    with pytest.raises(ValidationError):
        _choice(price_in=-1.0)
