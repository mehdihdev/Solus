"""SOLUSDEV-321 P2-T2 — predictions: how long until a limit, from a least-squares line.

- `temp_trend_to_limit`: the line through the temperature over the last `TREND_HORIZON_SECONDS` (at
  least `TREND_MIN_SAMPLES` over `TREND_MIN_SECONDS`) rises and reaches the envelope's limit within
  `TEMP_TREND_WITHIN_SECONDS` (T) of the newest sample, or is there already.
- `time_to_limit`: the line through the current's magnitude (a stall: its limit is the rating) and
  through the temperature, each over the last `TIME_TO_LIMIT_FIT_SECONDS`. Seconds to the limit =
  (limit - the line's value now) / slope, told when within `TIME_TO_LIMIT_WITHIN_SECONDS` for a line
  that explains at least `TIME_TO_LIMIT_MIN_R2` of the variance; the band is that distance ±
  `BAND_SIGMAS` residual standard deviations, over the slope. The sooner forecast is told ("stall in
  about N s"); a value already at its limit is the other rules' to tell.

Both WARNING. Time is event time throughout, counted from the newest sample.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from solus_contracts.relations import MatrixCell

from solus_api.checkers.interface import Severity
from solus_api.livebench.findings.rules.rule_base import (
    TREND_HORIZON_SECONDS,
    Cause,
    Needs,
    Point,
    RuleHit,
    SignalRule,
    WindowContext,
    amount,
    entity_label,
    fact_need,
    is_new,
    judged,
    limit_hi,
    make_hit,
    points,
    readings,
    trailing,
    unmet,
    window_evidence,
)

if TYPE_CHECKING:
    from solus_api.livebench.findings.envelopes import Envelope

TREND_MIN_SAMPLES: Final = 10
TREND_MIN_SECONDS: Final = 5.0
#: T: a temperature trend is told when it reaches the limit within this many seconds.
TEMP_TREND_WITHIN_SECONDS: Final = 120.0
TIME_TO_LIMIT_FIT_SECONDS: Final = 10.0
TIME_TO_LIMIT_WITHIN_SECONDS: Final = 60.0
TIME_TO_LIMIT_MIN_R2: Final = 0.5
BAND_SIGMAS: Final = 2.0


@dataclass(frozen=True)
class Trend:
    """A least-squares line through a signal, time in seconds before its newest sample: the slope
    per second, the line's value at the newest sample, the residuals' standard deviation, the
    share of the variance it explains, and the samples and span it was fitted over."""

    slope: float
    now: float
    sigma: float
    r_squared: float
    samples: int
    first: datetime
    last: datetime


def trend_of(series: Sequence[Point]) -> Trend | None:
    """The line through `series`; None under two samples or two distinct times."""
    if len(series) < 2:
        return None
    last = series[-1][0]
    xs = [(at - last).total_seconds() for at, _ in series]
    ys = [value for _, value in series]
    try:
        slope, intercept = statistics.linear_regression(xs, ys)
    except statistics.StatisticsError:
        return None
    residual = math.fsum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys, strict=True))
    mean = statistics.fmean(ys)
    total = math.fsum((y - mean) ** 2 for y in ys)
    r_squared = 1 - residual / total if total > 0 else 0.0
    sigma = math.sqrt(residual / (len(ys) - 2)) if len(ys) > 2 else 0.0
    return Trend(slope, intercept, sigma, r_squared, len(ys), series[0][0], last)


def _fresh_trend(ctx: WindowContext, channel: str, series: Sequence[Point]) -> bool:
    """Whether the series can carry a line this tick: `TREND_MIN_SAMPLES` or more over
    `TREND_MIN_SECONDS` (a start-up surge is no trend), its newest sample new."""
    return (
        len(series) >= TREND_MIN_SAMPLES
        and (series[-1][0] - series[0][0]).total_seconds() >= TREND_MIN_SECONDS
        and is_new(series[-1][0], judged(ctx, channel))
    )


def _per_second(unit: str | None) -> str | None:
    return f"{unit}/s" if unit else None


def _eta(seconds: float) -> str:
    return f"in about {round(seconds)} s" if seconds >= 1 else "now"


def _load_note(ctx: WindowContext, first: datetime) -> Cause:
    """The load, weighed by the current averaged since `first` against the nominal bound."""
    current = ctx.envelopes.get("current")
    drawn = [
        value for at, value in points(readings(ctx, "current")[1], magnitude=True) if at >= first
    ]
    nominal = current.nominal.hi if current is not None and current.nominal is not None else None
    if not drawn or current is None or nominal is None:
        return Cause(kind="mechanical_load", for_=("a sustained load heats it",))
    mean, unit = statistics.fmean(drawn), current.unit
    said = f"current averaged {amount(mean, unit)} over the window"
    if mean > nominal:
        return Cause(
            kind="mechanical_load", for_=(f"{said}, over the {amount(nominal, unit)} nominal",)
        )
    return Cause(
        kind="mechanical_load", against=(f"{said}, under the {amount(nominal, unit)} nominal",)
    )


class TempTrendToLimit:
    """The temperature's line reaches its limit within T."""

    rule_id = "temp_trend_to_limit"
    matrix_cell: MatrixCell | None = MatrixCell.ELECTRICAL_ELECTRICAL
    needs = Needs(channels=("temperature",), facts=(fact_need("temperature", "limit"),))

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        return Severity.WARNING

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        envelope = ctx.envelopes.get("temperature")
        top = limit_hi(envelope)
        channel, samples = readings(ctx, "temperature")
        if unmet(self.needs, ctx) or envelope is None or top is None or channel is None:
            return []
        series = trailing(points(samples), TREND_HORIZON_SECONDS)
        trend = trend_of(series) if _fresh_trend(ctx, channel, series) else None
        if trend is None or trend.slope <= 0:
            return []
        seconds = max(0.0, (top - trend.now) / trend.slope)
        if seconds > TEMP_TREND_WITHIN_SECONDS:
            return []
        unit = envelope.unit
        evidence = {
            "temperature": series[-1][1],
            "fitted": trend.now,
            "slope_per_s": trend.slope,
            "limit": top,
            "bound": top,
            "bounds_source": envelope.bounds_source.get("limit"),
            "seconds_to_limit": seconds,
            "r_squared": trend.r_squared,
            "unit": unit,
            "samples": trend.samples,
            **window_evidence(trend.first, trend.last),
        }
        rising = amount(trend.slope, _per_second(unit))
        headline = (
            f"{entity_label(ctx.graph, ctx.part_id)} temperature {amount(series[-1][1], unit)} "
            f"rising {rising}: at the {amount(top, unit)} limit {_eta(seconds)}"
        )
        causes = (
            _load_note(ctx, trend.first),
            Cause(
                kind="actuator",
                for_=(f"it warms {rising}: cooling or duty cycle beyond its rating",),
            ),
        )
        return [make_hit(self, ctx, headline=headline, evidence=evidence, causes=causes)]


@dataclass(frozen=True)
class Forecast:
    """When one quantity's line reaches its limit, with the band its residuals allow."""

    quantity: str
    value: float
    trend: Trend
    limit: float
    seconds: float
    band: tuple[float, float]
    envelope: Envelope


def _forecast(ctx: WindowContext, quantity: str) -> Forecast | None:
    """The quantity's forecast when its line rises toward its limit, explains enough, and gets
    there within `TIME_TO_LIMIT_WITHIN_SECONDS`; None otherwise."""
    envelope = ctx.envelopes.get(quantity)
    top = limit_hi(envelope)
    channel, samples = readings(ctx, quantity)
    if envelope is None or top is None or channel is None:
        return None
    series = trailing(points(samples, magnitude=quantity == "current"), TIME_TO_LIMIT_FIT_SECONDS)
    trend = trend_of(series) if _fresh_trend(ctx, channel, series) else None
    if trend is None or trend.slope <= 0 or trend.r_squared < TIME_TO_LIMIT_MIN_R2:
        return None
    distance = top - trend.now
    seconds = distance / trend.slope
    if distance <= 0 or seconds > TIME_TO_LIMIT_WITHIN_SECONDS:
        return None
    spread = BAND_SIGMAS * trend.sigma
    band = (max(0.0, (distance - spread) / trend.slope), (distance + spread) / trend.slope)
    return Forecast(quantity, series[-1][1], trend, top, seconds, band, envelope)


class TimeToLimit:
    """Seconds until the current (a stall) or the temperature reaches its limit."""

    rule_id = "time_to_limit"
    matrix_cell: MatrixCell | None = MatrixCell.ELECTRICAL_ELECTRICAL
    needs = Needs(channels=("current",), facts=(fact_need("current", "limit"),))

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        return Severity.WARNING

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        if unmet(self.needs, ctx):
            return []
        forecasts = [found for q in ("current", "temperature") if (found := _forecast(ctx, q))]
        if not forecasts:
            return []
        return [self._told(ctx, min(forecasts, key=lambda forecast: forecast.seconds))]

    def _told(self, ctx: WindowContext, forecast: Forecast) -> RuleHit:
        trend, unit, stall = forecast.trend, forecast.envelope.unit, forecast.quantity == "current"
        evidence = {
            "quantity": forecast.quantity,
            "value": forecast.value,
            "fitted": trend.now,
            "slope_per_s": trend.slope,
            "limit": forecast.limit,
            "bound": forecast.limit,
            "bounds_source": forecast.envelope.bounds_source.get("limit"),
            "seconds_to_limit": forecast.seconds,
            "band_seconds": list(forecast.band),
            "residual_sigma": trend.sigma,
            "r_squared": trend.r_squared,
            "unit": unit,
            "samples": trend.samples,
            **window_evidence(trend.first, trend.last),
            **({"current_a": forecast.value} if stall else {}),
        }
        name, rising = entity_label(ctx.graph, ctx.part_id), amount(trend.slope, _per_second(unit))
        limit = amount(forecast.limit, unit)
        headline = (
            f"{name} current {amount(forecast.value, unit)} rising {rising} toward its {limit} "
            f"rating: stall {_eta(forecast.seconds)}"
            if stall
            else f"{name} temperature {amount(forecast.value, unit)} rising {rising}: over the "
            f"{limit} limit {_eta(forecast.seconds)}"
        )
        causes = (
            (
                Cause(
                    kind="mechanical_load",
                    for_=(f"current climbs {rising} toward the {limit} rating: the load grows",),
                ),
                Cause(
                    kind="software_command",
                    for_=("a command driving into a stop raises the current until it stalls",),
                ),
            )
            if stall
            else (
                _load_note(ctx, trend.first),
                Cause(
                    kind="actuator",
                    for_=(f"it warms {rising}: cooling or duty cycle beyond its rating",),
                ),
            )
        )
        return make_hit(self, ctx, headline=headline, evidence=evidence, causes=causes)


PREDICTION_RULES: Final[tuple[SignalRule, ...]] = (TempTrendToLimit(), TimeToLimit())
