"""SOLUSDEV-321 P2-T2 — tracking: does the part follow its command?

- `tracking_error_stall`: the command stays away from a position that holds still while the
  current is at or over the envelope's warn bound, for `STALL_SUSTAIN_SECONDS` — the run
  analysis's still window (`rule_base.still_window`) on the warn bound instead of the rating.
- `tracking_error_slip`: under a steady command the error holds (it closes by less than the
  position tolerance over `SLIP_SUSTAIN_SECONDS`) while the current stays under the nominal bound
  and the reading moves (a bit-identical reading is `sensor_frozen`'s): nothing drives the part.
  Progress is absolute, so a slow move toward a far goal is still a move.
- `tracking_oscillation`: at a held setpoint the error swings past the position tolerance, and its
  autocorrelation, once it has crossed zero, peaks again at `OSCILLATION_MIN_PEAK` or more.

A part with a command channel and no position feedback (a dumb actuator) is judged on its current,
the settling signal: a stall is the current holding at the warn bound under an unchanged command,
a ring is the current's own autocorrelation. The headline names that channel and nothing is ranked
(`causes=()`); a slip needs feedback. The family is WARNING, CRITICAL once the current reaches the
envelope's limit. Rows pair one timestamp's current, position and command, as one packet carries a
part's channels (ponytail: exact timestamps; nearest-sample pairing when a part's channels arrive
from two devices).
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from datetime import datetime
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Final

from solus_contracts.relations import MatrixCell

from solus_api.checkers.interface import Severity
from solus_api.livebench.findings.rules.rule_base import (
    COMMAND,
    MIN_ROWS,
    Cause,
    Needs,
    RuleHit,
    SignalRule,
    StillRow,
    WindowContext,
    amount,
    channel_for,
    channels_named,
    entity_label,
    fact_need,
    is_new,
    judged,
    limit_hi,
    make_hit,
    outside,
    paired,
    readings,
    shown,
    since,
    still_window,
    trailing,
    unmet,
    window_evidence,
)

if TYPE_CHECKING:
    from solus_api.livebench.findings.envelopes import Bound, Envelope

#: A stall holds this long before it is one: the still window's sustain span. The run analysis
#: judges a whole recording on half a second; live, a second keeps a start-up surge out and still
#: lands the first hit inside two seconds of the onset on one-second ticks.
STALL_SUSTAIN_SECONDS: Final = 1.0
SLIP_SUSTAIN_SECONDS: Final = 1.0
OSCILLATION_WINDOW_SECONDS: Final = 5.0
OSCILLATION_MIN_SAMPLES: Final = 20
#: ponytail: the autocorrelation is O(n²) in pure Python, so it reads at most this many trailing
#: samples (five seconds at 20 Hz); decimate or vectorise when faster streams need longer periods.
OSCILLATION_MAX_SAMPLES: Final = 100
OSCILLATION_MIN_PEAK: Final = 0.6
#: A dumb actuator's current rings when its spread is at least this share of its mean.
OSCILLATION_MIN_SPREAD: Final = 0.1
_TRACKING: Final = (COMMAND, "current")  # what every tracking rule reads; position is optional
_TIE: Final = 1e-9  # autocorrelations closer than this are one value

type SettlingRow = tuple[datetime, float, float]  # (time, |current|, command)


def tracking_severity(evidence: Mapping[str, Any]) -> Severity:
    """WARNING; CRITICAL once the current reaches the envelope's limit."""
    current, limit = evidence.get("current_a"), evidence.get("limit")
    if isinstance(current, int | float) and isinstance(limit, int | float) and current >= limit:
        return Severity.CRITICAL
    return Severity.WARNING


def tracking_rows(ctx: WindowContext) -> list[StillRow]:
    """(time, |current|, position, command) at each timestamp the three channels share."""
    return [(at, abs(i), p, c) for at, i, p, c in paired(ctx, "current", "position", COMMAND)]


def settling_rows(ctx: WindowContext) -> list[SettlingRow]:
    """(time, |current|, command) at each timestamp the two channels share: a part judged
    without position feedback."""
    return [(at, abs(i), c) for at, i, c in paired(ctx, "current", COMMAND)]


def autocorrelation_peak(values: Sequence[float]) -> tuple[float, int] | None:
    """The highest autocorrelation of `values` once it has dropped below zero, and its lag in
    samples, over lags up to half the series: r(k) = mean(x_i · x_i+k) / mean(x_i²) with x the
    values less their mean. A tie goes to the shorter lag (a period's multiples peak as high as
    the period itself). None for a flat series or one that never crosses zero."""
    count = len(values)
    mean = statistics.fmean(values) if count else 0.0
    centred = [value - mean for value in values]
    power = sum(value * value for value in centred) / count if count else 0.0
    if power == 0:
        return None
    best: tuple[float, int] | None = None
    crossed = False
    for lag in range(1, count // 2 + 1):
        pairs = sum(centred[i] * centred[i + lag] for i in range(count - lag))
        correlation = pairs / (count - lag) / power
        crossed = crossed or correlation < 0
        if crossed and (best is None or correlation > best[0] + _TIE):
            best = (correlation, lag)
    return best


def _cut(ctx: WindowContext, *quantities: str) -> datetime | None:
    """The cursor over the part's channels for `quantities`."""
    channels = [channel_for(ctx.samples, quantity) for quantity in quantities]
    return judged(ctx, *(channel for channel in channels if channel is not None))


def _band(band: Bound, unit: str | None) -> str:
    if band.lo is not None and band.hi is not None:
        return f"{amount(band.lo)} to {amount(band.hi, unit)}"
    edge = band.hi if band.hi is not None else band.lo
    return f"{amount(edge or 0.0, unit)} {'upper' if band.hi is not None else 'lower'}"


def _rated(current: Envelope, warn: float) -> dict[str, Any]:
    """A stall's bounds: `bound` is the rating (the current limit's top) with its source, which
    the finding holds the current against; `warn` is the bound the stall was judged on."""
    rating = limit_hi(current)
    return {
        "bound": rating if rating is not None else warn,
        "limit": rating,
        "bounds_source": current.bounds_source.get("limit" if rating is not None else "warn"),
        "warn": warn,
        "warn_source": current.bounds_source.get("warn"),
    }


def _period(rows: Sequence[tuple[Any, ...]], lag: int) -> float:
    """`lag` samples in seconds, at the rows' median interval."""
    gaps: list[float] = [(b[0] - a[0]).total_seconds() for a, b in pairwise(rows)]
    return lag * statistics.median(gaps)


def _held_run(rows: Sequence[SettlingRow], bound: float, tolerance: float) -> list[SettlingRow]:
    """The first run at or over `bound` under one command (within `tolerance` of where it began),
    `MIN_ROWS` or more over `STALL_SUSTAIN_SECONDS`."""
    run: list[SettlingRow] = []
    for row in rows:
        if row[1] < bound:
            run = []
            continue
        if run and abs(row[2] - run[0][2]) > tolerance:
            run = []
        run.append(row)
        if len(run) >= MIN_ROWS and (row[0] - run[0][0]).total_seconds() >= STALL_SUSTAIN_SECONDS:
            return run
    return []


def _stall_causes(evidence: Mapping[str, Any], position: Envelope | None) -> tuple[Cause, ...]:
    """The load, the command and the actuator, with what the window says of each."""
    unit, drawn = evidence["unit"], amount(evidence["current_a"], evidence["current_unit"])
    command = f"the {amount(evidence['commanded'], unit)} command"
    band = position.limit if position is not None else None
    edge = outside(evidence["commanded"], band, evidence["tolerance"]) if band else None
    software = Cause(
        kind="software_command",
        for_=(
            f"{command} stays {amount(evidence['error'], unit)} from the held position",
            *((f"{command} is past the {amount(edge[0], unit)} limit",) if edge else ()),
        ),
        against=(f"{command} is inside the {_band(band, unit)} limit",)
        if band and not edge
        else (),
    )
    held = (
        f"the position held within {amount(evidence['tolerance'], unit)} for "
        f"{amount(evidence['window_seconds'], 's')} while drawing {drawn}"
    )
    jam = f"drawing {drawn} at a standstill fits a jam inside the actuator as well"
    return (
        Cause(kind="mechanical_load", for_=(held,)),
        software,
        Cause(kind="actuator", for_=(jam,)),
    )


class TrackingErrorStall:
    """The command stays away from a still position while the current holds at the warn bound."""

    rule_id = "tracking_error_stall"
    matrix_cell: MatrixCell | None = MatrixCell.SOFTWARE_MECHANICAL
    needs = Needs(channels=_TRACKING, facts=(fact_need("current", "warn"),))

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        return tracking_severity(evidence)

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        current = ctx.envelopes.get("current")
        bound = current.warn.hi if current is not None and current.warn is not None else None
        feedback = len(channels_named(ctx.samples, "position"))  # two: which one is not known
        if unmet(self.needs, ctx) or current is None or bound is None or feedback > 1:
            return []
        if not feedback:
            return self._unsettled(ctx, current, bound)
        cut = _cut(ctx, "current", "position", COMMAND)
        stretch = still_window(
            since(tracking_rows(ctx), cut, STALL_SUSTAIN_SECONDS),
            current_bound=bound,
            tolerance=ctx.tolerance,
            min_seconds=STALL_SUSTAIN_SECONDS,
        )
        return [self._stalled(ctx, current, bound, stretch)] if stretch else []

    def _stalled(
        self, ctx: WindowContext, current: Envelope, bound: float, stretch: Sequence[StillRow]
    ) -> RuleHit:
        first, last = stretch[0], stretch[-1]
        position = ctx.envelopes.get("position")
        unit = position.unit if position is not None else None
        drawn, rating = max(row[1] for row in stretch), limit_hi(current)
        evidence = {
            "current_a": drawn,
            **_rated(current, bound),
            "position": first[2],
            "commanded": last[3],
            "error": max(abs(row[3] - row[2]) for row in stretch),
            "tolerance": ctx.tolerance,
            "unit": unit,
            "current_unit": current.unit,
            "samples": len(stretch),
            **window_evidence(first[0], last[0]),
        }
        rated = (
            f"rating {amount(rating, current.unit)}"
            if rating is not None
            else f"warn {amount(bound, current.unit)}"
        )
        headline = (
            f"{entity_label(ctx.graph, ctx.part_id)} stalls at {amount(first[2], unit)} against a "
            f"{amount(last[3], unit)} command, drawing {amount(drawn, current.unit)} ({rated})"
        )
        causes = _stall_causes(evidence, position)
        return make_hit(self, ctx, headline=headline, evidence=evidence, causes=causes)

    def _unsettled(self, ctx: WindowContext, current: Envelope, bound: float) -> list[RuleHit]:
        """No position feedback: the current holds at the warn bound under an unchanged command."""
        rows = since(settling_rows(ctx), _cut(ctx, "current", COMMAND), STALL_SUSTAIN_SECONDS)
        run = _held_run(rows, bound, ctx.tolerance)
        if not run:
            return []
        signal = shown(readings(ctx, "current")[0] or "current")
        drawn = max(row[1] for row in run)
        evidence = {
            "current_a": drawn,
            **_rated(current, bound),
            "commanded": run[-1][2],
            "settling_signal": signal,
            "current_unit": current.unit,
            "samples": len(run),
            **window_evidence(run[0][0], run[-1][0]),
        }
        headline = (
            f"{entity_label(ctx.graph, ctx.part_id)} does not settle: {signal} holds "
            f"{amount(drawn, current.unit)} for {amount(evidence['window_seconds'], 's')} under "
            "an unchanged command (no position feedback)"
        )
        return [make_hit(self, ctx, headline=headline, evidence=evidence)]


def _slip_run(rows: Sequence[StillRow], bound: float, tolerance: float) -> list[StillRow]:
    """The first run under a steady command, more than `tolerance` off it on less than `bound`,
    whose reading moves and whose error stays (`_holds`)."""
    run: list[StillRow] = []
    moved = False
    for row in rows:
        _, current, position, command = row
        off = current < bound and abs(command - position) > tolerance
        if not off or (run and abs(command - run[0][3]) > tolerance):
            run, moved = ([row] if off else []), False
            continue
        moved = moved or (bool(run) and position != run[0][2])
        run.append(row)
        if moved and _holds(run, tolerance):
            return run
    return []


def _holds(run: Sequence[StillRow], tolerance: float) -> bool:
    """`MIN_ROWS` or more over `SLIP_SUSTAIN_SECONDS` in which the error closed by less than
    `tolerance`."""
    first, last = run[0], run[-1]
    if len(run) < MIN_ROWS or (last[0] - first[0]).total_seconds() < SLIP_SUSTAIN_SECONDS:
        return False
    return abs(first[3] - first[2]) - abs(last[3] - last[2]) < tolerance


class TrackingErrorSlip:
    """The error holds under a steady command while the current stays under nominal."""

    rule_id = "tracking_error_slip"
    matrix_cell: MatrixCell | None = MatrixCell.SOFTWARE_MECHANICAL
    needs = Needs(channels=_TRACKING, facts=(fact_need("current", "nominal"),))

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        return tracking_severity(evidence)

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        current = ctx.envelopes.get("current")
        bound = current.nominal.hi if current is not None and current.nominal is not None else None
        feedback = channel_for(ctx.samples, "position") is not None
        if unmet(self.needs, ctx) or current is None or bound is None or not feedback:
            return []
        cut = _cut(ctx, "current", "position", COMMAND)
        run = _slip_run(since(tracking_rows(ctx), cut, SLIP_SUSTAIN_SECONDS), bound, ctx.tolerance)
        return [self._slipping(ctx, current, bound, run)] if run else []

    def _slipping(
        self, ctx: WindowContext, current: Envelope, bound: float, run: Sequence[StillRow]
    ) -> RuleHit:
        first, last = run[0], run[-1]
        position = ctx.envelopes.get("position")
        unit, current_unit = (position.unit if position is not None else None), current.unit
        start, error = abs(first[3] - first[2]), abs(last[3] - last[2])
        drawn = max(row[1] for row in run)
        evidence = {
            "current_a": drawn,
            "bound": bound,
            "limit": limit_hi(current),
            "bounds_source": current.bounds_source.get("nominal"),
            "error_start": start,
            "error": error,
            "commanded": last[3],
            "position": last[2],
            "tolerance": ctx.tolerance,
            "unit": unit,
            "current_unit": current_unit,
            "samples": len(run),
            **window_evidence(first[0], last[0]),
        }
        seconds = amount(evidence["window_seconds"], "s")
        headline = (
            f"{entity_label(ctx.graph, ctx.part_id)} is not following its "
            f"{amount(last[3], unit)} command: {amount(error, unit)} off for {seconds} while "
            f"drawing {amount(drawn, current_unit)} (nominal {amount(bound, current_unit)})"
        )
        closed = amount(start - error, unit)
        causes = (
            Cause(
                kind="actuator",
                for_=(
                    f"drawing {amount(drawn, current_unit)}, under the "
                    f"{amount(bound, current_unit)} nominal, {amount(error, unit)} off the command",
                ),
            ),
            Cause(
                kind="mechanical_load",
                for_=(
                    f"the error closed only {closed} in {seconds}: a coupling or gear that slips",
                ),
            ),
            Cause(
                kind="software_command",
                for_=("a torque limit or gain set low in code leaves the part under-driven",),
            ),
        )
        return make_hit(self, ctx, headline=headline, evidence=evidence, causes=causes)


def _steady(commands: Sequence[float], tolerance: float) -> bool:
    return max(commands) - min(commands) <= tolerance


class TrackingOscillation:
    """At a held setpoint the error rings: its autocorrelation peaks again after crossing zero."""

    rule_id = "tracking_oscillation"
    matrix_cell: MatrixCell | None = MatrixCell.SOFTWARE_MECHANICAL
    needs = Needs(channels=_TRACKING)

    def severity(self, evidence: Mapping[str, Any]) -> Severity:
        return tracking_severity(evidence)

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        feedback = len(channels_named(ctx.samples, "position"))  # two: which one is not known
        if unmet(self.needs, ctx) or feedback > 1:
            return []
        if not feedback:
            return self._ringing_current(ctx)
        rows = trailing(tracking_rows(ctx), OSCILLATION_WINDOW_SECONDS)[-OSCILLATION_MAX_SAMPLES:]
        cut = _cut(ctx, "current", "position", COMMAND)
        if len(rows) < OSCILLATION_MIN_SAMPLES or not is_new(rows[-1][0], cut):
            return []
        errors = [row[3] - row[2] for row in rows]
        swing = statistics.pstdev(errors)
        if not _steady([row[3] for row in rows], ctx.tolerance) or swing <= ctx.tolerance:
            return []
        peak = autocorrelation_peak(errors)
        if peak is None or peak[0] < OSCILLATION_MIN_PEAK:
            return []
        position = ctx.envelopes.get("position")
        unit = position.unit if position is not None else None
        evidence = self._evidence(ctx, rows, errors, peak) | {"unit": unit}
        headline = (
            f"{entity_label(ctx.graph, ctx.part_id)} oscillates about its "
            f"{amount(rows[-1][3], unit)} setpoint: {amount(evidence['peak_to_peak'], unit)} peak "
            f"to peak every {amount(evidence['period_seconds'], 's')}"
        )
        return [make_hit(self, ctx, headline=headline, evidence=evidence, causes=_ring_causes())]

    def _evidence(
        self,
        ctx: WindowContext,
        rows: Sequence[tuple[Any, ...]],
        values: Sequence[float],
        peak: tuple[float, int],
    ) -> dict[str, Any]:
        current = ctx.envelopes.get("current")
        return {
            "peak": peak[0],
            "period_seconds": _period(rows, peak[1]),
            "amplitude": statistics.pstdev(values),
            "peak_to_peak": max(values) - min(values),
            "current_a": max(row[1] for row in rows),
            "limit": limit_hi(current),
            "current_unit": current.unit if current is not None else None,
            "commanded": rows[-1][-1],
            "tolerance": ctx.tolerance,
            "samples": len(rows),
            **window_evidence(rows[0][0], rows[-1][0]),
        }

    def _ringing_current(self, ctx: WindowContext) -> list[RuleHit]:
        """No position feedback: the current itself rings under a steady command."""
        rows = trailing(settling_rows(ctx), OSCILLATION_WINDOW_SECONDS)[-OSCILLATION_MAX_SAMPLES:]
        cut = _cut(ctx, "current", COMMAND)
        if len(rows) < OSCILLATION_MIN_SAMPLES or not is_new(rows[-1][0], cut):
            return []
        currents = [row[1] for row in rows]
        mean = statistics.fmean(currents)
        quiet = statistics.pstdev(currents) < OSCILLATION_MIN_SPREAD * mean
        if not _steady([row[2] for row in rows], ctx.tolerance) or mean <= 0 or quiet:
            return []
        peak = autocorrelation_peak(currents)
        if peak is None or peak[0] < OSCILLATION_MIN_PEAK:
            return []
        signal = shown(readings(ctx, "current")[0] or "current")
        evidence = self._evidence(ctx, rows, currents, peak) | {"settling_signal": signal}
        unit = evidence["current_unit"]
        headline = (
            f"{entity_label(ctx.graph, ctx.part_id)} rings: {signal} swings "
            f"{amount(evidence['peak_to_peak'], unit)} every "
            f"{amount(evidence['period_seconds'], 's')} under a steady command (no position "
            "feedback)"
        )
        return [make_hit(self, ctx, headline=headline, evidence=evidence)]


def _ring_causes() -> tuple[Cause, ...]:
    return (
        Cause(kind="software_command", for_=("it rings under a held command: gains set too high",)),
        Cause(
            kind="mechanical_load", for_=("a compliant or resonant load rings at its own period",)
        ),
        Cause(kind="actuator", for_=("backlash in the gear train drives a limit cycle",)),
    )


TRACKING_RULES: Final[tuple[SignalRule, ...]] = (
    TrackingErrorStall(),
    TrackingErrorSlip(),
    TrackingOscillation(),
)
