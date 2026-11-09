"""SOLUSDEV-321 P2-T2 — electrical (`rules/electrical_rules.py`): current over the rating, a rail
that sags with one part's current (every part on it → the supply or its wiring; that part alone →
its cable), and a controller that restarts under load."""

from __future__ import annotations

import statistics
import uuid
from collections.abc import Sequence

from solus_api.agent.interfaces import GraphContext
from solus_api.checkers.interface import Severity
from solus_api.graph.packet import RecentSample
from solus_api.livebench.findings.rules.electrical_rules import (
    ControllerResetUnderLoad,
    CurrentOverRating,
    RailSagCorrelated,
)
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

PEER1 = uuid.UUID(int=31)
PEER2 = uuid.UUID(int=32)
SUPPLY = uuid.UUID(int=33)
CURRENT = "servo3.current"
VOLTAGE = "servo3.voltage"

# ---------------------------------------------------------------------------- current over rating


def test_current_held_over_the_rating_is_critical() -> None:
    hit = only(CurrentOverRating().evaluate(context({CURRENT: series([1.0, 2.4, 2.5, 2.3, 1.0])})))
    assert hit.rule_id == "current_over_rating"
    assert hit.severity is Severity.CRITICAL
    assert hit.headline == f"{PART_NAME} current 2.5 A over the 2.0 A rating"
    assert hit.subjects == (PART, BUS, BRAIN)
    evidence = hit.evidence
    assert (evidence["current_a"], evidence["bound"], evidence["bounds_source"]) == (
        2.5,
        2.0,
        "config",
    )
    assert evidence["samples"] == 3
    assert (evidence["window_start"], evidence["window_end"]) == (
        at(0.05).isoformat(),
        at(0.15).isoformat(),
    )
    assert [cause.kind for cause in hit.causes] == [
        "mechanical_load",
        "software_command",
        "actuator",
    ]


def test_current_under_the_rating_or_a_two_sample_spike_is_quiet() -> None:
    assert CurrentOverRating().evaluate(context({CURRENT: series([1.9] * 10)})) == []
    assert CurrentOverRating().evaluate(context({CURRENT: series([1.0, 2.6, 2.7, 1.0])})) == []


def test_current_drawn_in_reverse_counts_its_magnitude() -> None:
    hit = only(CurrentOverRating().evaluate(context({CURRENT: series([-2.4] * 3)})))
    assert hit.evidence["current_a"] == 2.4


def test_an_excess_judged_by_an_earlier_tick_does_not_fire_again() -> None:
    samples = {CURRENT: series([2.4, 2.4, 2.4, 1.0, 1.0])}
    assert CurrentOverRating().evaluate(context(samples, judged={CURRENT: at(0.1)})) == []


# ---------------------------------------------------------------------------- rail sag


def peak(*, high: float = 2.4) -> tuple[RecentSample, ...]:
    """0.5 A for 3 s, `high` from 3.0 s to 4.0 s, then 0.5 A to 4.95 s."""
    return series([0.5] * 60 + [high] * 21 + [0.5] * 19)


def volts(sag: float) -> tuple[RecentSample, ...]:
    """7.4 V, down by `sag` while the current peaks."""
    return series([7.4] * 60 + [7.4 - sag] * 21 + [7.4] * 19)


def on_bus(*peers: uuid.UUID) -> GraphContext:
    names = {PEER1: "servo 1 (joint 1)", PEER2: "servo 2 (joint 2)"}
    return arm_graph(
        entities=[node(peer, names[peer]) for peer in peers],
        edges=[fact(BUS, peer, "drives") for peer in peers],
    )


def sharers(*sags: float) -> dict[uuid.UUID, dict[str, tuple[RecentSample, ...]]]:
    return {
        peer: {f"servo{n}.voltage": volts(sag), f"servo{n}.current": series([0.5] * 100)}
        for n, (peer, sag) in enumerate(zip((PEER1, PEER2), sags, strict=False), start=1)
    }


def test_the_whole_bus_sagging_with_one_part_points_at_the_supply() -> None:
    ctx = context(
        {CURRENT: peak(), VOLTAGE: volts(0.4)},
        graph=on_bus(PEER1, PEER2),
        peers=sharers(0.4, 0.3),
    )
    hit = only(RailSagCorrelated().evaluate(ctx))
    assert hit.rule_id == "rail_sag_correlated"
    assert hit.severity is Severity.WARNING
    assert hit.subjects == (BUS, PART, PEER1, PEER2)
    assert hit.headline == (
        f"fake bus sags: all 3 measured parts on it drop when {PART_NAME} draws 2.4 A"
    )
    evidence = hit.evidence
    assert (evidence["scope"], evidence["via"], evidence["rail"]) == ("rail", "drives", str(BUS))
    assert evidence["sagging"] == [str(PEER1), str(PEER2)]
    assert evidence["sharers"] == 2
    assert evidence["current_a"] == 2.4
    assert (evidence["bound"], evidence["bounds_source"]) == (1.0, "config")
    assert (evidence["voltage"], round(evidence["voltage_drop"], 6)) == (7.0, 0.4)
    assert evidence["correlation"] == statistics.correlation(
        [s.value for s in peak()], [s.value for s in volts(0.4)]
    )
    assert round(evidence["correlation"], 9) == -1.0  # two steps in lockstep
    assert [cause.kind for cause in hit.causes] == ["electrical_supply"]


def test_one_part_sagging_alone_points_at_its_cable() -> None:
    ctx = context(
        {CURRENT: peak(), VOLTAGE: volts(0.4)},
        graph=on_bus(PEER1, PEER2),
        peers=sharers(0.0, 0.0),
    )
    hit = only(RailSagCorrelated().evaluate(ctx))
    assert hit.subjects == (PART, BUS)
    assert hit.evidence["scope"] == "cable"
    assert hit.evidence["sagging"] == []
    assert hit.headline == (
        f"{PART_NAME} input sags 0.4 V when it draws 2.4 A while the 2 other measured parts on "
        "fake bus hold: its cable"
    )


def test_some_parts_sagging_point_at_the_wiring_they_share() -> None:
    ctx = context(
        {CURRENT: peak(), VOLTAGE: volts(0.4)},
        graph=on_bus(PEER1, PEER2),
        peers=sharers(0.4, 0.0),
    )
    hit = only(RailSagCorrelated().evaluate(ctx))
    assert hit.subjects == (BUS, PART, PEER1)
    assert hit.evidence["scope"] == "segment"
    assert hit.headline == (
        f"2 of 3 measured parts on fake bus sag when {PART_NAME} draws 2.4 A: the wiring they share"
    )


def test_a_powers_rail_wins_over_the_bus() -> None:
    graph = arm_graph(
        entities=[node(SUPPLY, "5 V rail", "power_rail"), node(PEER1, "servo 1 (joint 1)")],
        edges=[fact(SUPPLY, PART, "powers"), fact(SUPPLY, PEER1, "powers")],
    )
    ctx = context({CURRENT: peak(), VOLTAGE: volts(0.4)}, graph=graph, peers=sharers(0.4))
    hit = only(RailSagCorrelated().evaluate(ctx))
    assert (hit.evidence["via"], hit.evidence["rail"]) == ("powers", str(SUPPLY))
    assert hit.subjects == (SUPPLY, PART, PEER1)


def test_a_sag_with_no_part_sharing_a_known_rail_still_names_the_part() -> None:
    ctx = context({CURRENT: peak(), VOLTAGE: volts(0.4)})
    hit = only(RailSagCorrelated().evaluate(ctx))
    assert hit.evidence["scope"] == "part"
    assert hit.subjects == (PART, BUS, BRAIN)


def test_no_sag_or_no_peak_is_quiet() -> None:
    graph, peers = on_bus(PEER1), sharers(0.4)
    flat = context({CURRENT: peak(), VOLTAGE: volts(0.0)}, graph=graph, peers=peers)
    assert RailSagCorrelated().evaluate(flat) == []
    small = context({CURRENT: peak(), VOLTAGE: volts(0.1)}, graph=graph, peers=peers)
    assert RailSagCorrelated().evaluate(small) == []  # 0.1 V of 7.4 V is under 3 %
    calm = context({CURRENT: peak(high=0.9), VOLTAGE: volts(0.4)}, graph=graph, peers=peers)
    assert RailSagCorrelated().evaluate(calm) == []  # 0.9 A never leaves the nominal band


def test_a_peak_judged_by_an_earlier_tick_does_not_fire_again() -> None:
    ctx = context(
        {CURRENT: peak(), VOLTAGE: volts(0.4)},
        judged={CURRENT: at(4.0), VOLTAGE: at(4.0)},
    )
    assert RailSagCorrelated().evaluate(ctx) == []


# ---------------------------------------------------------------------------- reset under load


def counter(values: Sequence[float], current: float) -> dict[str, tuple[RecentSample, ...]]:
    return {"servo3.reset_count": series(values), CURRENT: series([current] * len(values))}


def test_a_restart_while_drawing_over_nominal_is_reported() -> None:
    hit = only(ControllerResetUnderLoad().evaluate(context(counter([3, 3, 3, 4, 4], 2.4))))
    assert hit.rule_id == "controller_reset_under_load"
    assert hit.severity is Severity.WARNING
    assert (
        hit.headline
        == f"{PART_NAME} controller restarted 1 time while drawing 2.4 A (nominal 1.0 A)"
    )
    evidence = hit.evidence
    assert (evidence["resets"], evidence["current_a"], evidence["bound"]) == (1, 2.4, 1.0)
    assert evidence["window_start"] == at(0.15).isoformat()
    assert [cause.kind for cause in hit.causes] == ["electrical_supply", "software_command"]


def test_a_restart_at_rest_or_no_restart_is_quiet() -> None:
    assert ControllerResetUnderLoad().evaluate(context(counter([3, 3, 4, 4], 0.2))) == []
    assert ControllerResetUnderLoad().evaluate(context(counter([3, 3, 3, 3], 2.4))) == []


def test_a_restart_judged_by_an_earlier_tick_does_not_fire_again() -> None:
    samples = counter([3, 4, 4, 4], 2.4)
    ctx = context(samples, judged={"servo3.reset_count": at(0.1)})
    assert ControllerResetUnderLoad().evaluate(ctx) == []
