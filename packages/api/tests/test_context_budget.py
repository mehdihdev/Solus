# SOLUSDEV-321 (P0-T2) — the SOL context budget follows the routing tier and
# lives in models.yaml: trivial 8,000 / standard 24,000 / hard 60,000 tokens,
# each layer's cap a configured share of the total. Also pins the two other
# config sections this task adds (`practice_patterns`, `scope`).
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fixtures.scope_doubles import empty_graph, no_hits
from pydantic import ValidationError
from solus_api.agent.interfaces import ContextBudget
from solus_api.agent.layers import LayerBudget, LayeredContextBudget
from solus_api.agent.turn_scope import ScopeInputs, plan_scope
from solus_api.orchestration import config as orchestration_config
from solus_api.orchestration.config import (
    ContextBudgetConfig,
    OrchestrationConfig,
    ScopeConfig,
    load_orchestration_config,
)
from solus_api.orchestration.enums import Complexity

_TOTALS = {Complexity.TRIVIAL: 8_000, Complexity.STANDARD: 24_000, Complexity.HARD: 60_000}
_TIERS = tuple(_TOTALS)
_PRACTICE_PHRASES = [
    "best practice",
    "how should",
    "design review",
    "is it ok to",
    "rule of thumb",
    "what is the right way",
]


def _shipped_budget() -> ContextBudgetConfig:
    return load_orchestration_config().context_budget


def _shipped_yaml() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(
        Path(orchestration_config.__file__).with_name("models.yaml").read_text()
    )
    return data


def test_for_tier_values_8000_24000_60000() -> None:
    for tier, total in _TOTALS.items():
        budget = LayeredContextBudget.for_tier(tier, _shipped_budget())
        assert isinstance(budget, ContextBudget)
        assert budget.max_tokens == total


def test_layer_caps_scale_with_tier() -> None:
    layers = [LayeredContextBudget.for_tier(tier, _shipped_budget()).layers for tier in _TIERS]
    for name, scale in _shipped_budget().layer_scale.items():
        caps = [getattr(layer, name) for layer in layers]
        assert caps == [round(_TOTALS[tier] * scale) for tier in _TIERS]
        assert caps[0] < caps[1] < caps[2]


def test_layer_scale_reproduces_the_pre_tier_caps_at_the_old_4000_total() -> None:
    """Standard behaviour only scales: at the old flat total the shares give back
    today's `LayerBudget` defaults."""
    for name, scale in _shipped_budget().layer_scale.items():
        assert round(4_000 * scale) == getattr(LayerBudget(), name)


@pytest.mark.parametrize("tier", _TIERS)
async def test_plan_scope_budget_follows_the_tier(tier: Complexity) -> None:
    plan = await plan_scope(
        ScopeInputs(message="why does the servo stall?", tier=tier),
        search=no_hits,
        load=empty_graph,
        disambiguate=None,
        config=load_orchestration_config(),
    )
    budget = plan.budget
    assert isinstance(budget, LayeredContextBudget)
    assert budget.max_tokens == _TOTALS[tier]
    assert budget.layers == LayeredContextBudget.for_tier(tier, _shipped_budget()).layers
    # Tier-independent (SEC-H3): the turn's one graph pull is bounded the same way (P1-T1).
    assert budget.max_entities == 60


def test_models_yaml_loads_with_new_sections() -> None:
    config = load_orchestration_config()
    budget = config.context_budget
    assert (budget.trivial, budget.standard, budget.hard) == (8_000, 24_000, 60_000)
    assert set(budget.layer_scale) == set(LayerBudget.model_fields)

    assert config.practice_patterns == _PRACTICE_PHRASES
    assert len(config.practice_regexes) == 6
    assert all(regex.flags & 2 for regex in config.practice_regexes)  # re.IGNORECASE

    keywords = config.scope.domain_keywords
    assert set(keywords) == {"runtime", "environment"}
    assert all(keywords[group] for group in keywords)
    # Outside `estimator.domain_keywords` on purpose: each extra estimator group
    # shifts complexity routing by `weights.extra_domain`.
    assert set(config.estimator.domain_keywords) == {"code", "electrical", "mechanical"}


@pytest.mark.parametrize("phrase", ["Best practice for decoupling?", "Is it OK to share a rail"])
def test_practice_patterns_match_case_insensitively(phrase: str) -> None:
    assert any(regex.search(phrase) for regex in load_orchestration_config().practice_regexes)


def test_a_practice_pattern_that_is_not_a_regex_fails_config_load() -> None:
    with pytest.raises(ValidationError, match="practice_patterns"):
        OrchestrationConfig.model_validate({**_shipped_yaml(), "practice_patterns": ["best ("]})


def test_hand_built_configs_get_the_defaults() -> None:
    config = OrchestrationConfig.model_validate(
        {k: v for k, v in _shipped_yaml().items() if k not in ("context_budget", "scope")}
    )
    assert config.context_budget == ContextBudgetConfig()
    assert config.scope == ScopeConfig()


def test_a_hard_budget_below_standard_is_rejected() -> None:
    with pytest.raises(ValidationError, match="ordered"):
        ContextBudgetConfig(trivial=8_000, standard=24_000, hard=10_000)


def test_a_non_positive_layer_share_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ContextBudgetConfig(layer_scale={"corpus": 0.0})


def test_a_layer_scale_naming_no_layer_fails_loudly_at_plan_time() -> None:
    config = ContextBudgetConfig(layer_scale={"not_a_layer": 0.5})
    with pytest.raises(ValidationError):
        LayeredContextBudget.for_tier(Complexity.STANDARD, config)


def test_scope_keywords_are_trimmed_and_lowercased() -> None:
    scope = ScopeConfig(domain_keywords={"runtime": [" Stall ", "RUN on"]})
    assert scope.domain_keywords == {"runtime": ["stall", "run on"]}


def test_a_blank_scope_keyword_is_rejected() -> None:
    """A blank keyword would match every message and silently make it runtime-shaped."""
    with pytest.raises(ValidationError):
        ScopeConfig(domain_keywords={"runtime": ["  "]})
