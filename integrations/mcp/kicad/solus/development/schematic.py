"""New-sheet and real-symbol operations with exact read-only planning."""

from dataclasses import asdict
from typing import Any

from solus.development.commit import parent_directory, read_at, read_schematic
from solus.development.common import (
    entity_uuid,
    finish,
    format_point,
    original_for,
    quoted,
    rotation,
    text,
    workspace,
)
from solus.development.common import (
    reference as valid_reference,
)
from solus.development.geometry import project_pin
from solus.development.library import LibraryResolver, _pins, installed_library_root
from solus.development.models import DevelopmentError, Point, fingerprint, validate_fingerprint
from solus.development.plan import MutationPlan
from solus.development.structural import children, document, insert_nodes
from solus.development.structural import value as node_value
from solus.write.sexpr import Node, parse


def create_schematic(
    schematic_path: str, title: str, expected_absent: bool, dry_run: bool = False
) -> dict[str, Any]:
    if expected_absent is not True:
        raise DevelopmentError("already_exists")
    text(title, 120)
    with parent_directory(workspace(), schematic_path) as (directory, name):
        if read_at(directory, name) is not None:
            raise DevelopmentError("already_exists")
    operation = {"operation": "create_schematic", "title": title}
    identity = entity_uuid(schematic_path, None, operation, "sheet")
    proposed = (
        b'(kicad_sch (version 20250114) (generator "solus") (generator_version "1.0") '
        + b"(uuid "
        + quoted(identity)
        + b') (paper "A4") (title_block (title '
        + quoted(title)
        + b')) (lib_symbols) (embedded_fonts no) (sheet_instances (path "/" (page "1"))))\n'
    )
    plan = MutationPlan.build(
        schematic_path,
        None,
        proposed,
        operation,
        [{"label": "Create schematic", "before": None, "after": title}],
    )
    return finish(plan, dry_run, [{"kind": "sheet", "uuid": identity}])


def get_symbol_definition(library_id: str) -> dict[str, Any]:
    definition = LibraryResolver(installed_library_root()).resolve(library_id)
    units = sorted({pin.unit for pin in definition.pins})
    return {
        "library_id": library_id,
        "library_fingerprint": definition.library_fingerprint,
        "units": [
            {
                "unit": unit,
                "pins": [
                    {key: value for key, value in asdict(pin).items() if key != "unit"}
                    for pin in definition.pins
                    if pin.unit == unit
                ],
            }
            for unit in units
        ],
        "default_reference": definition.default_reference,
        "default_value": definition.default_value,
        "footprint": definition.footprint,
    }


def _one(parent: Node, key: str) -> Node:
    nodes = children(parent, key)
    if len(nodes) != 1:
        raise DevelopmentError("ambiguous_target")
    return nodes[0]


def _point(node: Node) -> Point:
    try:
        return Point.from_dict(
            {"x_mm": float(node_value(node)), "y_mm": float(node_value(node, 2))}
        )
    except ValueError as exc:
        raise DevelopmentError("invalid_geometry") from exc


def _symbol_geometry(root: Node, symbol: Node) -> dict[str, Any]:
    props = {node_value(prop): node_value(prop, 2) for prop in children(symbol, "property")}
    library_id = node_value(_one(symbol, "lib_id"))
    definitions = children(_one(root, "lib_symbols"), "symbol")
    matches = [node for node in definitions if node_value(node) == library_id]
    if len(matches) != 1 or children(matches[0], "extends") or children(symbol, "mirror"):
        raise DevelopmentError("unsupported_symbol")
    placement = _one(symbol, "at")
    at = _point(placement)
    try:
        angle = rotation(int(node_value(placement, 3)))
        unit = int(node_value(_one(symbol, "unit")))
    except ValueError as exc:
        raise DevelopmentError("invalid_geometry") from exc
    pins = []
    for pin in _pins(matches[0]):
        if pin.unit not in (0, unit):
            continue
        point = project_pin(pin, at, angle)
        pins.append(
            {
                "number": pin.number,
                "name": pin.name,
                "electrical_type": pin.electrical_type,
                "x_mm": point.x_mm,
                "y_mm": point.y_mm,
            }
        )
    if len({pin["number"] for pin in pins}) != len(pins):
        raise DevelopmentError("ambiguous_target")
    return {
        "reference": props["Reference"],
        "library_id": library_id,
        "unit": unit,
        "x_mm": at.x_mm,
        "y_mm": at.y_mm,
        "rotation_deg": angle,
        "pins": pins,
    }


def geometry(data: bytes, schematic_path: str, reference: str | None = None) -> dict[str, Any]:
    root = document(data)
    require_supported_topology(root)
    symbols = [_symbol_geometry(root, node) for node in children(root, "symbol")]
    if reference is not None:
        valid_reference(reference)
        symbols = [symbol for symbol in symbols if symbol["reference"] == reference]
        if not symbols:
            raise DevelopmentError("not_found")
    wires: list[dict[str, Any]] = []
    for wire in children(root, "wire"):
        points = children(_one(wire, "pts"), "xy")
        if len(points) != 2:
            raise DevelopmentError("invalid_geometry")
        wires.append(
            {
                "uuid": node_value(_one(wire, "uuid")),
                "start": asdict(_point(points[0])),
                "end": asdict(_point(points[1])),
            }
        )
    labels: list[dict[str, Any]] = [
        {"name": node_value(label), "at": asdict(_point(_one(label, "at")))}
        for label in children(root, "label")
    ]
    if reference is not None:
        locations = {(pin["x_mm"], pin["y_mm"]) for symbol in symbols for pin in symbol["pins"]}
        wires = [
            wire
            for wire in wires
            if any((wire[end]["x_mm"], wire[end]["y_mm"]) in locations for end in ("start", "end"))
        ]
        labels = [
            label for label in labels if (label["at"]["x_mm"], label["at"]["y_mm"]) in locations
        ]
    return {
        "schematic_path": schematic_path,
        "fingerprint": fingerprint(data),
        "sheet_uuid": node_value(_one(root, "uuid")),
        "symbols": symbols,
        "wires": wires,
        "labels": labels,
    }


def get_schematic_geometry(schematic_path: str, reference: str | None = None) -> dict[str, Any]:
    result = geometry(read_schematic(workspace(), schematic_path), schematic_path, reference)
    import json

    if len(json.dumps(result).encode()) > 16 * 1024:
        raise DevelopmentError("file_too_large")
    return result


def _property(name: str, value: str, at: Point, *, hidden: bool = False) -> bytes:
    return (
        b"(property "
        + quoted(name)
        + b" "
        + quoted(value)
        + f" (at {format_point(at)} 0)".encode()
        + (b" (hide yes)" if hidden else b"")
        + b" (effects (font (size 1.27 1.27))"
        + (b"" if hidden else b" (justify left)")
        + b"))"
    )


def _field_positions(placement: Point, pins: list[Point]) -> tuple[Point, Point]:
    # Keep readable horizontal fields outside the transformed pin envelope. This
    # also works for single-point power flags and libraries without field layout.
    top = min((pin.y_mm for pin in pins), default=placement.y_mm)
    if top >= 6.35:
        reference_y, value_y = top - 6.35, top - 3.81
    else:
        bottom = max((pin.y_mm for pin in pins), default=placement.y_mm)
        reference_y, value_y = bottom + 3.81, bottom + 6.35
    # Leave the vertical pin/wire column clear for two-pin passives.
    label_x = min(placement.x_mm + 5.08, 1000)
    return (
        Point.from_saved({"x_mm": label_x, "y_mm": reference_y}),
        Point.from_saved({"x_mm": label_x, "y_mm": value_y}),
    )


def add_symbol(
    schematic_path: str,
    expected_fingerprint: str,
    library_id: str,
    library_fingerprint: str,
    reference: str,
    value: str,
    at: dict[str, float],
    rotation_deg: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    original = original_for(schematic_path, expected_fingerprint)
    valid_reference(reference)
    text(value, 120, allow_empty=True)
    placement, angle = Point.from_dict(at), rotation(rotation_deg)
    definition = LibraryResolver(installed_library_root()).resolve(library_id)
    if definition.library_fingerprint != validate_fingerprint(library_fingerprint):
        raise DevelopmentError("stale_plan")
    if len(definition.definitions) != 1 or any(pin.unit not in (0, 1) for pin in definition.pins):
        raise DevelopmentError("unsupported_symbol")
    root = document(original)
    existing = geometry(original, schematic_path)
    if any(symbol["reference"] == reference for symbol in existing["symbols"]):
        raise DevelopmentError("ambiguous_target")
    _check_placement(
        existing, root, [project_pin(pin, placement, angle) for pin in definition.pins]
    )
    operation = {
        "operation": "add_symbol",
        "library_id": library_id,
        "library_fingerprint": library_fingerprint,
        "reference": reference,
        "value": value,
        "at": at,
        "rotation_deg": angle,
    }
    identity = entity_uuid(schematic_path, original, operation, "symbol")
    raw = definition.definitions[0]
    name_token = parse(raw).children[1]
    embedded = raw[: name_token.start] + quoted(library_id) + raw[name_token.end :]
    matches = [
        node
        for node in children(_one(root, "lib_symbols"), "symbol")
        if node_value(node) == library_id
    ]
    if matches and original[matches[0].start : matches[0].end] != embedded:
        raise DevelopmentError("unsupported_symbol")
    reference_at, value_at = _field_positions(
        placement, [project_pin(pin, placement, angle) for pin in definition.pins]
    )
    datasheets = [
        node_value(prop, 2)
        for prop in children(parse(raw), "property")
        if node_value(prop) == "Datasheet"
    ]
    if len(datasheets) > 1:
        raise DevelopmentError("unsupported_symbol")
    props = b" ".join(
        [
            _property("Reference", reference, reference_at),
            _property("Value", value, value_at),
            _property("Footprint", definition.footprint, placement, hidden=True),
            _property("Datasheet", datasheets[0] if datasheets else "", placement, hidden=True),
        ]
    )
    pin_nodes = b" ".join(
        b"(pin "
        + quoted(pin.number)
        + b" (uuid "
        + quoted(entity_uuid(schematic_path, original, operation, "pin:" + pin.number))
        + b"))"
        for pin in definition.pins
    )
    sheet_uuid = node_value(_one(root, "uuid"))
    from pathlib import PurePosixPath

    project_name = PurePosixPath(schematic_path).stem
    # Close lib_id before the placement; all remaining bytes are generated nodes.
    instance = (
        b"(symbol (lib_id "
        + quoted(library_id)
        + b")"
        + f" (at {format_point(placement)} {angle})".encode()
    )
    instance += (
        b" (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid "
        + quoted(identity)
        + b") "
        + props
        + b" "
        + pin_nodes
        + b" (instances (project "
        + quoted(project_name)
        + b" (path "
        + quoted("/" + sheet_uuid)
        + b" (reference "
        + quoted(reference)
        + b") (unit 1)))))"
    )
    rows: list[dict[str, Any]] = [
        {"label": "Add symbol", "before": None, "after": f"{reference}: {library_id} = {value}"},
        {
            "label": "Placement",
            "before": None,
            "after": f"{format_point(placement, ', ')} mm; {angle}°",
        },
        {
            "label": "Library fingerprint",
            "before": library_fingerprint,
            "after": library_fingerprint,
        },
        {"label": "Library footprint", "before": None, "after": definition.footprint or None},
    ]
    for pin in definition.pins:
        position = project_pin(pin, placement, angle)
        rows.append(
            {
                "label": f"{reference} pin {pin.number}",
                "before": None,
                "after": (
                    f"{pin.name} ({pin.electrical_type}) at {format_point(position, ', ')} mm"
                ),
            }
        )
    proposed = insert_nodes(
        original, root_nodes=[instance], library_nodes=[] if matches else [embedded]
    )
    plan = MutationPlan.build(schematic_path, original, proposed, operation, rows)
    return finish(plan, dry_run, [{"kind": "symbol", "uuid": identity, "reference": reference}])


def _check_placement(existing: dict[str, Any], root: Node, positions: list[Point]) -> None:
    from solus.development.geometry import on_segment

    occupied = {
        Point(pin["x_mm"], pin["y_mm"]) for symbol in existing["symbols"] for pin in symbol["pins"]
    }
    occupied.update(Point.from_saved(label["at"]) for label in existing["labels"])
    occupied.update(_point(_one(node, "at")) for node in children(root, "no_connect"))
    if len(set(positions)) != len(positions) or any(point in occupied for point in positions):
        raise DevelopmentError("invalid_geometry")
    for wire in existing["wires"]:
        if any(
            on_segment(point, Point.from_saved(wire["start"]), Point.from_saved(wire["end"]))
            for point in positions
        ):
            raise DevelopmentError("invalid_geometry")


def require_supported_topology(root: Node) -> None:
    unsupported = {"global_label", "hierarchical_label", "sheet", "bus", "bus_entry", "junction"}
    if any(children(root, name) for name in unsupported):
        raise DevelopmentError("unsupported_symbol")
