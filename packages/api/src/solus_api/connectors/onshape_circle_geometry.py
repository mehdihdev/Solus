"""Measured complete-circle frames and independent native connector verification."""

import math
import re
from typing import Any

from solus_api.connectors.contracts import ConnectorError

_POSITION_TOL = 1e-8
_AXIS_TOL = 1e-8
_CIRCLE_TOL = 1e-10


def _invalid() -> ConnectorError:
    return ConnectorError(
        "api_error", "Complete circular geometry and rigid coordinate frames are required."
    )


def _number(value: Any) -> float:
    if type(value) not in (int, float):
        raise _invalid()
    try:
        result = float(value)
    except OverflowError:
        raise _invalid() from None
    if not math.isfinite(result):
        raise _invalid()
    return result


def _vector(value: Any) -> list[float]:
    if isinstance(value, dict):
        value = [value.get(key) for key in ("x", "y", "z")]
    if not isinstance(value, list) or len(value) != 3:
        raise _invalid()
    return [_number(item) for item in value]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _rigid(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 16:
        raise _invalid()
    matrix = [_number(item) for item in value]
    rows = [matrix[i : i + 3] for i in (0, 4, 8)]
    if any(abs(matrix[12 + i] - expected) > _AXIS_TOL for i, expected in enumerate((0, 0, 0, 1))):
        raise _invalid()
    for i, row in enumerate(rows):
        for j, other in enumerate(rows):
            if abs(_dot(row, other) - (1 if i == j else 0)) > _AXIS_TOL:
                raise _invalid()
    a, b, c = rows
    determinant = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )
    if abs(determinant - 1) > _AXIS_TOL:
        raise _invalid()
    return matrix


def _world(matrix: list[float], origin: list[float], axis: list[float]) -> dict[str, list[float]]:
    return {
        "origin": [_dot(matrix[i : i + 3], origin) + matrix[i + 3] for i in (0, 4, 8)],
        "axis": [_dot(matrix[i : i + 3], axis) for i in (0, 4, 8)],
    }


def _circle(edge: dict[str, Any]) -> tuple[list[float], list[float]]:
    curve, geometry = edge.get("curve"), edge.get("geometry")
    if (
        not isinstance(curve, dict)
        or not isinstance(geometry, dict)
        or curve.get("type") != "CIRCLE"
    ):
        raise _invalid()
    radius = _number(curve.get("radius"))
    origin, normal = _vector(curve.get("origin")), _vector(curve.get("normal"))
    sweep, length = _number(geometry.get("arcSweep")), _number(geometry.get("length"))
    if radius <= 0 or abs(_dot(normal, normal) - 1) > _AXIS_TOL:
        raise _invalid()
    if not math.isclose(abs(sweep), 2 * math.pi, rel_tol=1e-6, abs_tol=0):
        raise _invalid()
    if not math.isclose(length, 2 * math.pi * radius, rel_tol=1e-6, abs_tol=_CIRCLE_TOL):
        raise _invalid()
    start, end = _vector(geometry.get("startPoint")), _vector(geometry.get("endPoint"))
    if math.dist(start, end) > _CIRCLE_TOL:
        raise _invalid()
    for point in (start, end):
        delta = [a - b for a, b in zip(point, origin, strict=True)]
        if abs(_dot(delta, normal)) > _CIRCLE_TOL or not math.isclose(
            math.hypot(*delta), radius, rel_tol=1e-6, abs_tol=_CIRCLE_TOL
        ):
            raise _invalid()
    return origin, normal


def circle_frame(part: dict[str, Any], edge_id: str, transform: Any) -> dict[str, list[float]]:
    edges = part.get("edges")
    if str(part.get("type")).upper() != "SOLID" or not isinstance(edges, list):
        raise _invalid()
    matches = [edge for edge in edges if isinstance(edge, dict) and edge.get("id") == edge_id]
    if len(matches) != 1:
        raise _invalid()
    origin, axis = _circle(matches[0])
    return _world(_rigid(transform), origin, axis)


def _poses(root: dict[str, Any]) -> dict[tuple[str, ...], list[float]]:
    rows = root.get("occurrences")
    if not isinstance(rows, list):
        raise _invalid()
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise _invalid()
        path = row.get("path")
        if (
            not isinstance(path, list)
            or not path
            or any(not isinstance(p, str) or not p for p in path)
        ):
            raise _invalid()
        key = tuple(path)
        if key in result:
            raise _invalid()
        result[key] = _rigid(row.get("transform"))
    return result


def _connector_frame(
    root: dict[str, Any],
    identity: str,
    instance: str | tuple[str, ...] | list[str],
    *,
    include_basis: bool = False,
) -> dict[str, list[float]]:
    path = [instance] if isinstance(instance, str) else list(instance)
    if not 1 <= len(path) <= 8 or any(
        not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_+/-]{1,128}", item)
        for item in path
    ):
        raise _invalid()
    features = root.get("features")
    if not isinstance(features, list):
        raise _invalid()
    matches = [f for f in features if isinstance(f, dict) and f.get("id") == identity]
    if (
        len(matches) != 1
        or matches[0].get("featureType") != "mateConnector"
        or matches[0].get("suppressed") is not False
    ):
        raise _invalid()
    data = matches[0].get("featureData")
    if not isinstance(data, dict) or data.get("occurrence") != path:
        raise _invalid()
    cs = data.get("mateConnectorCS")
    if not isinstance(cs, dict):
        raise _invalid()
    origin = _vector(cs.get("origin"))
    axes = [_vector(cs.get(key)) for key in ("xAxis", "yAxis", "zAxis")]
    matrix = [value for i in range(3) for value in [*(axis[i] for axis in axes), origin[i]]]
    _rigid([*matrix, 0, 0, 0, 1])
    poses = _poses(root)
    if tuple(path) not in poses:
        raise _invalid()
    frame = _world(poses[tuple(path)], origin, axes[2])
    if include_basis:
        frame["x_axis"] = _world(poses[tuple(path)], origin, axes[0])["axis"]
        frame["y_axis"] = _world(poses[tuple(path)], origin, axes[1])["axis"]
    return frame


def verify_connector_frame(
    before: dict[str, Any],
    after: dict[str, Any],
    identity: str,
    instance: str | tuple[str, ...] | list[str],
    expected: dict[str, list[float]],
) -> dict[str, list[float]]:
    try:
        old, new = _poses(before), _poses(after)
        if old.keys() != new.keys() or any(
            any(abs(a - b) > _POSITION_TOL for a, b in zip(old[path], new[path], strict=True))
            for path in old
        ):
            raise _invalid()
        actual = _connector_frame(after, identity, instance)
        if (
            math.dist(actual["origin"], expected["origin"]) > _POSITION_TOL
            or min(
                math.dist(actual["axis"], expected["axis"]),
                math.dist(actual["axis"], [-value for value in expected["axis"]]),
            )
            > _AXIS_TOL
        ):
            raise _invalid()
        return actual
    except (ConnectorError, TypeError, ValueError, KeyError) as error:
        raise ConnectorError(
            "mutation_unverified",
            "The connector coordinate system or unchanged occurrence poses could not be verified. "
            "Inspect Onshape before retrying.",
        ) from error
