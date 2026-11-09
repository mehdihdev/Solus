"""SOLUSDEV-321 P2-T2 — predictions (`rules/prediction_rules.py`): a temperature whose least-squares
line crosses its limit within the horizon, and the seconds until the current (a stall) or the
temperature reaches its limit, with a band from the fit's residuals."""

from __future__ import annotations

import math

from solus_api.checkers.interface import Severity
from solus_api.livebench.findings.rules.prediction_rules import (
    TEMP_TREND_WITHIN_SECONDS,
    TempTrendToLimit,
    TimeToLimit,
    trend_of,
)
from solus_api.livebench.findings.rules.rule_base import points, unmet
from test_rule_base import BRAIN, BUS, PART, PART_NAME, arm_envelopes, at, context, only, series

TEMPERATURE = "servo3.temperature"
CURRENT = "servo3.current"


def ramp(start: float, per_second: float, *, seconds: float, hz: float) -> list[float]:
    return [start + per_second * n / hz for n in range(round(seconds * hz) + 1)]


# ---------------------------------------------------------------------------- the fit


def test_a_straight_line_fits_exactly() -> None:
    trend = trend_of(points(series(ramp(40.0, 0.6, seconds=25.0, hz=2.0), hz=2.0)))
    assert trend is not None
    assert math.isclose(trend.slope, 0.6)
    assert math.isclose(trend.now, 55.0)  # the line at the newest sample
    assert math.isclose(trend.r_squared, 1.0)
    assert trend.sigma < 1e-9
    assert trend_of(points(series([1.0]))) is None


def test_the_residuals_set_sigma() -> None:
    noisy = [
        value + (0.05 if n % 2 else -0.05)
        for n, value in enumerate(ramp(1.0, 0.05, seconds=10.0, hz=20.0))
    ]
    trend = trend_of(points(series(noisy)))
    assert trend is not None
    assert math.isclose(trend.sigma, 0.05, rel_tol=0.01)


# ---------------------------------------------------------------------------- temperature trend


def test_a_temperature_rising_to_its_limit_within_the_horizon_fires() -> None:
    samples = {TEMPERATURE: series(ramp(40.0, 0.6, seconds=25.0, hz=2.0), hz=2.0)}
    hit = only(TempTrendToLimit().evaluate(context(samples)))
    assert hit.rule_id == "temp_trend_to_limit"
    assert hit.severity is Severity.WARNING
    assert hit.subjects == (PART, BUS, BRAIN)
    assert hit.headline == (
        f"{PART_NAME} temperature 55.0 degC rising 0.6 degC/s: at the 70.0 degC limit in about 25 s"
    )
    evidence = hit.evidence
    assert (evidence["limit"], evidence["bounds_source"], evidence["unit"]) == (
        70.0,
        "config",
        "degC",
    )
    assert math.isclose(evidence["slope_per_s"], 0.6)
    assert math.isclose(evidence["seconds_to_limit"], 25.0)
    assert (evidence["samples"], evidence["window_seconds"]) == (51, 25.0)
    assert [cause.kind for cause in hit.causes] == ["mechanical_load", "actuator"]


def test_the_current_beside_a_warming_part_weighs_the_load() -> None:
    temperature = series(ramp(40.0, 0.6, seconds=25.0, hz=2.0), hz=2.0)
    loaded = context({TEMPERATURE: temperature, CURRENT: series([1.5] * 51, hz=2.0)})
    load = only(TempTrendToLimit().evaluate(loaded)).causes[0]
    assert load.for_[0] == "current averaged 1.5 A over the window, over the 1.0 A nominal"
    idle = context({TEMPERATURE: temperature, CURRENT: series([0.4] * 51, hz=2.0)})
    load = only(TempTrendToLimit().evaluate(idle)).causes[0]
    assert load.against == ("current averaged 0.4 A over the window, under the 1.0 A nominal",)


def test_a_flat_slow_or_short_trend_is_quiet() -> None:
    flat = {TEMPERATURE: series([45.0] * 51, hz=2.0)}
    assert TempTrendToLimit().evaluate(context(flat)) == []
    slow = {TEMPERATURE: series(ramp(40.0, 0.01, seconds=25.0, hz=2.0), hz=2.0)}
    assert (70.0 - 40.25) / 0.01 > TEMP_TREND_WITHIN_SECONDS
    assert TempTrendToLimit().evaluate(context(slow)) == []
    short = {TEMPERATURE: series(ramp(60.0, 2.0, seconds=2.0, hz=2.0), hz=2.0)}
    assert TempTrendToLimit().evaluate(context(short)) == []


def test_a_trend_judged_by_an_earlier_tick_or_without_a_limit_is_quiet() -> None:
    samples = {TEMPERATURE: series(ramp(40.0, 0.6, seconds=25.0, hz=2.0), hz=2.0)}
    assert TempTrendToLimit().evaluate(context(samples, judged={TEMPERATURE: at(25.0)})) == []
    no_limit = {k: v for k, v in arm_envelopes().items() if k != "temperature"}
    ctx = context(samples, envelopes=no_limit)
    assert TempTrendToLimit().evaluate(ctx) == []
    assert unmet(TempTrendToLimit.needs, ctx)[0].startswith("temperature.limit (set it in ")


# ---------------------------------------------------------------------------- time to limit


def test_a_climbing_current_forecasts_the_stall() -> None:
    samples = {CURRENT: series(ramp(1.0, 0.05, seconds=10.0, hz=20.0))}
    hit = only(TimeToLimit().evaluate(context(samples)))
    assert hit.rule_id == "time_to_limit"
    assert hit.severity is Severity.WARNING
    assert hit.headline == (
        f"{PART_NAME} current 1.5 A rising 0.05 A/s toward its 2.0 A rating: stall in about 10 s"
    )
    evidence = hit.evidence
    assert (evidence["quantity"], evidence["limit"], evidence["bounds_source"]) == (
        "current",
        2.0,
        "config",
    )
    assert math.isclose(evidence["seconds_to_limit"], 10.0)
    low, high = evidence["band_seconds"]
    assert math.isclose(low, 10.0) and math.isclose(high, 10.0)  # a perfect line: no band
    assert [cause.kind for cause in hit.causes] == ["mechanical_load", "software_command"]


def test_the_band_widens_with_the_residuals() -> None:
    noisy = [
        v + (0.05 if n % 2 else -0.05) for n, v in enumerate(ramp(1.0, 0.05, seconds=10.0, hz=20.0))
    ]
    hit = only(TimeToLimit().evaluate(context({CURRENT: series(noisy)})))
    low, high = hit.evidence["band_seconds"]
    assert math.isclose(low, 8.0, abs_tol=0.2) and math.isclose(high, 12.0, abs_tol=0.2)
    assert math.isclose(hit.evidence["residual_sigma"], 0.05, rel_tol=0.01)


def test_the_sooner_of_current_and_temperature_is_told() -> None:
    samples = {
        CURRENT: series(ramp(1.0, 0.03, seconds=10.0, hz=20.0)),  # 2.0 A in about 23 s
        TEMPERATURE: series(ramp(60.0, 0.5, seconds=10.0, hz=20.0)),  # 70 degC in about 10 s
    }
    hit = only(TimeToLimit().evaluate(context(samples)))
    assert hit.evidence["quantity"] == "temperature"
    assert hit.headline == (
        f"{PART_NAME} temperature 65.0 degC rising 0.5 degC/s: over the 70.0 degC limit in about "
        "10 s"
    )


def test_a_flat_noisy_or_already_over_current_forecasts_nothing() -> None:
    flat = {CURRENT: series([1.2] * 201)}
    assert TimeToLimit().evaluate(context(flat)) == []
    noisy = {CURRENT: series([1.0 + (0.4 if n % 3 == 0 else 0.0) + 0.001 * n for n in range(201)])}
    assert TimeToLimit().evaluate(context(noisy)) == []  # the line explains too little
    over = {CURRENT: series(ramp(2.1, 0.05, seconds=10.0, hz=20.0))}
    assert TimeToLimit().evaluate(context(over)) == []  # current_over_rating's to tell


def test_a_start_up_ramp_is_too_short_to_forecast() -> None:
    """A 0.95 s spin-up from 0.2 A to 1.8 A is no trend: the line needs `TREND_MIN_SECONDS`."""
    samples = {CURRENT: series([0.2 + 1.6 * n / 19 for n in range(20)])}
    assert TimeToLimit().evaluate(context(samples)) == []


def test_a_forecast_needs_a_current_channel_and_its_limit() -> None:
    ctx = context({TEMPERATURE: series(ramp(60.0, 0.5, seconds=10.0, hz=20.0))})
    assert TimeToLimit().evaluate(ctx) == []
    assert unmet(TimeToLimit.needs, ctx) == ("current channel",)
