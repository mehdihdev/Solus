"""Cost formula (real) + stub contracts for the debit/pre-flight hooks (ADR-024)."""

import uuid

import pytest
from solus_api.orchestration.choice import ModelChoice
from solus_api.orchestration.config import CostConfig
from solus_api.orchestration.cost import (
    compute_call_credits,
    has_sufficient_credits,
    track_cost,
)
from solus_api.orchestration.enums import Complexity, RouteType


def _model() -> ModelChoice:
    return ModelChoice(
        provider="anthropic",
        model_name="claude-sonnet-5",
        price_in=3.0,
        price_out=15.0,
        context_window=200_000,
        role="code_standard",
        complexity=Complexity.STANDARD,
        route_type=RouteType.CODE,
    )


def test_compute_call_credits_known_value() -> None:
    # 1M in @ $3 + 1M out @ $15 = $18; * 2.0 margin * 100 credits/$ = 3600.
    cost = CostConfig(credits_per_dollar=100.0)
    assert compute_call_credits(_model(), 1_000_000, 1_000_000, cost) == 3600


def test_compute_call_credits_rounds_up_nonzero() -> None:
    # A tiny real call still bills at least 1 credit (ceil), never 0.
    cost = CostConfig(credits_per_dollar=100.0)
    assert compute_call_credits(_model(), 1, 0, cost) == 1


async def test_has_sufficient_credits_is_stubbed() -> None:
    with pytest.raises(NotImplementedError):
        await has_sufficient_credits(uuid.uuid4(), 10, session=None)  # type: ignore[arg-type]


async def test_track_cost_is_stubbed() -> None:
    cost = CostConfig(credits_per_dollar=100.0)
    with pytest.raises(NotImplementedError):
        await track_cost(
            "call-1",
            uuid.uuid4(),
            _model(),
            10,
            10,
            session=None,  # type: ignore[arg-type]
            cost=cost,
        )
