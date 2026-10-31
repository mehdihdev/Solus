"""SOLUSDEV-321 P2-T2 — sensors (`rules/sensor_rules.py`): noise that follows a motor's current, a
frozen or impossible position reading, a channel whose rate drifts, and a channel gone silent on
the wall clock (the `GapWatchdog` semantics: once per gap, re-armed by the next sample)."""

from __future__ import annotations

import json
import string
import uuid
from collections.abc import Sequence
from dataclasses import replace

from solus_api.agent.interfaces import GraphContext
from solus_api.checkers.interface import Severity
from solus_api.graph.packet import RecentSample
from solus_api.livebench.findings.rules.rule_base import RuleHit
from solus_api.livebench.findings.rules.sensor_rules import (
    NoiseTracksMotorActivity,
    RateDrift,
    SensorFrozen,
    SensorOutOfRange,
    StreamGap,
)
from test_rule_base import (
    BRAIN,
    BUS,
    CODE,
    PART,
    PART_NAME,
    arm_envelopes,
    at,
    context,
    envelope_of,
    fact,
    node,
    only,
    series,
)

SENSOR = uuid.UUID(int=41)
MOTOR = uuid.UUID(int=42)
POSITION = "servo3.position"
COMMAND = "servo3.commanded_position"
LEVELS = ([0.2] * 20 + [2.0] * 20) * 2 + [0.2] * 20  # a motor's current, 1 s low / 1 s high


# ---------------------------------------------------------------------------- noise


def wired() -> GraphContext:
    """Code reads the sensor and commands the motor."""
    return GraphContext(
        entities=[node(SENSOR, "wrist imu"), node(MOTOR, "servo 3 (joint 3)")],
        edges=[fact(CODE, SENSOR, "reads"), fact(CODE, MOTOR, "commands")],
    )


def imu(*, noisy_when_high: bool = True) -> dict[str, tuple[RecentSample, ...]]:
    """9.8 with ±0.5 sample-to-sample noise while the motor is (or is not) drawing."""
    values = [
        9.8 + (0.5 * (-1) ** n if (level > 1.0) == noisy_when_high else 0.0)
        for n, level in enumerate(LEVELS)
    ]
    return {"imu.az": series(values)}


def motor() -> dict[uuid.UUID, dict[str, tuple[RecentSample, ...]]]:
    return {MOTOR: {"servo3.current": series(LEVELS)}}


def test_noise_that_follows_a_motors_current_fires() -> None:
    ctx = context(imu(), part=SENSOR, envelopes={}, graph=wired(), peers=motor())
    hit = only(NoiseTracksMotorActivity().evaluate(ctx))
    assert hit.rule_id == "noise_tracks_motor_activity"
    assert hit.severity is Severity.WARNING
    assert hit.subjects == (SENSOR, MOTOR)
    evidence = hit.evidence
    assert (evidence["channel"], evidence["motor"]) == ("imu.az", str(MOTOR))
    assert evidence["correlation"] >= 0.9
    assert evidence["current_a"] == 2.0
    assert hit.headline.startswith("wrist imu imu.az gets noisier with servo 3 (joint 3)'s current")
    assert [cause.kind for cause in hit.causes] == ["electrical_supply", "mechanical_load"]


def test_noise_against_the_motor_or_without_one_is_quiet() -> None:
    against = context(
        imu(noisy_when_high=False), part=SENSOR, envelopes={}, graph=wired(), peers=motor()
    )
    assert NoiseTracksMotorActivity().evaluate(against) == []
    alone = context(imu(), part=SENSOR, envelopes={}, graph=wired())
    assert NoiseTracksMotorActivity().evaluate(alone) == []


def test_only_a_part_code_reads_is_judged_for_noise() -> None:
    ctx = context(imu(), part=MOTOR, envelopes={}, graph=wired(), peers={SENSOR: motor()[MOTOR]})
    assert NoiseTracksMotorActivity().evaluate(ctx) == []


# ---------------------------------------------------------------------------- frozen


def frozen(*, commands: Sequence[float]) -> dict[str, tuple[RecentSample, ...]]:
    return {POSITION: series([10.0] * len(commands)), COMMAND: series(commands)}


def test_a_position_that_repeats_while_its_command_moves_is_frozen() -> None:
    samples = frozen(commands=[10.0 + n for n in range(30)])
    hit = only(SensorFrozen().evaluate(context(samples)))
    assert hit.rule_id == "sensor_frozen"
    assert hit.severity is Severity.WARNING
    assert hit.headline == (
        f"{PART_NAME} position reads exactly 10.0 deg for 30 samples while its command moves "
        "29.0 deg"
    )
    evidence = hit.evidence
    assert (evidence["position"], evidence["command_span"], evidence["samples"]) == (10.0, 29.0, 30)
    assert [cause.kind for cause in hit.causes] == ["actuator", "electrical_supply"]


def test_a_position_held_under_a_steady_command_is_not_frozen() -> None:
    assert SensorFrozen().evaluate(context(frozen(commands=[40.0] * 30))) == []


def test_a_reading_that_moves_or_a_quantized_channel_is_not_frozen() -> None:
    moving = {
        POSITION: series([10.0 + 0.5 * n for n in range(30)]),
        COMMAND: series([10.0 + n for n in range(30)]),
        "servo3.temperature": series([35.0] * 30),
    }
    assert SensorFrozen().evaluate(context(moving)) == []


def test_a_freeze_judged_by_an_earlier_tick_does_not_fire_again() -> None:
    samples = frozen(commands=[10.0 + n for n in range(30)])
    judged = {POSITION: at(1.45), COMMAND: at(1.45)}
    assert SensorFrozen().evaluate(context(samples, judged=judged)) == []


# ---------------------------------------------------------------------------- out of range


def test_a_position_past_its_limit_under_an_inside_command_is_out_of_range() -> None:
    samples = {POSITION: series([100.0, 160.0, 162.0]), COMMAND: series([100.0] * 3)}
    hit = only(SensorOutOfRange().evaluate(context(samples)))
    assert hit.rule_id == "sensor_out_of_range"
    assert hit.severity is Severity.WARNING
    assert hit.headline == (
        f"{PART_NAME} reads 162.0 deg, past its 150.0 deg limit, while the command stays inside"
    )
    evidence = hit.evidence
    assert (evidence["position"], evidence["bound"], evidence["side"]) == (162.0, 150.0, "upper")
    assert (evidence["commanded"], evidence["samples"], evidence["bounds_source"]) == (
        100.0,
        2,
        "config",
    )
    assert [cause.kind for cause in hit.causes] == ["actuator", "mechanical_load"]


def test_a_position_past_its_limit_with_no_command_is_judged_alone() -> None:
    hit = only(SensorOutOfRange().evaluate(context({POSITION: series([-151.0])})))
    assert (hit.evidence["side"], hit.evidence["commanded"]) == ("lower", None)
    assert hit.headline == f"{PART_NAME} reads -151.0 deg, past its -150.0 deg limit"


def test_a_command_past_the_limit_is_left_to_the_command_rule() -> None:
    samples = {POSITION: series([160.0] * 3), COMMAND: series([160.0] * 3)}
    assert SensorOutOfRange().evaluate(context(samples)) == []
    inside = {POSITION: series([149.0, 150.4]), COMMAND: series([149.0, 150.0])}
    assert SensorOutOfRange().evaluate(context(inside)) == []


# ---------------------------------------------------------------------------- rate drift


def test_a_channel_streaming_at_half_its_learned_rate_drifts() -> None:
    envelopes = {**arm_envelopes(), "current": envelope_of("current", "A", expected_hz=20.0)}
    ctx = context({"servo3.current": series([1.0] * 50, hz=10.0)}, envelopes=envelopes)
    hit = only(RateDrift().evaluate(ctx))
    assert hit.rule_id == "rate_drift"
    assert hit.severity is Severity.WARNING
    evidence = hit.evidence
    assert (evidence["channel"], evidence["expected_source"]) == ("servo3.current", "learned")
    assert (round(evidence["observed_hz"], 6), evidence["expected_hz"]) == (10.0, 20.0)
    assert round(evidence["drift"], 6) == 0.5
    assert hit.headline == f"{PART_NAME} servo3.current streams at 10.0 Hz, 50 % off its 20.0 Hz"


def test_a_channel_slowing_from_its_own_earlier_rate_drifts() -> None:
    samples = series([0.0] * 200) + series([0.0] * 50, hz=10.0, start=10.0)
    hit = only(RateDrift().evaluate(context({COMMAND: samples})))
    assert hit.evidence["expected_source"] == "history"
    assert round(hit.evidence["expected_hz"], 6) == 20.0


def test_a_steady_rate_or_a_judged_one_is_quiet() -> None:
    steady = {"servo3.current": series([1.0] * 200)}
    assert RateDrift().evaluate(context(steady)) == []
    envelopes = {**arm_envelopes(), "current": envelope_of("current", "A", expected_hz=20.0)}
    slow = {"servo3.current": series([1.0] * 50, hz=10.0)}
    judged = {"servo3.current": at(4.9)}
    assert RateDrift().evaluate(context(slow, envelopes=envelopes, judged=judged)) == []


# ---------------------------------------------------------------------------- stream gap


CURRENT = "servo3.current"
STREAM = {CURRENT: series([1.0] * 200)}  # 20 Hz to 9.95 s


def test_a_channel_silent_past_three_periods_and_a_tick_is_a_gap() -> None:
    ctx = context(STREAM, now=at(12.0), last={CURRENT: at(10.0)})
    hit = only(StreamGap().evaluate(ctx))
    assert hit.rule_id == "stream_gap"
    assert hit.severity is Severity.WARNING
    assert hit.subjects == (PART, BUS, BRAIN)
    evidence = hit.evidence
    assert (evidence["last_seen_seconds"], evidence["timeout"]) == (2.0, 1.0)  # GapWatchdog's keys
    assert evidence["gaps"] == {CURRENT: at(10.0).isoformat()}  # a plain name keys itself
    assert hit.headline == (
        f"{PART_NAME} servo3.current has been silent for 2.0 s (a sample every 0.05 s expected)"
    )


def test_the_expected_rate_sets_the_timeout() -> None:
    envelopes = {**arm_envelopes(), "current": envelope_of("current", "A", expected_hz=0.5)}
    quiet = context(STREAM, envelopes=envelopes, now=at(15.0), last={CURRENT: at(10.0)})
    assert StreamGap().evaluate(quiet) == []  # 5 s silent, 6 s allowed
    late = context(STREAM, envelopes=envelopes, now=at(17.0), last={CURRENT: at(10.0)})
    assert only(StreamGap().evaluate(late)).evidence["timeout"] == 6.0


def test_a_gap_fires_once_and_re_arms_on_the_next_sample() -> None:
    first = only(StreamGap().evaluate(context(STREAM, now=at(12.0), last={CURRENT: at(10.0)})))
    again = context(STREAM, now=at(13.0), last={CURRENT: at(10.0)}, prior=(first,))
    assert StreamGap().evaluate(again) == []
    resumed = context(STREAM, now=at(15.0), last={CURRENT: at(13.5)}, prior=(first,))
    gaps = only(StreamGap().evaluate(resumed)).evidence["gaps"]
    assert gaps == {CURRENT: at(13.5).isoformat()}


def test_a_channel_within_its_timeout_or_without_a_period_is_quiet() -> None:
    assert StreamGap().evaluate(context(STREAM, now=at(10.5), last={CURRENT: at(10.0)})) == []
    single = {CURRENT: series([1.0])}
    assert StreamGap().evaluate(context(single, now=at(30.0), last={CURRENT: at(0.0)})) == []


def test_two_channels_that_read_alike_redacted_are_each_told_once() -> None:
    entropic = (string.ascii_lowercase + string.digits) * 2  # long and varied: redacted
    names = (f"{entropic}.current", f"{entropic[::-1]}.current")
    samples = {name: series([1.0] * 200) for name in names}
    last = {names[0]: at(10.0), names[1]: at(10.5)}
    first = only(StreamGap().evaluate(context(samples, now=at(12.0), last=last)))
    assert first.evidence["channel"] == "[REDACTED]"  # shown redacted
    assert len(first.evidence["gaps"]) == 2  # remembered apart
    again = context(samples, now=at(13.0), last=last, prior=(first,))
    assert StreamGap().evaluate(again) == []


def test_a_secret_shaped_channel_name_leaves_no_fingerprint_beyond_its_session() -> None:
    secret = "sk-" + string.ascii_letters[:24]  # key-shaped once built; redact_text masks it
    name = f"{secret}.current"
    samples = {name: series([1.0] * 200)}
    ctx = context(samples, now=at(12.0), last={name: at(10.0)})
    hit = only(StreamGap().evaluate(ctx))
    told = json.dumps([hit.evidence, [cause.model_dump(mode="json") for cause in hit.causes]])
    assert secret not in told and secret not in hit.headline
    (key,) = hit.evidence["gaps"]
    other = only(StreamGap().evaluate(replace(ctx, session_id=uuid.UUID(int=77))))
    assert set(other.evidence["gaps"]) != {key}  # salted by the bench session
    assert StreamGap().evaluate(replace(ctx, prior_hits=(hit,))) == []  # still told once


def test_a_prior_hit_of_another_rule_does_not_silence_a_gap() -> None:
    other = RuleHit(
        rule_id="current_over_rating",
        severity=Severity.CRITICAL,
        headline="x",
        subjects=(PART,),
        evidence={"gaps": {CURRENT: at(10.0).isoformat()}},
    )
    ctx = context(STREAM, now=at(12.0), last={CURRENT: at(10.0)}, prior=(other,))
    assert StreamGap().evaluate(ctx)
