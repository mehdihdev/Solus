"""Step-1 gateway + route() stub contract (ADR-026)."""

import pytest
from solus_api.orchestration.config import load_orchestration_config
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.router import derive_complexity, route


def test_derive_complexity_maps_starter_contexts() -> None:
    assert derive_complexity(InteractionContext.CODE_AUTOCOMPLETE) is Complexity.TRIVIAL
    assert derive_complexity(InteractionContext.SOL_OPEN_QUESTION) is Complexity.HARD
    assert derive_complexity(InteractionContext.COMPATIBILITY_RESEARCH) is Complexity.STANDARD


def test_route_is_stubbed_until_mo01() -> None:
    config = load_orchestration_config()
    with pytest.raises(NotImplementedError):
        route("q", Complexity.STANDARD, RouteType.CODE, config=config)
