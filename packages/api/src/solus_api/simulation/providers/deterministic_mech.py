"""SOLUSDEV-321 P4-T2 — rung 1, mechanics: bending and the mass properties of a part
(docs/api/simulation.md §6).

- `cantilever_bending` gives `stress_mpa` and `yield_fraction`. The part is a prismatic cantilever
  of the stated `section` with the `load` at its arm: M = |F| * arm, stress = M c / I, and the
  yield fraction is the stress over the material's `yield_mpa`. A stress is reported only with the
  yield it is judged against, so the three attrs `load`, `section` and `material` are all needed.
- `mesh_mass` gives `mass_kg` and `mesh_com` the centre of mass (`com_x_m`, `com_y_m`, `com_z_m`).
  The part is a uniform solid whose triangles are its `mesh`, in metres. Its volume is the sum of
  the signed volumes of the tetrahedra the triangles make with a point (the divergence theorem),
  the centre of mass their weighted centroids, and the mass the material's `density_kg_m3` times
  the volume. The mesh must be a closed surface facing outward: its edges cancel in pairs, with
  corners matched exactly (`closed_surface`), and its volume is positive. An open mesh has no
  volume to speak of, however its rounding noise reads, so it is the named missing input `mesh`.

Sections (`dims_mm`): `rect` [width, depth] with the depth along the load, `round` [diameter] and
`tube` [outer diameter, inner diameter].
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from solus_api.livebench.findings.rules.rule_base import shown
from solus_api.livebench.scene.meshes import MAX_TRIANGLES
from solus_api.simulation.providers import (
    MAX_ABS,
    ClosedForm,
    Computed,
    Facts,
    Formula,
    Need,
    Reader,
    at_least,
    list_of,
    numbers_of,
    real_number,
    unsigned_number,
)
from solus_api.simulation.sim_capability import SimValue

#: How many dims each section shape states.
SHAPES: Final = {"rect": 2, "round": 1, "tube": 2}
#: How much of a material's name is read before it is shown: a name is untrusted text.
NAME_SCAN: Final = 256
#: N m to N mm: the stress comes out in N/mm^2, which is MPa.
NM_TO_NMM: Final = 1000.0
#: Floors, each in the unit it guards and far below any part: a nanometre, a pascal, and a gram per
#: cubic metre (aerogels, the lightest solids, are over a hundred times that). They keep a zero or
#: a denormal out of a division, and never refuse a part for being small.
MIN_MM: Final = 1e-6
MIN_MPA: Final = 1e-6
MIN_KG_M3: Final = 1e-3
#: The numbers a material states, each held to its own floor.
MATERIAL_FIELDS: Final = {"yield_mpa": at_least(MIN_MPA), "density_kg_m3": at_least(MIN_KG_M3)}
UNIFORM: Final = "non-uniform density"
CROSSING: Final = (
    "solids in the mesh that overlap or cross (only that its surface is closed is checked)"
)
CHORD: Final = "curved faces approximated by flat triangles (the mesh's volume is a little off)"


@dataclass(frozen=True)
class Solid:
    """A mesh as a uniform solid: its volume (m^3), centre (m) and triangle count."""

    volume_m3: float
    centre_m: tuple[float, float, float]
    triangles: int


def moment_of(force_n: float, arm_m: float) -> float:
    """The root bending moment in N m: the load's magnitude at its arm."""
    return abs(force_n) * arm_m


def inertia_of(shape: str, dims_mm: list[float]) -> tuple[float, float]:
    """A section's second moment of area about its neutral axis (mm^4) and the distance from that
    axis to its extreme fibre (mm). The dims are those the module docstring gives."""
    if shape == "rect":
        width, depth = dims_mm
        return width * depth**3 / 12, depth / 2
    if shape == "round":
        (diameter,) = dims_mm
        return math.pi * diameter**4 / 64, diameter / 2
    outer, inner = dims_mm
    return math.pi * (outer**4 - inner**4) / 64, outer / 2


def read_section(facts: Facts) -> dict[str, Any] | None:
    """The `section` attr: a known shape with its dims, all positive; a tube has a wall."""
    raw = facts.get("section")
    if not isinstance(raw, Mapping):
        return None
    shape = raw.get("shape")
    if not isinstance(shape, str) or shape not in SHAPES:
        return None
    sizes = range(SHAPES[shape], SHAPES[shape] + 1)
    dims = list_of(raw.get("dims_mm"), at_least(MIN_MM), sizes)
    if dims is None or (shape == "tube" and dims[1] >= dims[0]):
        return None
    return {"shape": shape, "dims_mm": dims} if inertia_of(shape, dims)[0] > 0 else None


def material_with(field: str) -> Reader:
    """A reader of the `material` attr, usable when it states `field` as a positive number. It
    returns the fields it could read (`name`, `yield_mpa`, `density_kg_m3`) and nothing else."""

    def read(facts: Facts) -> dict[str, Any] | None:
        raw = facts.get("material")
        if not isinstance(raw, Mapping):
            return None
        found: dict[str, Any] = {}
        name = raw.get("name")
        if isinstance(name, str) and (label := shown(name[:NAME_SCAN])):
            found["name"] = label
        for key, check in MATERIAL_FIELDS.items():
            number = check(raw.get(key))
            if number is not None:
                found[key] = number
        return found if field in found else None

    return read


def closed_surface(triangles: NDArray[np.float64]) -> bool:
    """Whether a triangle soup is a closed surface: its edges cancel in pairs, every directed edge
    having its reverse as many times. Corners are the same when their coordinates are equal. Only
    on a closed surface does the sum of the signed volumes mean a volume: an open mesh reads
    whatever its gap and its noise make it."""
    # ponytail: corners match exactly, as the faces of one tessellation share them bit for bit (an
    # STL repeats the same floats and the STEP reader transforms one node one way). A producer
    # whose shared corners differ by rounding is refused as open; weld them to a tolerance if
    # one ever turns up.
    _, ids = np.unique(triangles.reshape(-1, 3), axis=0, return_inverse=True)
    corners = np.asarray(ids).reshape(-1, 3)
    start = np.concatenate([corners[:, 0], corners[:, 1], corners[:, 2]])
    end = np.concatenate([corners[:, 1], corners[:, 2], corners[:, 0]])
    size = int(corners.max()) + 1
    return bool(np.array_equal(np.sort(start * size + end), np.sort(end * size + start)))


def surface_of(raw: object) -> NDArray[np.float64] | None:
    """A mesh as `MeshCatalog` stores one, `{"vertices": [x, y, z, ...]}` in metres with nine
    numbers per triangle, as its triangles; None unless it is a closed surface (`closed_surface`)
    of at most `MAX_TRIANGLES` finite triangles."""
    vertices = raw.get("vertices") if isinstance(raw, Mapping) else None
    if not isinstance(vertices, list) or not 9 <= len(vertices) <= MAX_TRIANGLES * 9:
        return None
    try:
        flat = np.asarray(vertices)
    except (ValueError, TypeError, OverflowError):
        return None
    if flat.ndim != 1 or len(flat) % 9 or flat.dtype.kind not in "fi":
        return None
    if not np.isfinite(flat).all() or np.abs(flat).max() > MAX_ABS:
        return None
    triangles = flat.astype(np.float64).reshape(-1, 3, 3)
    return triangles if closed_surface(triangles) else None


def read_mesh(facts: Facts) -> Solid | None:
    """The `mesh` attr (`surface_of`) as a solid (`solid_of`)."""
    triangles = surface_of(facts.get("mesh"))
    return None if triangles is None else solid_of(triangles)


def solid_of(triangles: NDArray[np.float64]) -> Solid | None:
    """A closed surface as a uniform solid. Facing outward it has a positive volume, and anything
    else is no solid."""
    # Measured from the mesh's own centre: far from the origin the signed volumes cancel badly.
    centre = triangles.reshape(-1, 3).mean(axis=0)
    first, second, third = (triangles - centre).transpose(1, 0, 2)
    signed = np.einsum("ij,ij->i", first, np.cross(second, third)) / 6.0
    volume = float(signed.sum())
    if not volume > 0:  # closed, but facing inward
        return None
    middle = (signed[:, None] * (first + second + third) / 4.0).sum(axis=0) / volume + centre
    return Solid(volume, (float(middle[0]), float(middle[1]), float(middle[2])), len(triangles))


def cantilever_bending(found: dict[str, Any]) -> Computed:
    load, section, material = found["load"], found["section"], found["material"]
    moment = moment_of(load["force_n"], load["arm_m"])
    inertia, fibre = inertia_of(section["shape"], section["dims_mm"])
    stress = moment * NM_TO_NMM * fibre / inertia
    return Computed(
        values={
            "stress_mpa": SimValue(value=stress, unit="MPa"),
            "yield_fraction": SimValue(value=stress / material["yield_mpa"]),
        },
        derived={"moment_nm": moment, "second_moment_mm4": inertia, "extreme_fibre_mm": fibre},
    )


def mesh_mass(found: dict[str, Any]) -> Computed:
    volume = found["mesh"].volume_m3
    mass = found["material"]["density_kg_m3"] * volume
    return Computed(
        values={"mass_kg": SimValue(value=mass, unit="kg")}, derived={"volume_m3": volume}
    )


def mesh_com(found: dict[str, Any]) -> Computed:
    x, y, z = found["mesh"].centre_m
    return Computed(
        values={
            "com_x_m": SimValue(value=x, unit="m"),
            "com_y_m": SimValue(value=y, unit="m"),
            "com_z_m": SimValue(value=z, unit="m"),
        }
    )


LOAD: Final = Need(
    "load",
    "the part's `load` attr: {force_n, arm_m}",
    numbers_of("load", force_n=real_number, arm_m=unsigned_number),
)
SECTION: Final = Need(
    "section",
    "the part's `section` attr: {shape, dims_mm}; rect [width, depth] with the depth along the "
    "load, round [diameter], tube [outer, inner]",
    read_section,
)
YIELD: Final = Need(
    "material", "the part's `material` attr: {name, yield_mpa}", material_with("yield_mpa")
)
DENSITY: Final = Need(
    "material", "the part's `material` attr: {name, density_kg_m3}", material_with("density_kg_m3")
)
MESH: Final = Need(
    "mesh",
    "the part's `mesh` attr: {vertices}, the triangles in metres of a closed surface facing "
    "outward (an open mesh is refused)",
    read_mesh,
    record=lambda solid: {"triangles": solid.triangles},
)


class DeterministicMech(ClosedForm):
    """The mechanics closed forms as a rung-1 provider."""

    name = "deterministic_mech"
    domain = "mechanical"
    formulas = (
        Formula(
            "cantilever_bending",
            (LOAD, SECTION, YIELD),
            ("stress_mpa", "yield_fraction"),
            (
                "shear and axial stress",
                "stress concentrations at holes and fillets",
                "dynamic loads and fatigue",
                "buckling",
                "temperature",
                "section changes along the member",
            ),
            cantilever_bending,
        ),
        Formula(
            "mesh_mass",
            (MESH, DENSITY),
            ("mass_kg",),
            ("voids, fasteners and coatings the mesh omits", UNIFORM, CROSSING, CHORD),
            mesh_mass,
        ),
        Formula(
            "mesh_com",
            (MESH,),
            ("com_x_m", "com_y_m", "com_z_m"),
            (UNIFORM, CROSSING, CHORD),
            mesh_com,
        ),
    )
