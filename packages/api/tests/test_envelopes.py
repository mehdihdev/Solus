"""SOLUSDEV-321 P2-T1 — envelopes: the bounds one quantity of one part runs inside, and where each
came from (`livebench/findings/envelopes.py`).

The builder is handed every input and reads nothing, so its tests walk the source order and the
key-to-bound table with inputs built in place. The loader reads the same inputs from the real
database — the fake arm's limits, a definition, a scene joint, an expected value — and only ever
from the project it was asked about. The cache is driven over the shared store's own backends.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fixtures.fake_arm import LIMITS, seed_fake_arm
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.graph import kinds
from solus_api.graph.graph_changed_fanout import GraphChangedFanout, graph_changed_callbacks
from solus_api.graph.live import LiveHub
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import PartConfig, PartLimits, TelemetryChannel
from solus_api.hardware.library import PartLimitsSpec
from solus_api.livebench.findings.envelopes import (
    QUANTITIES,
    Bound,
    Envelope,
    EnvelopeCache,
    EnvelopeKey,
    build_envelope,
    envelope_line,
    load_envelope_inputs,
    part_envelopes,
)
from solus_api.livebench.runs.models import PartEvidence, RunManifest
from solus_api.livebench.scene.part_bindings import JointRange
from solus_api.models import Domain, GraphEntity
from solus_api.orchestration.config import EnvelopesConfig
from solus_api.simulation.sim_capability import SimResult
from solus_api.simulation.sim_facts import record_sim_result
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_solus_layer import _project

Maker = async_sessionmaker[AsyncSession]
_CONFIG = EnvelopesConfig()
_PROJECT = uuid.uuid4()
_PART = uuid.uuid4()
_CHANNELS = (("j.position", "rad"), ("j.current", "A"))
_T0 = datetime(2026, 10, 1, tzinfo=UTC)
_LOGGER = "solus.livebench.findings.envelopes"


def _maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


def _config(
    limits: dict[str, float] | None = None, *channels: tuple[str, str | None]
) -> PartConfig:
    return PartConfig(
        limits=None if limits is None else PartLimits(values=limits),
        telemetry=[TelemetryChannel(name=name, unit=unit) for name, unit in channels],
    )


async def _build(db: AsyncSession, quantity: str, **over: Any) -> Envelope | None:
    inputs: dict[str, Any] = {
        "config": None,
        "definition": None,
        "scene_joint": None,
        "expected": None,
        "baseline_run": None,
        "envelopes": _CONFIG,
        **over,
    }
    return await build_envelope(db, _PROJECT, _PART, quantity, **inputs)


async def _built(db: AsyncSession, quantity: str, **over: Any) -> Envelope:
    envelope = await _build(db, quantity, **over)
    assert envelope is not None, f"no {quantity} envelope for {over}"
    return envelope


def _band(bound: Bound | None) -> tuple[float | None, float | None]:
    assert bound is not None
    return bound.lo, bound.hi


def _baseline(
    signal: str,
    values: Sequence[float],
    *,
    unit: str | None = "A",
    device: str = "dev/1",
    part: uuid.UUID = _PART,
    step: float = 1.0,
) -> RunManifest:
    """A run that captured `signal` of one part: one packet per value, `step` seconds apart."""
    return RunManifest(
        robot_id=uuid.uuid4(),
        started_at=_T0,
        parts=[PartEvidence(entity_id=part, name="joint", device_id=device)],
        packets=[
            TelemetryPacket(
                device_id=device,
                timestamp=_T0 + timedelta(seconds=index * step),
                values={signal: value},
                units={signal: unit} if unit else {},
            )
            for index, value in enumerate(values)
        ],
    )


def _scene(project_id: uuid.UUID, part: uuid.UUID, span: float) -> GraphEntity:
    joint = {"name": "j3", "type": "revolute", "lower": -span, "upper": span}
    return GraphEntity(
        project_id=project_id,
        kind=kinds.BENCH_SCENE_MODEL,
        domain=Domain.SIMULATION,
        origin="manual",
        name="scene",
        attrs={
            "model": {"joints": [joint]},
            "bindings": [{"joint": "j3", "part_entity_id": str(part)}],
        },
    )


def _range(lower: float, upper: float, unit: str = "rad") -> JointRange:
    """The scene joint bound to the part, as `scene_joint_for_part` answers it."""
    return JointRange(uuid.uuid4(), "j", lower, upper, unit)


def _envelope(part: uuid.UUID = _PART, quantity: str = "current") -> Envelope:
    return Envelope(
        part_id=part,
        quantity=quantity,
        unit="A",
        nominal=Bound(hi=1.0),
        warn=Bound(hi=1.6),
        limit=Bound(hi=2.0),
        bounds_source={"nominal": "config", "warn": "derived", "limit": "config"},
        confidence=1.0,
    )


def _envelope_key(
    project: uuid.UUID = _PROJECT, part: uuid.UUID = _PART, **over: Any
) -> EnvelopeKey:
    fields: dict[str, Any] = {
        "project_id": project,
        "part_id": part,
        "quantity": "current",
        "config_version": 3,
        "definition_id": "odrive-s1",
        "baseline_run_id": None,
        **over,
    }
    return EnvelopeKey(**fields)


# ------------------------------------------------------------------ the builder


async def test_source_order_config_definition_scene_expected_baseline(db: AsyncSession) -> None:
    """The first source to state a bound owns it: the part's config, its definition, the scene
    joint, a simulation's expected value, then what a baseline run measured. A source states the
    slots its keys map to — limit keys the `limit`, `current_a` and the expected value and the
    learned percentiles the `nominal` — so each slot's ladder is walked on its own."""
    # position: the `limit` slot — config, then definition, then the scene (all in rad here).
    limit_kw: dict[str, Any] = {
        "config": _config({"position_min": -1.0, "position_max": 1.0}, *_CHANNELS),
        "definition": PartLimitsSpec(position_min=-2.0, position_max=2.0),
        "scene_joint": _range(-3.0, 3.0),
    }
    env = await _built(db, "position", **limit_kw)
    assert (env.limit, env.bounds_source["limit"]) == (Bound(lo=-1.0, hi=1.0), "config")
    assert (env.unit, env.confidence) == ("rad", 1.0)
    limit_kw["config"] = _config(None, *_CHANNELS)
    env = await _built(db, "position", **limit_kw)
    assert (env.limit, env.bounds_source["limit"]) == (Bound(lo=-2.0, hi=2.0), "definition")
    limit_kw["definition"] = None
    env = await _built(db, "position", **limit_kw)
    assert (env.limit, env.bounds_source["limit"]) == (Bound(lo=-3.0, hi=3.0), "scene")
    assert _band(env.warn) == pytest.approx((-2.4, 2.4))

    # current: the `nominal` slot — config, definition, the expected value, the baseline.
    nominal_kw: dict[str, Any] = {
        "config": _config({"current_a": 1.0}, *_CHANNELS),
        "definition": PartLimitsSpec(current_a=0.9),
        "expected": {"current": {"value": 0.7, "unit": "A", "sim_result_id": str(uuid.uuid4())}},
        "baseline_run": _baseline("j.current", [float(n) for n in range(101)]),
    }
    env = await _built(db, "current", **nominal_kw)
    assert (env.nominal, env.bounds_source["nominal"]) == (Bound(hi=1.0), "config")
    nominal_kw["config"] = _config(None, *_CHANNELS)
    env = await _built(db, "current", **nominal_kw)
    assert (env.nominal, env.bounds_source["nominal"]) == (Bound(hi=0.9), "definition")
    nominal_kw["definition"] = None
    env = await _built(db, "current", **nominal_kw)
    assert (env.nominal, env.bounds_source["nominal"]) == (Bound(lo=0.7, hi=0.7), "sim")
    assert env.confidence == 0.8
    nominal_kw["expected"] = None
    env = await _built(db, "current", **nominal_kw)
    assert (env.nominal, env.bounds_source["nominal"]) == (Bound(lo=1.0, hi=99.0), "learned")
    assert env.confidence == 0.6


async def test_key_to_bound_mapping_and_derived_warn(engine: AsyncEngine) -> None:
    """The fake arm's limits, through the loader and the builder: `current_a` is the nominal top,
    the stall current, temperature, the voltage pair and the position pair are limits, and warn
    is 0.8 of the limit — of the half-range from the midpoint when it has two sides."""
    maker = _maker(engine)
    project_id = await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, project_id, user_id=None)
        await db.commit()
        found = await part_envelopes(db, project_id, [arm.parts[2]], envelopes=_CONFIG)
    by_quantity = {envelope.quantity: envelope for envelope in found[arm.parts[2]]}

    # the fake arm states no velocity or torque limit and has no such channel: nothing is invented
    assert list(by_quantity) == ["current", "temperature", "voltage", "position"]
    current = by_quantity["current"]
    assert (current.unit, current.confidence) == ("A", 1.0)
    assert current.nominal == Bound(hi=LIMITS["current_a"])
    assert current.limit == Bound(hi=LIMITS["stall_current_a"])
    assert _band(current.warn) == pytest.approx((None, 1.6))
    assert current.bounds_source == {"nominal": "config", "warn": "derived", "limit": "config"}
    temperature = by_quantity["temperature"]
    assert temperature.unit == "degC" and temperature.nominal is None
    assert temperature.limit == Bound(hi=70)
    assert _band(temperature.warn) == pytest.approx((None, 56.0))
    voltage = by_quantity["voltage"]
    assert (voltage.unit, voltage.limit) == ("V", Bound(lo=6.0, hi=8.4))
    assert _band(voltage.warn) == pytest.approx((6.24, 8.16))
    position = by_quantity["position"]
    assert position.unit == "deg"  # the channel's: the limit keys state none
    assert position.limit == Bound(lo=-150, hi=150)
    assert _band(position.warn) == pytest.approx((-120.0, 120.0))
    assert envelope_line(current) == (
        "current A: nominal <= 1, warn <= 1.6, limit <= 2 "
        "(sources: nominal=config, warn=derived, limit=config)"
    )
    assert envelope_line(voltage) == (
        "voltage V: warn 6.24 to 8.16, limit 6 to 8.4 (sources: warn=derived, limit=config)"
    )


#: limit key -> (quantity, slot, side, the unit the key states)
_KEY_TABLE = (
    ("current_a", "current", "nominal", "hi", "A"),
    ("stall_current_a", "current", "limit", "hi", "A"),
    ("temp_c", "temperature", "limit", "hi", "degC"),
    ("voltage_min_v", "voltage", "limit", "lo", "V"),
    ("voltage_max_v", "voltage", "limit", "hi", "V"),
    ("torque_nm", "torque", "limit", "hi", "N·m"),
    ("position_min", "position", "limit", "lo", None),
    ("position_max", "position", "limit", "hi", None),
    ("velocity_max", "velocity", "limit", "hi", None),
)


async def test_every_limit_key_lands_in_its_slot_and_unit(db: AsyncSession) -> None:
    """The nine `PartLimitsSpec` names, from the part's config and from its definition alike: each
    states one edge of one slot of ONE quantity, in the unit its name carries (none for the
    position and velocity keys, which take the channel's) — and no other quantity hears of it."""
    # a tenth limit on the spec must be given a slot here, not silently left unread
    assert {row[0] for row in _KEY_TABLE} == set(PartLimitsSpec.model_fields)
    for key, quantity, slot, side, unit in _KEY_TABLE:
        for source, inputs in (
            ("config", {"config": _config({key: 5.0})}),
            ("definition", {"definition": PartLimitsSpec(**{key: 5.0})}),
        ):
            envelope = await _built(db, quantity, **inputs)
            band = getattr(envelope, slot)
            assert (band.lo, band.hi) == ((5.0, None) if side == "lo" else (None, 5.0)), key
            assert envelope.bounds_source[slot] == source and envelope.unit == unit, key
            others = [q for q in QUANTITIES if q != quantity]
            assert [await _build(db, q, **inputs) for q in others] == [None] * len(others), key
    # the channel's unit rides on keys that state none
    with_channel = _config({"velocity_max": 90.0}, ("j.velocity", "deg/s"))
    assert (await _built(db, "velocity", config=with_channel)).unit == "deg/s"


async def test_warn_needs_a_span_and_follows_the_configured_fraction(db: AsyncSession) -> None:
    """A lone lower limit, or an upper one at or below zero, has nothing to take a fraction of:
    no warn, never a made-up one. The fraction is models.yaml's, not the code's."""
    low_only = await _built(db, "voltage", config=_config({"voltage_min_v": 6.0}))
    assert (low_only.limit, low_only.warn) == (Bound(lo=6.0), None)
    assert "warn" not in low_only.bounds_source
    negative = await _built(db, "position", config=_config({"position_max": -10.0}))
    assert (negative.limit, negative.warn) == (Bound(hi=-10.0), None)
    half = await _built(
        db,
        "current",
        config=_config({"stall_current_a": 2.0}),
        envelopes=EnvelopesConfig(warn_fraction=0.5),
    )
    assert half.warn == Bound(hi=1.0)


async def test_unit_suffixed_position_keys(db: AsyncSession) -> None:
    """`position_min_<unit>` / `position_max_<unit>` are read in the position channel's unit; with
    no channel, in the one unit the keys state. A unit the channel does not use is no limit."""
    both = {
        "position_min_deg": -90.0,
        "position_max_deg": 90.0,
        "position_min_rad": -1.5,
        "position_max_rad": 1.5,
    }
    deg = await _built(db, "position", config=_config(both, ("j.position", "deg")))
    assert (deg.limit, deg.unit) == (Bound(lo=-90.0, hi=90.0), "deg")
    rad = await _built(db, "position", config=_config(both, ("j.position", "rad")))
    assert (rad.limit, rad.unit) == (Bound(lo=-1.5, hi=1.5), "rad")

    only_deg = {"position_min_deg": -90.0, "position_max_deg": 90.0}
    no_channel = await _built(db, "position", config=_config(only_deg))
    assert (no_channel.limit, no_channel.unit) == (Bound(lo=-90.0, hi=90.0), "deg")
    # two units and no channel to choose by: which one is meant is not known
    assert await _build(db, "position", config=_config(both)) is None
    # a key in another unit than the channel's is skipped, not converted
    assert await _build(db, "position", config=_config(only_deg, ("j.position", "rad"))) is None
    # the explicit unit beats the bare key of the same side
    mixed = {"position_min": -10.0, "position_max": 10.0, **only_deg}
    explicit = await _built(db, "position", config=_config(mixed, ("j.position", "deg")))
    assert explicit.limit == Bound(lo=-90.0, hi=90.0)


async def test_a_source_in_another_unit_is_skipped_not_mixed(
    db: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """No unit conversion happens here, so a source that states a unit other than the envelope's
    is left out — with a log line saying so — and a source in the right unit still serves."""
    config = _config({"stall_current_a": 2.0}, ("j.current", "mA"))
    expected = {"current": {"value": 700.0, "unit": "mA"}}
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        assert await _build(db, "current", config=config) is None
        served = await _built(db, "current", config=config, expected=expected)
    assert served.unit == "mA" and served.bounds_source == {"nominal": "sim"}
    assert any(
        "unit" in record.getMessage() and str(_PROJECT) in record.getMessage()
        for record in caplog.records
    )
    # with no channel to say, the highest source's own unit is the envelope's
    scene_only = await _built(db, "position", scene_joint=_range(0.0, 0.3, "m"))
    assert (scene_only.unit, scene_only.limit) == ("m", Bound(lo=0.0, hi=0.3))
    # a source that states no unit is read in the channel's; with no channel it is read in
    # nothing, and the scene (rad) is not laid over it — nor mentioned: it would have owned
    # nothing the config does not
    caplog.clear()
    unitless = _config({"position_min": -150.0, "position_max": 150.0})
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        bare = await _built(db, "position", config=unitless, scene_joint=_range(-2.5, 2.5))
    assert (bare.unit, bare.limit) == (None, Bound(lo=-150.0, hi=150.0))
    assert bare.bounds_source["limit"] == "config"
    assert not [record for record in caplog.records if record.name == _LOGGER]


async def test_learned_p1_p99_confidence_0_6(db: AsyncSession) -> None:
    """A baseline run's own samples of the part's channel give p1 / p99 as the nominal band, at
    confidence 0.6, and the rate it streamed at. Too few samples, a stranger's packets, an
    ambiguous channel or mixed units give nothing."""
    config = _config(None, *_CHANNELS)
    run = _baseline("j.current", [float(n) for n in range(101)], step=0.5)
    env = await _built(db, "current", config=config, baseline_run=run)
    assert env.nominal == Bound(lo=1.0, hi=99.0)
    assert env.limit is None and env.warn is None
    assert (env.unit, env.confidence) == ("A", 0.6)
    assert env.expected_hz == pytest.approx(2.0)
    assert env.bounds_source == {"nominal": "learned", "expected_hz": "learned"}
    assert envelope_line(env) == (
        "current A: nominal 1 to 99, rate 2 Hz (sources: nominal=learned, expected_hz=learned)"
    )

    few = _baseline("j.current", [1.0] * 5)
    assert await _build(db, "current", config=config, baseline_run=few) is None
    stranger = _baseline("j.current", [float(n) for n in range(101)], part=uuid.uuid4())
    assert await _build(db, "current", config=config, baseline_run=stranger) is None
    wrong_signal = _baseline("j.temperature", [float(n) for n in range(101)])
    assert await _build(db, "current", config=config, baseline_run=wrong_signal) is None
    twice = _config(None, ("j.current", "A"), ("aux.current", "A"))
    assert await _build(db, "current", config=twice, baseline_run=run) is None
    assert await _build(db, "current", config=None, baseline_run=run) is None
    mixed = run.model_copy(deep=True)
    mixed.packets = [
        packet.model_copy(update={"units": {"j.current": "mA" if index % 2 else "A"}})
        for index, packet in enumerate(run.packets)
    ]
    assert await _build(db, "current", config=config, baseline_run=mixed) is None


async def test_no_source_returns_none(db: AsyncSession) -> None:
    """Empty beats invented: nothing stated anywhere is no envelope, whatever the part has."""
    for quantity in QUANTITIES:
        assert await _build(db, quantity) is None
        assert await _build(db, quantity, config=_config(None, *_CHANNELS)) is None
    stated = {"nothing_we_read": 5.0, "velocity_max": 100.0}
    assert await _build(db, "current", config=_config(stated, *_CHANNELS)) is None
    # a stated value that is not a finite number is not stated
    junk = PartLimits.model_construct(
        values={"current_a": float("nan"), "temp_c": True, "stall_current_a": float("inf")}
    )
    config = PartConfig(limits=junk)
    assert await _build(db, "current", config=config) is None
    assert await _build(db, "temperature", config=config) is None
    # a reversed pair is a mistake, not a band
    reversed_pair = _config({"position_min": 5.0, "position_max": -5.0})
    assert await _build(db, "position", config=reversed_pair) is None
    # a reversed scene range is a mistake too — and a range feeds the position only
    assert await _build(db, "position", scene_joint=_range(2.0, -2.0)) is None
    assert await _build(db, "velocity", scene_joint=_range(-1.0, 1.0)) is None
    # a malformed expected value
    assert await _build(db, "current", expected={}) is None
    assert await _build(db, "current", expected={"current": {"value": "high"}}) is None
    assert await _build(db, "current", expected={"current": 0.7}) is None
    assert await _build(db, "current", expected={"current": {"value": float("nan")}}) is None


# ------------------------------------------------------------------ the loader


async def test_loader_reads_each_source_inside_the_project(engine: AsyncEngine) -> None:
    """A part's config and its version, its library definition, the scene joint bound to it and
    its expected value — and nothing for an id the project does not hold as a live part: another
    project's part, the robot, a stranger."""
    maker = _maker(engine)
    mine, theirs = await _project(maker), await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, mine, user_id=None)
        other = await seed_fake_arm(db, theirs, user_id=None)
        servo = await db.get(GraphEntity, arm.parts[2])
        assert servo is not None
        expected = {"current": {"value": 0.7, "unit": "A", "sim_result_id": str(uuid.uuid4())}}
        servo.attrs = {**servo.attrs, "definition_id": "odrive-s1", "expected": expected}
        db.add(_scene(mine, servo.id, 2.5))
        await db.commit()
        asked = [servo.id, arm.parts[0], arm.robot, other.parts[0], uuid.uuid4()]
        loaded = await load_envelope_inputs(db, mine, asked)
        found = await part_envelopes(db, mine, [servo.id], envelopes=_CONFIG)

    assert set(loaded) == {servo.id, arm.parts[0]}
    inputs = loaded[servo.id]
    assert inputs.config is not None and inputs.config.limits is not None
    assert inputs.config.limits.values == LIMITS and inputs.config_version == 1
    assert inputs.definition_id == "odrive-s1"
    assert inputs.definition is not None and inputs.definition.voltage_max_v == 50
    assert inputs.scene_joint is not None
    assert (inputs.scene_joint.joint, inputs.scene_joint.lower) == ("j3", -2.5)
    assert (inputs.scene_joint.upper, inputs.scene_joint.unit) == (2.5, "rad")
    assert inputs.expected == expected
    # the inputs, read from the database, settle in source order: the config's degrees own the
    # position limit, and the scene's +-2.5 rad is another unit, so it is left out, not mixed
    position = {one.quantity: one for one in found[servo.id]}["position"]
    assert (position.unit, position.limit) == ("deg", Bound(lo=-150, hi=150))
    assert position.bounds_source["limit"] == "config"
    assert "scene" not in position.bounds_source.values()
    bare = loaded[arm.parts[0]]  # no definition, no scene, no expected value
    assert (bare.definition, bare.definition_id, bare.scene_joint, bare.expected) == (
        None,
        None,
        None,
        None,
    )


async def test_loader_declines_what_it_cannot_settle(engine: AsyncEngine) -> None:
    """A definition id the library does not hold, a deleted part, and two scene joints that
    disagree on the range are no definition, no part and no joint: which is meant is not known."""
    maker = _maker(engine)
    project_id = await _project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, project_id, user_id=None)
        servo = await db.get(GraphEntity, arm.parts[0])
        gone = await db.get(GraphEntity, arm.parts[1])
        assert servo is not None and gone is not None
        servo.attrs = {**servo.attrs, "definition_id": "not-in-the-library"}
        gone.deleted_at = datetime.now(UTC)
        db.add_all([_scene(project_id, servo.id, 1.0), _scene(project_id, servo.id, 2.0)])
        await db.commit()
        loaded = await load_envelope_inputs(db, project_id, [servo.id, gone.id])

    assert set(loaded) == {servo.id}
    inputs = loaded[servo.id]
    assert (inputs.definition, inputs.definition_id, inputs.scene_joint) == (None, None, None)
    assert inputs.config is not None  # the config still serves


async def test_expected_from_sim_result(engine: AsyncEngine) -> None:
    """P4-T5: a simulation's result, recorded the one way there is (`record_sim_result`, which
    writes `attrs.expected`), reaches the part's envelope through the loader. The quantity's
    nominal is the value, `bounds_source` names `sim` and the confidence is 0.8. A quantity the
    run did not compute has no envelope: empty beats invented."""
    maker = _maker(engine)
    project_id = await _project(maker)
    async with maker() as db:
        part = GraphEntity(
            project_id=project_id,
            kind=kinds.PART,
            domain=Domain.MECHANICAL,
            origin="manual",
            name="bracket",
        )
        db.add(part)
        await db.commit()
    result = SimResult.model_validate(
        {
            "values": {
                "stress_mpa": {"value": 234.6, "unit": "MPa"},
                "yield_fraction": {"value": 0.85, "unit": None},
            },
            "provenance": {
                "solver": "deterministic_mech:cantilever_bending",
                "inputs": {
                    "load": {"value": {"force_n": 1173.0, "arm_m": 0.025}, "source": "known"}
                },
                "leaves_out": ["fatigue"],
            },
        }
    )
    sim_id = await record_sim_result(
        maker,
        LiveHub(),
        project_id=project_id,
        subject_id=part.id,
        rung=1,
        result=result,
        created_by=None,
    )

    async with maker() as db:
        inputs = (await load_envelope_inputs(db, project_id, [part.id]))[part.id]
        stress = await _built(db, "stress_mpa", expected=inputs.expected)
        fraction = await _built(db, "yield_fraction", expected=inputs.expected)
        mass = await _build(db, "mass_kg", expected=inputs.expected)

    assert inputs.expected is not None
    assert inputs.expected["stress_mpa"]["sim_result_id"] == str(sim_id)
    assert (stress.nominal, stress.warn, stress.limit) == (Bound(lo=234.6, hi=234.6), None, None)
    assert (stress.unit, stress.bounds_source, stress.confidence) == (
        "MPa",
        {"nominal": "sim"},
        0.8,
    )
    assert (fraction.unit, fraction.bounds_source) == (None, {"nominal": "sim"})
    assert mass is None


# ------------------------------------------------------------------ the cache


class _RecordingStore(InMemoryCacheStore):
    def __init__(self) -> None:
        super().__init__()
        self.ttls: list[int] = []

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self.ttls.append(ttl_seconds)
        await super().set(key, value, ttl_seconds)

    def stored_keys(self) -> list[str]:
        return list(self._values)


class _HungStore(InMemoryCacheStore):
    async def get(self, key: str) -> str | None:
        await asyncio.Event().wait()  # never set
        return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await asyncio.Event().wait()

    async def delete(self, key: str) -> None:
        await asyncio.Event().wait()


class _BrokenStore(InMemoryCacheStore):
    async def get(self, key: str) -> str | None:
        raise ConnectionError("store down")

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        raise ConnectionError("store down")

    async def delete(self, key: str) -> None:
        raise ConnectionError("store down")


async def test_cache_key_and_invalidation(caplog: pytest.LogCaptureFixture) -> None:
    """The key carries every input the config's version, the definition and the baseline change;
    a miss on any is the point. A graph change drops the project's envelopes — and only its —
    through a per-project index, because the store has no scan."""
    store = _RecordingStore()
    cache = EnvelopeCache(store)
    key = _envelope_key()
    assert str(key) == f"solus:envelope:{_PROJECT}:{_PART}:current:3:odrive-s1:-"
    assert str(_envelope_key(config_version=None, definition_id=None)) == (
        f"solus:envelope:{_PROJECT}:{_PART}:current:-:-:-"
    )
    run = uuid.uuid4()
    assert str(_envelope_key(baseline_run_id=run)).endswith(f":3:odrive-s1:{run}")

    assert await cache.get(key) is None
    await cache.put(key, _envelope())
    assert await cache.get(key) == _envelope()
    assert store.ttls[0] == 600
    for changed in (
        _envelope_key(config_version=4),
        _envelope_key(definition_id="blheli32-esc"),
        _envelope_key(baseline_run_id=run),
        _envelope_key(quantity="voltage"),
        _envelope_key(part=uuid.uuid4()),
    ):
        assert await cache.get(changed) is None, changed

    # per-project invalidation, through the registration list the app installs
    foreign = _envelope_key(project=uuid.uuid4())
    await cache.put(foreign, _envelope())
    await cache.put(_envelope_key(quantity="voltage"), _envelope(quantity="voltage"))
    callbacks = graph_changed_callbacks(
        sessionmaker=async_sessionmaker(), enqueue=None, store=store
    )
    # budgets, the project card, the envelopes, the matrix (P3-T3): the drop is the third, by name
    assert len(callbacks) == 4
    dropping = callbacks[2]
    assert getattr(dropping, "__qualname__", None) == "EnvelopeCache.invalidate"
    await GraphChangedFanout([dropping])(_PROJECT)
    assert await cache.get(key) is None
    assert await cache.get(_envelope_key(quantity="voltage")) is None
    assert await cache.get(foreign) == _envelope()
    assert f"solus:envelope:{_PROJECT}:index" not in store.stored_keys()
    await cache.put(key, _envelope())  # the index starts afresh
    assert await cache.get(key) == _envelope()

    # the index holds 256 keys; past that a put is a no-op, logged once
    crowded = EnvelopeCache(_RecordingStore())
    parts = [uuid.uuid4() for _ in range(257)]
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        for part in parts:
            await crowded.put(_envelope_key(part=part), _envelope(part))
        await crowded.put(_envelope_key(part=uuid.uuid4()), _envelope())
    assert await crowded.get(_envelope_key(part=parts[255])) == _envelope(parts[255])
    assert await crowded.get(_envelope_key(part=parts[256])) is None
    assert len([r for r in caplog.records if r.name == _LOGGER]) == 1
    await crowded.invalidate(_PROJECT)
    assert await crowded.get(_envelope_key(part=parts[0])) is None


async def test_a_newer_stamp_replaces_the_older_keys_of_its_pair() -> None:
    """A config bump or a new baseline moves a stamp and publishes no `graph.changed`; the older
    key of that (part, quantity) is never hit again. A put drops it from the index — and from the
    store, so a baseline that comes back cannot resurrect an entry nobody can invalidate — and
    the 256 bound is therefore about distinct pairs, not about how often a config was saved."""
    store = _RecordingStore()
    cache = EnvelopeCache(store)
    first, second = _envelope_key(config_version=3), _envelope_key(config_version=4)
    voltage = _envelope_key(quantity="voltage")
    await cache.put(first, _envelope())
    await cache.put(voltage, _envelope(quantity="voltage"))
    await cache.put(second, _envelope())

    index = json.loads(await store.get(f"solus:envelope:{_PROJECT}:index") or "[]")
    assert sorted(index) == sorted([str(second), str(voltage)])  # ONE entry for the pair
    assert await cache.get(first) is None
    assert await cache.get(second) == _envelope()
    assert await cache.get(voltage) == _envelope(quantity="voltage")
    # the same stamp again is a refresh, not a second entry
    await cache.put(second, _envelope())
    again = json.loads(await store.get(f"solus:envelope:{_PROJECT}:index") or "[]")
    assert sorted(again) == sorted(index)

    # 300 saves of one pair never fill the index; 257 distinct pairs do
    saved = EnvelopeCache(_RecordingStore())
    for version in range(300):
        await saved.put(_envelope_key(config_version=version), _envelope())
    assert await saved.get(_envelope_key(config_version=299)) == _envelope()
    assert await saved.get(_envelope_key(config_version=298)) is None


async def test_cache_never_raises_and_a_bad_entry_is_a_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corrupt JSON, another deploy's shape and a store that hangs are all a miss — the bound is
    the fan-out's own — and a failing store never fails the caller."""
    monkeypatch.setattr("solus_api.graph.graph_changed_fanout.CALLBACK_TIMEOUT_SECONDS", 0.05)
    store = _RecordingStore()
    cache = EnvelopeCache(store)
    key = _envelope_key()
    await store.set(str(key), "{not json", 60)
    assert await cache.get(key) is None
    await store.set(str(key), json.dumps({"part_id": "x"}), 60)
    assert await cache.get(key) is None
    await store.set(f"solus:envelope:{_PROJECT}:index", "[1, 2", 60)
    await cache.put(key, _envelope())  # a corrupt index is replaced, not trusted
    assert await cache.get(key) == _envelope()

    started = asyncio.get_running_loop().time()
    for slow in (EnvelopeCache(_HungStore()), EnvelopeCache(_BrokenStore())):
        assert await slow.get(key) is None
        await slow.put(key, _envelope())
        await slow.invalidate(_PROJECT)
    assert asyncio.get_running_loop().time() - started < 2.0
