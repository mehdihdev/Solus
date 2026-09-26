"""Pure bounded XML normalization. Mesh references never become I/O instructions."""

import json
import math
import xml.etree.ElementTree as ET
from typing import Any

from .meshes import MAX_BYTES, MeshCatalog


def vector(value: str | None, default: list[float], count: int | None = None) -> list[float]:
    result = default if value is None else [float(v) for v in value.split()]
    if len(result) != (count or len(default)) or any(
        not math.isfinite(v) or abs(v) > 1e6 for v in result
    ):
        raise ValueError("Invalid bounded coordinate")
    return result


def name(value: str | None) -> str:
    if not value or len(value) > 128 or any(ord(c) < 32 for c in value):
        raise ValueError("Missing or invalid name")
    return value


def mjcf_rpy(angles: list[float]) -> list[float]:
    """Convert intrinsic xyz (Rx Ry Rz) into fixed-axis URDF Rz Ry Rx."""
    a, b, c = angles
    sa, ca, sb, cb, sc, cc = (
        math.sin(a),
        math.cos(a),
        math.sin(b),
        math.cos(b),
        math.sin(c),
        math.cos(c),
    )
    pitch = math.asin(max(-1.0, min(1.0, ca * sb * cc - sa * sc)))
    if abs(math.cos(pitch)) < 1e-10:
        return [0.0, pitch, math.atan2(cb * sc, ca * cc - sa * sb * sc)]
    return [
        math.atan2(sa * cc + ca * sb * sc, ca * cb),
        pitch,
        math.atan2(ca * sc + sa * sb * cc, cb * cc),
    ]


def pose(element: ET.Element | None, mjcf: bool = False) -> dict[str, Any]:
    if element is None:
        return {"xyz": [0, 0, 0], "rpy": [0, 0, 0]}
    if mjcf and any(
        k in element.attrib for k in ("quat", "axisangle", "xyaxes", "zaxis", "fromto")
    ):
        raise ValueError("Use explicit Euler coordinates")
    angles = vector(element.get("euler" if mjcf else "rpy"), [0, 0, 0])
    return {
        "xyz": vector(element.get("pos" if mjcf else "xyz"), [0, 0, 0]),
        "rpy": mjcf_rpy(angles) if mjcf else angles,
    }


def visuals(
    link: ET.Element, warnings: list[str], catalog: MeshCatalog, mjcf: bool = False
) -> list[dict[str, Any]]:
    result = []
    for visual in link.findall("geom" if mjcf else "visual"):
        geometry = visual if mjcf else visual.find("geometry")
        if geometry is None or (not mjcf and len(geometry) != 1):
            raise ValueError("One geometry required")
        item = geometry if mjcf else geometry[0]
        kind = item.get("type", "sphere") if mjcf else item.tag
        mesh_info: dict[str, Any] = {}
        if kind == "mesh" or (mjcf and item.get("mesh")):
            kind, size = "mesh", []
            mesh_info = catalog.visual(item, mjcf, warnings)
        elif kind == "box":
            size = vector(item.get("size"), [1, 1, 1])
            if mjcf:
                size = [v * 2 for v in size]
        elif kind == "sphere":
            size = vector(item.get("size" if mjcf else "radius"), [1])
        elif kind == "cylinder":
            size = (
                vector(item.get("size"), [1, 1])
                if mjcf
                else [float(item.get("radius", "nan")), float(item.get("length", "nan"))]
            )
            if mjcf:
                size[1] *= 2
        else:
            raise ValueError("Unsupported geometry")
        if any(not math.isfinite(v) or v <= 0 or v > 1e6 for v in size):
            raise ValueError("Invalid geometry dimensions")
        result.append(
            {
                "kind": kind,
                "size": size,
                **mesh_info,
                **pose(visual if mjcf else visual.find("origin"), mjcf),
            }
        )
    return result


def joint(
    element: ET.Element, parent: str, child: str, origin: dict[str, Any], mjcf: bool = False
) -> dict[str, Any]:
    kind = element.get("type", "hinge" if mjcf else "")
    kind = {"hinge": "revolute", "slide": "prismatic"}.get(kind, kind) if mjcf else kind
    if kind not in ("fixed", "revolute", "continuous", "prismatic"):
        raise ValueError("Unsupported joint type")
    if element.find("mimic") is not None or (mjcf and element.get("ref") is not None):
        raise ValueError("Joint reference/mimic coordinates require explicit normalization")
    axis_element = element.find("axis")
    axis = vector(
        element.get("axis")
        if mjcf
        else axis_element.get("xyz")
        if axis_element is not None
        else None,
        [0, 0, 1] if mjcf else [1, 0, 0],
    )
    norm = math.sqrt(sum(v * v for v in axis))
    if norm < 1e-12:
        raise ValueError("Zero joint axis")
    lower = upper = None
    if kind in ("revolute", "prismatic"):
        limit = element.find("limit")
        if mjcf:
            if element.get("range") is None:
                if kind == "revolute" and element.get("limited") == "false":
                    kind = "continuous"
                else:
                    raise ValueError("Explicit joint range required")
            else:
                lower, upper = vector(element.get("range"), [0, 0])
        elif limit is not None:
            lower, upper = vector(
                f"{limit.get('lower', 'nan')} {limit.get('upper', 'nan')}", [0, 0]
            )
        else:
            raise ValueError("Joint limits required")
        if lower is not None and upper is not None and lower > upper:
            raise ValueError("Reversed joint limits")
    return {
        "name": name(element.get("name")),
        "type": kind,
        "parent": parent,
        "child": child,
        **origin,
        "axis": [v / norm for v in axis],
        "lower": lower,
        "upper": upper,
    }


def _urdf(
    root: ET.Element, warnings: list[str], catalog: MeshCatalog
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    joints: list[dict[str, Any]] = []
    links = [
        {"name": name(link.get("name")), "visuals": visuals(link, warnings, catalog)}
        for link in root.findall("link")
    ]
    for item in root.findall("joint"):
        parent, child = item.find("parent"), item.find("child")
        if parent is None or child is None:
            raise ValueError("Missing joint link")
        joints.append(
            joint(
                item,
                name(parent.get("link")),
                name(child.get("link")),
                pose(item.find("origin")),
            )
        )
    return links, joints


def _mjcf(
    root: ET.Element, warnings: list[str], catalog: MeshCatalog
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    links: list[dict[str, Any]] = []
    joints: list[dict[str, Any]] = []
    compiler = root.find("compiler")
    if (
        compiler is None
        or compiler.get("angle") != "radian"
        or compiler.get("coordinate", "local") != "local"
        or compiler.get("eulerseq", "xyz") != "xyz"
    ):
        raise ValueError("MJCF requires explicit radians and local xyz Euler coordinates")
    world = root.find("worldbody")
    if world is None:
        raise ValueError("Missing worldbody")
    pending: list[tuple[ET.Element, str | None]] = [(body, None) for body in world.findall("body")]
    while pending:
        body, parent_name = pending.pop(0)
        body_name = name(body.get("name"))
        links.append({"name": body_name, "visuals": visuals(body, warnings, catalog, True)})
        items = body.findall("joint")
        if body.find("freejoint") is not None or len(items) > 1:
            raise ValueError("Unsupported multiaxis/free body")
        if parent_name is None:
            if items or pose(body, True) != pose(None):
                raise ValueError("Root body must have identity pose and no joint")
        else:
            if items:
                if vector(items[0].get("pos"), [0, 0, 0]) != [0, 0, 0]:
                    raise ValueError("Joint offset requires normalized body coordinates")
                joints.append(joint(items[0], parent_name, body_name, pose(body, True), True))
            else:
                joints.append(
                    joint(
                        ET.Element("joint", name=f"{body_name}:fixed", type="fixed"),
                        parent_name,
                        body_name,
                        pose(body, True),
                    )
                )
        pending.extend((child, body_name) for child in body.findall("body"))
    return links, joints


def parse_model(
    content: bytes, format: str, meshes: dict[str, bytes] | None = None
) -> dict[str, Any]:
    if len(content) > 1048576 or b"<!" in content or b"\x00" in content:
        raise ValueError("Unsafe or oversized XML")
    try:
        root = ET.fromstring(content)  # noqa: S314 — DTD/entities and non-UTF8 XML refused above
    except ET.ParseError:
        raise ValueError("Malformed XML") from None
    stack = [(root, 0)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if (
            depth > 32
            or count > 4096
            or node.tag
            in ("include", "plugin", "extension", "default", "script", "composite", "flexcomp")
        ):
            raise ValueError("Unsupported or oversized XML structure")
        stack.extend((child, depth + 1) for child in node)
    if len(content) + sum(map(len, (meshes or {}).values())) > MAX_BYTES:
        raise ValueError("Model asset byte limit exceeded")
    catalog = MeshCatalog(root, meshes or {})
    links: list[dict[str, Any]] = []
    joints: list[dict[str, Any]] = []
    warnings: list[str] = []
    if format == "urdf" and root.tag == "robot":
        links, joints = _urdf(root, warnings, catalog)
    elif format == "mjcf" and root.tag == "mujoco":
        links, joints = _mjcf(root, warnings, catalog)
    else:
        raise ValueError("Model format does not match XML")
    _validate_tree(links, joints, warnings)
    result = {
        "links": links,
        "joints": joints,
        "warnings": list(dict.fromkeys(warnings)),
        "meshes": catalog.finish(),
    }
    if len(json.dumps(result).encode()) > MAX_BYTES:
        raise ValueError("Normalized geometry exceeds output limit")
    return result


def _validate_tree(
    links: list[dict[str, Any]], joints: list[dict[str, Any]], warnings: list[str]
) -> None:
    names = {link["name"] for link in links}
    if (
        not links
        or len(links) > 128
        or len(joints) > 128
        or len(names) != len(links)
        or sum(len(link["visuals"]) for link in links) > 512
    ):
        raise ValueError("Duplicate or excessive links/geometry")
    if len({j["name"] for j in joints}) != len(joints):
        raise ValueError("Duplicate joints")
    parents: dict[str, str] = {}
    for edge in joints:
        if edge["parent"] not in names or edge["child"] not in names or edge["child"] in parents:
            raise ValueError("Missing link or ambiguous parent")
        parents[edge["child"]] = edge["parent"]
    for cursor in parents:
        visited: set[str] = set()
        while cursor in parents:
            if cursor in visited:
                raise ValueError("Cyclic model")
            visited.add(cursor)
            cursor = parents[cursor]
    if not any(j["type"] != "fixed" for j in joints):
        warnings.append("Jointless model: no movable joints are available for telemetry mapping.")
