"""SOLUSDEV-321 P2-T2 — commands against the part's limits (`rules/command_rules.py`): a commanded
position past the joint's limit, a commanded velocity past `velocity_max`."""

from __future__ import annotations

from solus_api.checkers.interface import Severity
from solus_api.livebench.findings.rules.command_rules import (
    CommandExceedsLimit,
    CommandRateExceedsLimit,
)
from solus_api.livebench.findings.rules.rule_base import unmet
from test_rule_base import (
    BRAIN,
    BUS,
    CODE,
    CODE_PATH,
    PART,
    PART_NAME,
    arm_envelopes,
    at,
    context,
    envelope_of,
    only,
    series,
)

GOAL = "servo3.commanded_position"
SPEED = "servo3.commanded_velocity"


def test_a_command_past_the_joint_limit_fires() -> None:
    hit = only(CommandExceedsLimit().evaluate(context({GOAL: series([100.0, 200.0, 180.0])})))
    assert hit.rule_id == "command_exceeds_limit"
    assert hit.severity is Severity.WARNING
    assert hit.headline == f"{PART_NAME} commanded to 200.0 deg, past its 150.0 deg limit"
    assert hit.subjects == (PART, BUS, BRAIN)
    evidence = hit.evidence
    assert (evidence["commanded"], evidence["bound"], evidence["side"]) == (200.0, 150.0, "upper")
    assert (evidence["bounds_source"], evidence["unit"], evidence["samples"]) == (
        "config",
        "deg",
        2,
    )
    assert (evidence["window_start"], evidence["window_end"]) == (
        at(0.05).isoformat(),
        at(0.1).isoformat(),
    )
    assert evidence["code_site"] == {
        "entity_id": str(CODE),
        "source_id": None,
        "path": CODE_PATH,
        "line": 13,
    }
    assert [cause.kind for cause in hit.causes] == ["software_command"]
    assert "200.0 deg" in hit.causes[0].for_[0]


def test_a_command_below_the_lower_limit_names_that_edge() -> None:
    hit = only(CommandExceedsLimit().evaluate(context({GOAL: series([-160.0])})))
    assert (hit.evidence["bound"], hit.evidence["side"]) == (-150.0, "lower")


def test_a_command_inside_the_limit_or_within_tolerance_is_quiet() -> None:
    ctx = context({GOAL: series([100.0, 150.3, -150.4])}, tolerance=0.5)
    assert CommandExceedsLimit().evaluate(ctx) == []


def test_a_command_an_earlier_tick_judged_does_not_fire_again() -> None:
    samples = {GOAL: series([200.0, 200.0, 100.0, 100.0])}  # past the limit at 0.0 s and 0.05 s
    assert CommandExceedsLimit().evaluate(context(samples, judged={GOAL: at(0.05)})) == []
    hit = only(CommandExceedsLimit().evaluate(context(samples, judged={GOAL: at(0.0)})))
    assert hit.evidence["samples"] == 1


def test_no_position_limit_is_unmet_and_fires_nothing() -> None:
    envelopes = {k: v for k, v in arm_envelopes().items() if k != "position"}
    ctx = context({GOAL: series([200.0])}, envelopes=envelopes)
    assert CommandExceedsLimit().evaluate(ctx) == []
    (missing,) = unmet(CommandExceedsLimit.needs, ctx)
    assert missing.startswith("position.limit (set it in ")


def test_a_commanded_velocity_over_velocity_max_fires_either_way() -> None:
    velocity = envelope_of("velocity", "deg/s", limit=(None, 90.0))
    ctx = context(
        {SPEED: series([40.0, -120.0, 60.0])},
        envelopes={**arm_envelopes(), "velocity": velocity},
    )
    hit = only(CommandRateExceedsLimit().evaluate(ctx))
    assert hit.rule_id == "command_rate_exceeds_limit"
    assert hit.severity is Severity.WARNING
    assert (
        hit.headline == f"{PART_NAME} commanded at 120.0 deg/s, over its 90.0 deg/s velocity limit"
    )
    evidence = hit.evidence
    assert (evidence["commanded_velocity"], evidence["speed"], evidence["bound"]) == (
        -120.0,
        120.0,
        90.0,
    )
    assert (evidence["bounds_source"], evidence["samples"]) == ("config", 1)
    assert [cause.kind for cause in hit.causes] == ["software_command"]


def test_a_commanded_velocity_within_velocity_max_is_quiet() -> None:
    velocity = envelope_of("velocity", "deg/s", limit=(None, 90.0))
    ctx = context(
        {SPEED: series([40.0, -90.0, 89.0])},
        envelopes={**arm_envelopes(), "velocity": velocity},
    )
    assert CommandRateExceedsLimit().evaluate(ctx) == []


def test_no_velocity_limit_is_unmet() -> None:
    ctx = context({SPEED: series([400.0])})  # the fake arm states no velocity_max
    assert CommandRateExceedsLimit().evaluate(ctx) == []
    (missing,) = unmet(CommandRateExceedsLimit.needs, ctx)
    assert missing.startswith("velocity.limit (set it in ")
