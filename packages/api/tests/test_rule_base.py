"""SOLUSDEV-321 P2-T2 — the rule base (`livebench/findings/rules/rule_base.py`): the still window
the run analysis and the stall rule share, needs, blame, and the shapes every rule returns.

Pure: every test hands a rule a `WindowContext` built in place — synthetic samples on a fixed
clock, the fake arm's envelopes, a small fact graph. The builders here are shared by the other
rule test files (`from test_rule_base import …`).
"""

from __future__ import annotations

import json
import math
import string
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from pydantic import ValidationError
from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers.interface import Severity
from solus_api.graph import kinds
from solus_api.graph.packet import RecentSample
from solus_api.livebench.findings.envelopes import Bound, Envelope
from solus_api.livebench.findings.rules import SIGNAL_RULES
from solus_api.livebench.findings.rules.rule_base import (
    MAX_ABS_VALUE,
    MAX_LABEL_CHARS,
    Cause,
    Needs,
    RuleHit,
    SignalRule,
    WindowContext,
    amount,
    blame,
    channel_for,
    entity_label,
    fact_need,
    peer_readings,
    readings,
    still_window,
    unmet,
)
from solus_api.livebench.findings.rules.tracking_rules import TrackingErrorStall
from solus_api.livebench.runs.analysis import _STILL_TOLERANCE, _observations, _stall_window
from solus_api.livebench.runs.models import RunManifest
from solus_contracts.relations import MatrixCell

T0: Final = datetime(2026, 10, 25, tzinfo=UTC)
ROBOT: Final = uuid.UUID(int=1)
SESSION: Final = uuid.UUID(int=2)
PART: Final = uuid.UUID(int=3)
BUS: Final = uuid.UUID(int=4)
BRAIN: Final = uuid.UUID(int=5)
CODE: Final = uuid.UUID(int=6)
PART_NAME: Final = "servo 3 (joint 3)"
CODE_PATH: Final = "fw/fake_arm.ino"
type Band = tuple[float | None, float | None]


# ---------------------------------------------------------------------------- shared builders


def at(seconds: float) -> datetime:
    """`seconds` after the fixed epoch."""
    return T0 + timedelta(seconds=seconds)


def series(
    values: Sequence[float], *, hz: float = 20.0, start: float = 0.0
) -> tuple[RecentSample, ...]:
    """One sample per value, `hz` apart, from `start` seconds."""
    return tuple(
        RecentSample(timestamp=at(start + index / hz), value=value)
        for index, value in enumerate(values)
    )


def envelope_of(
    quantity: str,
    unit: str | None,
    *,
    nominal: Band | None = None,
    warn: Band | None = None,
    limit: Band | None = None,
    expected_hz: float | None = None,
    source: str = "config",
    part: uuid.UUID = PART,
) -> Envelope:
    """An envelope as P2-T1 builds one: `warn` derived, the other bounds from `source`."""
    bands = {"nominal": nominal, "warn": warn, "limit": limit}
    present = {slot: Bound(lo=band[0], hi=band[1]) for slot, band in bands.items() if band}
    sources = {slot: "derived" if slot == "warn" else source for slot in present}
    if expected_hz is not None:
        sources["expected_hz"] = "learned"
    return Envelope(
        part_id=part,
        quantity=quantity,
        unit=unit,
        nominal=present.get("nominal"),
        warn=present.get("warn"),
        limit=present.get("limit"),
        expected_hz=expected_hz,
        bounds_source=sources,
        confidence=1.0,
    )


def arm_envelopes(part: uuid.UUID = PART) -> dict[str, Envelope]:
    """The fake arm's limits (`fixtures/fake_arm.py:LIMITS`) as envelopes, warn at 0.8."""
    return {
        "current": envelope_of(
            "current", "A", nominal=(None, 1.0), warn=(None, 1.6), limit=(None, 2.0), part=part
        ),
        "temperature": envelope_of(
            "temperature", "degC", warn=(None, 56.0), limit=(None, 70.0), part=part
        ),
        "voltage": envelope_of("voltage", "V", warn=(6.24, 8.16), limit=(6.0, 8.4), part=part),
        "position": envelope_of(
            "position", "deg", warn=(-120.0, 120.0), limit=(-150.0, 150.0), part=part
        ),
    }


def node(
    entity_id: uuid.UUID, name: str, kind: str = kinds.PART, domain: str = "electrical"
) -> EntityRead:
    return EntityRead(id=entity_id, kind=kind, domain=domain, name=name)


def fact(src: uuid.UUID, dst: uuid.UUID, relation: str, *refs: str) -> EdgeRead:
    """A fact edge; each `ref` is a `firmware_symbol` evidence item."""
    evidence = [{"kind": "firmware_symbol", "ref": ref, "detail": None} for ref in refs]
    return EdgeRead(
        src_id=src,
        dst_id=dst,
        relation_type=relation,
        domain_pair="electrical<->electrical",
        confidence=1.0,
        attrs={"evidence": evidence},
    )


def arm_graph(
    *, name: str = PART_NAME, entities: Sequence[EntityRead] = (), edges: Sequence[EdgeRead] = ()
) -> GraphContext:
    """The part on the fake arm's bus, the bus on its brain, and the code that commands it."""
    return GraphContext(
        entities=[
            node(PART, name),
            node(BUS, "fake bus", kinds.HARDWARE_BUS),
            node(BRAIN, "fake brain", kinds.HARDWARE_BRAIN),
            node(CODE, CODE_PATH, kinds.CODE_FILE, "code"),
            *entities,
        ],
        edges=[
            fact(BRAIN, BUS, "hardware_connected_to"),
            fact(BUS, PART, "drives"),
            fact(CODE, PART, "commands", f"{CODE_PATH}:13"),
            *edges,
        ],
    )


def context(
    samples: Mapping[str, tuple[RecentSample, ...]],
    *,
    envelopes: Mapping[str, Envelope] | None = None,
    graph: GraphContext | None = None,
    judged: Mapping[str, datetime] | None = None,
    peers: Mapping[uuid.UUID, Mapping[str, tuple[RecentSample, ...]]] | None = None,
    prior: tuple[RuleHit, ...] = (),
    now: datetime | None = None,
    last: Mapping[str, datetime] | None = None,
    tolerance: float = 0.5,
    part: uuid.UUID = PART,
) -> WindowContext:
    """The window of `part` (the fake arm's envelopes and graph unless given)."""
    return WindowContext(
        part_id=part,
        robot_id=ROBOT,
        session_id=SESSION,
        now=now or at(60.0),
        samples=samples,
        envelopes=arm_envelopes(part) if envelopes is None else envelopes,
        graph=graph or arm_graph(),
        last_sample_at=last or {},
        prior_hits=prior,
        tolerance=tolerance,
        judged_through=judged or {},
        peers=peers or {},
    )


def only(hits: Sequence[RuleHit]) -> RuleHit:
    """The one hit."""
    assert len(hits) == 1, hits
    return hits[0]


# ---------------------------------------------------------------------------- the still window


def _run(
    *,
    seconds: Sequence[float] = (0.0, 1.0, 2.0),
    positions: Sequence[float] | None = None,
    current: float = 2.1,
    command: float = 100.0,
    unit: str = "deg",
) -> RunManifest:
    """A run of one part, shaped like `tests/test_run_analysis.py:manifest` (held at 0 unless
    `positions` say otherwise)."""
    start = datetime(2026, 9, 14, tzinfo=UTC)
    positions = positions or [0.0] * len(seconds)
    return RunManifest.model_validate(
        {
            "schema_version": 1,
            "robot_id": str(ROBOT),
            "started_at": start,
            "parts": [
                {
                    "entity_id": str(PART),
                    "name": "Fixture joint",
                    "device_id": "fixture/joint",
                    "current_signal": "current",
                    "position_signal": "position",
                    "command_signal": "command",
                    "stall_current_a": 2.0,
                    "position_min": -90,
                    "position_max": 90,
                    "position_unit": unit,
                    "code_site": "control.py:12",
                    "cad_revision": "fixture-r1",
                }
            ],
            "packets": [
                {
                    "device_id": "fixture/joint",
                    "timestamp": start + timedelta(seconds=second),
                    "values": {"position": position, "command": command, "current": current},
                    "units": {"position": unit, "command": unit, "current": "A"},
                }
                for second, position in zip(seconds, positions, strict=True)
            ],
        }
    )


@pytest.mark.parametrize(
    ("run", "stalls"),
    [
        (_run(), True),
        (_run(seconds=(0.0, 0.25, 0.5, 0.75)), True),
        (_run(seconds=(0.0, 0.1, 0.2)), False),  # three rows, under half a second
        (_run(seconds=(0.0, 2.0, 4.0)), False),  # every gap over 1.5 s starts over
        (_run(current=1.9), False),
        (_run(positions=(0.0, 0.6, 1.2)), False),  # drifts past the still tolerance
        (_run(positions=(0.0, 0.2, 0.4), unit="m"), False),  # a moving prismatic joint
    ],
)
def test_still_window_matches_runs_analysis(run: RunManifest, stalls: bool) -> None:
    part = run.parts[0]
    assert part.stall_current_a is not None
    tolerance = _STILL_TOLERANCE[part.position_unit or ""]
    rows = _observations(run, part)
    window = still_window(rows, current_bound=part.stall_current_a, tolerance=tolerance)
    assert window == _stall_window(run, part)
    assert bool(window) is stalls


def test_still_window_holds_out_for_the_sustain_span() -> None:
    rows = _observations(_run(), _run().parts[0])  # three rows over two seconds
    assert still_window(rows, current_bound=2.0, tolerance=0.5, min_seconds=2.0) == rows
    assert still_window(rows, current_bound=2.0, tolerance=0.5, min_seconds=2.5) == []


def test_still_window_drops_rows_older_than_its_horizon() -> None:
    rows = [(at(second), 2.4, 0.0, 40.0) for second in (0.0, 0.5, 1.0, 1.5, 2.0)]
    window = still_window(rows, current_bound=2.0, tolerance=0.5, seconds=1.0, min_seconds=1.0)
    assert [row[0] for row in window] == [at(0.0), at(0.5), at(1.0)]
    assert still_window(rows, current_bound=2.0, tolerance=0.5, seconds=0.5, min_seconds=1.0) == []


# ---------------------------------------------------------------------------- needs


def test_unmet_names_missing_channels_relations_and_facts() -> None:
    needs = Needs(
        channels=("current", "commanded_position"),
        relations=("drives", "powers"),
        facts=(fact_need("current", "warn"), fact_need("position", "limit")),
    )
    ctx = context(
        {"servo3.current": series([1.0])},
        envelopes={"current": arm_envelopes()["current"]},
    )
    missing = unmet(needs, ctx)
    assert missing[:2] == ("commanded_position channel", "powers relation")
    assert missing[2].startswith("position.limit (set it in ")
    assert "position_max" in missing[2]
    assert len(missing) == 3
    assert unmet(Needs(), ctx) == ()


def test_a_quantity_on_two_channels_is_no_channel() -> None:
    samples = {"left.current": series([1.0]), "right.current": series([1.0])}
    assert channel_for(samples, "current") is None
    assert channel_for({"servo3.current": ()}, "current") == "servo3.current"
    assert channel_for({"current": ()}, "current") == "current"
    assert unmet(Needs(channels=("current",)), context(samples)) == ("one current channel, not 2",)
    assert unmet(Needs(channels=("current",)), context({})) == ("current channel",)


def test_an_envelope_without_the_slot_is_an_unmet_fact() -> None:
    ctx = context({}, envelopes={"current": envelope_of("current", "A", nominal=(None, 1.0))})
    assert unmet(Needs(facts=(fact_need("current", "nominal"),)), ctx) == ()
    assert unmet(Needs(facts=(fact_need("current", "limit"),)), ctx)[0].startswith(
        "current.limit (set it in "
    )


# ---------------------------------------------------------------------------- blame


def test_blame_order() -> None:
    subjects, site = blame(context({}), PART)
    assert subjects == (PART, BUS, BRAIN)
    assert site == {"entity_id": str(CODE), "source_id": None, "path": CODE_PATH, "line": 13}


def test_blame_walks_every_bus_then_their_brains_and_reads_only_symbol_evidence() -> None:
    bus2, brain2, other_code = uuid.UUID(int=14), uuid.UUID(int=15), uuid.UUID(int=0)
    graph = arm_graph(
        entities=[node(bus2, "second bus", kinds.HARDWARE_BUS)],
        edges=[
            fact(bus2, PART, "drives"),
            fact(brain2, bus2, "hardware_connected_to"),
            # sorts first, but its evidence names no line: skipped for the next code site
            fact(other_code, PART, "commands", "fw/other.ino"),
        ],
    )
    subjects, site = blame(context({}, graph=graph), PART)
    assert subjects == (PART, BUS, bus2, BRAIN, brain2)
    assert site is not None and site["entity_id"] == str(CODE)


def test_no_commands_edge_means_no_code_site() -> None:
    graph = GraphContext(entities=[node(PART, PART_NAME)], edges=[])
    assert blame(context({}, graph=graph), PART) == ((PART,), None)


# ---------------------------------------------------------------------------- shapes and text


def test_cause_reads_and_writes_for() -> None:
    cause = Cause(kind="actuator", for_=("held",), against=("moving",))
    assert cause.model_dump() == {"kind": "actuator", "for": ("held",), "against": ("moving",)}
    assert Cause.model_validate({"kind": "actuator", "for": ["held"]}).for_ == ("held",)
    with pytest.raises(ValidationError):
        Cause.model_validate({"kind": "thermal"})


def test_names_reach_a_headline_redacted_on_one_line() -> None:
    entropic = (string.ascii_letters[:26] + string.digits) * 2  # a long, varied token
    graph = arm_graph(name=f"servo\n3\x1b[2J {entropic} " + "x" * 200)
    label = entity_label(graph, PART)
    assert label.startswith("servo 3 [2J [REDACTED] ")
    assert entropic not in label and "\n" not in label and "\x1b" not in label
    assert len(label) <= MAX_LABEL_CHARS
    assert entity_label(graph, uuid.UUID(int=99)) == "entity 00000000"


@pytest.mark.parametrize(
    ("value", "unit", "text"),
    [
        (2.4, "A", "2.4 A"),
        (2.0, "A", "2.0 A"),
        (2.004, "A", "2.004 A"),  # four digits: the reading is not rounded onto the rating
        (150.0, "deg", "150.0 deg"),
        (150.4, "deg", "150.4 deg"),
        (-150.0, "deg", "-150.0 deg"),
        (0.012, "rad", "0.012 rad"),
        (4e-05, "s", "4e-05 s"),
        (4095.0, None, "4095.0"),
        (123456.0, "count", "1.235e+05 count"),
    ],
)
def test_amounts_carry_their_unit(value: float, unit: str | None, text: str) -> None:
    assert amount(value, unit) == text


# ---------------------------------------------------------------------------- the stall rule here


def _stalled(part: str = "servo3", *, position: bool = True) -> dict[str, tuple[RecentSample, ...]]:
    """Two seconds held at 10 deg against a 40 deg command on 2.4 A (no position channel when
    `position` is false)."""
    samples = {
        f"{part}.commanded_position": series([40.0] * 41),
        f"{part}.current": series([2.4] * 41),
    }
    return {**samples, f"{part}.position": series([10.0] * 41)} if position else samples


def test_unmet_needs_record_missing_signals_and_fire_nothing() -> None:
    rule = TrackingErrorStall()
    no_limits = context(_stalled(), envelopes={})  # the part has no limits anywhere
    (missing,) = unmet(rule.needs, no_limits)
    assert missing.startswith("current.warn (set it in the part's limits (`current_a`")
    assert rule.evaluate(no_limits) == []
    no_current = context({k: v for k, v in _stalled().items() if not k.endswith(".current")})
    assert unmet(rule.needs, no_current) == ("current channel",)
    assert rule.evaluate(no_current) == []
    assert unmet(rule.needs, context(_stalled())) == ()
    assert rule.evaluate(context(_stalled()))


SEVENTEEN: Final = (
    "command_exceeds_limit",
    "command_rate_exceeds_limit",
    "tracking_error_stall",
    "tracking_error_slip",
    "tracking_oscillation",
    "error_flag",
    "body_lag",
    "current_over_rating",
    "temp_trend_to_limit",
    "rail_sag_correlated",
    "controller_reset_under_load",
    "noise_tracks_motor_activity",
    "sensor_frozen",
    "sensor_out_of_range",
    "rate_drift",
    "stream_gap",
    "time_to_limit",
)


def test_the_seventeen_rules_each_declare_needs_a_cell_and_a_severity() -> None:
    assert sorted(rule.rule_id for rule in SIGNAL_RULES) == sorted(SEVENTEEN)
    for rule in SIGNAL_RULES:
        assert isinstance(rule.needs, Needs)
        assert isinstance(rule.matrix_cell, MatrixCell)
        severity = rule.severity({})
        assert isinstance(severity, Severity) and severity is not Severity.INFO


def test_dumb_actuator_names_settling_signal() -> None:
    """No position feedback: the stall is judged on the current settling, the headline names that
    channel, and nothing is ranked."""
    hit = only(TrackingErrorStall().evaluate(context(_stalled("servo5", position=False))))
    assert hit.rule_id == "tracking_error_stall"
    assert "servo5.current" in hit.headline
    assert "no position feedback" in hit.headline
    assert hit.causes == ()
    assert hit.subjects == (PART, BUS, BRAIN)
    assert hit.evidence["settling_signal"] == "servo5.current"
    assert hit.evidence["current_a"] == 2.4
    assert (hit.evidence["bound"], hit.evidence["bounds_source"]) == (2.0, "config")
    assert (hit.evidence["warn"], hit.evidence["warn_source"]) == (1.6, "derived")


# ---------------------------------------------------------------------------- every rule's contract

MOTOR: Final = uuid.UUID(int=7)
LINK: Final = uuid.UUID(int=8)
SENSOR: Final = uuid.UUID(int=9)
SHARER: Final = uuid.UUID(int=10)
ROWS: Final = 201  # ten seconds at 20 Hz
EXTREMES: Final = (1e308, -1e308, 1e200)


def _ramp(start: float, end: float) -> list[float]:
    return [start + (end - start) * n / (ROWS - 1) for n in range(ROWS)]


def _sagging(current: list[float]) -> list[float]:
    """A supply that drops a volt as the current climbs from 0.5 A to 2.6 A."""
    return [7.4 - (value - 0.5) / 2.1 for value in current]


def _busy() -> dict[str, list[float]]:
    """Stalled against a command running past its limit, warming, sagging its rail, raising an
    overload and restarting under load."""
    current = _ramp(0.5, 2.6)
    return {
        "servo3.position": [10.0] * ROWS,
        "servo3.commanded_position": _ramp(100.0, 200.0),
        "servo3.commanded_velocity": [200.0] * ROWS,
        "servo3.current": current,
        "servo3.voltage": _sagging(current),
        "servo3.temperature": _ramp(40.0, 65.0),
        "servo3.overload_flag": [0.0] * (ROWS - 5) + [1.0] * 5,
        "servo3.reset_count": [3.0] * (ROWS - 5) + [4.0] * 5,
    }


def _resting() -> dict[str, list[float]]:
    """At rest at its target while the link it drives keeps moving."""
    return {
        "servo3.position": [40.0] * ROWS,
        "servo3.commanded_position": [40.0] * ROWS,
        "servo3.current": [0.3] * ROWS,
    }


def _ringing() -> dict[str, list[float]]:
    """Ringing about a held setpoint."""
    wave = [math.sin(2 * math.pi * n / 10) for n in range(ROWS)]
    return {
        "servo3.position": [20.0 + 2.0 * value for value in wave],
        "servo3.commanded_position": [20.0] * ROWS,
        "servo3.current": [0.6 + 0.3 * value for value in wave],
    }


SCENARIOS: Final = {"busy": _busy, "resting": _resting, "ringing": _ringing}


def _spoiled(values: list[float], *, flip: bool) -> list[float]:
    """`values` with 1e308, -1e308 and 1e200 in three places; with `flip` the ±1e308 swap, so a
    command and its position sit at opposite ends of the float range."""
    spoiled = list(values)
    for index, extreme in zip((ROWS // 4, ROWS // 2, 3 * ROWS // 4), EXTREMES, strict=True):
        spoiled[index] = -extreme if flip and abs(extreme) == 1e308 else extreme
    return spoiled


def scenario(name: str, *, extreme: bool = False) -> WindowContext:
    """A window that meets every rule's needs: the part's channels from `SCENARIOS[name]`, a link
    it mates with that mounts a motion sensor, a motor and a rail sharer on its bus, code that
    reads it, and every envelope a rule asks for. `extreme` spoils every channel, the peers' too."""

    def stream(channel: str, values: list[float]) -> tuple[RecentSample, ...]:
        flip = channel.rsplit(".", 1)[-1].startswith("commanded")
        return series(_spoiled(values, flip=flip) if extreme else values)

    current = _ramp(0.5, 2.6)
    peers = {
        SENSOR: {"imu.position": _ramp(10.0, 30.0)},
        MOTOR: {"servo4.current": current},
        SHARER: {"servo2.voltage": _sagging(current)},
    }
    graph = arm_graph(
        entities=[
            node(MOTOR, "servo 4 (joint 4)"),
            node(LINK, "forearm link", "cad_part", "mechanical"),
            node(SENSOR, "wrist imu"),
            node(SHARER, "servo 2 (joint 2)"),
        ],
        edges=[
            fact(PART, LINK, "mates_with"),
            fact(LINK, SENSOR, "mounts"),
            fact(CODE, PART, "reads"),
            fact(CODE, MOTOR, "commands"),
            fact(BUS, SHARER, "drives"),
            fact(BUS, MOTOR, "drives"),
        ],
    )
    current_envelope = envelope_of(
        "current", "A", nominal=(None, 1.0), warn=(None, 1.6), limit=(None, 2.0), expected_hz=10.0
    )
    envelopes = {
        **arm_envelopes(),
        "current": current_envelope,
        "velocity": envelope_of("velocity", "deg/s", limit=(None, 90.0)),
    }
    return context(
        {channel: stream(channel, values) for channel, values in SCENARIOS[name]().items()},
        envelopes=envelopes,
        graph=graph,
        peers={peer: {c: stream(c, v) for c, v in chans.items()} for peer, chans in peers.items()},
        now=at(13.0),
        last={"servo3.current": at(10.0)},
    )


def test_readings_drop_values_that_are_not_finite_or_past_the_bound() -> None:
    values = [1.0, math.inf, -math.inf, math.nan, MAX_ABS_VALUE, -2 * MAX_ABS_VALUE, 1e308, 2.0]
    ctx = context(
        {"servo3.current": series(values)}, peers={MOTOR: {"servo4.current": series(values)}}
    )
    assert [s.value for s in readings(ctx, "current")[1]] == [1.0, MAX_ABS_VALUE, 2.0]
    channel, samples = peer_readings(ctx, MOTOR, "current")
    assert channel == "servo4.current"
    assert [s.value for s in samples] == [1.0, MAX_ABS_VALUE, 2.0]
    assert peer_readings(ctx, SHARER, "current") == (None, ())


def _strict(hit: RuleHit) -> None:
    """The hit's evidence and causes are strict JSON, its headline one bounded line."""
    json.dumps(hit.evidence, allow_nan=False)
    json.dumps([cause.model_dump(mode="json") for cause in hit.causes], allow_nan=False)
    assert len(hit.headline) <= 400 and "\n" not in hit.headline


def _starved(rule: SignalRule) -> WindowContext:
    """The busy window less everything `rule` declares it needs."""
    ctx = scenario("busy")
    facts = {need.name.partition(".")[0] for need in rule.needs.facts}
    return replace(
        ctx,
        samples={
            c: s for c, s in ctx.samples.items() if c.rsplit(".", 1)[-1] not in rule.needs.channels
        },
        envelopes={q: e for q, e in ctx.envelopes.items() if q not in facts},
        graph=GraphContext(
            entities=ctx.graph.entities,
            edges=[e for e in ctx.graph.edges if e.relation_type not in rule.needs.relations],
        ),
    )


@pytest.mark.parametrize("rule", SIGNAL_RULES, ids=lambda rule: rule.rule_id)
def test_every_rule_fires_nothing_while_its_needs_are_unmet(rule: SignalRule) -> None:
    assert rule.evaluate(context({}, envelopes={}, graph=GraphContext(entities=[], edges=[]))) == []
    needs = rule.needs
    if needs.channels or needs.relations or needs.facts:
        starved = _starved(rule)
        assert unmet(needs, starved)
        assert rule.evaluate(starved) == []


@pytest.mark.parametrize("name", sorted(SCENARIOS))
@pytest.mark.parametrize("rule", SIGNAL_RULES, ids=lambda rule: rule.rule_id)
def test_every_rule_survives_extreme_readings_with_strict_evidence(
    rule: SignalRule, name: str
) -> None:
    for hit in rule.evaluate(scenario(name, extreme=True)):
        _strict(hit)


def test_ordinary_readings_fire_most_rules_with_strict_evidence() -> None:
    fired: set[str] = set()
    for name in SCENARIOS:
        for rule in SIGNAL_RULES:
            for hit in rule.evaluate(scenario(name)):
                _strict(hit)
                fired.add(hit.rule_id)
    assert fired >= {
        "command_exceeds_limit",
        "command_rate_exceeds_limit",
        "tracking_error_stall",
        "tracking_oscillation",
        "body_lag",
        "error_flag",
        "current_over_rating",
        "rail_sag_correlated",
        "controller_reset_under_load",
        "sensor_frozen",
        "rate_drift",
        "stream_gap",
        "temp_trend_to_limit",
        "time_to_limit",
    }
