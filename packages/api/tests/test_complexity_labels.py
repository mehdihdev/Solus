"""Integrity checks for the labeled complexity fixture (the MO-02 estimator spec)."""

from fixtures.complexity_labels import LABELED_QUERIES
from solus_api.orchestration.enums import Complexity


def test_fixture_is_large_enough_to_be_a_spec() -> None:
    assert len(LABELED_QUERIES) >= 30


def test_fixture_covers_all_three_tiers() -> None:
    labels = {tier for _, tier in LABELED_QUERIES}
    assert labels == set(Complexity)


def test_fixture_queries_are_unique_and_labels_are_tiers() -> None:
    queries = [query for query, _ in LABELED_QUERIES]
    assert len(queries) == len(set(queries))
    assert all(isinstance(tier, Complexity) for _, tier in LABELED_QUERIES)
