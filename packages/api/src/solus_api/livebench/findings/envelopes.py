"""SOLUSDEV-321 P2-T1 — the envelope: what normal, warning and limit look like for one quantity of
one part, and where each bound came from.

P2's rules compare live samples against an `Envelope`, SOL reads one (`get_envelope`, the
`envelope` sections of the findings layer) and the narration packet carries them. It is built from
what a part can have, and from nothing else: no source, no envelope (empty beats invented).

**Sources**, highest first — a slot is owned by the first source that states it:

1. the part's own config limits (`PartConfig.limits.values`: the nine `PartLimitsSpec` names, and
   `position_min_<unit>` / `position_max_<unit>`), source `config`, confidence 1.0
2. the part's library definition (`PartLimitsSpec`), `definition`, 1.0
3. the scene joint the part is bound to (`lower` / `upper`), `scene`, 1.0
4. a simulation's expected value (`attrs.expected[quantity]`, written by P4), `sim`, 0.8
5. what a baseline run measured on the part's channel (p1 / p99), `learned`, 0.6

**Key to slot.** `current_a` is the `nominal` top; `stall_current_a`, `temp_c`,
`voltage_min_v` / `voltage_max_v`, `position_min` / `position_max` (and the unit-suffixed pair),
`velocity_max` and `torque_nm` are the `limit`; an expected value or the learned percentiles are
the `nominal`. `warn` is never stated by a part: it is `envelopes.warn_fraction` of the limit
(models.yaml), `bounds_source["warn"] == "derived"` — of the half-range from the midpoint for a
two-sided limit, and of the upper edge for a one-sided limit above zero. A lone lower limit, or an
upper one at or below zero, has no span to take a fraction of and gets no warn.

A slot comes whole from ONE source (never a lower edge from one and an upper from another), so
`bounds_source` names it honestly; the envelope's `confidence` is the lowest of the sources its
slots came from. The baseline also gives `expected_hz`, the rate it streamed the channel at.

**Units.** The unit is the part's telemetry channel's for the quantity when it has one, else the
unit the highest source states its numbers in (`_a` is A, `_c` degC, `_v` V, `_nm` N·m, a suffixed
position key its suffix, a scene joint rad or m; None when that source states none). A source that
states no unit (`position_min`, `velocity_max`) is read in the channel's, so without one it is
read in nothing and meets only sources that state none. Every unit is first put in its one
canonical spelling (`canonical_unit`: `N.m` and `Nm` are `N·m`, `°C` is `degC`), and that is the
spelling the envelope carries. Nothing is converted here (the rules compare in the envelope's
unit): a source in another unit is left out, and logged when it would have owned a slot — at
WARNING for a config or definition limit, which somebody stated. A unit reaches the prompt, so
it is one short printable line (`_short_line`) or it states nothing: a source whose unit is not
one is unstated (`_stating`, one DEBUG line, never the unit), a channel whose unit is not has none.

The builder reads nothing (it is pure); `load_envelope_inputs` reads each part's inputs from the
database, for one project only; `EnvelopeCache` keeps what was built.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import statistics
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select

from solus_api.connectors.httpcache import within_bound
from solus_api.core.errors import APIError
from solus_api.hardware.config import EntityHardwareConfig, PartConfig, TelemetryChannel
from solus_api.hardware.library import DefinitionError, PartDefinition, PartLimitsSpec, load_library
from solus_api.hardware.store import PART_KINDS, config_of, configuration_entries
from solus_api.livebench.scene.part_bindings import (
    JointRange,
    bound_scenes,
    channel_for_quantity,
    finite_number,
    scene_joint_for_part,
)
from solus_api.models import GraphEntity

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from solus_api.connectors.httpcache import CacheStore
    from solus_api.livebench.runs.models import RunManifest
    from solus_api.models import SolusEntry
    from solus_api.orchestration.config import EnvelopesConfig

logger = logging.getLogger("solus.livebench.findings.envelopes")

type BoundSource = Literal["config", "definition", "scene", "sim", "learned"]

#: The quantities an envelope describes: the stems of the limit keys and of the telemetry channel
#: names (`<role>.<quantity>`), in the order the context shows them.
QUANTITIES: Final = ("current", "temperature", "voltage", "position", "velocity", "torque")
#: The bounds an envelope carries, in the order they are told.
_SLOTS: Final = ("nominal", "warn", "limit")
_CONFIDENCE: Final[dict[BoundSource, float]] = {
    "config": 1.0,
    "definition": 1.0,
    "scene": 1.0,
    "sim": 0.8,
    "learned": 0.6,
}
#: limit key -> (quantity, slot, side, the unit the key itself states)
_KEYS: Final[dict[str, tuple[str, str, str, str | None]]] = {
    "current_a": ("current", "nominal", "hi", "A"),
    "stall_current_a": ("current", "limit", "hi", "A"),
    "temp_c": ("temperature", "limit", "hi", "degC"),
    "voltage_min_v": ("voltage", "limit", "lo", "V"),
    "voltage_max_v": ("voltage", "limit", "hi", "V"),
    "torque_nm": ("torque", "limit", "hi", "N·m"),
    "position_min": ("position", "limit", "lo", None),
    "position_max": ("position", "limit", "hi", None),
    "velocity_max": ("velocity", "limit", "hi", None),
}
#: A unit is one short line: the channel field's own bound (`TelemetryChannel.unit`).
MAX_UNIT_CHARS: Final = 32
_POSITION_KEY: Final = re.compile(rf"position_(?P<side>min|max)_(?P<unit>\S{{1,{MAX_UNIT_CHARS}}})")
#: canonical unit -> its other spellings. Compared whitespace-stripped and case-insensitively; the
#: canonical spelling is the one an envelope carries. Extend it when the library-seed sweep
#: (`tests/test_envelope_units.py`) names a spelling it does not know.
_SPELLINGS: Final = {
    "N·m": ("n.m", "n*m", "nm", "n-m"),
    "degC": ("°c", "c", "celsius"),
    "deg": ("°", "degree", "degrees"),
    "rad": ("radian", "radians"),
    "rev": ("revolution", "revolutions"),
    "count": ("counts",),
    "A": ("amp", "amps"),
    "V": ("volt", "volts"),
    "m": ("meter", "metre", "meters", "metres"),
    "deg/s": ("°/s", "degree/s", "degrees/s", "deg/sec"),
    "rad/s": ("radian/s", "radians/s", "rad/sec"),
    "rev/s": ("revolution/s", "revolutions/s", "rev/sec"),
    "m/s": ("meter/s", "metre/s", "meters/s", "metres/s", "m/sec"),
}
CANONICAL_UNITS: Final = frozenset(_SPELLINGS)
_BY_SPELLING: Final = {
    spelling.casefold(): unit
    for unit, spellings in _SPELLINGS.items()
    for spelling in (unit, *spellings)
}
#: The sources whose limits somebody stated: one left out for its unit is a warning, not a note.
_STATED_LIMITS: Final = ("config", "definition")
#: A baseline needs this many samples of a channel before its percentiles say anything.
MIN_LEARNED_SAMPLES: Final = 20
ENVELOPE_TTL_SECONDS: Final = 600
#: Keys one project's index lists; past it a `put` is a no-op (the store has no scan to fall
#: back on).
MAX_INDEXED_KEYS: Final = 256


class Bound(BaseModel):
    """The two edges of a band; an edge nobody stated is None."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lo: float | None = None
    hi: float | None = None


class Envelope(BaseModel):
    """What normal, warning and limit look like for `quantity` of one part, in `unit`.

    `bounds_source` maps each present bound (`nominal`, `warn`, `limit`) to where it came from
    (`config`, `definition`, `scene`, `sim`, `learned`, or `derived` for `warn`), and
    `expected_hz` to `learned` when a baseline gave a rate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    part_id: uuid.UUID
    quantity: str
    unit: str | None = None
    nominal: Bound | None = None
    warn: Bound | None = None
    limit: Bound | None = None
    expected_hz: float | None = None
    bounds_source: dict[str, str]
    confidence: float


@dataclass(frozen=True)
class _Stated:
    """What one source states about the quantity: a band per slot it owns, the unit it states
    them in (None when it says nothing of one), and for a baseline the rate."""

    source: BoundSource
    unit: str | None
    slots: Mapping[str, Bound]
    hz: float | None = None


def _bound(lo: float | None, hi: float | None) -> Bound | None:
    """A band, or None when no edge is stated or the edges are reversed (a mistake, not a band)."""
    if lo is None and hi is None:
        return None
    if lo is not None and hi is not None and lo > hi:
        return None
    return Bound(lo=lo, hi=hi)


def canonical_unit(unit: str | None) -> str | None:
    """`unit` in the one spelling envelopes compare and carry (`N.m` and `Nm` are `N·m`, `°C` is
    `degC`). A unit the table does not know is left as written, trimmed; blank is no unit.
    Equivalence, not conversion: `mA` stays `mA`."""
    text = (unit or "").strip()
    if not text:
        return None
    return _BY_SPELLING.get("".join(text.split()).casefold(), text)


#: canonical (source, target) -> factor: the pairs a sample may be converted across to reach its
#: envelope's unit (a simulated joint's rad against a real part's deg; a driver's mA against a
#: rating in A). The run analysis and the window evaluator share this one table.
_SCALES: Final = {
    ("rad", "deg"): 180 / math.pi,
    ("deg", "rad"): math.pi / 180,
    ("rad/s", "deg/s"): 180 / math.pi,
    ("deg/s", "rad/s"): math.pi / 180,
    ("mA", "A"): 0.001,
    ("A", "mA"): 1000.0,
}


def convert_unit(value: float, source: str | None, target: str | None) -> float | None:
    """`value` in `target`, when `source` is `target` or the table scales between them; None for
    a unit left out, a pair it does not know, or a result that is not finite — never a guess."""
    if source is None or target is None:
        return None
    if source == target:
        return value
    factor = _SCALES.get((source, target))
    if factor is None:
        return None
    converted = value * factor
    return converted if math.isfinite(converted) else None


def _short_line(unit: object) -> bool:
    """Whether `unit` may reach a prompt: one printable string of at most `MAX_UNIT_CHARS`, with
    no control character or newline."""
    return isinstance(unit, str) and len(unit) <= MAX_UNIT_CHARS and unit.isprintable()


def _stating(
    source: BoundSource,
    unit: str | None,
    picks: Mapping[tuple[str, str], float],
    *,
    part_id: uuid.UUID,
    quantity: str,
    hz: float | None = None,
) -> _Stated | None:
    """`picks` ((slot, side) -> number) as the bands they make, in `unit` (canonicalised); None
    when they make none. Every source a unit is stated by comes through here, and the unit
    reaches the prompt: one that is not a short line (`_short_line`) leaves the source unstated,
    with one DEBUG line naming the part, quantity and source, never the unit."""
    slots = {
        slot: band
        for slot in ("nominal", "limit")
        if (band := _bound(picks.get((slot, "lo")), picks.get((slot, "hi")))) is not None
    }
    if not slots:
        return None
    if unit is not None and not _short_line(unit):
        logger.debug(
            "envelope source left out, its unit is not one short line "
            "part=%s quantity=%s source=%s",
            part_id,
            quantity,
            source,
        )
        return None
    return _Stated(source, canonical_unit(unit), slots, hz)


def _suffixed_position(
    values: Mapping[str, Any], channel_unit: str | None
) -> tuple[dict[tuple[str, str], float], str | None]:
    """The unit-suffixed position keys of ONE unit (spellings of a unit are one unit): the
    channel's (already canonical) when the keys state it, else the only unit they state. Several
    units and nothing to say which is meant: none."""
    by_unit: dict[str, dict[tuple[str, str], float]] = {}
    for key, raw in values.items():
        match, number = _POSITION_KEY.fullmatch(key), finite_number(raw)
        if match and number is not None and (spelled := canonical_unit(match["unit"])):
            side = "lo" if match["side"] == "min" else "hi"
            by_unit.setdefault(spelled, {})["limit", side] = number
    if channel_unit is not None and channel_unit in by_unit:
        unit = channel_unit
    elif len(by_unit) == 1:
        unit = next(iter(by_unit))
    else:
        return {}, None
    return by_unit[unit], unit


def _limits_stated(
    source: BoundSource,
    values: Mapping[str, Any],
    quantity: str,
    part_id: uuid.UUID,
    channel_unit: str | None,
) -> _Stated | None:
    """The limit keys of `quantity` in `values`, by the key-to-slot table."""
    picks: dict[tuple[str, str], float] = {}
    unit: str | None = None
    for key, (stem, slot, side, key_unit) in _KEYS.items():
        number = finite_number(values.get(key))
        if stem == quantity and number is not None:
            picks[slot, side] = number
            unit = unit or key_unit
    bare = _stating(source, unit, picks, part_id=part_id, quantity=quantity)
    if quantity != "position":
        return bare
    suffixed, suffix_unit = _suffixed_position(values, channel_unit)
    # the two families never mix an edge: the suffixed pair stands only as a pair (both sides),
    # or when no bare key is stated; a lone suffixed edge beside a bare one is left out. A pair
    # that states nothing (its unit is not one short line) leaves the bare keys to speak.
    if suffixed and (len(suffixed) == 2 or not picks):
        return _stating(source, suffix_unit, suffixed, part_id=part_id, quantity=quantity) or bare
    return bare


def _scene_stated(joint: JointRange | None, quantity: str, part_id: uuid.UUID) -> _Stated | None:
    """The scene joint's bounds as the position limit, in the unit the scene states them in."""
    if joint is None or quantity != "position":
        return None
    picks = {("limit", "lo"): joint.lower, ("limit", "hi"): joint.upper}
    return _stating("scene", joint.unit, picks, part_id=part_id, quantity=quantity)


def _channel_unit(channel: TelemetryChannel | None, part_id: uuid.UUID) -> str | None:
    """The channel's unit in its canonical spelling; None when it states none. A unit that is not
    one short line (`_short_line`) states none, with one DEBUG line naming the part."""
    if channel is None:
        return None
    if channel.unit is not None and not _short_line(channel.unit):
        logger.debug("channel unit left out, it is not one short line part=%s", part_id)
        return None
    return canonical_unit(channel.unit)


def _expected_stated(
    expected: Mapping[str, Any] | None, quantity: str, part_id: uuid.UUID
) -> _Stated | None:
    """A simulation's `{value, unit, sim_result_id}` for the quantity: the nominal, as a point,
    in the unit it states (`_stating` leaves it out when that is not one short line)."""
    entry = (expected or {}).get(quantity)
    if not isinstance(entry, Mapping):
        return None
    value = finite_number(entry.get("value"))
    if value is None:
        return None
    picks = {("nominal", "lo"): value, ("nominal", "hi"): value}
    return _stating("sim", entry.get("unit"), picks, part_id=part_id, quantity=quantity)


def _learned_stated(
    manifest: RunManifest | None,
    quantity: str,
    part_id: uuid.UUID,
    channel: TelemetryChannel | None,
    channel_unit: str | None,
) -> _Stated | None:
    """p1 / p99 of what the baseline run measured on the part's channel, as the nominal band, and
    the rate it streamed at, in the unit the packets state or else the channel's (`channel_unit`,
    already bounded). Nothing without the channel, the part in the run, enough samples
    (`MIN_LEARNED_SAMPLES`) or one unit across them.

    ponytail: scans the run's packets per (part, quantity); the cache is what makes that once
    per baseline."""
    if manifest is None or channel is None:
        return None
    device = next((p.device_id for p in manifest.parts if p.entity_id == part_id), None)
    if device is None:
        return None
    samples = [
        (packet.timestamp, packet.values[channel.name], packet.units.get(channel.name))
        for packet in manifest.packets
        if packet.device_id == device and channel.name in packet.values
    ]
    stated = {spelled for _, _, raw in samples if (spelled := canonical_unit(raw))}
    if len(samples) < MIN_LEARNED_SAMPLES or len(stated) > 1:
        return None
    cuts = statistics.quantiles([value for _, value, _ in samples], n=100, method="inclusive")
    times = sorted(at for at, _, _ in samples)
    span = (times[-1] - times[0]).total_seconds()
    picks = {("nominal", "lo"): cuts[0], ("nominal", "hi"): cuts[98]}
    return _stating(
        "learned",
        next(iter(stated), channel_unit),
        picks,
        part_id=part_id,
        quantity=quantity,
        hz=(len(times) - 1) / span if span > 0 else None,
    )


def _derive_warn(limit: Bound | None, fraction: float) -> Bound | None:
    """`fraction` of the limit: of the half-range from the midpoint when it has two sides, of the
    upper edge when only that is stated and it is above zero. Else there is nothing to take a
    fraction of."""
    if limit is None:
        return None
    lo, hi = limit.lo, limit.hi
    if lo is not None and hi is not None:
        middle, half = (lo + hi) / 2, (hi - lo) / 2
        return Bound(lo=middle - fraction * half, hi=middle + fraction * half)
    if hi is not None and hi > 0:
        return Bound(hi=fraction * hi)
    return None


def _assemble(
    part_id: uuid.UUID,
    quantity: str,
    unit: str | None,
    stated: Sequence[_Stated],
    warn_fraction: float,
) -> Envelope | None:
    """The envelope the sources make, highest first; None when they state nothing."""
    slots: dict[str, Bound] = {}
    sources: dict[str, BoundSource] = {}
    for one in stated:
        for slot, band in one.slots.items():
            if slot not in slots:
                slots[slot], sources[slot] = band, one.source
    if not slots:
        return None
    limit = slots.get("limit")
    bands: dict[str, Bound | None] = {
        "nominal": slots.get("nominal"),
        "warn": _derive_warn(limit, warn_fraction),
        "limit": limit,
    }
    bounds_source: dict[str, str] = {
        slot: "derived" if slot == "warn" else sources[slot]
        for slot in _SLOTS
        if bands[slot] is not None
    }
    rate = next((one for one in stated if one.hz is not None), None)
    if rate is not None:
        bounds_source["expected_hz"] = rate.source
    return Envelope(
        part_id=part_id,
        quantity=quantity,
        unit=unit,
        nominal=bands["nominal"],
        warn=bands["warn"],
        limit=bands["limit"],
        expected_hz=rate.hz if rate is not None else None,
        bounds_source=bounds_source,
        confidence=min(_CONFIDENCE[source] for source in sources.values()),
    )


async def build_envelope(
    session: AsyncSession,
    project_id: uuid.UUID,
    part_id: uuid.UUID,
    quantity: str,
    *,
    config: PartConfig | None,
    definition: PartLimitsSpec | None,
    scene_joint: JointRange | None,
    expected: Mapping[str, Any] | None,
    baseline_run: RunManifest | None,
    envelopes: EnvelopesConfig,
) -> Envelope | None:
    """The envelope of `quantity` for the part, from the inputs handed in; None when no source
    states anything. Pure: every input is passed, so `session` is the caller's handle (the
    evaluator's) and is not read, and `project_id` names the project in the log.

    `config` is the part's own config (its limits and channels), `definition` its library
    definition's limits, `scene_joint` the joint the scene binds to it (`part_bindings`),
    `expected` its `attrs.expected` and `baseline_run` the baseline run's manifest."""
    channel = channel_for_quantity(config.telemetry if config is not None else (), quantity)
    channel_unit = _channel_unit(channel, part_id)
    limits = config.limits.values if config is not None and config.limits is not None else {}
    stated = [
        one
        for one in (
            _limits_stated("config", limits, quantity, part_id, channel_unit),
            _limits_stated(
                "definition",
                definition.model_dump() if definition is not None else {},
                quantity,
                part_id,
                channel_unit,
            ),
            _scene_stated(scene_joint, quantity, part_id),
            _expected_stated(expected, quantity, part_id),
            _learned_stated(baseline_run, quantity, part_id, channel, channel_unit),
        )
        if one is not None
    ]
    unit = channel_unit if channel_unit is not None else (stated[0].unit if stated else None)
    usable: list[_Stated] = []
    owned: set[str] = set()  # the slots the usable sources above have taken
    for one in stated:
        # a source that states no unit is read in the channel's, when there is one to say
        if one.unit == unit or (one.unit is None and channel_unit is not None):
            usable.append(one)
            owned.update(one.slots)
        elif hidden := one.slots.keys() - owned:  # it would have owned a slot nobody above does
            logger.log(
                logging.WARNING if one.source in _STATED_LIMITS else logging.INFO,
                "envelope source left out, its unit is not the envelope's project=%s part=%s "
                "quantity=%s source=%s unit=%s envelope_unit=%s slots=%s",
                project_id,
                part_id,
                quantity,
                one.source,
                one.unit,
                unit,
                sorted(hidden),
            )
    return _assemble(part_id, quantity, unit, usable, envelopes.warn_fraction)


# ---------------------------------------------------------------------------- the loader


@dataclass(frozen=True)
class EnvelopeInputs:
    """What one part's envelopes are built from, as the database holds it: the part's config and
    the version it is at, its library definition's limits and the id that names it, the scene
    joint bound to it and its `attrs.expected`. The two stamps are what the cache key carries."""

    config: PartConfig | None
    config_version: int | None
    definition: PartLimitsSpec | None
    definition_id: str | None
    scene_joint: JointRange | None
    expected: dict[str, Any] | None


def _part_config(entry: SolusEntry | None) -> PartConfig | None:
    """The part's own component config; None when it has none or it does not read (logged)."""
    if entry is None:
        return None
    try:
        stored = config_of(entry)
    except (APIError, ValidationError):
        logger.warning(
            "part config unreadable project=%s entry=%s", entry.project_id, entry.id, exc_info=True
        )
        return None
    return stored.component if isinstance(stored, EntityHardwareConfig) else None


def _resolve_definition(raw: object) -> tuple[str | None, PartLimitsSpec | None]:
    """The library part `attrs.definition_id` names: its id (only when the library holds it, so
    nothing foreign reaches a cache key) and its limits."""
    if not isinstance(raw, str):
        return None, None
    try:
        found = load_library().get("part", raw)
    except DefinitionError:
        logger.warning("the part library does not load; no definition limits", exc_info=True)
        return None, None
    return (raw, found.limits) if isinstance(found, PartDefinition) else (None, None)


async def load_envelope_inputs(
    session: AsyncSession, project_id: uuid.UUID, part_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, EnvelopeInputs]:
    """The inputs of each of `part_ids` that is a live part of THIS project (another project's
    part, a robot, a deleted part and a stranger are simply absent), in three reads however many
    parts: the parts, their config entries, the scenes that bind them. Raises what those reads
    raise (an inconsistent config entry is a 409): the callers decide what that costs."""
    wanted = set(part_ids)
    if not wanted:
        return {}
    parts = list(
        await session.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == project_id,
                GraphEntity.id.in_(wanted),
                GraphEntity.kind.in_(PART_KINDS),
                GraphEntity.deleted_at.is_(None),
            )
        )
    )
    if not parts:
        return {}
    ids = [part.id for part in parts]
    entries = {
        e.configured_entity_id: e for e in await configuration_entries(session, project_id, ids)
    }
    scenes = await bound_scenes(session, project_id, ids)
    loaded: dict[uuid.UUID, EnvelopeInputs] = {}
    for part in parts:
        entry = entries.get(part.id)
        definition_id, definition = _resolve_definition(part.attrs.get("definition_id"))
        expected = part.attrs.get("expected")
        loaded[part.id] = EnvelopeInputs(
            config=_part_config(entry),
            config_version=entry.config_version if entry is not None else None,
            definition=definition,
            definition_id=definition_id,
            scene_joint=scene_joint_for_part(scenes, part.id),
            expected=expected if isinstance(expected, dict) else None,
        )
    return loaded


async def part_envelopes(
    session: AsyncSession,
    project_id: uuid.UUID,
    part_ids: Iterable[uuid.UUID],
    *,
    envelopes: EnvelopesConfig,
) -> dict[uuid.UUID, list[Envelope]]:
    """Every envelope the database lets be built for each live part of the project among
    `part_ids`, in `QUANTITIES` order (a part with none maps to []; an id that is no live part of
    the project is absent). No baseline: a run's packets are an artifact, which a read tool and a
    context read hold no store for — a caller that has one passes the manifest to
    `build_envelope`."""
    found: dict[uuid.UUID, list[Envelope]] = {}
    for part_id, inputs in (await load_envelope_inputs(session, project_id, part_ids)).items():
        built = [
            await build_envelope(
                session,
                project_id,
                part_id,
                quantity,
                config=inputs.config,
                definition=inputs.definition,
                scene_joint=inputs.scene_joint,
                expected=inputs.expected,
                baseline_run=None,
                envelopes=envelopes,
            )
            for quantity in QUANTITIES
        ]
        found[part_id] = [envelope for envelope in built if envelope is not None]
    return found


def _band_text(bound: Bound) -> str:
    lo, hi = bound.lo, bound.hi
    if lo is not None and hi is not None:
        return f"{lo:g} to {hi:g}"
    if hi is not None:
        return f"<= {hi:g}"
    if lo is not None:
        return f">= {lo:g}"
    return "unstated"


def envelope_line(envelope: Envelope) -> str:
    """`<quantity> <unit>: nominal …, warn …, limit … (sources: …)` — what `get_envelope` answers
    and what the context shows (plus the baseline's rate, when it gave one)."""
    told = [
        f"{slot} {_band_text(band)}"
        for slot in _SLOTS
        if (band := getattr(envelope, slot)) is not None
    ]
    if envelope.expected_hz is not None:
        told.append(f"rate {envelope.expected_hz:g} Hz")
    sources = ", ".join(
        f"{slot}={source}"
        for slot in (*_SLOTS, "expected_hz")
        if (source := envelope.bounds_source.get(slot))
    )
    head = f"{envelope.quantity} {envelope.unit}" if envelope.unit else envelope.quantity
    return f"{head}: {', '.join(told)} (sources: {sources})"


# ---------------------------------------------------------------------------- the cache


@dataclass(frozen=True)
class EnvelopeKey:
    """What an envelope was built from that its text does not carry: the config's version, the
    definition and the baseline run (any missing one is `-`). A bump of any of them is another
    key, so a config bump (an Activity row, never a live frame) needs no invalidation. The inputs
    the key does not carry are the scene joint and the expected value, which a published
    `graph.changed` drops (`EnvelopeCache.invalidator`; a writer that publishes none leaves an
    entry stale for its TTL), and `envelopes.warn_fraction`, which changes only with a deploy.
    `definition_id` is a library id (`load_envelope_inputs` only hands one the library holds), so
    it carries no separator."""

    project_id: uuid.UUID
    part_id: uuid.UUID
    quantity: str
    config_version: int | None
    definition_id: str | None
    baseline_run_id: uuid.UUID | None

    def family(self) -> str:
        """What every stamp of one envelope shares — project, part, quantity — as the key's
        prefix: a newer stamp supersedes the older keys of its family."""
        return f"solus:envelope:{self.project_id}:{self.part_id}:{self.quantity}:"

    def __str__(self) -> str:
        stamps = (self.config_version, self.definition_id, self.baseline_run_id)
        return self.family() + ":".join("-" if stamp is None else str(stamp) for stamp in stamps)


def _index_key(project_id: uuid.UUID) -> str:
    return f"solus:envelope:{project_id}:index"


#: Each store call bounded by the fan-out's own store timeout: a stalled store never stalls a tick.
_within_bound = within_bound


class EnvelopeCache:
    """Envelopes in the shared store (Redis when there is one) under `str(EnvelopeKey)`, 600 s.

    The store protocol has no scan, so each project keeps an INDEX key listing its envelope keys
    (the newest stamp of each (part, quantity), at most `MAX_INDEXED_KEYS`; past that a `put` is
    a no-op, logged once), rewritten on every `put` — which drops the pair's superseded keys —
    and read back by the invalidator. Nothing here raises: a store that is down, slow, or
    holding something that does not read is a miss, and a `put` that cannot be indexed is not
    written — a value nobody could invalidate would be worse than none.

    ponytail: the index is read, extended and written back without a lock, so two racing puts
    (or two processes) can drop one key from it; that key then outlives a graph change until its
    TTL. Only inputs the key does not carry could make it stale. A per-project Redis set is the
    upgrade."""

    def __init__(self, store: CacheStore, ttl: int = ENVELOPE_TTL_SECONDS) -> None:
        self._store = store
        self._ttl = ttl
        self._full: set[uuid.UUID] = set()

    async def get(self, key: EnvelopeKey) -> Envelope | None:
        try:
            raw = await _within_bound(self._store.get(str(key)))
            return None if raw is None else Envelope.model_validate_json(raw)
        except ValidationError:  # another deploy's shape, or a corrupt entry: rebuild
            return None
        except Exception as exc:  # noqa: BLE001 — a miss, never a failed tick
            logger.warning("envelope cache read failed key=%s: %s", key, type(exc).__name__)
            return None

    async def put(self, key: EnvelopeKey, envelope: Envelope) -> None:
        text = str(key)
        try:
            index = await self._index(key.project_id)
            # a newer stamp of the same (part, quantity) supersedes its older keys: never hit again
            older = [k for k in index if k.startswith(key.family()) and k != text]
            kept = [k for k in index if k != text and k not in older]
            if len(kept) >= MAX_INDEXED_KEYS:
                self._warn_full(key.project_id)
                return
            listed = json.dumps([*kept, text])
            # the index first, and rewritten on every put: its TTL must outlast every key's
            await _within_bound(self._store.set(_index_key(key.project_id), listed, self._ttl))
            # the superseded values go too: unindexed, none could be invalidated; best effort
            await asyncio.gather(
                *(_within_bound(self._store.delete(k)) for k in older), return_exceptions=True
            )
            await _within_bound(self._store.set(text, envelope.model_dump_json(), self._ttl))
        except Exception as exc:  # noqa: BLE001 — not cached, never a failed tick
            logger.warning("envelope cache write failed key=%s: %s", key, type(exc).__name__)

    def _warn_full(self, project_id: uuid.UUID) -> None:
        if project_id not in self._full:
            self._full.add(project_id)
            logger.warning(
                "envelope cache index is full, not caching project=%s limit=%s",
                project_id,
                MAX_INDEXED_KEYS,
            )

    async def invalidate(self, project_id: uuid.UUID) -> None:
        """Drop every envelope the project has cached, then its index; the index stays when a
        delete failed, so the next graph change retries."""
        self._full.discard(project_id)
        try:
            keys = await self._index(project_id)
            results = await asyncio.gather(
                *(_within_bound(self._store.delete(k)) for k in keys), return_exceptions=True
            )
            if any(isinstance(result, BaseException) for result in results):
                logger.warning("envelope cache entries not dropped project=%s", project_id)
                return
            await _within_bound(self._store.delete(_index_key(project_id)))
        except Exception as exc:  # noqa: BLE001 — a failed drop is retried by the next change
            logger.warning(
                "envelope cache invalidation failed project=%s: %s", project_id, type(exc).__name__
            )

    def invalidator(self) -> Callable[[uuid.UUID], Awaitable[None]]:
        """The `graph.changed` callback `graph_changed_callbacks` registers."""
        return self.invalidate

    async def _index(self, project_id: uuid.UUID) -> list[str]:
        """The project's listed keys; [] when there is no index or it does not read. A store that
        fails raises, so a caller never mistakes an unreadable index for an empty one."""
        raw = await _within_bound(self._store.get(_index_key(project_id)))
        if raw is None:
            return []
        try:
            listed = json.loads(raw)
        except ValueError:
            return []
        return [k for k in listed if isinstance(k, str)] if isinstance(listed, list) else []
