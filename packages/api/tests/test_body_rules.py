"""SOLUSDEV-321 P2-T2 — the body (`rules/body_rules.py`): an actuator that reports it reached its
target while a motion sensor on its output link still moves (`body_lag`), and the device's own
error flags (`error_flag`: overload → command or mechanism, overheat → thermal, voltage → rail)."""

from __future__ import annotations

import uuid

from solus_api.agent.interfaces import GraphContext
from solus_api.checkers.interface import Severity
from solus_api.graph.packet import RecentSample
from solus_api.livebench.findings.rules.body_rules import BodyLag, ErrorFlag
from solus_api.livebench.findings.rules.rule_base import unmet
from test_rule_base import (
    BRAIN,
    BUS,
    PART,
    PART_NAME,
    arm_graph,
    at,
    context,
    fact,
    node,
    only,
    series,
)

LINK = uuid.UUID(int=21)
SENSOR = uuid.UUID(int=22)
SENSOR_CHANNEL = "imu.position"
HELD = {"servo3.position": series([40.0] * 21), "servo3.commanded_position": series([40.0] * 21)}


def linked_graph(*, mated: bool = True) -> GraphContext:
    """The part mates with a link; the link mounts a motion sensor."""
    return arm_graph(
        entities=[node(LINK, "forearm link", "cad_part", "mechanical"), node(SENSOR, "wrist imu")],
        edges=[
            *([fact(PART, LINK, "mates_with")] if mated else []),
            fact(LINK, SENSOR, "mounts"),
        ],
    )


def sensor(values: list[float]) -> dict[uuid.UUID, dict[str, tuple[RecentSample, ...]]]:
    """The motion sensor's samples, as the evaluator hands a peer's."""
    return {SENSOR: {SENSOR_CHANNEL: series(values)}}


# ---------------------------------------------------------------------------- body lag


def test_a_link_that_still_moves_after_the_actuator_settles_lags() -> None:
    ctx = context(HELD, graph=linked_graph(), peers=sensor([10.0 + 0.1 * n for n in range(21)]))
    hit = only(BodyLag().evaluate(ctx))
    assert hit.rule_id == "body_lag"
    assert hit.severity is Severity.WARNING
    assert hit.subjects == (PART, BUS, BRAIN, SENSOR)
    assert hit.headline == (
        f"{PART_NAME} reports it reached 40.0 deg but wrist imu on its output link still moves "
        "1.0 deg"
    )
    evidence = hit.evidence
    assert (evidence["sensor"], evidence["sensor_channel"]) == (str(SENSOR), SENSOR_CHANNEL)
    assert round(evidence["sensor_motion"], 6) == 1.0  # 0.1 deg a row over the half second
    assert (evidence["position"], evidence["commanded"], evidence["unit"]) == (40.0, 40.0, "deg")
    assert evidence["window_start"] == at(0.0).isoformat()
    assert [cause.kind for cause in hit.causes] == ["mechanical_load", "actuator"]


def test_a_link_that_holds_with_the_actuator_does_not_lag() -> None:
    ctx = context(HELD, graph=linked_graph(), peers=sensor([10.0] * 21))
    assert BodyLag().evaluate(ctx) == []


def test_a_moving_actuator_is_not_judged() -> None:
    moving = {
        "servo3.position": series([10.0 + 2.0 * n for n in range(21)]),
        "servo3.commanded_position": series([10.0 + 2.0 * n for n in range(21)]),
    }
    ctx = context(moving, graph=linked_graph(), peers=sensor([10.0 + n for n in range(21)]))
    assert BodyLag().evaluate(ctx) == []


def test_no_mated_link_is_unmet() -> None:
    ctx = context(
        HELD, graph=linked_graph(mated=False), peers=sensor([10.0 + n for n in range(21)])
    )
    assert BodyLag().evaluate(ctx) == []
    assert unmet(BodyLag.needs, ctx) == ("mates_with relation",)


def test_a_rest_judged_by_an_earlier_tick_does_not_fire_again() -> None:
    ctx = context(
        HELD,
        graph=linked_graph(),
        peers=sensor([10.0 + 0.1 * n for n in range(21)]),
        judged={name: at(1.0) for name in HELD},
    )
    assert BodyLag().evaluate(ctx) == []


# ---------------------------------------------------------------------------- error flags


def test_an_overload_flag_is_critical_and_names_command_and_mechanism() -> None:
    samples = {
        "servo3.overload_flag": series([0.0, 0.0, 1.0, 1.0]),
        "servo3.current": series([1.0, 1.5, 2.6, 2.7]),
    }
    hit = only(ErrorFlag().evaluate(context(samples)))
    assert hit.rule_id == "error_flag"
    assert hit.severity is Severity.CRITICAL
    assert hit.headline == f"{PART_NAME} raised its overload error flag"
    assert hit.evidence["flags"] == ["overload"]
    assert hit.evidence["current_a"] == 2.7
    assert hit.evidence["samples"] == 2
    assert [cause.kind for cause in hit.causes] == ["software_command", "mechanical_load"]
    assert "2.7 A" in hit.causes[0].for_[0]


def test_an_overheat_flag_alone_is_a_warning_and_thermal() -> None:
    samples = {"servo3.overheat_flag": series([1.0]), "servo3.temperature": series([71.0])}
    hit = only(ErrorFlag().evaluate(context(samples)))
    assert hit.severity is Severity.WARNING
    assert hit.evidence["flags"] == ["overheat"]
    assert hit.evidence["temperature"] == 71.0
    assert [cause.kind for cause in hit.causes] == ["mechanical_load", "actuator"]


def test_flags_together_name_each_and_rank_the_rail() -> None:
    samples = {
        "servo3.voltage_flag": series([1.0]),
        "servo3.overload_flag": series([1.0]),
        "servo3.voltage": series([5.2]),
    }
    hit = only(ErrorFlag().evaluate(context(samples)))
    assert hit.severity is Severity.CRITICAL
    assert hit.headline == f"{PART_NAME} raised its overload and voltage error flags"
    assert hit.evidence["flags"] == ["overload", "voltage"]
    assert [cause.kind for cause in hit.causes] == [
        "software_command",
        "mechanical_load",
        "electrical_supply",
    ]
    assert "5.2 V" in hit.causes[2].for_[0]


def test_clear_flags_or_flags_already_judged_are_quiet() -> None:
    clear = {"servo3.overload_flag": series([0.0, 0.0])}
    assert ErrorFlag().evaluate(context(clear)) == []
    judged = {"servo3.overload_flag": series([1.0, 0.0])}
    ctx = context(judged, judged={"servo3.overload_flag": at(0.0)})
    assert ErrorFlag().evaluate(ctx) == []


def test_a_part_without_flags_needs_nothing_and_fires_nothing() -> None:
    ctx = context({"servo3.current": series([1.0])}, graph=GraphContext(entities=[], edges=[]))
    assert unmet(ErrorFlag.needs, ctx) == ()
    assert ErrorFlag().evaluate(ctx) == []
