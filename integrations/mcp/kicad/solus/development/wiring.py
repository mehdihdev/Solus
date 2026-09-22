"""Explicit pin/wire endpoint edits; no guessed junctions or auto-routing."""

import uuid
from typing import Any

from solus.development.common import (
    entity_uuid,
    finish,
    format_point,
    original_for,
    quoted,
    reference,
    rotation,
    text,
)
from solus.development.geometry import on_segment as _on
from solus.development.models import DevelopmentError, Point
from solus.development.plan import MutationPlan
from solus.development.schematic import _one, _point, geometry
from solus.development.structural import children, document, insert_nodes


def _pin(data: dict[str, Any], target: Any) -> tuple[Point, str]:
    if not isinstance(target, dict) or set(target) != {"reference", "pin_number"}:
        raise DevelopmentError("invalid_geometry")
    ref = reference(target["reference"])
    number = text(target["pin_number"], 32)
    matches = [
        pin
        for symbol in data["symbols"]
        if symbol["reference"] == ref
        for pin in symbol["pins"]
        if pin["number"] == number
    ]
    if len(matches) != 1:
        raise DevelopmentError("ambiguous_target")
    pin = matches[0]
    return Point(pin["x_mm"], pin["y_mm"]), f"{ref} pin {number} ({pin['name']})"


def _anchor(data: dict[str, Any], target: Any) -> tuple[Point, str]:
    if not isinstance(target, dict):
        raise DevelopmentError("invalid_geometry")
    if set(target) == {"pin"}:
        return _pin(data, target["pin"])
    if (
        set(target) != {"wire_uuid", "endpoint"}
        or type(target["endpoint"]) is not int
        or target["endpoint"] not in (0, 1)
    ):
        raise DevelopmentError("invalid_geometry")
    try:
        identity = str(uuid.UUID(target["wire_uuid"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise DevelopmentError("invalid_geometry") from exc
    if identity != target["wire_uuid"]:
        raise DevelopmentError("invalid_geometry")
    matches = [wire for wire in data["wires"] if wire["uuid"] == identity]
    if len(matches) != 1:
        raise DevelopmentError("ambiguous_target")
    endpoint = "start" if target["endpoint"] == 0 else "end"
    return Point.from_saved(matches[0][endpoint]), f"wire {identity} {endpoint}"


def anchor(data: dict[str, Any], target: Any) -> tuple[Point, str]:
    point, description = _anchor(data, target)
    names = sorted(
        {entry["name"] for entry in data["labels"] if Point.from_saved(entry["at"]) == point}
    )
    if names:
        description += " [net: " + ", ".join(names) + "]"
    return point, description


def _intersections(a: Point, b: Point, c: Point, d: Point) -> set[Point]:
    points = {p for p in (a, b, c, d) if _on(p, a, b) and _on(p, c, d)}
    crossing = Point(a.x_mm, c.y_mm) if a.x_mm == b.x_mm else Point(c.x_mm, a.y_mm)
    if _on(crossing, a, b) and _on(crossing, c, d):
        points.add(crossing)
    return points


def _markers(original: bytes) -> set[Point]:
    return {_point(_one(node, "at")) for node in children(document(original), "no_connect")}


def _safe_route(data: dict[str, Any], points: list[Point], markers: set[Point]) -> None:
    segments = list(zip(points, points[1:], strict=False))
    endpoints = {points[0], points[-1]}
    pins = {Point(pin["x_mm"], pin["y_mm"]) for symbol in data["symbols"] for pin in symbol["pins"]}
    pins.update(Point.from_saved(label["at"]) for label in data["labels"])
    for index, (start, end) in enumerate(segments):
        if start == end or (start.x_mm != end.x_mm and start.y_mm != end.y_mm):
            raise DevelopmentError("invalid_geometry")
        if any(_on(point, start, end) for point in markers) or any(
            _on(point, start, end) for point in pins - endpoints
        ):
            raise DevelopmentError("invalid_geometry")
        for wire in data["wires"]:
            a, b = Point.from_saved(wire["start"]), Point.from_saved(wire["end"])
            cross = _intersections(start, end, a, b)
            if cross and (len(cross) != 1 or not cross <= endpoints or not cross <= {a, b}):
                raise DevelopmentError("invalid_geometry")
        for prior, (a, b) in enumerate(segments[:index]):
            cross = _intersections(start, end, a, b)
            if cross and not (prior == index - 1 and cross == {start}):
                raise DevelopmentError("invalid_geometry")


def add_wire(
    schematic_path: str,
    expected_fingerprint: str,
    start: dict[str, Any],
    end: dict[str, Any],
    via: list[dict[str, float]] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    original = original_for(schematic_path, expected_fingerprint)
    data = geometry(original, schematic_path)
    first, first_label = anchor(data, start)
    last, last_label = anchor(data, end)
    if via is not None and (not isinstance(via, list) or len(via) > 31):
        raise DevelopmentError("invalid_geometry")
    points = [first] + [Point.from_dict(p) for p in via or []] + [last]
    _safe_route(data, points, _markers(original))
    operation = {"operation": "add_wire", "start": start, "end": end, "via": via or []}
    nodes, created, rows = (
        [],
        [],
        [{"label": "Connect pins", "before": None, "after": first_label + " → " + last_label}],
    )
    for index, (a, b) in enumerate(zip(points, points[1:], strict=False)):
        identity = entity_uuid(schematic_path, original, operation, f"wire:{index}")
        nodes.append(
            (
                f"(wire (pts (xy {format_point(a)}) (xy {format_point(b)})) "
                f'(stroke (width 0) (type default)) (uuid "{identity}"))'
            ).encode()
        )
        created.append({"kind": "wire", "uuid": identity})
        rows.append(
            {
                "label": f"Segment {index + 1}",
                "before": None,
                "after": f"{format_point(a, ', ')} → {format_point(b, ', ')} mm",
            }
        )
    plan = MutationPlan.build(
        schematic_path, original, insert_nodes(original, root_nodes=nodes), operation, rows
    )
    return finish(plan, dry_run, created)


def add_net_label(
    schematic_path: str,
    expected_fingerprint: str,
    name: str,
    anchor: dict[str, Any],
    rotation_deg: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    original = original_for(schematic_path, expected_fingerprint)
    data = geometry(original, schematic_path)
    point, label = resolve_anchor(data, anchor)
    text(name, 80)
    angle = rotation(rotation_deg)
    if point in _markers(original):
        raise DevelopmentError("invalid_geometry")
    present = [entry for entry in data["labels"] if Point.from_saved(entry["at"]) == point]
    if any(entry["name"] != name for entry in present):
        raise DevelopmentError("invalid_geometry")
    operation = {
        "operation": "add_net_label",
        "name": name,
        "anchor": anchor,
        "rotation_deg": angle,
    }
    identity = entity_uuid(schematic_path, original, operation, "label")
    node = (
        b"(label "
        + quoted(name)
        + (
            f" (at {format_point(point)} {angle}) "
            f'(effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "{identity}"))'
        ).encode()
    )
    proposed = original if present else insert_nodes(original, root_nodes=[node])
    rows = [
        {
            "label": "Net label",
            "before": name if present else None,
            "after": f"{name} at {label}; {format_point(point, ', ')} mm",
        },
        {
            "label": "Connectivity",
            "before": None,
            "after": f"Joins all local labels named {name} on this sheet",
        },
    ]
    return finish(
        MutationPlan.build(schematic_path, original, proposed, operation, rows),
        dry_run,
        [] if present else [{"kind": "label", "uuid": identity}],
    )


# Avoid shadowing the exact-anchor resolver with the public tool argument.
resolve_anchor = anchor


def mark_no_connect(
    schematic_path: str, expected_fingerprint: str, pin: dict[str, str], dry_run: bool = False
) -> dict[str, Any]:
    original = original_for(schematic_path, expected_fingerprint)
    data = geometry(original, schematic_path)
    point, label = _pin(data, pin)
    if any(
        _on(point, Point.from_saved(w["start"]), Point.from_saved(w["end"])) for w in data["wires"]
    ) or any(Point.from_saved(entry["at"]) == point for entry in data["labels"]):
        raise DevelopmentError("invalid_geometry")
    present = point in _markers(original)
    operation = {"operation": "mark_no_connect", "pin": pin}
    identity = entity_uuid(schematic_path, original, operation, "no_connect")
    node = f'(no_connect (at {format_point(point)}) (uuid "{identity}"))'.encode()
    proposed = original if present else insert_nodes(original, root_nodes=[node])
    rows = [
        {"label": "Intentionally unused pin", "before": label if present else None, "after": label}
    ]
    return finish(
        MutationPlan.build(schematic_path, original, proposed, operation, rows),
        dry_run,
        [] if present else [{"kind": "no_connect", "uuid": identity}],
    )
