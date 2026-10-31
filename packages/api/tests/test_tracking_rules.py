"""SOLUSDEV-321 P2-T2 — tracking (`rules/tracking_rules.py`): a stall (the still window on the warn
bound, sustained a second), a slip (the error holds under a steady command on little current) and
an oscillation (the error's autocorrelation peaks again at a held setpoint)."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence

from solus_api.checkers.interface import Severity
from solus_api.graph.packet import RecentSample
from solus_api.livebench.findings.rules.tracking_rules import (
    STALL_SUSTAIN_SECONDS,
    TrackingErrorSlip,
    TrackingErrorStall,
    TrackingOscillation,
    autocorrelation_peak,
)
from test_rule_base import BRAIN, BUS, PART, PART_NAME, at, context, only, series

POSITION = "servo3.position"
COMMAND = "servo3.commanded_position"
CURRENT = "servo3.current"
LEAD = 10  # rows tracking at 10 deg on 0.5 A before anything happens (0.0 s to 0.45 s)


def arm(
    positions: Sequence[float], commands: Sequence[float], currents: Sequence[float]
) -> dict[str, tuple[RecentSample, ...]]:
    return {POSITION: series(positions), COMMAND: series(commands), CURRENT: series(currents)}


def stall(
    seconds: float, *, current: float = 2.4, tail: int = 0
) -> dict[str, tuple[RecentSample, ...]]:
    """Tracking at 10 deg, then held at 10 deg against a 40 deg command on `current` for
    `seconds` (from 0.5 s), then `tail` rows tracking again."""
    held = round(seconds * 20) + 1
    return arm(
        [10.0] * (LEAD + held + tail),
        [10.0] * LEAD + [40.0] * held + [10.0] * tail,
        [0.5] * LEAD + [current] * held + [0.5] * tail,
    )


# ---------------------------------------------------------------------------- stall


def test_a_stall_of_1_2_s_fires_once_with_its_window() -> None:
    hit = only(TrackingErrorStall().evaluate(context(stall(1.2))))
    assert hit.rule_id == "tracking_error_stall"
    assert hit.severity is Severity.CRITICAL  # 2.4 A reaches the 2.0 A rating
    assert hit.headline == (
        f"{PART_NAME} stalls at 10.0 deg against a 40.0 deg command, drawing 2.4 A (rating 2.0 A)"
    )
    assert hit.subjects == (PART, BUS, BRAIN)
    evidence = hit.evidence
    assert (evidence["current_a"], evidence["bound"], evidence["limit"]) == (2.4, 2.0, 2.0)
    assert evidence["bounds_source"] == "config"  # the rating's source, as P2's acceptance reads
    assert (evidence["warn"], evidence["warn_source"]) == (1.6, "derived")  # the bound judged
    assert (evidence["position"], evidence["commanded"], evidence["error"]) == (10.0, 40.0, 30.0)
    assert evidence["window_start"] == at(0.5).isoformat()
    assert evidence["window_end"] == at(0.5 + STALL_SUSTAIN_SECONDS).isoformat()
    assert evidence["window_seconds"] == STALL_SUSTAIN_SECONDS
    assert [cause.kind for cause in hit.causes] == [
        "mechanical_load",
        "software_command",
        "actuator",
    ]
    command_cause = hit.causes[1]
    assert command_cause.against == (
        "the 40.0 deg command is inside the -150.0 to 150.0 deg limit",
    )


def test_a_half_second_transient_is_not_a_stall() -> None:
    assert TrackingErrorStall().evaluate(context(stall(0.5, tail=20))) == []


def test_a_stall_under_the_rating_is_a_warning() -> None:
    hit = only(TrackingErrorStall().evaluate(context(stall(1.2, current=1.8))))
    assert hit.severity is Severity.WARNING
    assert hit.headline.endswith("drawing 1.8 A (rating 2.0 A)")


def test_current_under_the_warn_bound_is_not_a_stall() -> None:
    assert TrackingErrorStall().evaluate(context(stall(2.0, current=1.5))) == []


def test_a_reverse_stall_counts_the_current_magnitude() -> None:
    hit = only(TrackingErrorStall().evaluate(context(stall(1.2, current=-2.4))))
    assert hit.evidence["current_a"] == 2.4


def test_a_stall_needs_a_sample_newer_than_judged_through() -> None:
    samples = stall(1.2)  # held from 0.5 s to 1.7 s, the newest sample
    newest = {name: at(1.7) for name in samples}
    assert TrackingErrorStall().evaluate(context(samples, judged=newest)) == []
    earlier = {name: at(1.6) for name in samples}
    hit = only(TrackingErrorStall().evaluate(context(samples, judged=earlier)))
    assert hit.evidence["window_end"] > at(1.6).isoformat()


def test_a_stall_that_ended_before_the_cursor_does_not_fire_again() -> None:
    samples = stall(1.2, tail=40)  # held 0.5 s to 1.7 s, then tracking to 3.7 s
    judged = {name: at(2.0) for name in samples}
    assert TrackingErrorStall().evaluate(context(samples, judged=judged)) == []


# ---------------------------------------------------------------------------- slip


def slip(*, current: float = 0.2, drift: float = 0.02) -> dict[str, tuple[RecentSample, ...]]:
    """A steady 40 deg command from 0.5 s; the position creeps from 10 deg by `drift` a row."""
    rows = 30  # 1.45 s
    return arm(
        [10.0] * LEAD + [10.0 + drift * n for n in range(rows)],
        [10.0] * LEAD + [40.0] * rows,
        [0.5] * LEAD + [current] * rows,
    )


def test_an_error_that_holds_on_little_current_is_a_slip() -> None:
    hit = only(TrackingErrorSlip().evaluate(context(slip())))
    assert hit.rule_id == "tracking_error_slip"
    assert hit.severity is Severity.WARNING
    evidence = hit.evidence
    assert (evidence["current_a"], evidence["bound"], evidence["bounds_source"]) == (
        0.2,
        1.0,
        "config",
    )
    assert evidence["error_start"] == 30.0
    assert 29.0 < evidence["error"] < 30.0
    assert evidence["window_start"] == at(0.5).isoformat()
    assert hit.headline.startswith(f"{PART_NAME} is not following its 40.0 deg command")
    assert {cause.kind for cause in hit.causes} == {
        "actuator",
        "mechanical_load",
        "software_command",
    }


def test_normal_travel_toward_the_command_is_not_a_slip() -> None:
    rows = 30
    travel = arm(
        [10.0] * LEAD + [10.0 + 1.5 * n for n in range(rows)],  # 30 deg/s, closing the error
        [10.0] * LEAD + [55.0] * rows,
        [0.5] * LEAD + [0.3] * rows,
    )
    assert TrackingErrorSlip().evaluate(context(travel)) == []


def test_a_slow_move_toward_a_steady_goal_is_not_a_slip() -> None:
    """A goal servo with a profile velocity: 10 deg/s toward a steady 90 deg goal on 0.3 A closes
    far more than the tolerance each second, so no tick over the first 3 s calls it a slip."""
    rows = 61
    move = arm([10.0 + 0.5 * n for n in range(rows)], [90.0] * rows, [0.3] * rows)
    for tick in (1.0, 2.0, 3.0):
        seen = {
            name: tuple(s for s in samples if s.timestamp <= at(tick))
            for name, samples in move.items()
        }
        judged = {name: at(tick - 1.0) for name in move} if tick > 1.0 else {}
        assert TrackingErrorSlip().evaluate(context(seen, judged=judged)) == []


def test_a_bit_identical_reading_is_left_to_sensor_frozen() -> None:
    assert TrackingErrorSlip().evaluate(context(slip(drift=0.0))) == []


def test_an_error_on_nominal_current_is_not_a_slip() -> None:
    assert TrackingErrorSlip().evaluate(context(slip(current=1.2))) == []


def test_slip_needs_position_feedback() -> None:
    samples = {COMMAND: series([40.0] * 30), CURRENT: series([0.2] * 30)}
    assert TrackingErrorSlip().evaluate(context(samples)) == []


# ---------------------------------------------------------------------------- oscillation


def ringing(amplitude: float, *, period_rows: int = 10, rows: int = 100) -> list[float]:
    return [amplitude * math.sin(2 * math.pi * n / period_rows) for n in range(rows)]


def test_autocorrelation_peaks_at_the_period() -> None:
    peak = autocorrelation_peak(ringing(2.0))
    assert peak is not None
    value, lag = peak
    assert lag == 10
    assert math.isclose(value, 1.0)
    assert autocorrelation_peak([1.0] * 50) is None
    assert autocorrelation_peak([float(n) for n in range(50)]) is not None  # crosses, never peaks
    flat = autocorrelation_peak([float(n) for n in range(50)])
    assert flat is not None and flat[0] < 0


def test_ringing_about_a_held_setpoint_is_an_oscillation() -> None:
    positions = [20.0 + value for value in ringing(2.0)]
    samples = arm(positions, [20.0] * 100, [0.6] * 100)
    hit = only(TrackingOscillation().evaluate(context(samples)))
    assert hit.rule_id == "tracking_oscillation"
    assert hit.severity is Severity.WARNING
    evidence = hit.evidence
    assert math.isclose(evidence["period_seconds"], 0.5)
    assert evidence["peak"] >= 0.99
    assert math.isclose(evidence["amplitude"], math.sqrt(2.0), rel_tol=1e-6)  # RMS of 2 sin
    assert math.isclose(evidence["peak_to_peak"], 4 * math.sin(0.4 * math.pi))  # sampled peaks
    assert hit.headline == (
        f"{PART_NAME} oscillates about its 20.0 deg setpoint: 3.804 deg peak to peak every 0.5 s"
    )
    assert [cause.kind for cause in hit.causes] == [
        "software_command",
        "mechanical_load",
        "actuator",
    ]


def test_noise_about_a_setpoint_is_not_an_oscillation() -> None:
    noise = random.Random(7)
    positions = [20.0 + noise.uniform(-2.0, 2.0) for _ in range(100)]
    samples = arm(positions, [20.0] * 100, [0.6] * 100)
    assert TrackingOscillation().evaluate(context(samples)) == []


def test_following_a_moving_command_is_not_an_oscillation() -> None:
    commands = [20.0 + value for value in ringing(10.0)]
    positions = [20.0 + value * 0.8 for value in ringing(10.0)]
    samples = arm(positions, commands, [0.6] * 100)
    assert TrackingOscillation().evaluate(context(samples)) == []


def test_swings_inside_the_tolerance_are_not_an_oscillation() -> None:
    positions = [20.0 + value for value in ringing(0.3)]
    samples = arm(positions, [20.0] * 100, [0.6] * 100)
    assert TrackingOscillation().evaluate(context(samples, tolerance=0.5)) == []


def test_two_position_channels_leave_tracking_unjudged() -> None:
    """Which reading is the feedback is not known: no rule takes the part for one without any."""
    held = stall(1.2)
    ringing_current = [1.0 + value for value in ringing(0.5)]
    for samples in (
        {**held, "motor.position": held[POSITION]},
        {
            "a.position": series([20.0] * 100),
            "b.position": series([20.0] * 100),
            COMMAND: series([20.0] * 100),
            CURRENT: series(ringing_current),
        },
    ):
        for rule in (TrackingErrorStall(), TrackingErrorSlip(), TrackingOscillation()):
            assert rule.evaluate(context(samples)) == []


def test_a_dumb_actuator_rings_on_its_current() -> None:
    currents = [1.0 + value for value in ringing(0.5)]
    samples = {COMMAND: series([20.0] * 100), CURRENT: series(currents)}
    hit = only(TrackingOscillation().evaluate(context(samples)))
    assert CURRENT in hit.headline
    assert hit.causes == ()
    assert hit.evidence["settling_signal"] == CURRENT
