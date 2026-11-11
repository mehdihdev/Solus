"""SOLUSDEV-322 P6-T2 — a generated model as URDF bytes. Pure: no I/O, no engine, no vendor.

The generator (`simulation/model_job.py`) hands in links and joints already placed in the CAD
assembly frame: a link's mesh is the placed triangle soup the CAD import stored, a joint's axis and
origin are its mate frame placed by the parent part's transform. This module keeps every link frame
world-aligned and puts it at the origin of the joint that moves the link (the root at the assembly
origin), so a mesh is re-expressed by subtracting its link frame's origin and a joint origin is the
offset from the parent's frame. A joint always carries `<limit lower upper effort velocity>`: a
joint whose limits are not known is a gap, never a joint (`scene/parser.py` refuses a revolute
without limits), and an actuator limit that is not known is written as SDF's "not enforced"
sentinel (`-1`: a negative limit is no limit, so nothing is invented; urdfdom refuses a `<limit>`
without `effort` and `velocity`).

`uniform_inertia` turns a known mass and a closed mesh into an `<inertial>` (uniform density over
the mesh's volume); without a known mass no inertial is written and the mass is a gap the report
names — except where the URDF→SDF importer would drop the link and every joint under it (a
massless root, or a massless link a non-fixed joint moves; fixing the root to a `world` link does
not help, the importer lumps it into the world and drops it): that link carries a placeholder
inertial at its frame so the engines keep it, and the report's `<link>.mass` gap still names the
mass. The placeholder weighs as much as the heaviest known link (`PLACEHOLDER_MASS_KG` when no mass
is known): a 1 g root under a 0.42 kg arm diverged in a live physics step and aborted the server
(P9-T6), a 1:1 ratio ran. Every mesh is written as
the link's `<visual>` and its `<collision>`: a simulated part collides. `stl_bytes` writes the
scene's flat triangle soup as binary STL, the form `scene/meshes.py` reads back.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, Literal
from xml.etree import ElementTree as ET

import numpy as np

from solus_api.simulation.providers.deterministic_mech import solid_of, surface_of

Vec3 = tuple[float, float, float]
JointType = Literal["revolute", "prismatic", "fixed"]
#: The covariance of the canonical tetrahedron (origin, e1, e2, e3) with unit density.
_CANONICAL: Final = np.array([[2, 1, 1], [1, 2, 1], [1, 1, 2]], dtype=np.float64) / 120.0
_ORIGIN: Final[Vec3] = (0.0, 0.0, 0.0)
MAX_LINKS: Final = 128
MAX_JOINTS: Final = 128
#: SDF's "not enforced" actuator limit: a negative effort or velocity is no limit.
UNENFORCED: Final = -1.0
#: The floor of the mass a link the engines would otherwise drop carries until its real mass is
#: set (the heaviest known link's mass above that), and its squared radius of gyration (3 cm).
PLACEHOLDER_MASS_KG: Final = 1e-3
PLACEHOLDER_GYRATION_M2: Final = 1e-3


def _finite_tuple(values: Sequence[float], count: int, what: str) -> tuple[float, ...]:
    if len(values) != count or any(not math.isfinite(v) or abs(v) > 1e6 for v in values):
        raise ValueError(f"{what} must be {count} finite numbers")
    return tuple(float(v) for v in values)


def _xyz_text(values: Sequence[float]) -> str:
    return " ".join(f"{v:.9g}" for v in values)


@dataclass(frozen=True)
class Inertial:
    """A link's mass distribution: the mass, its centre (assembly frame, metres) and the tensor
    about that centre as `(ixx, iyy, izz, ixy, ixz, iyz)` in kg·m²."""

    mass_kg: float
    com_m: Vec3
    inertia: tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class GeneratedLink:
    name: str
    #: Root-relative STL path the URDF references (`meshes/<link>.stl`), or no geometry.
    mesh: str | None = None
    inertial: Inertial | None = None


@dataclass(frozen=True)
class GeneratedJoint:
    name: str
    type: JointType
    parent: str
    child: str
    #: The joint axis and origin in the assembly frame (the mate frame, placed). A `fixed`
    #: attachment (a mate whose frame or limits are a gap, a part no mate moves) keeps the
    #: child where CAD placed it: its axis and limits are not read.
    axis: Vec3 = (0.0, 0.0, 1.0)
    origin_m: Vec3 = _ORIGIN
    lower: float = 0.0
    upper: float = 0.0
    #: The actuator's limits when known (N·m or N, rad/s or m/s); None is written as `UNENFORCED`.
    effort_nm: float | None = None
    velocity_rad_s: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin_m", _finite_tuple(self.origin_m, 3, "origin"))
        if self.type == "fixed":
            return
        for value in (self.effort_nm, self.velocity_rad_s):
            if value is not None and not (math.isfinite(value) and value > 0):
                raise ValueError("actuator limits must be positive and finite")
        axis = _finite_tuple(self.axis, 3, "axis")
        norm = math.sqrt(sum(v * v for v in axis))
        if norm < 1e-9:
            raise ValueError("a joint axis must not be zero")
        object.__setattr__(self, "axis", tuple(v / norm for v in axis))
        if not (
            math.isfinite(self.lower) and math.isfinite(self.upper) and self.lower < self.upper
        ):
            raise ValueError("joint limits must be finite with lower < upper")


@dataclass(frozen=True)
class GeneratedModel:
    name: str
    links: tuple[GeneratedLink, ...]
    joints: tuple[GeneratedJoint, ...] = field(default_factory=tuple)


def _frames(model: GeneratedModel) -> dict[str, Vec3]:
    """Each link frame's origin in the assembly frame: the joint that moves it, else the origin."""
    names = {link.name for link in model.links}
    if len(names) != len(model.links) or not 0 < len(model.links) <= MAX_LINKS:
        raise ValueError("links must be uniquely named")
    if len({joint.name for joint in model.joints}) != len(model.joints) or len(model.joints) > (
        MAX_JOINTS
    ):
        raise ValueError("joints must be uniquely named")
    frames: dict[str, Vec3] = dict.fromkeys(names, _ORIGIN)
    for joint in model.joints:
        if joint.parent not in names or joint.child not in names or joint.parent == joint.child:
            raise ValueError(f"joint {joint.name!r} must join two distinct links")
        frames[joint.child] = joint.origin_m
    return frames


def _relative_to(point: Vec3, frame: Vec3) -> Vec3:
    return (point[0] - frame[0], point[1] - frame[1], point[2] - frame[2])


def _kept_massless(model: GeneratedModel) -> set[str]:
    """The links the SDF importer drops without an `<inertial>`: every root, and every child of a
    non-fixed joint (a massless child of a fixed joint is lumped into its parent instead)."""
    children = {joint.child for joint in model.joints}
    moved = {joint.child for joint in model.joints if joint.type != "fixed"}
    return {link.name for link in model.links if link.name not in children} | moved


def _inertial_element(element: ET.Element, inertial: Inertial, frame: Vec3) -> None:
    node = ET.SubElement(element, "inertial")
    com = _xyz_text(_relative_to(inertial.com_m, frame))
    ET.SubElement(node, "origin", xyz=com, rpy="0 0 0")
    ET.SubElement(node, "mass", value=f"{inertial.mass_kg:.9g}")
    ixx, iyy, izz, ixy, ixz, iyz = (f"{v:.9g}" for v in inertial.inertia)
    ET.SubElement(node, "inertia", ixx=ixx, iyy=iyy, izz=izz, ixy=ixy, ixz=ixz, iyz=iyz)


def placeholder_mass(model: GeneratedModel) -> float:
    """What a kept massless link weighs: the heaviest known link, else the 1 g floor."""
    known = [link.inertial.mass_kg for link in model.links if link.inertial is not None]
    return max([PLACEHOLDER_MASS_KG, *known])


def _link_element(
    robot: ET.Element, link: GeneratedLink, frame: Vec3, placeholder_kg: float | None
) -> None:
    element = ET.SubElement(robot, "link", name=link.name)
    if link.inertial is not None:
        _inertial_element(element, link.inertial, frame)
    elif placeholder_kg is not None:
        # ponytail: a point-ish mass at the link frame is the least that keeps the link through
        # the SDF importer AND the physics step (module docstring); the `<link>.mass` gap is the
        # upgrade path, not a better guess.
        moment = placeholder_kg * PLACEHOLDER_GYRATION_M2
        inertial = Inertial(placeholder_kg, frame, (moment, moment, moment, 0.0, 0.0, 0.0))
        _inertial_element(element, inertial, frame)
    if link.mesh is not None:
        for tag in ("visual", "collision"):
            shape = ET.SubElement(element, tag)
            ET.SubElement(shape, "origin", xyz=_xyz_text(_relative_to(_ORIGIN, frame)), rpy="0 0 0")
            ET.SubElement(ET.SubElement(shape, "geometry"), "mesh", filename=link.mesh)


def _joint_element(robot: ET.Element, joint: GeneratedJoint, parent_frame: Vec3) -> None:
    element = ET.SubElement(robot, "joint", name=joint.name, type=joint.type)
    ET.SubElement(element, "parent", link=joint.parent)
    ET.SubElement(element, "child", link=joint.child)
    origin = _xyz_text(_relative_to(joint.origin_m, parent_frame))
    ET.SubElement(element, "origin", xyz=origin, rpy="0 0 0")
    if joint.type != "fixed":
        ET.SubElement(element, "axis", xyz=_xyz_text(joint.axis))
        ET.SubElement(
            element,
            "limit",
            lower=f"{joint.lower:.9g}",
            upper=f"{joint.upper:.9g}",
            effort=_limit_text(joint.effort_nm),
            velocity=_limit_text(joint.velocity_rad_s),
        )


def _limit_text(value: float | None) -> str:
    return f"{UNENFORCED if value is None else value:.9g}"


def write_urdf(model: GeneratedModel) -> bytes:
    """The model as URDF (module docstring). Names are written through the XML builder, so no
    text a part was named with can break out of its attribute."""
    frames = _frames(model)
    kept = _kept_massless(model)
    placeholder = placeholder_mass(model)
    robot = ET.Element("robot", name=model.name)
    for link in model.links:
        _link_element(robot, link, frames[link.name], placeholder if link.name in kept else None)
    for joint in model.joints:
        _joint_element(robot, joint, frames[joint.parent])
    ET.indent(robot)
    return bytes(ET.tostring(robot, encoding="utf-8", xml_declaration=True))


def uniform_inertia(vertices: Sequence[float], mass_kg: float) -> Inertial | None:
    """The `<inertial>` of a closed mesh carrying `mass_kg` as a uniform solid: its centre and the
    tensor about it, by signed tetrahedra from the mesh's own centre. None when the surface is not
    a solid (`deterministic_mech.solid_of`) or the mass is not positive: nothing is invented."""
    triangles = surface_of({"vertices": list(vertices)})
    solid = solid_of(triangles) if triangles is not None else None
    if triangles is None or solid is None or not (math.isfinite(mass_kg) and mass_kg > 0):
        return None
    centre = triangles.reshape(-1, 3).mean(axis=0)
    # Each tetrahedron (centre, a, b, c): J has the corners as columns; its covariance is
    # det(J) · J · C · Jᵀ. The signed sum over a closed surface is the solid's covariance.
    jacobians = (triangles - centre).transpose(0, 2, 1)
    determinants = np.linalg.det(jacobians)
    covariance = np.einsum("n,nij,jk,nlk->il", determinants, jacobians, _CANONICAL, jacobians)
    covariance *= mass_kg / solid.volume_m3  # unit density → the solid's density
    com = np.asarray(solid.centre_m) - centre
    covariance -= mass_kg * np.outer(com, com)  # about the centre of mass
    tensor = np.trace(covariance) * np.eye(3) - covariance
    if not np.isfinite(tensor).all() or np.any(np.diag(tensor) <= 0):
        return None
    return Inertial(
        mass_kg=float(mass_kg),
        com_m=solid.centre_m,
        inertia=(
            float(tensor[0, 0]),
            float(tensor[1, 1]),
            float(tensor[2, 2]),
            float(-tensor[0, 1]),
            float(-tensor[0, 2]),
            float(-tensor[1, 2]),
        ),
    )


def stl_bytes(vertices: Sequence[float]) -> bytes:
    """The scene's flat triangle soup (nine numbers a triangle, metres) as binary STL with zero
    normals, the form `scene/meshes.stl_vertices` reads back."""
    if not vertices or len(vertices) % 9:
        raise ValueError("a triangle soup holds nine numbers a triangle")
    _finite_tuple(vertices, len(vertices), "mesh vertices")
    count = len(vertices) // 9
    out = bytearray(b"\0" * 80 + struct.pack("<I", count))
    for index in range(count):
        out += struct.pack("<3f", 0.0, 0.0, 0.0)
        out += struct.pack("<9f", *vertices[index * 9 : index * 9 + 9])
        out += b"\0\0"
    return bytes(out)
