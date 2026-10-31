"""SOLUSDEV-321 P4-T2 — the bracket of the P4 acceptance, three ways.

The geometry is real. `bracket.step` (a 30 x 20 x 5 mm base plate with two 4 x 4 x 12 mm pegs) is
tessellated once through `connectors/step_tessellation.py`, each leaf is placed in the assembly by
its occurrence transform, and the triangles are stored the way `MeshCatalog` stores a mesh:
`{"vertices": [x, y, z, ...]}`, nine floats per triangle, in metres.

The material, the section and the load are fake, and each attr says so (`"fake": true`). The
section is the plate's width and thickness, so its bending stress is 6 F L / (b h^2) with
b = 30 mm and h = 5 mm: a section modulus of 125 mm^3.

The material is fake-6061: yield 276 MPa, density 2700 kg/m^3. The load acts 25 mm from the root.

- Variant a: 207 N. The root moment is 5.175 N m, so the stress is 5175 N mm / 125 mm^3 = 41.4 MPa,
  15 % of yield.
- Variant b: 1173 N. The moment is 29.325 N m and the stress 234.6 MPa, 85 % of yield.
- Variant c: 207 N, and no material at all. Its stress cannot be judged: nothing states a yield.
"""

from __future__ import annotations

import functools
import uuid
from pathlib import Path
from typing import Any, Final, Literal

from solus_api.connectors.mechanical import CadNode
from solus_api.connectors.step_parser import parse_step
from solus_api.connectors.step_tessellation import tessellate_step
from solus_api.graph import kinds
from solus_api.livebench.scene.cad_import import compose, rigid_matrix, transform_mesh
from solus_api.models import Domain, GraphEntity
from sqlalchemy.ext.asyncio import AsyncSession

STEP: Final = Path(__file__).parent / "bracket.step"
type Variant = Literal["a", "b", "c"]
VARIANTS: Final[tuple[Variant, ...]] = ("a", "b", "c")
NAMES: Final[dict[Variant, str]] = {
    "a": "bracket (15 % of yield)",
    "b": "bracket (85 % of yield)",
    "c": "bracket (no material)",
}
ARM_M: Final = 0.025
FORCE_N: Final[dict[Variant, float]] = {"a": 207.0, "b": 1173.0, "c": 207.0}
IDENTITY: Final = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _placement(nodes: dict[str, CadNode], key: str) -> list[float]:
    """The occurrence's transform in the assembly frame: its parents' `parent_transform`s, root
    first, composed with its own."""
    chain: list[str] = []
    cursor: str | None = key
    while cursor is not None:
        chain.append(cursor)
        cursor = nodes[cursor].parent_key
    matrix = IDENTITY
    for step in reversed(chain):
        matrix = compose(matrix, rigid_matrix(nodes[step].properties["parent_transform"]))
    return matrix


@functools.cache
def assembled_mesh() -> tuple[float, ...]:
    """The whole bracket's triangles in metres, in the assembly frame. Tessellated once per test
    session: OCP is slow."""
    text = STEP.read_text(encoding="utf-8")
    nodes = {node.key: node for node in parse_step(text).nodes}
    leaves = [key for key, node in nodes.items() if not node.is_assembly]
    local = tessellate_step(text, leaves)
    vertices: list[float] = []
    for key in leaves:
        vertices += transform_mesh(local[key], _placement(nodes, key))["vertices"]
    return tuple(vertices)


def bracket_attrs(variant: Variant) -> dict[str, Any]:
    """The part attrs of one variant, new on every call. Variant c has no material."""
    attrs: dict[str, Any] = {
        "section": {"shape": "rect", "dims_mm": [30.0, 5.0], "fake": True},
        "load": {"force_n": FORCE_N[variant], "arm_m": ARM_M, "fake": True},
        "mesh": {"vertices": list(assembled_mesh())},
    }
    if variant != "c":
        attrs["material"] = {
            "name": "fake-6061",
            "yield_mpa": 276.0,
            "density_kg_m3": 2700.0,
            "fake": True,
        }
    return attrs


async def seed_brackets(db: AsyncSession, project_id: uuid.UUID) -> dict[Variant, uuid.UUID]:
    """The three variants as mechanical parts of `project_id`, by variant. Commits."""
    rows = {
        variant: GraphEntity(
            project_id=project_id,
            kind=kinds.PART,
            domain=Domain.MECHANICAL,
            origin="manual",
            name=NAMES[variant],
            attrs=bracket_attrs(variant),
        )
        for variant in VARIANTS
    }
    db.add_all(rows.values())
    await db.commit()
    return {variant: row.id for variant, row in rows.items()}
