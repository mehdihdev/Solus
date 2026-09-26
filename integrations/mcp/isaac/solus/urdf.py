"""Bounded declarative URDF validation before any vendor importer sees input."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

from .models import Model, safe_path

_ALLOWED = {
    "robot",
    "link",
    "joint",
    "parent",
    "child",
    "origin",
    "axis",
    "limit",
    "dynamics",
    "inertial",
    "mass",
    "inertia",
    "visual",
    "collision",
    "geometry",
    "box",
    "cylinder",
    "sphere",
    "mesh",
    "material",
    "color",
}
_NUMERIC = {
    "xyz",
    "rpy",
    "lower",
    "upper",
    "effort",
    "velocity",
    "damping",
    "friction",
    "value",
    "ixx",
    "ixy",
    "ixz",
    "iyy",
    "iyz",
    "izz",
    "size",
    "radius",
    "length",
    "scale",
    "rgba",
}

_ATTRIBUTES = {
    "robot": {"name"},
    "link": {"name"},
    "joint": {"name", "type"},
    "parent": {"link"},
    "child": {"link"},
    "origin": {"xyz", "rpy"},
    "axis": {"xyz"},
    "limit": {"lower", "upper", "effort", "velocity"},
    "dynamics": {"damping", "friction"},
    "inertial": set(),
    "mass": {"value"},
    "inertia": {"ixx", "ixy", "ixz", "iyy", "iyz", "izz"},
    "visual": {"name"},
    "collision": {"name"},
    "geometry": set(),
    "box": {"size"},
    "cylinder": {"radius", "length"},
    "sphere": {"radius"},
    "mesh": {"filename", "scale"},
    "material": {"name"},
    "color": {"rgba"},
}
_CHILDREN = {
    "robot": {"link", "joint", "material"},
    "link": {"inertial", "visual", "collision"},
    "joint": {"parent", "child", "origin", "axis", "limit", "dynamics"},
    "inertial": {"mass", "inertia", "origin"},
    "visual": {"origin", "geometry", "material"},
    "collision": {"origin", "geometry"},
    "geometry": {"box", "cylinder", "sphere", "mesh"},
    "material": {"color"},
}


def _structure(element: ET.Element) -> None:
    if set(element.attrib) - _ATTRIBUTES[element.tag]:
        raise ValueError("unsupported URDF attribute")
    tags = [child.tag for child in element]
    if set(tags) - _CHILDREN.get(element.tag, set()):
        raise ValueError("unsupported URDF nesting")
    repeatable = (
        {"link", "joint", "material"}
        if element.tag == "robot"
        else {"visual", "collision"}
        if element.tag == "link"
        else set()
    )
    if any(tags.count(tag) > 1 for tag in set(tags) - repeatable):
        raise ValueError("ambiguous URDF element")
    if element.tag == "geometry" and len(tags) != 1:
        raise ValueError("one geometry shape required")
    for key in ("name", "link"):
        if key in element.attrib and not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]{0,63}", element.attrib[key]
        ):
            raise ValueError("unsafe URDF name")


class _DeclarativeTree(ET.TreeBuilder):
    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise ValueError("DTD forbidden")


def _parse_urdf(data: bytes) -> ET.Element:
    if len(data) > 1_000_000:
        raise ValueError("URDF size exceeded")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("UTF-8 URDF required") from error
    text = text.removeprefix("\ufeff")
    declaration = re.match(
        r"""^<\?xml\s+version=(["'])1\.0\1"""
        r"""(?:\s+encoding=(["'])(?i:utf-8)\2)?"""
        r"""(?:\s+standalone=(["'])(?:yes|no)\3)?\s*\?>""",
        text,
    )
    if declaration:
        text = text[declaration.end() :]
    if "\x00" in text or "<!" in text or "<?" in text:
        raise ValueError("unsupported URDF declaration")
    # UTF-8-only text, no NUL/declarations/entities; target also rejects every DTD.
    parser = ET.XMLParser(target=_DeclarativeTree())  # noqa: S314 - guarded declarative XML only
    try:
        parser.feed(text)
        return parser.close()
    except ET.ParseError as error:
        raise ValueError("invalid URDF XML") from error


def validate_urdf(model: Model, root: Path) -> None:
    robot = _parse_urdf((root / model.asset.urdf_path).read_bytes())
    elements = list(robot.iter())
    if robot.tag != "robot" or len(elements) > 4096:
        raise ValueError("bounded robot URDF required")
    for element in elements:
        if element.tag not in _ALLOWED or len(element.attrib) > 16:
            raise ValueError("unsupported URDF element")
        _structure(element)
        _attribute_values(element)
        if element.tag == "mesh":
            filename = element.get("filename", "")
            path = str(PurePosixPath(model.asset.urdf_path).parent / filename)
            if (
                not safe_path(filename)
                or not safe_path(path)
                or path not in model.asset.files
                or not path.endswith(".stl")
            ):
                raise ValueError("only manifested relative STL meshes are supported")
    _validate_topology(model, robot)


def _attribute_values(element: ET.Element) -> None:
    for key, value in element.attrib.items():
        if len(value) > 512 or any(token in value for token in ("://", "\\", "${")):
            raise ValueError("unsafe URDF value")
        if key in _NUMERIC:
            try:
                numbers = [float(number) for number in value.split()]
            except ValueError as error:
                raise ValueError("invalid URDF number") from error
            if not numbers or any(
                not math.isfinite(number) or abs(number) > 1e9 for number in numbers
            ):
                raise ValueError("unbounded URDF number")


def _validate_topology(model: Model, robot: ET.Element) -> None:
    links = robot.findall("link")
    names = [link.get("name") for link in links]
    expected = {link.name: link.entity_id for link in model.links}
    if len(names) != len(set(names)) or set(names) != set(expected):
        raise ValueError("URDF links do not match graph")
    joints = robot.findall("joint")
    if len(joints) != len(links) - 1:
        raise ValueError("single tree required")
    graph_joints = {joint.name: joint for joint in model.joints}
    observed: set[str] = set()
    parents: dict[str, str] = {}
    all_names: set[str] = set()
    for joint in joints:
        name, kind = joint.get("name", ""), joint.get("type")
        if not name or name in all_names or kind not in ("fixed", "revolute"):
            raise ValueError("unique fixed or revolute joints required")
        all_names.add(name)
        parent, child = joint.find("parent"), joint.find("child")
        if parent is None or child is None:
            raise ValueError("joint parent and child required")
        source, target = parent.get("link", ""), child.get("link", "")
        if source not in expected or target not in expected or target in parents:
            raise ValueError("invalid joint topology")
        parents[target] = source
        if kind == "revolute":
            _match_joint(model, joint, name, expected[source], expected[target])
            observed.add(name)
    if observed != set(graph_joints) or len(set(expected) - set(parents)) != 1:
        raise ValueError("joint set or root mismatch")
    _acyclic(parents)


def _acyclic(parents: dict[str, str]) -> None:
    for child in parents:
        visited: set[str] = set()
        while child in parents:
            if child in visited:
                raise ValueError("cyclic URDF")
            visited.add(child)
            child = parents[child]


def _match_joint(model: Model, joint: ET.Element, name: str, source: str, target: str) -> None:
    spec = next((item for item in model.joints if item.name == name), None)
    limit = joint.find("limit")
    if spec is None or limit is None:
        raise ValueError("graph joint and limits required")
    if (spec.parent_link_entity_id, spec.child_link_entity_id) != (source, target):
        raise ValueError("joint graph endpoints mismatch")
    if (float(limit.get("lower", "nan")), float(limit.get("upper", "nan"))) != (
        spec.lower_rad,
        spec.upper_rad,
    ):
        raise ValueError("joint graph limits mismatch")
