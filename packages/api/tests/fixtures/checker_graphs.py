"""Seeded-bug + clean-control graph fixtures for the checker eval (SOLUS-CHK-01, SOLUSDEV-115).

Two populations drive the eval that the ticket's acceptance criteria require:

- **Seeded bugs** — small, realistic linked graphs each carrying ONE cross-domain integration
  fault the corresponding rule must catch (wrong op-amp, sensor-frequency clash, under-rated /
  wrong-voltage supply). ``expected_checker_ids`` names the rule(s) that must fire → catch rate.
- **Clean controls** — well-matched graphs, plus deliberately UNDER-SPECIFIED and UNRELATED
  graphs, that must produce ZERO warnings → false-positive rate. The incomplete-graph control
  guards the core invariant: an incomplete graph is skipped, never guessed at.
"""

from dataclasses import dataclass
from uuid import uuid4

from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers import attributes as av
from solus_api.checkers.core import OpAmpMismatchChecker, PowerCompatibilityChecker
from solus_api.checkers.core import SensorFrequencyConflictChecker as _Sensor

_OP_AMP = OpAmpMismatchChecker.checker_id
_SENSOR = _Sensor.checker_id
_POWER = PowerCompatibilityChecker.checker_id


@dataclass(frozen=True)
class CheckerCase:
    """One eval graph. ``expected_checker_ids`` is empty for a clean control."""

    name: str
    graph: GraphContext
    expected_checker_ids: frozenset[str]


def _entity(name: str, domain: str, attrs: dict[str, object]) -> EntityRead:
    return EntityRead(id=uuid4(), kind="component", domain=domain, name=name, attrs=attrs)


def _edge(src: EntityRead, dst: EntityRead, relation_type: str) -> EdgeRead:
    return EdgeRead(
        src_id=src.id,
        dst_id=dst.id,
        relation_type=relation_type,
        domain_pair=f"{src.domain}<->{dst.domain}",
        confidence=1.0,
    )


# ------------------------------------------------------------------------- seeded bugs


def _wrong_op_amp() -> CheckerCase:
    """A jellybean LM358 (1 MHz, ~40 mA) put where a fast, high-current driver is needed."""
    op_amp = _entity(
        "U1 (LM358)",
        "electrical",
        {
            av.PART_CLASS: av.OP_AMP,
            av.GBW_HZ: 1_000_000,
            av.OUTPUT_CURRENT_MAX_A: 0.04,
            av.SUPPLY_V_MIN: 3.0,
            av.SUPPLY_V_MAX: 32.0,
        },
    )
    stage = _entity(
        "motor_current_driver",
        "electrical",
        {
            av.PART_CLASS: av.LOAD,
            av.REQUIRED_GBW_HZ: 10_000_000,
            av.REQUIRED_OUTPUT_CURRENT_A: 0.25,
            av.REQUIRED_SUPPLY_V: 24.0,
        },
    )
    graph = GraphContext(entities=[op_amp, stage], edges=[_edge(op_amp, stage, av.DRIVES)])
    return CheckerCase("wrong_op_amp", graph, frozenset({_OP_AMP}))


def _sensor_frequency_clash() -> CheckerCase:
    """A 1 kHz IMU on a 400 Hz I2C bus, polled by a 50 Hz control loop below its Nyquist floor."""
    imu = _entity(
        "imu (ICM-20948)",
        "electrical",
        {
            av.PART_CLASS: av.SENSOR,
            av.SAMPLE_RATE_HZ: 1_000.0,
            av.MIN_SAMPLE_RATE_HZ: 100.0,
            av.BUS_MAX_HZ: 400.0,
        },
    )
    loop = _entity("control_loop.cpp", "code", {av.LOOP_RATE_HZ: 50.0})
    graph = GraphContext(entities=[imu, loop], edges=[_edge(loop, imu, av.READS_FROM)])
    return CheckerCase("sensor_frequency_clash", graph, frozenset({_SENSOR}))


def _under_rated_supply() -> CheckerCase:
    """A 5 V / 2 A regulator feeding a compute module + radio that together pull 4.5 A."""
    supply = _entity(
        "buck_5v (2A)",
        "electrical",
        {av.PART_CLASS: av.SUPPLY, av.VOLTAGE_NOMINAL_V: 5.0, av.CURRENT_MAX_A: 2.0},
    )
    compute = _entity(
        "jetson_rail",
        "electrical",
        {av.PART_CLASS: av.LOAD, av.VOLTAGE_REQUIRED_V: 5.0, av.CURRENT_DRAW_A: 3.0},
    )
    radio = _entity(
        "radio",
        "electrical",
        {av.PART_CLASS: av.LOAD, av.VOLTAGE_REQUIRED_V: 5.0, av.CURRENT_DRAW_A: 1.5},
    )
    graph = GraphContext(
        entities=[supply, compute, radio],
        edges=[_edge(supply, compute, av.POWERS), _edge(supply, radio, av.POWERS)],
    )
    return CheckerCase("under_rated_supply", graph, frozenset({_POWER}))


def _wrong_supply_voltage() -> CheckerCase:
    """A 3.3 V rail wired to a 12 V motor — a voltage mismatch the power rule must flag."""
    supply = _entity(
        "ldo_3v3",
        "electrical",
        {av.PART_CLASS: av.SUPPLY, av.VOLTAGE_NOMINAL_V: 3.3, av.CURRENT_MAX_A: 1.0},
    )
    motor = _entity(
        "drive_motor",
        "electrical",
        {av.PART_CLASS: av.LOAD, av.VOLTAGE_REQUIRED_V: 12.0, av.CURRENT_DRAW_A: 0.5},
    )
    graph = GraphContext(entities=[supply, motor], edges=[_edge(supply, motor, av.POWERS)])
    return CheckerCase("wrong_supply_voltage", graph, frozenset({_POWER}))


def seeded_bug_cases() -> list[CheckerCase]:
    """Every seeded-bug fixture — the catch-rate population."""
    return [
        _wrong_op_amp(),
        _sensor_frequency_clash(),
        _under_rated_supply(),
        _wrong_supply_voltage(),
    ]


# ------------------------------------------------------------------------ clean controls


def _clean_op_amp() -> CheckerCase:
    op_amp = _entity(
        "U2 (OPA1612)",
        "electrical",
        {
            av.PART_CLASS: av.OP_AMP,
            av.GBW_HZ: 40_000_000,
            av.OUTPUT_CURRENT_MAX_A: 0.03,
            av.SUPPLY_V_MIN: 4.5,
            av.SUPPLY_V_MAX: 36.0,
        },
    )
    load = _entity(
        "audio_buffer",
        "electrical",
        {
            av.PART_CLASS: av.LOAD,
            av.REQUIRED_GBW_HZ: 2_000_000,
            av.REQUIRED_OUTPUT_CURRENT_A: 0.01,
            av.REQUIRED_SUPPLY_V: 12.0,
        },
    )
    graph = GraphContext(entities=[op_amp, load], edges=[_edge(op_amp, load, av.DRIVES)])
    return CheckerCase("clean_op_amp", graph, frozenset())


def _clean_sensor() -> CheckerCase:
    sensor = _entity(
        "encoder",
        "electrical",
        {
            av.PART_CLASS: av.SENSOR,
            av.SAMPLE_RATE_HZ: 200.0,
            av.MIN_SAMPLE_RATE_HZ: 100.0,
            av.BUS_MAX_HZ: 1_000.0,
        },
    )
    loop = _entity("odom.py", "code", {av.LOOP_RATE_HZ: 150.0})
    graph = GraphContext(entities=[sensor, loop], edges=[_edge(loop, sensor, av.READS_FROM)])
    return CheckerCase("clean_sensor", graph, frozenset())


def _clean_supply() -> CheckerCase:
    supply = _entity(
        "buck_5v (5A)",
        "electrical",
        {av.PART_CLASS: av.SUPPLY, av.VOLTAGE_NOMINAL_V: 5.0, av.CURRENT_MAX_A: 5.0},
    )
    mcu = _entity(
        "mcu",
        "electrical",
        {av.PART_CLASS: av.LOAD, av.VOLTAGE_REQUIRED_V: 5.0, av.CURRENT_DRAW_A: 1.0},
    )
    radio = _entity(
        "radio",
        "electrical",
        {av.PART_CLASS: av.LOAD, av.VOLTAGE_REQUIRED_V: 5.0, av.CURRENT_DRAW_A: 1.2},
    )
    graph = GraphContext(
        entities=[supply, mcu, radio],
        edges=[_edge(supply, mcu, av.POWERS), _edge(supply, radio, av.POWERS)],
    )
    return CheckerCase("clean_supply", graph, frozenset())


def _incomplete_graph() -> CheckerCase:
    """Real cross-domain edges but NONE of the attributes the rules need → must be SKIPPED."""
    op_amp = _entity("U3", "electrical", {av.PART_CLASS: av.OP_AMP})
    load = _entity("stage", "electrical", {av.PART_CLASS: av.LOAD})
    sensor = _entity("lidar", "electrical", {av.PART_CLASS: av.SENSOR})
    code = _entity("nav.cpp", "code", {})
    supply = _entity("rail", "electrical", {av.PART_CLASS: av.SUPPLY})
    graph = GraphContext(
        entities=[op_amp, load, sensor, code, supply],
        edges=[
            _edge(op_amp, load, av.DRIVES),
            _edge(code, sensor, av.READS_FROM),
            _edge(supply, load, av.POWERS),
        ],
    )
    return CheckerCase("incomplete_graph", graph, frozenset())


def _unrelated_graph() -> CheckerCase:
    """Fully-specified parts but only a generic ``connected_to`` edge — no rule applies."""
    a = _entity("test_point", "electrical", {av.GBW_HZ: 1.0, av.VOLTAGE_NOMINAL_V: 3.3})
    b = _entity("header", "electrical", {av.CURRENT_MAX_A: 1.0})
    graph = GraphContext(entities=[a, b], edges=[_edge(a, b, av.CONNECTED_TO)])
    return CheckerCase("unrelated_graph", graph, frozenset())


def _malicious_attrs() -> CheckerCase:
    """Attacker-influenceable connector data (CLAUDE.md §7): non-finite and negative values on
    real cross-domain edges. The hardened extractors must drop them so NO warning is fabricated."""
    op_amp = _entity(
        "U9",
        "electrical",
        {
            av.PART_CLASS: av.OP_AMP,
            av.OUTPUT_CURRENT_MAX_A: 0.5,
            av.SUPPLY_V_MIN: 32.0,
            av.SUPPLY_V_MAX: 3.0,
        },
    )
    load = _entity(
        "stage",
        "electrical",
        {av.REQUIRED_OUTPUT_CURRENT_A: "nan", av.REQUIRED_SUPPLY_V: 12.0},
    )
    supply = _entity(
        "rail",
        "electrical",
        {
            av.PART_CLASS: av.SUPPLY,
            av.VOLTAGE_NOMINAL_V: 5.0,
            av.VOLTAGE_TOLERANCE_PCT: -5.0,
            av.CURRENT_MAX_A: 2.0,
        },
    )
    mcu = _entity("mcu", "electrical", {av.VOLTAGE_REQUIRED_V: 5.0, av.CURRENT_DRAW_A: -3.0})
    graph = GraphContext(
        entities=[op_amp, load, supply, mcu],
        edges=[_edge(op_amp, load, av.DRIVES), _edge(supply, mcu, av.POWERS)],
    )
    return CheckerCase("malicious_attrs", graph, frozenset())


def clean_cases() -> list[CheckerCase]:
    """Every clean-control fixture — the false-positive population."""
    return [
        _clean_op_amp(),
        _clean_sensor(),
        _clean_supply(),
        _incomplete_graph(),
        _unrelated_graph(),
        _malicious_attrs(),
    ]
