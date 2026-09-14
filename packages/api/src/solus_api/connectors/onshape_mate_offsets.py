"""Pose-preserving revolute offsets and measured primary-axis flip selection."""

from __future__ import annotations

import math
from typing import Any

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape_circle_geometry import _connector_frame, _number, _poses

_TOLERANCE = 1e-8
_NATIVE_OFFSET_BOUND_M = 500


def _refuse() -> ConnectorError:
    return ConnectorError(
        "config_invalid",
        "Revolute offset requires distinct coaxial connector frames "
        "and an offset matching their observed separation",
    )


def _path(root: dict[str, Any], identity: str) -> list[str]:
    features = root.get("features")
    if not isinstance(features, list) or not isinstance(identity, str) or not identity:
        raise _refuse()
    matches = [row for row in features if isinstance(row, dict) and row.get("id") == identity]
    if len(matches) != 1 or not isinstance(matches[0].get("featureData"), dict):
        raise _refuse()
    path = matches[0]["featureData"].get("occurrence")
    if not isinstance(path, list) or not path or any(not isinstance(p, str) for p in path):
        raise _refuse()
    return path


def _leaf_frames(
    root: dict[str, Any], first: str, second: str
) -> tuple[list[str], list[str], dict[str, list[float]], dict[str, list[float]]]:
    paths = [_path(root, identity) for identity in (first, second)]
    if paths[0] == paths[1]:
        raise _refuse()
    poses = _poses(root)
    for path in paths:
        if any(len(other) > len(path) and other[: len(path)] == tuple(path) for other in poses):
            raise _refuse()
    frames = [
        _connector_frame(root, identity, path)
        for identity, path in zip((first, second), paths, strict=True)
    ]
    for frame in frames:
        for key in ("origin", "axis"):
            frame[key] = [_number(value) for value in frame[key]]
    return paths[0], paths[1], frames[0], frames[1]


def measure_revolute_offset(
    root: dict[str, Any],
    first_connector_id: str,
    second_connector_id: str,
    requested_offset_m: float | None,
) -> dict[str, Any]:
    """Measure second-to-first along first Z and flip only opposite primary axes."""
    first_path, second_path, first, second = _leaf_frames(
        root, first_connector_id, second_connector_id
    )
    opposite = math.dist(first["axis"], [-v for v in second["axis"]]) <= _TOLERANCE
    if not opposite and math.dist(first["axis"], second["axis"]) > _TOLERANCE:
        raise _refuse()
    delta = [_number(a - b) for a, b in zip(first["origin"], second["origin"], strict=True)]
    measured = _number(sum(d * z for d, z in zip(delta, first["axis"], strict=True)))
    residual = [_number(d - measured * z) for d, z in zip(delta, first["axis"], strict=True)]
    if math.hypot(*residual) > _TOLERANCE or abs(measured) > _NATIVE_OFFSET_BOUND_M:
        raise _refuse()
    applied = measured
    if requested_offset_m is None:
        if math.hypot(*delta) > _TOLERANCE:
            raise _refuse()
        applied = 0.0
    else:
        requested = _number(requested_offset_m)
        if abs(requested) > _NATIVE_OFFSET_BOUND_M or abs(requested - measured) > _TOLERANCE:
            raise _refuse()
    return {
        "first_frame": first,
        "second_frame": second,
        "first_occurrence_path": first_path,
        "second_occurrence_path": second_path,
        "measured_offset_m": measured,
        "applied_offset_m": applied,
        "primary_axis_alignment": opposite,
    }


def verify_revolute_poses(before: dict[str, Any], after: dict[str, Any]) -> None:
    """A created mate is verified only when every observed occurrence pose is retained."""
    try:
        old, new = _poses(before), _poses(after)
        if old.keys() != new.keys() or any(
            any(abs(a - b) > _TOLERANCE for a, b in zip(old[path], new[path], strict=True))
            for path in old
        ):
            raise _refuse()
    except (
        ConnectorError,
        TypeError,
        ValueError,
        KeyError,
        AttributeError,
        OverflowError,
    ) as error:
        raise ConnectorError(
            "mutation_unverified",
            "The revolute mate may have been created, but unchanged "
            "assembly poses could not be verified. Inspect Onshape before retrying.",
        ) from error
