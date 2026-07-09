"""Orchestration enums (ADR-026) — values are the lowercase keys used in models.yaml."""

from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType


def test_complexity_tiers_in_order() -> None:
    assert [c.value for c in Complexity] == ["trivial", "standard", "hard"]


def test_route_type_members() -> None:
    assert RouteType.GENERAL.value == "general"
    assert {t.value for t in RouteType} == {"code", "visual_log", "long_context", "general"}


def test_interaction_context_members() -> None:
    assert InteractionContext.CODE_AUTOCOMPLETE.value == "code_autocomplete"
    assert InteractionContext.SOL_OPEN_QUESTION.value == "sol_open_question"
