"""SOLUSDEV-321 P2-T2 — sensors: is what the part reports believable, and is it still reporting?

- `noise_tracks_motor_activity`: on a part code `reads` (a sensor), a channel's noise — the
  magnitude of its second difference, which a smooth reading keeps small — rises and falls with the
  current of a part code `commands` (a motor): their Pearson correlation over the last
  `NOISE_WINDOW_SECONDS` is at least `NOISE_MIN_CORRELATION`.
- `sensor_frozen`: the position reads bit-identical for `FROZEN_MIN_SAMPLES` samples over
  `FROZEN_MIN_SECONDS` while the command moves more than the tolerance. Only a reading with a
  command to follow is judged: a quantized channel (temperature in whole degrees) legitimately
  repeats itself.
- `sensor_out_of_range`: the position reads past its limit by more than the tolerance while the
  command stays inside (a command past it is `command_exceeds_limit`'s); with no command channel
  the reading is judged alone.
- `rate_drift`: any channel's rate over the last `RATE_WINDOW_SECONDS` (one over its median
  interval) is more than `RATE_DRIFT_MAX_FRACTION` off what is expected of it — the envelope's
  `expected_hz` (a baseline's), else the channel's own rate before that window.
- `stream_gap`: wall clock. A channel whose newest sample arrived more than `STREAM_GAP_PERIODS`
  expected periods ago (the envelope's `expected_hz`, else the observed median interval; at least
  `STREAM_GAP_MIN_SECONDS`, one evaluator tick, since an arrival is stamped when a tick reads it).
  The semantics of `livebench/src/livebench/anomaly/observers.py:GapWatchdog` over the evaluator's
  arrival times, with its evidence keys `last_seen_seconds` and `timeout`: one hit per gap (the
  latest `stream_gap` hit in `prior_hits` names the gaps already told), re-armed by the next sample.

All WARNING.
"""

from __future__ import annotations

import hashlib
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby, pairwise
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from solus_contracts.relations import MatrixCell, RelationType

from solus_api.checkers.interface import Severity
from solus_api.livebench.findings.rules.rule_base import (
    COMMAND,
    Cause,
    Needs,
    Point,
    RuleHit,
    SignalRule,
    WindowContext,
    aligned,
    amount,
    blame,
    channel_for,
    entity_label,
    fact_need,
    is_new,
    judged,
    make_hit,
    one_line,
    outside,
    paired,
    past,
    peer_readings,
    points,
    readings,
    sane,
    shown,
    trailing,
    unit_of,
    unmet,
    window_evidence,
)

if TYPE_CHECKING:
    from solus_api.graph.packet import RecentSample

NOISE_WINDOW_SECONDS: Final = 5.0
NOISE_MIN_SAMPLES: Final = 20
NOISE_MIN_CORRELATION: Final = 0.6
FROZEN_MIN_SAMPLES: Final = 10
FROZEN_MIN_SECONDS: Final = 1.0
RATE_WINDOW_SECONDS: Final = 5.0
RATE_MIN_SAMPLES: Final = 10
RATE_DRIFT_MAX_FRACTION: Final = 0.2
STREAM_GAP_PERIODS: Final = 3
STREAM_GAP_MIN_SECONDS: Final = 1.0


def _severity(evidence: Mapping[str, Any]) -> Severity:
    return Severity.WARNING


# ---------------------------------------------------------------------------- noise


def _noise(series: Sequence[Point]) -> list[Point]:
    """|x[i+1] - 2 x[i] + x[i-1]| at each inner point: what a smooth reading keeps small."""
    return [
        (series[i][0], abs(series[i + 1][1] - 2 * series[i][1] + series[i - 1][1]))
        for i in range(1, len(series) - 1)
    ]


def _motors(ctx: WindowContext) -> list[tuple[UUID, list[Point]]]:
    """(motor, its current's magnitude) for each other part code `commands` that streams one."""
    commanded = {e.dst_id for e in ctx.graph.edges if e.relation_type == RelationType.COMMANDS}
    found: list[tuple[UUID, list[Point]]] = []
    for motor in sorted(commanded - {ctx.part_id}, key=str):
        channel, samples = peer_readings(ctx, motor, "current")
        if channel is not None:
            found.append((motor, points(samples, magnitude=True)))
    return found


def _correlated(noise: Sequence[Point], current: Sequence[Point]) -> float | None:
    """The correlation of the noise with the current where both have a sample."""
    rows = aligned(noise, current)
    if len(rows) < NOISE_MIN_SAMPLES:
        return None
    try:
        return statistics.correlation([row[1] for row in rows], [row[2] for row in rows])
    except statistics.StatisticsError:  # a steady noise or current follows nothing
        return None


class NoiseTracksMotorActivity:
    """A sensor's noise rises and falls with a motor's current."""

    rule_id = "noise_tracks_motor_activity"
    matrix_cell: MatrixCell | None = MatrixCell.ELECTRICAL_ELECTRICAL
    needs = Needs()  # judged only on a part code reads, against the parts code commands

    severity = staticmethod(_severity)

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        read = {e.dst_id for e in ctx.graph.edges if e.relation_type == RelationType.READS}
        motors = _motors(ctx)
        if unmet(self.needs, ctx) or ctx.part_id not in read or not motors:
            return []
        found: list[tuple[float, str, UUID, list[Point]]] = []
        for channel, samples in sorted(ctx.samples.items()):
            series = trailing(points(sane(samples)), NOISE_WINDOW_SECONDS)
            if not series or not is_new(series[-1][0], judged(ctx, channel)):
                continue
            noise = _noise(series)
            for motor, current in motors:
                correlation = _correlated(noise, current)
                if correlation is not None and correlation >= NOISE_MIN_CORRELATION:
                    found.append((correlation, channel, motor, noise))
        if not found:
            return []
        correlation, channel, motor, noise = max(found, key=lambda match: match[0])
        return [self._noisy(ctx, correlation, channel, motor, noise, dict(motors)[motor])]

    def _noisy(
        self,
        ctx: WindowContext,
        correlation: float,
        channel: str,
        motor: UUID,
        noise: Sequence[Point],
        current: Sequence[Point],
    ) -> RuleHit:
        start, end = noise[0][0], noise[-1][0]
        drawn = max((value for at, value in current if start <= at <= end), default=0.0)
        signal = shown(channel)
        evidence = {
            "channel": signal,
            "motor": str(motor),
            "correlation": correlation,
            "noise": statistics.fmean(value for _, value in noise),
            "current_a": drawn,
            "samples": len(noise),
            **window_evidence(start, end),
        }
        sensor, driver = entity_label(ctx.graph, ctx.part_id), entity_label(ctx.graph, motor)
        headline = f"{sensor} {signal} gets noisier with {driver}'s current (r = {correlation:.2f})"
        causes = (
            Cause(
                kind="electrical_supply",
                for_=(
                    f"noise on {signal} follows {driver}'s current (r = {correlation:.2f}): a "
                    "shared supply, ground or cable run",
                ),
            ),
            Cause(kind="mechanical_load", for_=(f"vibration from {driver} reaches the sensor",)),
        )
        blamed, _ = blame(ctx, ctx.part_id)
        subjects = tuple(dict.fromkeys((*blamed, motor)))
        return make_hit(
            self, ctx, headline=headline, evidence=evidence, causes=causes, subjects=subjects
        )


# ---------------------------------------------------------------------------- the position


def _frozen(
    run: Sequence[tuple[datetime, float, float]], cut: datetime | None, tolerance: float
) -> bool:
    """`FROZEN_MIN_SAMPLES` identical readings over `FROZEN_MIN_SECONDS`, reaching a new one,
    under a command that moved more than `tolerance`."""
    commands = [row[2] for row in run]
    return (
        len(run) >= FROZEN_MIN_SAMPLES
        and (run[-1][0] - run[0][0]).total_seconds() >= FROZEN_MIN_SECONDS
        and is_new(run[-1][0], cut)
        and max(commands) - min(commands) > tolerance
    )


class SensorFrozen:
    """The position reads the same value while its command moves."""

    rule_id = "sensor_frozen"
    matrix_cell: MatrixCell | None = MatrixCell.ELECTRICAL_SOFTWARE
    needs = Needs(channels=("position", COMMAND))

    severity = staticmethod(_severity)

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        position_channel = channel_for(ctx.samples, "position")
        command_channel = channel_for(ctx.samples, COMMAND)
        if unmet(self.needs, ctx) or position_channel is None or command_channel is None:
            return []
        rows = [(at, p, c) for at, p, c in paired(ctx, "position", COMMAND)]
        cut = judged(ctx, position_channel, command_channel)
        for _, group in groupby(rows, key=lambda row: row[1]):
            run = list(group)
            if _frozen(run, cut, ctx.tolerance):
                return [self._frozen_hit(ctx, run)]
        return []

    def _frozen_hit(
        self, ctx: WindowContext, run: Sequence[tuple[datetime, float, float]]
    ) -> RuleHit:
        unit, value = unit_of(ctx, "position"), run[0][1]
        low, high = min(row[2] for row in run), max(row[2] for row in run)
        evidence = {
            "position": value,
            "commanded_min": low,
            "commanded_max": high,
            "command_span": high - low,
            "tolerance": ctx.tolerance,
            "unit": unit,
            "samples": len(run),
            **window_evidence(run[0][0], run[-1][0]),
        }
        headline = (
            f"{entity_label(ctx.graph, ctx.part_id)} position reads exactly {amount(value, unit)} "
            f"for {len(run)} samples while its command moves {amount(high - low, unit)}"
        )
        causes = (
            Cause(
                kind="actuator",
                for_=(
                    f"the reading repeats {amount(value, unit)} exactly while the command moves "
                    f"{amount(high - low, unit)}: its position sensor stopped updating",
                ),
            ),
            Cause(
                kind="electrical_supply",
                for_=("a sensor that loses its power or its line can hold its last value",),
            ),
        )
        return make_hit(self, ctx, headline=headline, evidence=evidence, causes=causes)


class SensorOutOfRange:
    """The position reads past its limit while the command stays inside it."""

    rule_id = "sensor_out_of_range"
    matrix_cell: MatrixCell | None = MatrixCell.ELECTRICAL_SOFTWARE
    needs = Needs(channels=("position",), facts=(fact_need("position", "limit"),))

    severity = staticmethod(_severity)

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        envelope = ctx.envelopes.get("position")
        channel, positions = readings(ctx, "position")
        band = envelope.limit if envelope is not None else None
        if unmet(self.needs, ctx) or envelope is None or band is None or channel is None:
            return []
        asked = {at: command for at, _, command in paired(ctx, "position", COMMAND)}
        found = [
            (sample, edge, side)
            for sample, edge, side in past(positions, band, ctx.tolerance, judged(ctx, channel))
            if asked.get(sample.timestamp) is None
            or outside(asked[sample.timestamp], band, ctx.tolerance) is None
        ]
        if not found:
            return []
        worst, edge, side = max(found, key=lambda item: abs(item[0].value - item[1]))
        commanded, unit = asked.get(worst.timestamp), envelope.unit
        evidence = {
            "position": worst.value,
            "bound": edge,
            "side": side,
            "bounds_source": envelope.bounds_source.get("limit"),
            "commanded": commanded,
            "tolerance": ctx.tolerance,
            "unit": unit,
            "samples": len(found),
            **window_evidence(found[0][0].timestamp, found[-1][0].timestamp),
        }
        inside = ", while the command stays inside" if commanded is not None else ""
        headline = (
            f"{entity_label(ctx.graph, ctx.part_id)} reads {amount(worst.value, unit)}, past its "
            f"{amount(edge, unit)} limit{inside}"
        )
        causes = (
            Cause(
                kind="actuator",
                for_=(
                    f"the reading is past the {amount(edge, unit)} limit{inside}: an offset or a "
                    "failing position sensor",
                ),
            ),
            Cause(
                kind="mechanical_load", for_=("an outside force pushed the joint past its limit",)
            ),
        )
        return [make_hit(self, ctx, headline=headline, evidence=evidence, causes=causes)]


# ---------------------------------------------------------------------------- rates and gaps


def _rate(times: Sequence[datetime]) -> float | None:
    """One over the median interval of `times`; None under two distinct times."""
    gaps: list[float] = [(b - a).total_seconds() for a, b in pairwise(times)]
    middle = statistics.median(gaps) if gaps else 0.0
    return 1 / middle if middle > 0 else None


@dataclass(frozen=True)
class Drift:
    """A channel's rate against what was expected of it."""

    channel: str
    observed_hz: float
    expected_hz: float
    expected_source: str
    drift: float


def _expected_rate(
    ctx: WindowContext, channel: str, earlier: Sequence[datetime]
) -> tuple[float, str] | None:
    """What the channel is expected to stream at, and where that comes from: the envelope's
    `expected_hz` (`learned`), else its own rate before the window (`history`)."""
    envelope = ctx.envelopes.get(channel.rsplit(".", 1)[-1])
    if envelope is not None and envelope.expected_hz:
        return envelope.expected_hz, "learned"
    rate = _rate(earlier) if len(earlier) >= RATE_MIN_SAMPLES else None
    return (rate, "history") if rate else None


def _drift(ctx: WindowContext, channel: str, samples: Sequence[RecentSample]) -> Drift | None:
    """The channel's drift when it is over `RATE_DRIFT_MAX_FRACTION` and reaches a new sample."""
    times = [sample.timestamp for sample in samples]
    if not times or not is_new(times[-1], judged(ctx, channel)):
        return None
    recent = [t for t in times if (times[-1] - t).total_seconds() <= RATE_WINDOW_SECONDS]
    observed = _rate(recent) if len(recent) >= RATE_MIN_SAMPLES else None
    expected = _expected_rate(ctx, channel, times[: len(times) - len(recent)])
    if observed is None or expected is None:
        return None
    rate, source = expected
    drift = abs(observed - rate) / rate
    return (
        Drift(shown(channel), observed, rate, source, drift)
        if drift > RATE_DRIFT_MAX_FRACTION
        else None
    )


class RateDrift:
    """A channel streams off the rate expected of it."""

    rule_id = "rate_drift"
    matrix_cell: MatrixCell | None = MatrixCell.ELECTRICAL_SOFTWARE
    needs = Needs()  # any channel

    severity = staticmethod(_severity)

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        drifting = sorted(
            (
                found
                for name, samples in ctx.samples.items()
                if (found := _drift(ctx, name, samples))
            ),
            key=lambda found: -found.drift,
        )
        if unmet(self.needs, ctx) or not drifting:
            return []
        worst = drifting[0]
        evidence = {
            "channel": worst.channel,
            "observed_hz": worst.observed_hz,
            "expected_hz": worst.expected_hz,
            "expected_source": worst.expected_source,
            "drift": worst.drift,
            "channels": sorted(found.channel for found in drifting),
        }
        observed, expected = amount(worst.observed_hz, "Hz"), amount(worst.expected_hz, "Hz")
        headline = (
            f"{entity_label(ctx.graph, ctx.part_id)} {worst.channel} streams at {observed}, "
            f"{round(100 * worst.drift)} % off its {expected}"
        )
        causes = (
            Cause(
                kind="software_command",
                for_=(
                    f"the producer's loop streams {worst.channel} at {observed}, not {expected}",
                ),
            ),
            Cause(kind="electrical_supply", for_=("a link or bus that drops or delays samples",)),
        )
        return [make_hit(self, ctx, headline=headline, evidence=evidence, causes=causes)]


@dataclass(frozen=True)
class Gap:
    """A channel gone silent (its raw name), since when, for how long, against what timeout."""

    channel: str
    last: datetime
    silent: float
    timeout: float
    period: float


def _period_of(ctx: WindowContext, channel: str) -> float | None:
    """The channel's expected sample period: the envelope's `expected_hz`, else the median
    interval of its samples; None with neither."""
    envelope = ctx.envelopes.get(channel.rsplit(".", 1)[-1])
    if envelope is not None and envelope.expected_hz:
        return 1 / envelope.expected_hz
    rate = _rate([sample.timestamp for sample in ctx.samples.get(channel, ())])
    return 1 / rate if rate else None


def _gap(ctx: WindowContext, channel: str, last: datetime) -> Gap | None:
    period = _period_of(ctx, channel)
    if period is None:
        return None
    timeout = max(STREAM_GAP_PERIODS * period, STREAM_GAP_MIN_SECONDS)
    silent = (ctx.now - last).total_seconds()
    return Gap(channel, last, silent, timeout, period) if silent > timeout else None


def _gap_key(channel: str, session_id: UUID) -> str:
    """How a told gap names its channel in the evidence: the name itself when redaction and the
    one-line bound leave it as it is; else a digest salted with the bench session, so two names
    that redact or cut alike stay two and a name kept from display leaves no fingerprint that
    matches across sessions or robots (a pure rule holds no secret to key an HMAC with)."""
    if shown(channel) == channel:
        return one_line(channel)
    salted = f"{session_id}\0{channel}".encode("utf-8", "surrogatepass")
    return hashlib.sha1(salted, usedforsecurity=False).hexdigest()[:16]


def _reported(prior: Sequence[RuleHit]) -> dict[str, str]:
    """The gaps the part's latest `stream_gap` hit named (channel key → last seen)."""
    latest = next((hit for hit in reversed(prior) if hit.rule_id == "stream_gap"), None)
    gaps = latest.evidence.get("gaps") if latest is not None else None
    if not isinstance(gaps, dict):
        return {}
    return {k: v for k, v in gaps.items() if isinstance(k, str) and isinstance(v, str)}


class StreamGap:
    """A channel that has streamed goes silent past its timeout (wall clock)."""

    rule_id = "stream_gap"
    matrix_cell: MatrixCell | None = MatrixCell.ELECTRICAL_SOFTWARE
    needs = Needs()  # any channel

    severity = staticmethod(_severity)

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]:
        told = _reported(ctx.prior_hits)
        active = [
            gap
            for name, last in sorted(ctx.last_sample_at.items())
            if (gap := _gap(ctx, name, last))
        ]
        session = ctx.session_id
        fresh = [g for g in active if told.get(_gap_key(g.channel, session)) != g.last.isoformat()]
        if unmet(self.needs, ctx) or not fresh:
            return []
        worst = max(fresh, key=lambda gap: gap.silent)
        signal = shown(worst.channel)
        evidence = {
            "last_seen_seconds": worst.silent,
            "timeout": worst.timeout,
            "channel": signal,
            "last_seen_at": worst.last.isoformat(),
            "period_seconds": worst.period,
            "gaps": {_gap_key(gap.channel, session): gap.last.isoformat() for gap in active},
        }
        silent = amount(worst.silent, "s")
        headline = (
            f"{entity_label(ctx.graph, ctx.part_id)} {signal} has been silent for {silent} "
            f"(a sample every {amount(worst.period, 's')} expected)"
        )
        causes = (
            Cause(
                kind="electrical_supply",
                for_=(f"no sample for {silent}: the device lost its power or its link",),
            ),
            Cause(kind="software_command", for_=("the producer or its driver stopped sending",)),
        )
        return [make_hit(self, ctx, headline=headline, evidence=evidence, causes=causes)]


SENSOR_RULES: Final[tuple[SignalRule, ...]] = (
    NoiseTracksMotorActivity(),
    SensorFrozen(),
    SensorOutOfRange(),
    RateDrift(),
    StreamGap(),
)
