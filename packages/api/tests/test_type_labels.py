"""Integrity checks for the labeled type fixture (the MO-04 type-estimator spec)."""

from fixtures.type_labels import LABELED_TYPES
from solus_api.orchestration.enums import RouteType


def test_fixture_is_large_enough_to_be_a_spec() -> None:
    assert len(LABELED_TYPES) >= 24


def test_fixture_covers_all_four_types() -> None:
    labels = {expected for _, _, expected in LABELED_TYPES}
    assert labels == set(RouteType)


def test_fixture_covers_the_precedence_cases() -> None:
    """At least one LONG_CONTEXT entry must carry code-flavored text and one
    must carry visual/log-flavored text — the hard-constraint-beats-preference
    cases the estimator exists to get right."""
    long_queries = [q for q, _, expected in LABELED_TYPES if expected is RouteType.LONG_CONTEXT]
    assert any("(" in q for q in long_queries)  # code-flavored (call syntax)
    assert any("telemetry" in q or "logs" in q for q in long_queries)  # visual-flavored


def test_fixture_queries_are_unique() -> None:
    queries = [q for q, _, _ in LABELED_TYPES]
    assert len(queries) == len(set(queries))
