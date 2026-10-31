"""MO-04 type estimator: labeled fixture, precedence, chain, determinism, tunability."""

import time
from functools import partial

import pytest
from fixtures.type_labels import LABELED_TYPES
from pydantic import ValidationError
from solus_api.graph import kinds
from solus_api.orchestration.config import TypeEstimatorConfig, load_orchestration_config
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.type_estimator import (
    CONTEXT_TYPE_DEFAULTS,
    AttachmentHint,
    derive_type,
    estimate_tokens,
    estimate_type,
    round_one_complexity,
    route_type_for_kinds,
)

_SHIPPED = load_orchestration_config().type_estimator


@pytest.mark.parametrize(
    ("query", "attachments", "expected"),
    LABELED_TYPES,
    ids=[q[:40] for q, _, _ in LABELED_TYPES],
)
def test_labeled_type_fixture_matches(
    query: str, attachments: tuple[AttachmentHint, ...] | None, expected: RouteType
) -> None:
    """The labeled fixture IS the type-estimator spec: shipped config reproduces it."""
    assert estimate_type(query, config=_SHIPPED, attachments=attachments) is expected


def test_deterministic_same_inputs_same_type() -> None:
    for query, attachments, _ in LABELED_TYPES:
        results = {
            estimate_type(query, config=_SHIPPED, attachments=attachments) for _ in range(20)
        }
        assert len(results) == 1


def test_precedence_long_context_beats_visual_beats_code() -> None:
    """Hard constraints beat soft preferences: window > modality > strength."""
    code_and_logs = "why does init_pwm() crash — see these telemetry logs"
    # code + visual words, no size -> VISUAL_LOG (modality beats code strength)
    assert estimate_type(code_and_logs, config=_SHIPPED, attachments=None) is RouteType.VISUAL_LOG
    # same query with a huge attachment -> LONG_CONTEXT (window beats modality)
    huge = (AttachmentHint(kind="log", tokens=400_000),)
    assert estimate_type(code_and_logs, config=_SHIPPED, attachments=huge) is RouteType.LONG_CONTEXT


def test_attachment_modality_alone_forces_visual_log() -> None:
    """An attached image is a physical constraint even with zero visual wording."""
    attachments = (AttachmentHint(kind="Image", tokens=0),)  # kind is case-insensitive
    assert (
        estimate_type("does this look right", config=_SHIPPED, attachments=attachments)
        is RouteType.VISUAL_LOG
    )


def test_derive_type_maps_starter_contexts() -> None:
    assert derive_type(InteractionContext.CODE_AUTOCOMPLETE) is RouteType.CODE
    assert derive_type(InteractionContext.TELEMETRY_SUMMARY) is RouteType.VISUAL_LOG
    assert derive_type(InteractionContext.SOL_OPEN_QUESTION) is RouteType.GENERAL
    assert derive_type(InteractionContext.COMPATIBILITY_RESEARCH) is RouteType.GENERAL
    assert set(CONTEXT_TYPE_DEFAULTS) == set(InteractionContext)


def test_empty_query_without_attachments_is_general() -> None:
    assert estimate_type("", config=_SHIPPED) is RouteType.GENERAL
    assert estimate_type("   ", config=_SHIPPED) is RouteType.GENERAL


def test_estimate_tokens_is_the_documented_chars_heuristic() -> None:
    config = TypeEstimatorConfig(chars_per_token=4)
    assert estimate_tokens("abcdefgh", config=config) == 2
    # SOLUSDEV-321: the one estimator floors at 1 (context packing relied on that), so
    # an empty string is one token, not zero.
    assert estimate_tokens("", config=config) == 1


def test_thresholds_are_tunable_without_code_change() -> None:
    tiny_threshold = TypeEstimatorConfig(long_context_min_tokens=2)
    assert estimate_type("a query of many words", config=tiny_threshold) is RouteType.LONG_CONTEXT
    custom_code = TypeEstimatorConfig(code_patterns=[r"\bfoo\b"])
    assert estimate_type("please fix foo now", config=custom_code) is RouteType.CODE
    assert estimate_type("please fix bar now", config=custom_code) is RouteType.GENERAL


def test_max_length_adversarial_query_stays_fast() -> None:
    """ReDoS ratchet (security C1): a 1M-char all-word-char query — the exact
    shape that made the old '\\w+\\(\\)' pattern quadratic (~15 min) — must
    resolve in milliseconds. Size rule short-circuits, scans are edge-bounded,
    and every shipped pattern must stay linear."""
    start = time.perf_counter()
    result = estimate_type("a" * 1_000_000, config=_SHIPPED)
    elapsed = time.perf_counter() - start
    assert result is RouteType.LONG_CONTEXT  # 250K tokens >= threshold
    assert elapsed < 0.5


def test_sub_threshold_huge_query_scans_are_bounded() -> None:
    """Below the LONG_CONTEXT threshold the regex scans DO run — bounded to the
    edge windows, so still fast on ~300KB of word chars."""
    query = "a" * 300_000  # 75K tokens < 100K threshold -> scans run
    start = time.perf_counter()
    result = estimate_type(query, config=_SHIPPED)
    elapsed = time.perf_counter() - start
    assert result is RouteType.GENERAL
    assert elapsed < 0.5


def test_signals_at_the_end_of_a_long_paste_still_count() -> None:
    """The scan window covers first+last chunks: a huge paste with the actual
    question at the END keeps its signals."""
    config = TypeEstimatorConfig(
        code_patterns=[r"\btraceback\b"], scan_max_chars=1_000, long_context_min_tokens=10**9
    )
    query = "x " * 30_000 + " fix this traceback please"
    assert estimate_type(query, config=config) is RouteType.CODE


def test_invalid_regex_fails_at_config_load() -> None:
    with pytest.raises(ValidationError, match="code_patterns"):
        TypeEstimatorConfig(code_patterns=["(unclosed"])


def test_min_hits_knobs_gate_the_signals() -> None:
    config = TypeEstimatorConfig(code_patterns=[r"\bfoo\b", r"\bbar\b"], code_min_hits=2)
    assert estimate_type("foo only", config=config) is RouteType.GENERAL
    assert estimate_type("foo and bar", config=config) is RouteType.CODE


def test_code_kinds_route_code() -> None:
    """SOLUSDEV-321 P0-T7: a scope holding a code file, module or Arduino sketch routes CODE
    whatever the message says, and so does a message the estimator reads as code. Anything
    else is None: VISUAL_LOG and LONG_CONTEXT stay with the estimator and the attachments, and
    a repository on its own is not a code scope."""
    route = partial(route_type_for_kinds, config=_SHIPPED)
    for kind in (kinds.CODE_FILE, kinds.CODE_MODULE, kinds.ARDUINO_SKETCH):
        assert route(iter([kinds.COMPONENT, kind]), "what is I2C") is RouteType.CODE
    assert route((), "fix the traceback in motor.py") is RouteType.CODE
    assert route([kinds.CODE_REPO, kinds.COMPONENT], "what is I2C") is None
    assert route((), "what is I2C") is None
    # The estimator's precedence stands: logs beat a code hit, so this message alone is not code.
    assert route((), "why does init_pwm() crash — see these telemetry logs") is None


def test_round_one_complexity_routes_a_finding_hard() -> None:
    """SOLUSDEV-321 P0-T7: a turn about a finding runs round 1 HARD whatever tier was explicit
    before it ("think harder"'s, or none); without one, the explicit tier, or None, stands."""
    for explicit in (None, Complexity.STANDARD):
        assert round_one_complexity(explicit, about_finding=True) is Complexity.HARD
    assert round_one_complexity(Complexity.STANDARD, about_finding=False) is Complexity.STANDARD
    assert round_one_complexity(None, about_finding=False) is None
