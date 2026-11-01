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
