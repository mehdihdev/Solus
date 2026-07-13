"""Integrity meta-tests for the FP-01 labeled fingerprint fixture.

These do not run the matcher. They assert the fixture itself is well-formed:
big enough, uniquely keyed, fully partitioned (every observation labeled into
exactly one bucket), and covering every v1-relevant modality plus the
injection red-team case CLAUDE.md §7 requires. Mirrors test_complexity_labels.py.
"""

from fixtures.fingerprint_labels import (
    ALL_CASES,
    CONFUSABLE_CASES,
    MATCHED_CASES,
    Case,
)
from solus_api.fingerprint.contract import Modality


def test_corpus_is_large_enough() -> None:
    assert len(ALL_CASES) >= 24
    assert len(CONFUSABLE_CASES) >= 8


def test_all_cases_is_matched_plus_confusable() -> None:
    assert ALL_CASES == [*MATCHED_CASES, *CONFUSABLE_CASES]


def test_case_ids_unique_and_named() -> None:
    ids = [case.case_id for case in ALL_CASES]
    assert len(ids) == len(set(ids))
    assert all(ids), "every case needs a non-empty case_id"


def test_refs_unique_within_each_case() -> None:
    for case in ALL_CASES:
        refs = [obs.ref for obs in case.observations]
        assert len(refs) == len(set(refs)), case.case_id


def _labeled_buckets(case: Case) -> list[frozenset[str]]:
    return [*(group.refs for group in case.groups), case.unmatched, case.ambiguous]


def test_every_ref_labeled_into_exactly_one_bucket() -> None:
    for case in ALL_CASES:
        refs = {obs.ref for obs in case.observations}
        seen: set[str] = set()
        for bucket in _labeled_buckets(case):
            assert not bucket & seen, f"{case.case_id}: ref labeled twice"
            assert bucket <= refs, f"{case.case_id}: label references unknown ref"
            seen |= bucket
        assert seen == refs, f"{case.case_id}: unlabeled refs {refs - seen}"


def test_groups_are_non_empty() -> None:
    for case in ALL_CASES:
        for group in case.groups:
            assert group.refs, f"{case.case_id}: empty expected group"


def test_conflict_refs_are_grouped_refs() -> None:
    """Conflict evidence only exists inside a CanonicalPart, so the refs must be grouped."""
    for case in ALL_CASES:
        grouped = {ref for group in case.groups for ref in group.refs}
        assert case.expect_conflict_in <= grouped, case.case_id


def test_every_v1_modality_is_exercised() -> None:
    seen = {obs.modality for case in ALL_CASES for obs in case.observations}
    assert seen >= (set(Modality) - {Modality.PHOTO})


def test_injection_red_team_case_present() -> None:
    """CLAUDE.md §7: adversarial-instruction fixtures are part of the agent test suite."""
    values = [obs.value.lower() for case in CONFUSABLE_CASES for obs in case.observations]
    assert any("ignore previous" in value for value in values)


def test_debatable_flags_carry_rationales() -> None:
    for case in ALL_CASES:
        if case.debatable is not None:
            assert len(case.debatable.strip()) >= 20, f"{case.case_id}: rationale too thin"


def test_confusable_cases_never_expect_cross_group_merges() -> None:
    """A confusable case labels at least two identities apart (or everything out)."""
    for case in CONFUSABLE_CASES:
        assert len(case.groups) != 1 or case.unmatched or case.ambiguous, case.case_id
