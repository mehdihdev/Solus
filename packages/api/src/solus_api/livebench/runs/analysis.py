"""Deterministic evidence checks, with no execution or model-generated facts."""

import math
from collections import deque
from datetime import datetime
from typing import Any

from solus_api.livebench.runs.models import PartEvidence, RunManifest


def _convert(value: float, source: str | None, target: str | None) -> float | None:
    if source is None or target is None:
        return None
    if source == target:
        return value
    scales = {
        ("rad", "deg"): 180 / math.pi,
        ("deg", "rad"): math.pi / 180,
        ("mA", "A"): 0.001,
        ("A", "mA"): 1000.0,
    }
    factor = scales.get((source, target))
    converted = value * factor if factor is not None else None
    return converted if converted is not None and math.isfinite(converted) else None


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
    window: deque[tuple[datetime, float, float, float]] = deque()
    last: tuple[datetime, float, float, float] | None = None
    for row in sorted(_observations(run, part)):
        timestamp, current, position, command = row
        if last is not None and timestamp == last[0]:
            if row != last:
                window.clear()
            continue
        if last is not None and (timestamp - last[0]).total_seconds() > 1.5:
            window.clear()
        last = row
        if current < part.stall_current_a or abs(command - position) <= tolerance:
            window.clear()
            continue
        while window and (timestamp - window[0][0]).total_seconds() > 5:
            window.popleft()
        if window and abs(position - window[0][2]) > tolerance:
            window.clear()
        window.append(row)
        if len(window) >= 3 and (timestamp - window[0][0]).total_seconds() >= 0.5:
            return list(window)
    return []


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


def compare(baseline: RunManifest, candidate: RunManifest) -> dict[str, Any]:
    if baseline.robot_id != candidate.robot_id:
        raise ValueError("runs must belong to the same robot")
    divergences, insufficient = _divergences(baseline, candidate)
    return {
        "config_changes": _config_changes(baseline, candidate),
        "source_snapshots_changed": baseline.snapshots != candidate.snapshots,
        "divergences": divergences,
        "clamp_attributions": _clamps(baseline, candidate),
        "insufficient": insufficient,
    }
