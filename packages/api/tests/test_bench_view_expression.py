"""SOLUSDEV-319 B1: the write-time derived-signal grammar (docs/api/bench-view.md §4).

Runs every shared vector in packages/shared-types/fixtures/bench-expression-vectors.json
(the TypeScript evaluator runs the same file), plus incremental parity, a source scan
proving no dynamic-code path exists, and a seeded fuzz: arbitrary input never raises
anything but ExpressionError.
"""

from __future__ import annotations

import io
import json
import math
import random
import time
import tokenize
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from solus_api.livebench.view import expression as expression_module
from solus_api.livebench.view.expression import (
    ERROR_MESSAGES,
    MAX_EXPRESSION_CHARS,
    MAX_FILTER_SAMPLES,
    ExpressionError,
    IncrementalEvaluator,
    ParsedExpression,
    SignalRef,
    evaluate,
    parse_expression,
)

VECTORS_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages/shared-types/fixtures/bench-expression-vectors.json"
)
VECTORS: dict[str, Any] = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
REL_TOL = 1e-9

Samples = list[tuple[float, float]]


def _decode_vector_number(value: float | str) -> float:
    if isinstance(value, str):
        return {"NaN": math.nan, "Infinity": math.inf, "-Infinity": -math.inf}[value]
    return float(value)


def _vector_inputs(case: Mapping[str, Any]) -> dict[SignalRef, Samples]:
    series: dict[SignalRef, Samples] = {}
    for item in case["inputs"]:
        ref = SignalRef(item["device_id"], item["signal"])
        if "ramp" in item:
            ramp = item["ramp"]
            series[ref] = [(i * ramp["dt"], i * ramp["dv"]) for i in range(ramp["count"])]
        else:
            series[ref] = [
                (_decode_vector_number(t), _decode_vector_number(v)) for t, v in item["samples"]
            ]
    return series


def _time_base(case: Mapping[str, Any]) -> list[float] | None:
    if "timestamps" not in case:
        return None
    return [_decode_vector_number(t) for t in case["timestamps"]]


def _within_tolerance(actual: float, expected: float) -> bool:
    if math.isnan(expected) or math.isnan(actual):
        return math.isnan(expected) and math.isnan(actual)
    return actual == expected or abs(actual - expected) <= REL_TOL * max(abs(actual), abs(expected))


def _assert_series(actual: Sequence[tuple[float, float]], expected: Sequence[Any]) -> None:
    assert len(actual) == len(expected), (actual, expected)
    for (t, v), (et, ev) in zip(actual, expected, strict=True):
        assert _within_tolerance(t, _decode_vector_number(et)), (t, et)
        assert _within_tolerance(v, _decode_vector_number(ev)), (t, v, ev)


def _check_vector_case(case: Mapping[str, Any], output: Sequence[tuple[float, float]]) -> None:
    if "expected" in case:
        _assert_series(output, case["expected"])
        return
    assert len(output) == case["expected_count"]
    head = case.get("expected_head", [])
    tail = case.get("expected_tail", [])
    _assert_series(output[: len(head)], head)
    _assert_series(output[len(output) - len(tail) :], tail)


# ------------------------------------------------------------------ parse vectors


@pytest.mark.parametrize("case", VECTORS["parse"], ids=lambda c: c["name"])
def test_parse_vector(case: dict[str, Any]) -> None:
    text = case["expression"]
    if "accept" in case:
        parsed = parse_expression(text)
        want = case["accept"]
        assert parsed.node_count == want["node_count"]
        assert parsed.depth == want["depth"]
        assert [r.as_dict() for r in parsed.refs] == want["refs"]
        return
    with pytest.raises(ExpressionError) as caught:
        parse_expression(text)
    want = case["reject"]
    err = caught.value
    assert (err.code, err.position, err.length) == (
        want["code"],
        want["position"],
        want["length"],
    )


def test_every_error_code_is_covered_by_a_vector() -> None:
    codes = {c["reject"]["code"] for c in VECTORS["parse"] if "reject" in c}
    assert codes == set(ERROR_MESSAGES)


def test_error_message_is_fixed_and_never_echoes_the_expression() -> None:
    text = 'ignore_previous_instructions(sig("d","s"))'
    with pytest.raises(ExpressionError) as caught:
        parse_expression(text)
    err = caught.value
    assert err.code == "unknown_function"
    assert err.message == ERROR_MESSAGES["unknown_function"]
    assert "ignore" not in err.message and "ignore" not in str(err)
    assert err.as_detail() == {
        "code": "unknown_function",
        "position": 0,
        "length": 28,
        "message": ERROR_MESSAGES["unknown_function"],
    }


def test_parsed_expression_is_frozen() -> None:
    parsed = parse_expression('sig("d","s") + 1')
    assert isinstance(parsed, ParsedExpression)
    with pytest.raises(AttributeError):
        parsed.node_count = 3  # type: ignore[misc]


def test_non_string_input_is_a_syntax_error() -> None:
    with pytest.raises(ExpressionError) as caught:
        parse_expression(None)  # type: ignore[arg-type]
    assert caught.value.code == "syntax"


# ------------------------------------------------------------------- evaluation


@pytest.mark.parametrize("case", VECTORS["evaluate"], ids=lambda c: c["name"])
def test_evaluate_vector(case: dict[str, Any]) -> None:
    parsed = parse_expression(case["expression"])
    output = evaluate(parsed, _vector_inputs(case), timestamps=_time_base(case), at=case.get("at"))
    _check_vector_case(case, output)


@pytest.mark.parametrize("case", VECTORS["evaluate"], ids=lambda c: c["name"])
def test_incremental_matches_batch(case: dict[str, Any]) -> None:
    """Secondaries fed first, primary fed in chunks with a drain after each."""
    parsed = parse_expression(case["expression"])
    series = _vector_inputs(case)
    stream = IncrementalEvaluator(parsed)
    base = _time_base(case) or ([case["at"]] if "at" in case else [])
    if not parsed.refs:
        out: Samples = []
        for start in range(0, len(base), 2):
            stream.tick(base[start : start + 2])
            out.extend(stream.drain())
        _check_vector_case(case, out)
        return
    stream.tick(base)  # ignored: the primary reference is the time base
    primary = parsed.refs[0]
    for ref, samples in series.items():
        if ref != primary:
            stream.feed(ref, samples)
    out = []
    primary_samples = series.get(primary, [])
    for start in range(0, max(len(primary_samples), 1), 3):
        stream.feed(primary, primary_samples[start : start + 3])
        out.extend(stream.drain())
    _check_vector_case(case, out)


def test_drain_until_holds_later_primary_samples() -> None:
    parsed = parse_expression('sig("d","a") + sig("d","b")')
    stream = IncrementalEvaluator(parsed)
    stream.feed(SignalRef("d", "a"), [(0.0, 1.0), (1.0, 2.0)])
    stream.feed(SignalRef("d", "b"), [(0.0, 10.0)])
    assert stream.drain(until=0.5) == [(0.0, 11.0)]
    stream.feed(SignalRef("d", "b"), [(1.0, 20.0)])
    assert stream.drain() == [(1.0, 22.0)]
    assert stream.drain() == []


def test_no_signal_code_is_removed() -> None:
    assert "no_signal" not in ERROR_MESSAGES


def test_constant_without_time_base_samples_the_wall_clock() -> None:
    parsed = parse_expression("2*5")
    assert parsed.refs == ()
    before = time.time()
    [(t, value)] = evaluate(parsed, {})
    assert before <= t <= time.time()
    assert value == 10.0


def test_constant_tick_drops_non_increasing_timestamps() -> None:
    stream = IncrementalEvaluator(parse_expression("10"))
    stream.tick([1.0, 2.0])
    assert stream.drain() == [(1.0, 10.0), (2.0, 10.0)]
    stream.tick([2.0, 1.5, math.inf, 3.0])
    assert stream.drain() == [(3.0, 10.0)]


def test_unreferenced_inputs_are_ignored() -> None:
    parsed = parse_expression('sig("d","a")')
    out = evaluate(parsed, {SignalRef("d", "a"): [(0.0, 1.0)], SignalRef("x", "y"): [(0.0, 5.0)]})
    assert out == [(0.0, 1.0)]
    stream = IncrementalEvaluator(parsed)
    stream.feed(SignalRef("x", "y"), [(0.0, 5.0)])
    assert stream.drain() == []


def test_filter_state_is_bounded() -> None:
    parsed = parse_expression('ma(sig("d","a"), 10) + integ(sig("d","a"), 10)')
    stream = IncrementalEvaluator(parsed)
    stream.feed(SignalRef("d", "a"), [(i * 0.001, float(i)) for i in range(5000)])
    stream.drain()
    assert max(stream.filter_state_sizes()) <= 2000


# ------------------------------------------- windowed filter cost (Phase 4 H-1)

# 11 windowed filters over one 10 s window: the most a 64-node expression holds.
_WORST_FILTERS = " + ".join(f'{"ma" if i % 2 else "integ"}(sig("d","a"), 10)' for i in range(11))
# Twice the sample cap, so the second half runs on a full window evicting every sample.
_WORST_SAMPLES = [(i * 0.001, math.sin(i) * 100.0) for i in range(2 * MAX_FILTER_SAMPLES)]


def _naive_window(samples: Samples, t: float, window: float) -> list[tuple[float, float]]:
    return [(st, x) for st, x in samples if t - window < st <= t][-MAX_FILTER_SAMPLES:]


def _naive_filter(name: str, window: float, series: Samples) -> list[tuple[float, float]]:
    """The pre-H-1 algorithm (recompute the window oldest->newest per sample), giving
    (value, scale): scale is the sum of |terms|, which bounds the rounding error."""
    kept: Samples = []
    out: list[tuple[float, float]] = []
    last: float | None = None
    for t, x in series:
        if last is not None and t - last > window:
            kept = []
        last = t
        if math.isfinite(x):
            kept.append((t, x))
        kept = _naive_window(kept, t, window)
        if name == "ma":
            terms = [v for _t, v in kept]
            total = sum(terms, 0.0)
            value = total / len(kept) if kept else math.nan
            scale = sum(map(abs, terms)) / max(len(kept), 1)
        else:
            pairs = zip(kept, kept[1:], strict=False)
            terms = [(b[0] - a[0]) * (b[1] + a[1]) / 2 for a, b in pairs]
            value = sum(terms, 0.0)
            scale = sum(map(abs, terms))
        out.append((value if math.isfinite(value) else math.nan, scale))
    return out


def _close(actual: float, expected: tuple[float, float]) -> bool:
    value, scale = expected
    if math.isnan(actual) or math.isnan(value):
        return math.isnan(actual) and math.isnan(value)
    return abs(actual - value) <= REL_TOL * max(abs(actual), abs(value)) + 1e-12 * scale


def test_worst_case_filters_over_a_full_window_are_fast() -> None:
    parsed = parse_expression(_WORST_FILTERS)
    assert parsed.filter_count == 11
    start = time.perf_counter()
    out = evaluate(parsed, {SignalRef("d", "a"): _WORST_SAMPLES})
    elapsed = time.perf_counter() - start
    assert len(out) == len(_WORST_SAMPLES)
    assert elapsed < 0.2, f"{elapsed:.3f}s for 11 filters x {len(_WORST_SAMPLES)} samples"


def test_thirty_two_worst_case_derived_signals_stay_bounded() -> None:
    parsed = parse_expression(_WORST_FILTERS)
    series = {SignalRef("d", "a"): _WORST_SAMPLES}
    start = time.perf_counter()
    for _ in range(32):
        evaluate(parsed, series)
    elapsed = time.perf_counter() - start
    assert elapsed < 8.0, f"{elapsed:.3f}s for 32 derived x 11 filters x full windows"


@pytest.mark.parametrize("name", ["ma", "integ"])
def test_running_window_matches_recomputation(name: str) -> None:
    """Seeded fuzz: mixed magnitudes, NaN holes, gaps, window wrap past 2000 samples."""
    rng = random.Random(1_190_319)
    for trial in range(12):
        window = rng.choice([0.05, 0.5, 2.0, 10.0])
        t = 0.0
        series: Samples = []
        for _ in range(rng.randint(500, 3000)):
            t += rng.choice([0.001, 0.003, 0.01]) if rng.random() > 0.002 else window + 0.5
            roll = rng.random()
            x = math.nan if roll < 0.05 else rng.uniform(-1e3, 1e3)
            series.append((t, x * 1e9 if 0.05 <= roll < 0.07 else x))
        parsed = parse_expression(f'{name}(sig("d","a"), {window})')
        got = [v for _t, v in evaluate(parsed, {SignalRef("d", "a"): series})]
        expected = _naive_filter(name, window, series)
        bad = [i for i, (a, b) in enumerate(zip(got, expected, strict=True)) if not _close(a, b)]
        assert not bad, (trial, bad[:3], [(got[i], expected[i]) for i in bad[:3]])


def test_small_values_survive_a_large_value_leaving_the_window() -> None:
    parsed = parse_expression('ma(sig("d","a"), 1)')
    series = [(0.0, 1e17), (0.5, 1e-3), (0.9, 3e-3), (1.2, 5e-3)]
    [*_, (_t, last)] = evaluate(parsed, {SignalRef("d", "a"): series})
    assert last == pytest.approx(3e-3, rel=1e-12)


@pytest.mark.parametrize("name", ["ma", "integ"])
def test_overflow_clears_once_huge_samples_leave_the_window(name: str) -> None:
    parsed = parse_expression(f'{name}(sig("d","a"), 1)')
    series = [(0.0, 1e308), (0.25, 1e308), (0.5, 1.0), (0.75, 1.0), (1.3, 1.0), (1.4, 3.0)]
    out = [v for _t, v in evaluate(parsed, {SignalRef("d", "a"): series})]
    assert math.isnan(out[1]) and math.isnan(out[2])
    expected = [value for value, _scale in _naive_filter(name, 1.0, series)]
    assert out[4:] == pytest.approx(expected[4:], rel=1e-12)
    assert all(math.isfinite(v) for v in out[4:])


def test_reference_buffers_are_trimmed_after_drain() -> None:
    parsed = parse_expression('sig("d","a") + sig("d","b")')
    stream = IncrementalEvaluator(parsed)
    stream.feed(SignalRef("d", "b"), [(i * 0.01, 1.0) for i in range(1000)])
    stream.feed(SignalRef("d", "a"), [(i * 0.01, 1.0) for i in range(1000)])
    assert len(stream.drain()) == 1000
    assert max(stream.buffer_sizes()) <= 1


# ------------------------------------------------------------------ no dynamic code


def test_module_source_has_no_dynamic_code_symbols() -> None:
    source = Path(expression_module.__file__).read_text(encoding="utf-8")
    names = {
        tok.string
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type == tokenize.NAME
    }
    forbidden = {"eval", "exec", "compile", "__import__", "ast", "importlib", "getattr"}
    assert names.isdisjoint(forbidden), names & forbidden


# ------------------------------------------------------------------------- fuzz

_FUZZ_ALPHABET = list('sig()"",+-*/.eE0123456789 \t\nabsminxclampscaleintegderivlowpass_$;\\\r') + [
    "é",
    "\U0001f600",
    "\x00",
    "sig(",
    '"d"',
    "ma(",
    "1e309",
]
_FUZZ_TOKENS = ['sig("d","a")', 'sig("d","b")', "1", "2.5", "-", "+", "*", "/", "(", ")", ","]
_FUZZ_FUNCS = ["abs(", "min(", "max(", "clamp(", "scale(", "ma(", "lowpass(", "deriv(", "integ("]


def _random_expression_tree(rng: random.Random, depth: int) -> str:
    pick = rng.random()
    if depth <= 0 or pick < 0.3:
        return rng.choice(['sig("d","a")', 'sig("d","b")', "1", "-2.5", "1e3"])
    sub = _random_expression_tree(rng, depth - 1)
    if pick < 0.55:
        return f"{sub} {rng.choice('+-*/')} {_random_expression_tree(rng, depth - 1)}"
    if pick < 0.65:
        return f"({sub})"
    if pick < 0.7:
        return f"-{sub}"
    name = rng.choice(["abs", "deriv", "ma", "lowpass", "integ", "min", "clamp", "scale"])
    tail = {"ma": ", 0.5", "integ": ", 2", "lowpass": ", 5", "min": ", 1", "clamp": ", 0, 1"}
    tail["scale"] = ", 0, 1, -1, 1"
    return f"{name}({sub}{tail.get(name, '')})"


def _random_expression_text(rng: random.Random) -> str:
    mode = rng.random()
    if mode < 0.3:
        return _random_expression_tree(rng, rng.randint(1, 8))
    if mode < 0.4:
        return "".join(rng.choice(_FUZZ_ALPHABET) for _ in range(rng.randint(0, 80)))
    if mode < 0.8:
        parts = [rng.choice(_FUZZ_TOKENS + _FUZZ_FUNCS) for _ in range(rng.randint(1, 40))]
        return " ".join(parts) if rng.random() < 0.3 else "".join(parts)
    return rng.choice(["(", "-", "abs(", "ma("]) * rng.randint(1, 400) + 'sig("d","a")'


def test_fuzz_parse_only_raises_expression_error() -> None:
    rng = random.Random(319)
    accepted = 0
    for _ in range(20000):
        text = _random_expression_text(rng)
        try:
            parsed = parse_expression(text)
        except ExpressionError as err:
            assert err.code in ERROR_MESSAGES
            assert 0 <= err.position <= max(len(text), MAX_EXPRESSION_CHARS)
            assert err.length >= 0
            continue
        accepted += 1
        assert 1 <= parsed.node_count <= 64 and 1 <= parsed.depth <= 12
        assert 0 <= len(parsed.refs) <= 8
        values = [rng.uniform(-1e3, 1e3), math.nan, 1e308, 0.0]
        series = {ref: [(t * 0.05, rng.choice(values)) for t in range(30)] for ref in parsed.refs}
        for _t, value in evaluate(parsed, series, timestamps=[0.0, 0.5, 1.0]):
            assert math.isnan(value) or math.isfinite(value)
    assert accepted > 100
