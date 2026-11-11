"""Deterministic evidence checks, with no execution or model-generated facts."""

import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import datetime, timedelta
from itertools import islice
from typing import Any, Final, Literal
from uuid import UUID

import numpy as np
from numpy.typing import NDArray

from solus_api.graph import kinds
from solus_api.graph.packet import TelemetryPacket
from solus_api.livebench.findings.envelopes import convert_unit
from solus_api.livebench.findings.rules.rule_base import still_window
from solus_api.livebench.findings.sim_control import (
    SimControl,
    classify_sim_control,
    simulation_gap,
)
from solus_api.livebench.runs.models import (
    MAX_PACKETS,
    PartEvidence,
    RevisionSnapshot,
    RunFinding,
    RunManifest,
)
from solus_api.livebench.scene.part_bindings import JointRange, finite_number

#: The one scale table (`envelopes.convert_unit`), shared with the window evaluator.
_convert = convert_unit


def _observations(
    run: RunManifest, part: PartEvidence
) -> list[tuple[datetime, float, float, float]]:
    rows = []
    for packet in run.packets:
        if packet.device_id != part.device_id:
            continue
        roles = (
            (part.current_signal, "A"),
            (part.position_signal, part.position_unit),
            (part.command_signal, part.position_unit),
        )
        values = [
            _convert(packet.values[name], packet.units.get(name), unit)
            if name in packet.values
            else None
            for name, unit in roles
        ]
        if all(value is not None for value in values):
            current, position, command = values
            assert current is not None and position is not None and command is not None
            rows.append((packet.timestamp, current, position, command))
    return rows


def _triples(run: RunManifest, part: PartEvidence) -> list[tuple[float, float, float]]:
    return [
        (current, position, command) for _, current, position, command in _observations(run, part)
    ]


# Conservative observed-still thresholds, in the explicitly declared physical unit.
_STILL_TOLERANCE = {"rad": 0.01, "deg": 0.5, "m": 0.001}


def _stall_window(
    run: RunManifest, part: PartEvidence
) -> list[tuple[datetime, float, float, float]]:
    tolerance = _STILL_TOLERANCE.get(part.position_unit or "")
    if part.stall_current_a is None or tolerance is None:
        return []
    return still_window(
        _observations(run, part), current_bound=part.stall_current_a, tolerance=tolerance
    )


def findings(run: RunManifest) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    insufficient: list[dict[str, Any]] = []
    for part in run.parts:
        rows = _triples(run, part)
        if (
            len(rows) < 3
            or part.stall_current_a is None
            or part.position_unit not in _STILL_TOLERANCE
        ):
            insufficient.append(
                {
                    "entity_id": str(part.entity_id),
                    "reason": (
                        "Need three aligned current, position and command samples "
                        "with compatible rad, deg or m position units and a stall-current rating."
                    ),
                }
            )
            continue
        window = _stall_window(run, part)
        if window:
            _, currents, positions, commands = zip(*window, strict=True)
            cards.append(
                {
                    "entity_id": str(part.entity_id),
                    "headline": f"Possible stall at {part.name}",
                    "explanation": (
                        "Current reached the snapshotted stall rating while position "
                        "remained still despite a different commanded target."
                    ),
                    "detail": (
                        "This evidence suggests a stall; it does not establish "
                        "the mechanical cause."
                    ),
                    "code_site": part.code_site,
                    "cad_revision": part.cad_revision,
                    "evidence": {
                        "stall_current_a": part.stall_current_a,
                        "measured_current_min_a": min(currents),
                        "commanded_min": min(commands),
                        "commanded_max": max(commands),
                        "configured_min": part.position_min,
                        "configured_max": part.position_max,
                        "position_unit": part.position_unit,
                        "samples": len(window),
                        "window_start": window[0][0].isoformat(),
                        "window_end": window[-1][0].isoformat(),
                    },
                }
            )
    if not run.parts:
        insufficient.append({"entity_id": None, "reason": "No accepted part mapping was captured."})
    return {"findings": cards, "insufficient": insufficient}


def _series(run: RunManifest) -> dict[tuple[str, str], dict[int, tuple[float, str | None]]]:
    result: dict[tuple[str, str], dict[int, tuple[float, str | None]]] = {}
    # Each run's first recorded sample is elapsed zero. Producer clock offset is
    # not a physical divergence. Millisecond alignment never interpolates gaps.
    if not run.packets:
        return result
    start = min(packet.timestamp for packet in run.packets)
    for packet in run.packets:
        elapsed = round((packet.timestamp - start).total_seconds() * 1000)
        for name, value in packet.values.items():
            result.setdefault((packet.device_id, name), {})[elapsed] = (
                value,
                packet.units.get(name),
            )
    return result


def _config_changes(baseline: RunManifest, candidate: RunManifest) -> list[dict[str, Any]]:
    changes = []
    before_parts = {part.entity_id: part for part in baseline.parts}
    for part in candidate.parts:
        old = before_parts.get(part.entity_id)
        if old is not None:
            for key in (
                "position_min",
                "position_max",
                "position_unit",
                "code_site",
                "cad_revision",
            ):
                if getattr(old, key) != getattr(part, key):
                    changes.append(
                        {
                            "entity_id": str(part.entity_id),
                            "field": key,
                            "before": getattr(old, key),
                            "after": getattr(part, key),
                        }
                    )
    return changes


def _divergences(
    baseline: RunManifest, candidate: RunManifest
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    before, after = _series(baseline), _series(candidate)
    divergences = []
    insufficient: list[dict[str, Any]] = []
    for identity in sorted(before.keys() | after.keys()):
        a, b = before.get(identity, {}), after.get(identity, {})
        aligned = []
        for timestamp in sorted(a.keys() & b.keys()):
            value, unit = a[timestamp]
            converted = _convert(b[timestamp][0], b[timestamp][1], unit)
            if converted is not None and math.isfinite(converted - value):
                aligned.append(abs(converted - value))
        if not aligned:
            insufficient.append(
                {
                    "device_id": identity[0],
                    "signal": identity[1],
                    "reason": "No aligned samples with compatible explicit units.",
                }
            )
        elif max(aligned) > 1e-9:
            divergences.append(
                {
                    "device_id": identity[0],
                    "signal": identity[1],
                    "aligned_samples": len(aligned),
                    "max_difference": max(aligned),
                    "unit": next(iter(a.values()))[1],
                }
            )
    return divergences, insufficient


def _clamps(baseline: RunManifest, candidate: RunManifest) -> list[dict[str, Any]]:
    before_parts = {part.entity_id: part for part in baseline.parts}
    attributions = []
    for part in candidate.parts:
        old = before_parts.get(part.entity_id)
        if old is None or old.position_max is None or part.position_max is None:
            continue
        if old.position_max == part.position_max or old.position_unit != part.position_unit:
            continue
        left, right = _triples(baseline, old), _triples(candidate, part)
        if (
            len(left) >= 3
            and len(right) >= 3
            and all(
                abs(position - old.position_max) < 0.01 and command > old.position_max
                for _, position, command in left
            )
            and all(
                abs(position - part.position_max) < 0.01 and command > part.position_max
                for _, position, command in right
            )
        ):
            attributions.append(
                {
                    "entity_id": str(part.entity_id),
                    "explanation": (
                        "Both observed positions follow their changed configured "
                        "upper bound while commands exceed that bound."
                    ),
                    "before_limit": old.position_max,
                    "after_limit": part.position_max,
                }
            )
    return attributions


#: What a comparison's expected behaviour comes from. Two runs compare against the baseline
#: run; `definition` and `sim` are for comparing against those (SOLUSDEV-321 P4-T5).
ExpectedSource = Literal["baseline_run", "definition", "sim"]
_CHANGE_ORDER: Final = {"new": 0, "cleared": 1, "persisting": 2}


def _by_identity(run: RunManifest) -> dict[tuple[str, tuple[UUID, ...]], RunFinding]:
    return {(item.rule_id, tuple(item.subjects)): item for item in run.findings}


def _occurrence(item: RunFinding | None) -> dict[str, Any] | None:
    return None if item is None else {"finding_id": str(item.finding_id), "count": item.count}


def _finding_deltas(baseline: RunManifest, candidate: RunManifest) -> list[dict[str, Any]]:
    """How the two runs' findings differ, matched on the rule and the sorted subjects: a finding's
    id is per bench session, so one condition seen in both runs is two ids."""
    before, after = _by_identity(baseline), _by_identity(candidate)
    deltas = []
    for key in before.keys() | after.keys():
        old, new = before.get(key), after.get(key)
        latest = new or old
        if latest is None:
            continue
        deltas.append(
            {
                "rule_id": key[0],
                "subjects": [str(subject) for subject in key[1]],
                "change": "persisting" if old and new else "new" if new else "cleared",
                "severity": latest.severity,
                "baseline": _occurrence(old),
                "candidate": _occurrence(new),
            }
        )
    return sorted(deltas, key=lambda d: (_CHANGE_ORDER[d["change"]], d["rule_id"], d["subjects"]))


def compare(baseline: RunManifest, candidate: RunManifest) -> dict[str, Any]:
    """The two runs' differences. A baseline that is the twin's run is a simulation's expectation
    (`expected_source = sim`), and when exactly one run is the twin's, the real one is read
    against it under `evidence` (P4-T5, the section at the end)."""
    if baseline.robot_id != candidate.robot_id:
        raise ValueError("runs must belong to the same robot")
    divergences, insufficient = _divergences(baseline, candidate)
    expected: ExpectedSource = "sim" if _twin_of(baseline) is not None else "baseline_run"
    result: dict[str, Any] = {
        "config_changes": _config_changes(baseline, candidate),
        "source_snapshots_changed": _sources(baseline) != _sources(candidate),
        "divergences": divergences,
        "clamp_attributions": _clamps(baseline, candidate),
        "insufficient": insufficient,
        "finding_deltas": _finding_deltas(baseline, candidate),
        "expected_source": expected,
    }
    control = _sim_control(baseline, candidate)
    return result if control is None else {**result, "evidence": control}


# ---------------------------------------------- a run against a simulation (SOLUSDEV-321 P4-T4)
#
# The residual of what a run measured against what a `sim_result` expected
# (`provenance.inputs.expected_trajectory`), attributed joint by joint to ONE of
# `RESIDUAL_PARAMETERS` by a deterministic grid (R93). Each parameter's forward model is tried at
# `GRID_STEPS` values over the expected motion: a lag (`mass`: a heavier or lighter link than the
# model's tracks late), a clip (`limit`), a constant shift (`sensor_offset`) and a stop that holds
# (`contact`). The parameter that alone explains most of the residual's energy is named when it
# explains at least `ATTRIBUTION_MIN` and leads the next by `ATTRIBUTION_MARGIN`; otherwise the
# residual is `unattributed`, never forced onto one. Both series are resampled onto
# `RESIDUAL_SAMPLES` points of the time they share, so the work is bounded whatever the rates.
# `compare` judges each part a real run shares with its routine's twin this way (P4-T5, below).

#: The samples a joint's residual is judged on.
RESIDUAL_SAMPLES: Final = 256
#: The values each parameter's model is tried at; a limit is tried as an upper and a lower clip.
GRID_STEPS: Final = 33
#: What a residual is attributed to, in tie-break order.
RESIDUAL_PARAMETERS: Final = ("mass", "limit", "sensor_offset", "contact")
#: The share of the residual's energy the best parameter must explain alone, and its lead on the
#: next parameter's best.
ATTRIBUTION_MIN: Final = 0.8
ATTRIBUTION_MARGIN: Final = 0.1
#: A residual this small against the expected motion's span is consistent: nothing to attribute.
CONSISTENT_FRACTION: Final = 0.01
#: The fewest samples a series is judged with.
MIN_RESIDUAL_SAMPLES: Final = 8

type Series = NDArray[np.float64]
#: One parameter's tries: what each try states, and the observed motion it predicts.
type Tries = list[tuple[dict[str, float | str], Series]]
type Aligned = tuple[Series, Series, Series]


def residual_attribution(
    expected_t: Sequence[float],
    expected: Sequence[float],
    observed_t: Sequence[float],
    observed: Sequence[float],
) -> dict[str, Any]:
    """One joint's residual, observed minus expected in the trajectory's unit, attributed to one
    of `RESIDUAL_PARAMETERS` (the section comment); `consistent` when it is negligible, and
    `insufficient`, with the reason, when the two series cannot be compared."""
    aligned = _aligned(expected_t, expected, observed_t, observed)
    if isinstance(aligned, str):
        return {"status": "insufficient", "parameter": None, "reason": aligned}
    grid, wanted, seen = aligned
    residual = seen - wanted
    rms = float(np.sqrt(np.mean(residual**2)))
    if rms <= CONSISTENT_FRACTION * float(np.ptp(wanted)) or not np.any(residual):
        return {
            "status": "consistent",
            "parameter": None,
            "residual_rms": rms,
            "samples": len(grid),
        }
    best = {name: _best(residual, wanted, tries) for name, tries in _tries(grid, wanted, residual)}
    top, runner = sorted(RESIDUAL_PARAMETERS, key=lambda name: -best[name][0])[:2]
    named = best[top][0] >= ATTRIBUTION_MIN and best[top][0] - best[runner][0] >= ATTRIBUTION_MARGIN
    return {
        "status": "attributed" if named else "unattributed",
        "parameter": top if named else None,
        "explained": {name: round(best[name][0], 3) for name in RESIDUAL_PARAMETERS},
        "estimate": {name: best[name][1] for name in RESIDUAL_PARAMETERS},
        "residual_rms": round(rms, 6),
        "samples": len(grid),
    }


def run_positions(run: RunManifest, part: PartEvidence) -> tuple[list[float], list[float]]:
    """A part's measured positions over a run: seconds since the run started, and each position in
    the part's own position unit. A packet without the position, or in a unit that does not
    convert, is skipped."""
    times: list[float] = []
    positions: list[float] = []
    signal = part.position_signal
    for packet in run.packets:
        if signal is None or packet.device_id != part.device_id or signal not in packet.values:
            continue
        value = _convert(packet.values[signal], packet.units.get(signal), part.position_unit)
        if value is not None:
            times.append((packet.timestamp - run.started_at).total_seconds())
            positions.append(value)
    return times, positions


def _samples(
    times: Sequence[float], values: Sequence[float], whose: str
) -> str | tuple[Series, Series]:
    """`(times, values)` as arrays, or why they cannot be judged."""
    if len(times) != len(values):
        return f"{whose}'s times and values are not as many"
    if len(times) < MIN_RESIDUAL_SAMPLES:
        return f"{whose} needs at least {MIN_RESIDUAL_SAMPLES} samples"
    try:
        t, v = np.asarray(times, dtype=np.float64), np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError):
        return f"{whose}'s samples must be finite numbers"
    if not (np.all(np.isfinite(t)) and np.all(np.isfinite(v))):
        return f"{whose}'s samples must be finite numbers"
    if not np.all(np.diff(t) > 0):
        return f"{whose}'s times must be increasing"
    return t, v


def _aligned(
    expected_t: Sequence[float],
    expected: Sequence[float],
    observed_t: Sequence[float],
    observed: Sequence[float],
) -> str | Aligned:
    """The shared timeline and both series on it, or why there is none."""
    wanted = _samples(expected_t, expected, "the simulation")
    if isinstance(wanted, str):
        return wanted
    seen = _samples(observed_t, observed, "the run")
    if isinstance(seen, str):
        return seen
    (wanted_t, wanted_v), (seen_t, seen_v) = wanted, seen
    start, end = max(wanted_t[0], seen_t[0]), min(wanted_t[-1], seen_t[-1])
    if end <= start:
        return "the simulation and the run share no time"
    grid = np.linspace(start, end, RESIDUAL_SAMPLES)
    return grid, np.interp(grid, wanted_t, wanted_v), np.interp(grid, seen_t, seen_v)


def _tries(grid: Series, wanted: Series, residual: Series) -> list[tuple[str, Tries]]:
    return [
        ("mass", _lags(grid, wanted)),
        ("limit", _clips(wanted)),
        ("sensor_offset", _offsets(wanted, residual)),
        ("contact", _stops(grid, wanted)),
    ]


def _lags(grid: Series, wanted: Series) -> Tries:
    """A first-order lag of time constant tau over a log grid from a thousandth to half the
    motion: o[0] = e[0], o[k] = o[k-1] + alpha (e[k] - o[k-1]), as one convolution."""
    duration = float(grid[-1] - grid[0])
    step = duration / (len(grid) - 1)
    later = wanted.copy()
    later[0] = 0.0
    tries: Tries = []
    for tau in np.geomspace(duration / 1000, duration / 2, GRID_STEPS):
        alpha = 1.0 - math.exp(-step / float(tau))
        keep = (1.0 - alpha) ** np.arange(len(wanted))
        lagged = keep * wanted[0] + np.convolve(later, alpha * keep)[: len(wanted)]
        tries.append(({"tau_s": round(float(tau), 6)}, lagged))
    return tries


def _clips(wanted: Series) -> Tries:
    """A limit inside the expected range, as a ceiling and as a floor."""
    levels = np.linspace(float(wanted.min()), float(wanted.max()), GRID_STEPS + 2)[1:-1]
    upper: Tries = [
        ({"side": "upper", "at": round(float(level), 6)}, np.minimum(wanted, level))
        for level in levels
    ]
    lower: Tries = [
        ({"side": "lower", "at": round(float(level), 6)}, np.maximum(wanted, level))
        for level in levels
    ]
    return upper + lower


def _offsets(wanted: Series, residual: Series) -> Tries:
    """A constant shift, over the residual's own reach."""
    reach = float(np.max(np.abs(residual)))
    return [
        ({"offset": round(float(shift), 6)}, wanted + shift)
        for shift in np.linspace(-reach, reach, GRID_STEPS)
    ]


def _stops(grid: Series, wanted: Series) -> Tries:
    """The motion held where it was from a moment inside the shared time on."""
    tries: Tries = []
    for at in np.linspace(float(grid[0]), float(grid[-1]), GRID_STEPS + 2)[1:-1]:
        stop = int(np.searchsorted(grid, at))
        held = wanted.copy()
        held[stop:] = wanted[stop]
        tries.append(({"at_s": round(float(at), 6)}, held))
    return tries


def _best(residual: Series, wanted: Series, tries: Tries) -> tuple[float, dict[str, float | str]]:
    """A parameter's best try: the share of the residual's energy it explains, and what it states.
    The first of equals wins, so the result is the same for the same series."""
    energy = float(residual @ residual)
    scored = [
        (1.0 - float(np.sum((residual - (predicted - wanted)) ** 2)) / energy, estimate)
        for estimate, predicted in tries
    ]
    return max(scored, key=lambda item: item[0])


# ------------------------------------- the simulation as the control (SOLUSDEV-321 P4-T5)
#
# A run whose snapshots carry a `sim_result` is the twin's run of its routine (`_twin_of`). When
# exactly one of the two runs compare reads is the twin's, the other, the real one, is read
# against it from what the two manifests hold, and nothing else (R98):
# - a run failed when it shows a stall (`findings`) or raised a warning or critical finding,
#   passed when the stall check judged a part of it and it did neither, and says nothing (None)
#   otherwise;
# - the real run's task passed when every commanded part ends within its unit's tolerance of its
#   command. A run that passed had a part judged, whose last command says it, so a passing run's
#   task is always known;
# - the twin models a fault when the same stall check judged, in the twin's run, a part that
#   stalled in the real one. A raised finding is never counted as modelled: the manifest does not
#   say what it read.
# `classify_sim_control` names where the failure lives, read with `simulation_gap` (M80):
# `electrical_or_mechanical` beside a gap is a twin that models the fault and missed it, so its
# model is the first suspect. Each part both runs observed carries its residual against the twin.


def _twin_of(run: RunManifest) -> UUID | None:
    """The `sim_result` a run's snapshots name: the run is that simulation's, the twin's."""
    return next((item.entity_id for item in run.snapshots if item.kind == kinds.SIM_RESULT), None)


def _sim_control(baseline: RunManifest, candidate: RunManifest) -> dict[str, Any] | None:
    """The real run read against its routine's twin (the section comment); None unless exactly
    one of the two runs is the twin's."""
    ids = _twin_of(baseline), _twin_of(candidate)
    if (ids[0] is None) == (ids[1] is None):
        return None
    twin, real = (baseline, candidate) if ids[0] is not None else (candidate, baseline)
    real_seen, twin_seen = findings(real), findings(twin)
    real_passed, sim_passed = _passed(real, real_seen), _passed(twin, twin_seen)
    task_passed = _reached(real)
    stalled = {card["entity_id"] for card in real_seen["findings"]}
    covered = bool(stalled & _judged(twin, twin_seen))
    label, reason = _labelled(real_passed, sim_passed, task_passed)
    return {
        "sim_result_id": str(ids[0] or ids[1]),
        "real_passed": real_passed,
        "sim_passed": sim_passed,
        "task_passed": task_passed,
        "sim_control": label,
        "reason": reason,
        "simulation_gap": None not in (real_passed, sim_passed)
        and simulation_gap(bool(real_passed), bool(sim_passed), sim_covers_fault=covered),
        "residuals": _residuals(real, twin),
    }


def _judged(run: RunManifest, seen: Mapping[str, Any]) -> set[str]:
    """The parts of a run the stall check judged: every one it did not find insufficient."""
    unjudged = {item["entity_id"] for item in seen["insufficient"]}
    return {str(part.entity_id) for part in run.parts} - unjudged


def _passed(run: RunManifest, seen: Mapping[str, Any]) -> bool | None:
    """False on a stall or a warning or critical finding; True when the stall check judged a part
    and neither showed; None when nothing could be judged."""
    if seen["findings"] or any(item.severity != "info" for item in run.findings):
        return False
    return True if _judged(run, seen) else None


def _reached(run: RunManifest) -> bool | None:
    """Whether every commanded part ends within its unit's tolerance of its command; None when no
    part states its current, position and command together."""
    ends: list[bool] = []
    for part in run.parts:
        tolerance, rows = _STILL_TOLERANCE.get(part.position_unit or ""), _triples(run, part)
        if tolerance is not None and rows:
            _, position, command = rows[-1]
            ends.append(abs(position - command) <= tolerance)
    return all(ends) if ends else None


def _labelled(
    real: bool | None, sim: bool | None, task: bool | None
) -> tuple[SimControl | None, str | None]:
    """Where the real run's failure lives, or why the runs do not say."""
    if real is None:
        return None, "the real run states nothing that says whether it passed"
    if sim is None:
        return None, "the twin's run states nothing that says whether it passed"
    return classify_sim_control(real, sim, task is True), None


def _residuals(real: RunManifest, twin: RunManifest) -> dict[str, dict[str, Any]]:
    """Each part both runs observed in one position unit, judged against the twin's motion."""
    twins = {part.entity_id: part for part in twin.parts}
    return {
        str(part.entity_id): residual_attribution(
            *run_positions(twin, twins[part.entity_id]), *run_positions(real, part)
        )
        for part in real.parts
        if part.entity_id in twins and twins[part.entity_id].position_unit == part.position_unit
    }


def _sources(run: RunManifest) -> list[RevisionSnapshot]:
    """A run's snapshots without the twin's marker, which names a simulation, not a source."""
    return [item for item in run.snapshots if item.kind != kinds.SIM_RESULT]


# ------------------------------------ the twin's run, from its simulation (P4-T5 fix 1, R117)
#
# The twin's run of a real run's routine, built from a rung-3 trajectory `sim_result`'s attrs
# (`provenance.inputs`: the `trajectory` routine, the `expected_trajectory {t, positions}` it
# recorded and the `expected_current_a`), for `compare` to read the real run against when a
# comparison names the simulation (`POST /bench/runs/compare`, `sim_result_id`). Pure, and
# bounded: a stored shape is never trusted, a recording is read for at most `MAX_TWIN_SAMPLES`
# samples within `MAX_TWIN_SECONDS`, and a twin carries the parts a manifest's packets hold.

#: The most samples and seconds of a recording read (a routine's recorder keeps 200 samples of
#: at most 30 s), and so the most parts one twin carries within `MAX_PACKETS`.
MAX_TWIN_SAMPLES: Final = 256
MAX_TWIN_SECONDS: Final = 3600.0
MAX_TWIN_PARTS: Final = MAX_PACKETS // MAX_TWIN_SAMPLES
#: The marker's name: the snapshot that makes a run the twin's.
TWIN_SNAPSHOT: Final = "the routine's simulated twin"

type JointOf = Callable[[UUID], JointRange | None]
type Signals = dict[str, tuple[Series, str]]


def twin_run(
    sim_result: Mapping[str, Any], real: RunManifest, joint_of: JointOf, *, sim_result_id: UUID
) -> RunManifest:
    """The twin's run of `real`'s routine (the section comment): each part of the real run that
    `joint_of` binds to a joint the simulation recorded gets, at each recorded sample from the
    real run's start, that joint's recorded position, its expected current and the routine's
    command, in the part's own units. A part bound to no recorded joint, or whose unit does not
    convert from the joint's, is left out. The twin carries the real run's snapshots and the
    `sim_result`'s marker."""
    laid = list(islice(_laid(sim_result, real, joint_of), MAX_TWIN_PARTS))
    marker = RevisionSnapshot(entity_id=sim_result_id, kind=kinds.SIM_RESULT, name=TWIN_SNAPSHOT)
    return RunManifest(
        robot_id=real.robot_id,
        started_at=real.started_at,
        packets=[packet for _, packets in laid for packet in packets],
        parts=[part for part, _ in laid],
        # ponytail: a run at the 256-snapshot bound gives its last one up to the marker
        snapshots=[*real.snapshots[:255], marker],
    )


def _laid(
    sim_result: Mapping[str, Any], real: RunManifest, joint_of: JointOf
) -> Iterator[tuple[PartEvidence, list[TelemetryPacket]]]:
    """Each part of `real` whose position the simulation recorded, with its twin's packets."""
    times = _times(_at(_recorded(sim_result, "expected_trajectory"), "t"))
    if times is None:
        return
    for part in real.parts:
        signals = _signals(part, joint_of(part.entity_id), sim_result, times)
        if part.position_signal in signals:
            yield part, _packets(part, signals, times, real.started_at)


def _signals(
    part: PartEvidence, joint: JointRange | None, sim_result: Mapping[str, Any], times: Series
) -> Signals:
    """What the simulation states of one part at each sample, by the part's signal, with its unit:
    the recorded position and the routine's command in the part's position unit, and the
    expected current in A. Nothing when the part's joint is none or its unit does not convert."""
    scale = None if joint is None else _convert(1.0, joint.unit, part.position_unit)
    if joint is None or scale is None or part.position_unit is None:
        return {}
    recorded = _at(_recorded(sim_result, "expected_trajectory"), "positions")
    positions = _numbers(_at(recorded, joint.joint), len(times))
    currents = _numbers(_at(_recorded(sim_result, "expected_current_a"), joint.joint), len(times))
    targets = _targets(_recorded(sim_result, "trajectory"), joint.joint)
    commands = None if targets is None else np.interp(times, *targets)
    stated = (
        (
            part.position_signal,
            None if positions is None else positions * scale,
            part.position_unit,
        ),
        (part.command_signal, None if commands is None else commands * scale, part.position_unit),
        (part.current_signal, currents, "A"),
    )
    return {
        signal: (values, unit)
        for signal, values, unit in stated
        if signal is not None and values is not None and bool(np.all(np.isfinite(values)))
    }


def _packets(
    part: PartEvidence, signals: Signals, times: Series, start: datetime
) -> list[TelemetryPacket]:
    return [
        TelemetryPacket(
            device_id=part.device_id,
            timestamp=start + timedelta(seconds=float(at)),
            values={signal: float(values[k]) for signal, (values, _) in signals.items()},
            units={signal: unit for signal, (_, unit) in signals.items()},
        )
        for k, at in enumerate(times)
    ]


def _targets(routine: Any, joint: str) -> tuple[Series, Series] | None:
    """The routine's timed targets for `joint` (`{joints, points: [{t, positions}]}`), or None."""
    joints, points = _at(routine, "joints"), _at(routine, "points")
    if not isinstance(joints, list) or joint not in joints or not isinstance(points, list):
        return None
    index = joints.index(joint)
    at = _times([_at(point, "t") for point in points])
    to = _numbers([_nth(_at(point, "positions"), index) for point in points], len(points))
    return None if at is None or to is None else (at, to)


def _times(raw: Any) -> Series | None:
    """Sample times: 1 to `MAX_TWIN_SAMPLES` finite seconds, increasing from 0 to at most
    `MAX_TWIN_SECONDS`; None otherwise."""
    if not isinstance(raw, list) or not 0 < len(raw) <= MAX_TWIN_SAMPLES:
        return None
    times = _numbers(raw, len(raw))
    if times is None or times[0] < 0 or times[-1] > MAX_TWIN_SECONDS:
        return None
    return times if bool(np.all(np.diff(times) > 0)) else None


def _numbers(raw: Any, length: int) -> Series | None:
    """`raw` as exactly `length` finite numbers (never a bool or text), or None."""
    if not isinstance(raw, list) or len(raw) != length:
        return None
    found = [number for item in raw if (number := finite_number(item)) is not None]
    return np.array(found, dtype=np.float64) if len(found) == length else None


def _recorded(sim_result: Mapping[str, Any], name: str) -> Any:
    """One input a `sim_result` recorded (`provenance.inputs[name].value`), or None."""
    return _at(_at(_at(_at(sim_result, "provenance"), "inputs"), name), "value")


def _at(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, Mapping) else None


def _nth(value: Any, index: int) -> Any:
    return value[index] if isinstance(value, list) and len(value) > index else None
