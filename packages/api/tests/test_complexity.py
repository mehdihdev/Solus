"""Query-based complexity estimator (MO-02): labeled fixture, determinism, tunability."""

import time

import pytest
from fixtures.complexity_labels import LABELED_QUERIES
from pydantic import ValidationError
from solus_api.orchestration.complexity import estimate_complexity
from solus_api.orchestration.config import (
    EstimatorConfig,
    EstimatorWeights,
    load_orchestration_config,
)
from solus_api.orchestration.enums import Complexity

_SHIPPED = load_orchestration_config().estimator


@pytest.mark.parametrize(
    ("query", "expected"), LABELED_QUERIES, ids=[q[:40] for q, _ in LABELED_QUERIES]
)
def test_labeled_fixture_matches(query: str, expected: Complexity) -> None:
    """The labeled fixture IS the estimator spec: shipped config reproduces it."""
    assert estimate_complexity(query, config=_SHIPPED) is expected


def test_deterministic_same_query_same_tier() -> None:
    for query, _ in LABELED_QUERIES:
        tiers = {estimate_complexity(query, config=_SHIPPED) for _ in range(20)}
        assert len(tiers) == 1


def test_deterministic_across_fresh_config_loads() -> None:
    fresh = load_orchestration_config().estimator
    for query, _ in LABELED_QUERIES:
        assert estimate_complexity(query, config=fresh) is estimate_complexity(
            query, config=_SHIPPED
        )


def test_threshold_change_flips_tier_with_no_code_change() -> None:
    """Tunable-without-code proof: only the config object differs."""
    query = "what pin is PWM on an Arduino Nano"  # 8 words, zero keyword signals
    relaxed = EstimatorConfig(trivial_max_words=12)
    stricter = EstimatorConfig(trivial_max_words=3)
    assert estimate_complexity(query, config=relaxed) is Complexity.TRIVIAL
    assert estimate_complexity(query, config=stricter) is Complexity.STANDARD


def test_keyword_lists_are_config_too() -> None:
    plain = EstimatorConfig()
    flagged = EstimatorConfig(reasoning_keywords=["drift"], hard_threshold=2)
    query = "drift"
    assert estimate_complexity(query, config=plain) is Complexity.TRIVIAL
    assert estimate_complexity(query, config=flagged) is Complexity.HARD


@pytest.mark.parametrize("query", ["", "   ", "\n\t "])
def test_empty_and_whitespace_return_standard(query: str) -> None:
    """No signal at all -> the safe default, never a crash, never HARD."""
    assert estimate_complexity(query, config=_SHIPPED) is Complexity.STANDARD
    assert estimate_complexity(query, config=EstimatorConfig()) is Complexity.STANDARD


def test_no_signal_queries_split_on_length_only() -> None:
    config = EstimatorConfig()  # empty keyword lists: length is the only signal
    short = "ok"
    longer = " ".join(["word"] * 13)  # > trivial_max_words, < hard_min_words
    assert estimate_complexity(short, config=config) is Complexity.TRIVIAL
    assert estimate_complexity(longer, config=config) is Complexity.STANDARD


def test_very_long_query_adds_the_length_weight() -> None:
    config = EstimatorConfig(
        hard_min_words=35, hard_threshold=2, weights=EstimatorWeights(long_query=2)
    )
    ramble = " ".join(["word"] * 35)
    assert estimate_complexity(ramble, config=config) is Complexity.HARD


def test_keyword_entries_are_regexes_matching_exactly_what_they_say() -> None:
    """MO-02b: entries are explicit regex patterns — the author writes the
    anchors and morphology; the estimator adds nothing."""
    config = EstimatorConfig(reasoning_keywords=[r"\bdrift(s|ing|ed)?\b"], hard_threshold=99)
    hit = estimate_complexity("the odometry is drifting badly", config=config)
    miss = estimate_complexity("the boat went adrift yesterday", config=config)
    assert hit is Complexity.STANDARD  # 'drifting' is written into the pattern
    assert miss is Complexity.TRIVIAL  # 'adrift' has no boundary before 'drift'


def test_invalid_regex_fails_at_config_load_not_estimate_time() -> None:
    with pytest.raises(ValidationError, match="tool_keywords"):
        EstimatorConfig(tool_keywords=["(unclosed"])
    with pytest.raises(ValidationError, match="domain_keywords"):
        EstimatorConfig(domain_keywords={"code": ["*bad"]})


# --- MO-02b adversarial false positives (frozen 32 labels stay untouched) ------
# Each probe pairs a LOOKALIKE word with one real CODE-domain hit: if the
# lookalike wrongly fired its domain, the query would score cross-domain (+2)
# and land STANDARD; staying TRIVIAL proves the pattern did not fire.


@pytest.mark.parametrize(
    "query",
    [
        "currently flashing the firmware",  # 'currently' must not hit current
        "a framework for the firmware tests",  # 'framework' must not hit frame
        "wireless telemetry from the firmware",  # 'wireless' must not hit wire
        "escape sequences in the firmware logs",  # 'escape' must not hit esc
        "the arm64 image and the firmware",  # 'arm64' must not hit arm
        "the ARM processor and the firmware",  # ARM-the-architecture must not hit arm
        "a powerful update to the firmware",  # 'powerful' must not hit power
    ],
)
def test_lookalike_words_do_not_fire_domain_patterns(query: str) -> None:
    assert estimate_complexity(query, config=_SHIPPED) is Complexity.TRIVIAL


@pytest.mark.parametrize(
    "query",
    [
        "the current draw and the firmware",  # current (elec) + firmware (code)
        "the wiring and the firmware",  # wiring (elec) + firmware (code)
        "the ESC and the firmware",  # esc (elec) + firmware (code)
        "the robot arm and the firmware",  # arm (mech) + firmware (code)
    ],
)
def test_real_domain_words_still_fire(query: str) -> None:
    assert estimate_complexity(query, config=_SHIPPED) is Complexity.STANDARD


def test_arm64_build_query_is_not_scored_cross_domain() -> None:
    """The ticket's canonical adversarial case: an ARM-architecture CI question
    must not be billed as a cross-domain mechanical+electrical diagnosis."""
    tier = estimate_complexity("why is my arm64 build currently failing in CI", config=_SHIPPED)
    assert tier is Complexity.STANDARD  # 'why' alone; NOT HARD, NOT cross-domain


def test_adversarial_long_queries_complete_quickly() -> None:
    """ReDoS ratchet: the shipped patterns must stay linear-time. The patterns
    are hand-tunable config — a future edit introducing nested unbounded
    repetition (catastrophic backtracking) should fail HERE, not hang prod.
    Budget is ~10x the measured worst case for these ~140-350KB inputs."""
    for adversarial in ("is not " * 20_000, "not " + "a " * 50_000, "why arm " * 20_000):
        start = time.perf_counter()
        estimate_complexity(adversarial, config=_SHIPPED)
        assert time.perf_counter() - start < 1.0


def test_which_framework_lookup_is_trivial() -> None:
    tier = estimate_complexity(
        "which framework should I use for the wireless dashboard", config=_SHIPPED
    )
    assert tier is Complexity.TRIVIAL


# --- MO-02b phrase-variant equivalence (the malfunction/negation family) -------


_MALFUNCTION_VARIANTS = [
    "why is my servo not working",
    "why doesn't my servo work",
    "why won't my servo turn",
    "why isn't my servo responding",
    "why does my servo fail to move",
    "why has my servo stopped moving",
]


def test_semantically_equivalent_malfunction_phrasings_tier_identically() -> None:
    tiers = {estimate_complexity(q, config=_SHIPPED) for q in _MALFUNCTION_VARIANTS}
    assert len(tiers) == 1, f"variants split across tiers: {tiers}"


# --- MO-02b: phrasing is not complexity ----------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "how do I turn on the LED",
        "how to update the firmware on my board",
    ],
)
def test_plain_how_to_lookups_are_trivial(query: str) -> None:
    """'how do i' / 'how to' are phrasing, not complexity — plain lookups must
    reach the cheap tier instead of flooring at STANDARD."""
    assert estimate_complexity(query, config=_SHIPPED) is Complexity.TRIVIAL


def test_cross_domain_breadth_pushes_hard() -> None:
    config = EstimatorConfig(
        domain_keywords={
            "code": ["firmware"],
            "electrical": ["wiring"],
            "mechanical": ["chassis"],
        },
        weights=EstimatorWeights(extra_domain=2),
        hard_threshold=4,
    )
    cross = "the firmware and the wiring fight inside the chassis"
    single = "update the firmware"
    assert estimate_complexity(cross, config=config) is Complexity.HARD  # 3 domains
    assert estimate_complexity(single, config=config) is Complexity.TRIVIAL


def test_distinct_keywords_counted_once() -> None:
    """Repeating one keyword must not stack score (no keyword stuffing)."""
    config = EstimatorConfig(reasoning_keywords=["drift"], hard_threshold=4)
    query = "drift drift drift drift drift"
    assert estimate_complexity(query, config=config) is Complexity.STANDARD
