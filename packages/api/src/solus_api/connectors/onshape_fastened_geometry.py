"""Select only native quarter-turn alignments that preserve a rigid assembly pose."""

from __future__ import annotations

import math
from typing import Any

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape_circle_geometry import _connector_frame, _number, _poses
from solus_api.connectors.onshape_mate_offsets import _path

_TOLERANCE = 1e-8


def _refuse() -> ConnectorError:
    return ConnectorError(
        "config_invalid",
        "Fastened mating requires coincident, antiparallel connector frames "
        "with a supported secondary alignment that preserves the observed pose",
    )


def _cross(left: list[float], right: list[float]) -> list[float]:
    return [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]


def _alignment(first: dict[str, list[float]], second: dict[str, list[float]]) -> str:
    z = [-v for v in second["axis"]]
    if (
        math.dist(first["origin"], second["origin"]) > _TOLERANCE
        or math.dist(first["axis"], z) > _TOLERANCE
    ):
        raise _refuse()
    for label, key, sign in (
        ("PLUS_X", "x_axis", 1),
        ("MINUS_X", "x_axis", -1),
        ("PLUS_Y", "y_axis", 1),
        ("MINUS_Y", "y_axis", -1),
    ):
        x = [sign * v for v in second[key]]
        if (
            math.dist(first["x_axis"], x) <= _TOLERANCE
            and math.dist(first["y_axis"], _cross(z, x)) <= _TOLERANCE
        ):
            return label
    raise _refuse()


def measure_fastened(root: dict[str, Any], first_id: str, second_id: str) -> dict[str, Any]:
    """Measure current native CS bases; do not guess rotations from circle normals."""
    first_path, second_path = _path(root, first_id), _path(root, second_id)
    if first_path == second_path:
        raise _refuse()
    poses = _poses(root)
    for path in (first_path, second_path):
        if any(len(other) > len(path) and other[: len(path)] == tuple(path) for other in poses):
            raise _refuse()
    first = _connector_frame(root, first_id, first_path, include_basis=True)
    second = _connector_frame(root, second_id, second_path, include_basis=True)
    for frame in (first, second):
        for key, values in frame.items():
            frame[key] = [_number(value) for value in values]
    return {
        "first_frame": first,
        "second_frame": second,
        "first_occurrence_path": first_path,
        "second_occurrence_path": second_path,
        "secondary_axis_alignment": _alignment(first, second),
    }
