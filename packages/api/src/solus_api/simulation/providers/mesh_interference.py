"""SOLUSDEV-321 P4-T3 — rung 3, mechanics: do a part's bodies interpenetrate, at one pose or
through a sampled joint range (docs/api/simulation.md §7)?

`MeshInterference` is a `ClosedForm` at rung 3 with two formulas:

- `mesh_interference` gives `interference_mm`.
  - The bodies are the pieces of the subject's `mesh`, plus any `meshes` the caller adds by name.
    An assembly's mesh holds one piece per leaf: the bracket's plate and its two pegs. Triangles
    belong to one piece when they share an edge, as a closed surface's do. The pieces are named
    `mesh` when there is one, and `mesh#1`, `mesh#2`, … in the order they appear.
  - Each body is a closed surface in metres facing outward, read by rung 1's own readers
    (`surface_of`, `solid_of`).
  - `poses` places the bodies: one pose set (body → a 4x4 row-major rigid transform, translation in
    metres) or a list of them, a joint range sampled pose by pose. The subject's pieces move
    together as `mesh`, and a body a pose set does not name stays where it is.
- `cantilever_bending` is rung 1's formula, reused, not copied. A climb from rung 1 on a stress near
  its yield (the bracket at 85 %) runs the mesh check and still reports the stress estimate.

**When two bodies interfere.** They interfere when some point of one is firmly inside the other:
the point and the six points around it are inside by the other's winding number. A point outside
the other body's bounding box cannot be inside it, and costs nothing to rule out. The candidates,
in order:

1. An edge of one that crosses a face's interior of the other, leaving its plane strictly. This
   needs no probe.
2. The centres of each body's faces, the deepest inside the other's bounding box first.
3. Each body's volume centre, when it is inside its own body. This catches two copies of one part
   laid on each other.
4. A point just past a crossing that meets a face only on its boundary.

Bodies that only touch do not interfere: a face on a face, an edge on an edge or on a face.

`interference_mm` is the depth of the deepest pair: the shortest distance either body's bounding
box must move along an axis to clear the other's. It is an upper bound on how far they
interpenetrate, and 0 when nothing interferes.

**Bounds.** The work is planned before anything is tested, and no list grows past its bound before
it is cut (R105). A run takes at most:

- `MAX_BODIES` bodies and `MAX_TRIANGLES` triangles in all. A mesh's pieces are counted before any
  is built;
- `MAX_POSE_SETS` pose sets;
- `MAX_EDGE_FACE_TESTS` edge-face tests. Only pairs whose bounding boxes overlap with depth are
  tested, and within them only the edges and faces that reach the overlap;
- `MAX_PROBES` probes for the whole run, never a pair's own allowance. A pair's rim points are
  gathered only up to the probes left, and cut inside the vectorised batch that yields them. Once
  the probes are spent, no later pair builds a probe point or checks one against a box. A run that
  reaches the bound says so in `leaves_out`, with how many pair checks it tested for crossings
  only.

A scene past the other bounds is the named missing input `mesh`, never a partial answer.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray
from pydantic import JsonValue

from solus_api.livebench.scene.meshes import MAX_TRIANGLES
from solus_api.simulation.providers import (
    ClosedForm,
    Computed,
    Facts,
    Formula,
    Need,
    list_of,
    real_number,
)
from solus_api.simulation.providers.deterministic_mech import (
    DeterministicMech,
    solid_of,
    surface_of,
)
from solus_api.simulation.sim_capability import SimInput, SimValue

type Points = NDArray[np.float64]
type Ids = NDArray[np.intp]
type Pose = Mapping[str, Points]

#: The bounds of one run (module docstring).
# ponytail: numpy over the bounding-box-pruned pairs, refused past MAX_EDGE_FACE_TESTS (two dense
# meshes overlapping deeply are). The upgrade is trimesh with python-fcl, which also needs rtree and
# scipy: a bounding-volume hierarchy and an exact contact depth, when dense meshes must be checked.
MAX_BODIES: Final = 16
MAX_POSE_SETS: Final = 16
MAX_EDGE_FACE_TESTS: Final = 2_000_000
MAX_PROBES: Final = 256
#: Face centres of each body tried per pair, the deepest inside the other's box first.
SURFACE_PROBES: Final = 8
#: How many interfering pairs a result names.
MAX_NAMED: Final = 8
#: The subject's own mesh, and the pose key its pieces move by.
SUBJECT: Final = "mesh"
#: The attrs read beside `mesh`: the other bodies and their poses.
OPTIONAL: Final = ("meshes", "poses")
BODY_NAME: Final = re.compile(r"[A-Za-z0-9_.\-]{1,64}")
#: How far from orthonormal a pose's rotation may be.
RIGID: Final = 1e-6
#: Relative to a pair's size, cubed for a volume. A signed volume within `TOUCH` of zero is a touch.
#: A probe sits `PROBE_STEP` past its crossing, and its six neighbours sit `JITTER` around it.
TOUCH: Final = 1e-12
PROBE_STEP: Final = 1e-7
JITTER: Final = 1e-10
#: A winding number past this is inside. It is 1 inside a closed surface, 0 outside and 1/2 on it.
INSIDE: Final = 0.75
#: The label sweeps that may be spent finding a mesh's pieces.
MAX_SWEEPS: Final = 128
#: Edge-face pairs per numpy batch.
CHUNK: Final = 65_536
M_TO_MM: Final = 1000.0
#: A probe point and its six neighbours along the axes.
AROUND: Final = np.vstack([np.zeros(3), np.eye(3), -np.eye(3)])
#: No probe points.
NO_POINTS: Final = np.empty((0, 3))
UPPER_BOUND: Final = (
    "the depth is the shortest distance either body's bounding box must move along an axis to "
    "clear the other's: an upper bound on how far they interpenetrate"
)


@dataclass(frozen=True)
class MeshBody:
    """One closed body facing outward. It holds its corners in its own frame, its faces and its
    edges (each edge once) as corner ids, its volume centre, and the pose key that moves it."""

    name: str
    corners: Points
    faces: Ids
    edges: Ids
    centre: Points
    pose_key: str

    @classmethod
    def of(cls, name: str, triangles: Points, pose_key: str) -> MeshBody | None:
        """The body of a closed surface; None when it faces inward."""
        solid = solid_of(triangles)
        if solid is None:
            return None
        corners, ids = np.unique(triangles.reshape(-1, 3), axis=0, return_inverse=True)
        faces = np.asarray(ids).reshape(-1, 3)
        sides = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
        edges = np.unique(np.sort(sides, axis=1), axis=0)
        return cls(name, corners, faces, edges, np.array(solid.centre_m), pose_key)

    def place(self, points: Points, pose: Pose) -> Points:
        """Points of this body where `pose` puts them; where they are when it does not name it."""
        matrix = pose.get(self.pose_key)
        return points if matrix is None else points @ matrix[:3, :3].T + matrix[:3, 3]


@dataclass(frozen=True)
class MeshScene:
    """The bodies of one question, the pose sets they are checked at, and the edge-face tests the
    check plans: the most it runs."""

    bodies: tuple[MeshBody, ...]
    poses: tuple[Pose, ...]
    tests: int

    def summary(self) -> dict[str, int]:
        """What a provenance records of the scene: its counts, never its geometry."""
        triangles = sum(len(body.faces) for body in self.bodies)
        return {"bodies": len(self.bodies), "triangles": triangles, "pose_sets": len(self.poses)}


@dataclass(frozen=True)
class PairCheck:
    """Two bodies at one pose whose bounding boxes overlap with depth.

    - `corners` and `centres` are placed and centred on the overlap.
    - `edges` and `faces` are the corner ids of each body's edges and faces that reach the overlap.
    - `surfaces` are all of each body's faces: the closed surface a winding number needs.
    """

    pose: int
    pair: tuple[int, int]
    corners: tuple[Points, Points]
    centres: tuple[Points, Points]
    edges: tuple[Ids, Ids]
    faces: tuple[Ids, Ids]
    surfaces: tuple[Ids, Ids]
    size: float
    depth_m: float

    @property
    def tests(self) -> int:
        return len(self.edges[0]) * len(self.faces[1]) + len(self.edges[1]) * len(self.faces[0])

    @cached_property
    def boxes(self) -> tuple[tuple[Points, Points], ...]:
        """Each body's bounding box, its lowest and highest corner, worked out once for the pair: a
        probe point's box check then costs no pass over a body's corners (review Minor 1)."""
        return tuple((corners.min(axis=0), corners.max(axis=0)) for corners in self.corners)

    def depth_in_box(self, points: Points, side: int) -> NDArray[np.float64]:
        """How deep each point is inside body `side`'s bounding box: negative outside it."""
        low, high = self.boxes[side]
        return np.minimum(points - low, high - points).min(axis=-1)

    def inside_box(self, points: Points, side: int) -> NDArray[np.bool_]:
        """Which points are inside body `side`'s bounding box with room for their six neighbours:
        a point outside the box cannot be inside the body."""
        return self.depth_in_box(points, side) > 2 * JITTER * self.size


@dataclass
class ProbeBudget:
    """The probes a run may still spend. The bound is the run's, never a pair's (R105, review
    Minor 1), and is read when a run starts. `unprobed` counts the pair checks that needed a probe
    once they were spent; `short` marks the pair being checked when one did."""

    left: int = field(default_factory=lambda: MAX_PROBES)
    unprobed: int = 0
    short: bool = False


def pieces_of(triangles: Points, limit: int) -> list[Points] | None:
    """The pieces of a closed triangle soup, in the order they first appear. Triangles belong to one
    piece when they share an edge. None when there are more than `limit`, which are counted and
    never built, or when the labels do not settle within `MAX_SWEEPS`."""
    # ponytail: min-label sweeps with pointer jumping settle in a few sweeps on real meshes; a
    # union-find if one ever needs more than MAX_SWEEPS
    _, ids = np.unique(triangles.reshape(-1, 3), axis=0, return_inverse=True)
    corners = np.asarray(ids).reshape(-1, 3)
    sides = np.sort(np.stack([corners[:, [0, 1]], corners[:, [1, 2]], corners[:, [2, 0]]], 1), 2)
    _, edge_ids = np.unique(sides.reshape(-1, 2), axis=0, return_inverse=True)
    edges = np.asarray(edge_ids).reshape(-1, 3)
    label = np.arange(len(triangles))
    for _ in range(MAX_SWEEPS):
        lowest = np.full(int(edges.max()) + 1, len(triangles))
        np.minimum.at(lowest, edges.ravel(), np.repeat(label, 3))
        merged = np.minimum(label, lowest[edges].min(axis=1))
        merged = merged[merged]
        if np.array_equal(merged, label):
            _, first = np.unique(label, return_index=True)
            if len(first) > limit:
                return None
            return [triangles[label == label[start]] for start in sorted(first)]
        label = merged
    return None


def named_bodies(others: Mapping[Any, Any]) -> list[MeshBody] | None:
    """The `meshes` beside the subject, each by a plain name; None when any is unusable."""
    bodies: list[MeshBody] = []
    for name, raw in others.items():
        if not isinstance(name, str) or not BODY_NAME.fullmatch(name) or name == SUBJECT:
            return None
        triangles = surface_of(raw)
        body = None if triangles is None else MeshBody.of(name, triangles, name)
        if body is None:
            return None
        bodies.append(body)
    return bodies


def bodies_of(facts: Facts) -> tuple[MeshBody, ...] | None:
    """The subject's pieces and the named bodies beside them, within the bounds; None when any is
    unusable."""
    others = facts.get("meshes", {})
    if not isinstance(others, Mapping) or len(others) >= MAX_BODIES:
        return None
    surface = surface_of(facts.get(SUBJECT))
    pieces = None if surface is None else pieces_of(surface, MAX_BODIES - len(others))
    if pieces is None:
        return None
    names = [f"{SUBJECT}#{n}" for n in range(1, len(pieces) + 1)] if len(pieces) > 1 else [SUBJECT]
    own = [MeshBody.of(name, piece, SUBJECT) for name, piece in zip(names, pieces, strict=True)]
    beside = named_bodies(others)
    if beside is None or any(body is None for body in own):
        return None
    bodies = [body for body in own if body is not None] + beside
    return tuple(bodies) if sum(len(body.faces) for body in bodies) <= MAX_TRIANGLES else None


def rigid_pose(raw: object) -> Points | None:
    """A 4x4 row-major rigid transform with its translation in metres. It is sixteen finite numbers
    whose last row is 0 0 0 1 and whose rotation is orthonormal and right-handed. None for anything
    else: a pose that scales, mirrors or shears is no pose."""
    numbers = list_of(raw, real_number, range(16, 17))
    if numbers is None:
        return None
    matrix = np.array(numbers, dtype=np.float64).reshape(4, 4)
    rotation = matrix[:3, :3]
    if not np.array_equal(matrix[3], np.array([0.0, 0.0, 0.0, 1.0])):
        return None
    orthonormal = np.allclose(rotation.T @ rotation, np.eye(3), rtol=0.0, atol=RIGID)
    return matrix if orthonormal and np.linalg.det(rotation) > 0 else None


def poses_of(raw: object, keys: set[str]) -> tuple[Pose, ...] | None:
    """`poses` as pose sets. Absent is one set that moves nothing, a mapping is one set, and a list
    is a joint range sampled (at most `MAX_POSE_SETS`). Each set names only bodies there are."""
    if raw is None:
        return ({},)
    sets = [raw] if isinstance(raw, Mapping) else raw
    if not isinstance(sets, list) or not 1 <= len(sets) <= MAX_POSE_SETS:
        return None
    poses: list[Pose] = []
    for entry in sets:
        if not isinstance(entry, Mapping) or not set(entry) <= keys:
            return None
        matrices: dict[str, Points] = {}
        for key, value in entry.items():
            matrix = rigid_pose(value)
            if matrix is None:
                return None
            matrices[key] = matrix
        poses.append(matrices)
    return tuple(poses)


def reaching(elements: Points, low: Points, high: Points) -> Ids:
    """The edges or faces (their corners on axis 1) whose bounding boxes meet [low, high]."""
    meets = (elements.min(axis=1) <= high).all(axis=1) & (elements.max(axis=1) >= low).all(axis=1)
    return np.flatnonzero(meets)


def pair_check(
    pose_index: int, pair: tuple[int, int], bodies: tuple[MeshBody, ...], pose: Pose
) -> PairCheck | None:
    """The check of one pair at one pose; None when their bounding boxes are apart or meet with no
    depth, so the bodies cannot interpenetrate."""
    first, second = (bodies[index] for index in pair)
    a, b = first.place(first.corners, pose), second.place(second.corners, pose)
    low_a, high_a, low_b, high_b = a.min(axis=0), a.max(axis=0), b.min(axis=0), b.max(axis=0)
    low, high = np.maximum(low_a, low_b), np.minimum(high_a, high_b)
    if not (low < high).all():
        return None
    # Centred on the overlap: far from the origin the signed volumes would cancel badly.
    centre = (low + high) / 2
    a, b, low, high = a - centre, b - centre, low - centre, high - centre
    return PairCheck(
        pose=pose_index,
        pair=pair,
        corners=(a, b),
        centres=(
            first.place(first.centre, pose) - centre,
            second.place(second.centre, pose) - centre,
        ),
        edges=(
            first.edges[reaching(a[first.edges], low, high)],
            second.edges[reaching(b[second.edges], low, high)],
        ),
        faces=(
            first.faces[reaching(a[first.faces], low, high)],
            second.faces[reaching(b[second.faces], low, high)],
        ),
        surfaces=(first.faces, second.faces),
        size=float(np.linalg.norm(np.maximum(high_a, high_b) - np.minimum(low_a, low_b))),
        depth_m=float(np.minimum(high_a - low_b, high_b - low_a).min()),
    )


def pair_checks(bodies: tuple[MeshBody, ...], poses: tuple[Pose, ...]) -> Iterator[PairCheck]:
    """Every pair of bodies whose bounding boxes overlap with depth, pose set by pose set."""
    for index, pose in enumerate(poses):
        for pair in itertools.combinations(range(len(bodies)), 2):
            check = pair_check(index, pair, bodies, pose)
            if check is not None:
                yield check


def read_scene(facts: Facts) -> MeshScene | None:
    """The bodies and poses of `facts`, with the work planned; None when anything is unusable or
    past a bound."""
    bodies = bodies_of(facts)
    if bodies is None:
        return None
    poses = poses_of(facts.get("poses"), {body.pose_key for body in bodies})
    if poses is None:
        return None
    tests = sum(check.tests for check in pair_checks(bodies, poses))
    return MeshScene(bodies, poses, tests) if tests <= MAX_EDGE_FACE_TESTS else None


def winding_number(point: Points, triangle: tuple[Points, Points, Points]) -> float:
    """The winding number of a closed surface's triangles about `point`, as van Oosterom and
    Strackee's solid angles sum: 1 inside, 0 outside."""
    a, b, c = (corner - point for corner in triangle)
    la, lb, lc = (np.linalg.norm(corner, axis=1) for corner in (a, b, c))
    volume = np.einsum("ij,ij->i", a, np.cross(b, c))
    dots = np.einsum("ij,ij->i", a, b) * lc + np.einsum("ij,ij->i", b, c) * la
    angle = la * lb * lc + dots + np.einsum("ij,ij->i", c, a) * lb
    return float(np.arctan2(volume, angle).sum() / (2 * np.pi))


def firmly_inside(point: Points, check: PairCheck, side: int) -> bool:
    """Whether `point` and its six neighbours are all inside body `side` of `check`. A point on a
    face's plane is ill-conditioned for the winding number, and one of its neighbours is not
    inside."""
    corners, surface = check.corners[side], check.surfaces[side]
    triangle = (corners[surface[:, 0]], corners[surface[:, 1]], corners[surface[:, 2]])
    shifts = AROUND * (JITTER * check.size)
    return all(winding_number(point + shift, triangle) > INSIDE for shift in shifts)


def probe(point: Points, check: PairCheck, side: int, budget: ProbeBudget) -> bool:
    """Whether `point` is firmly inside body `side`. Once the run's probes are spent nothing is
    checked and the pair is marked short; a point outside its bounding box is not inside, at no
    cost; any other spends one probe."""
    if budget.left <= 0:
        budget.short = True
        return False
    if not check.inside_box(point, side):
        return False
    budget.left -= 1
    return firmly_inside(point, check, side)


def plane_crossings(check: PairCheck, side: int, rows: slice, limit: int) -> tuple[bool, Points]:
    """The edges `rows` of body `side` against the faces of the other body that reach the overlap.

    It returns whether one of them crosses a face's interior, leaving its plane strictly. When none
    does, it also returns the probe points: each sits just past a crossing that leaves a face's
    plane strictly but meets the face only on its boundary, toward the face's inner side, and inside
    the other body's bounding box. At most `limit` are returned. Every step is vectorised, and the
    points are cut to `limit` before any of them is handled one by one (R105)."""
    own, other = check.corners[side], check.corners[1 - side]
    edges, faces = check.edges[side][rows], check.faces[1 - side]
    starts, ends = own[edges[:, 0]], own[edges[:, 1]]
    a, b, c = other[faces[:, 0]], other[faces[:, 1]], other[faces[:, 2]]
    tolerance = TOUCH * check.size**3
    normal = np.cross(b - a, c - a)
    offset = np.einsum("ij,ij->i", a, normal)
    side_start, side_end = starts @ normal.T - offset, ends @ normal.T - offset
    through = ((side_start > tolerance) & (side_end < -tolerance)) | (
        (side_start < -tolerance) & (side_end > tolerance)
    )
    edge, face = np.nonzero(through)
    way = (ends - starts)[edge]
    signs = np.stack(
        [
            np.einsum("ij,ij->i", way, np.cross(x[face] - starts[edge], y[face] - starts[edge]))
            for x, y in ((a, b), (b, c), (c, a))
        ],
        axis=1,
    )
    if ((signs > tolerance).all(axis=1) | (signs < -tolerance).all(axis=1)).any():
        return True, NO_POINTS
    if limit <= 0:
        return False, NO_POINTS
    rim = (signs >= -tolerance).all(axis=1) | (signs <= tolerance).all(axis=1)
    edge, face, way = edge[rim], face[rim], way[rim]
    before, after = side_start[edge, face], side_end[edge, face]
    inward = np.where((after < 0)[:, None], way, -way)
    inward /= np.linalg.norm(inward, axis=1, keepdims=True)
    crossing = starts[edge] + (before / (before - after))[:, None] * way
    points = crossing + inward * (PROBE_STEP * check.size)
    return False, points[check.inside_box(points, 1 - side)][:limit]


def crossings(check: PairCheck, side: int, limit: int) -> tuple[bool, list[Points]]:
    """Whether an edge of body `side` crosses a face's interior of the other body. When none does,
    it returns at most `limit` probe points past boundary crossings (`plane_crossings`): the probes
    the run has left, never a pair's own allowance (review Minor 1). Every batch is still tested
    for a crossing once the points are gathered."""
    edges, faces = check.edges[side], check.faces[1 - side]
    if not len(edges) or not len(faces):
        return False, []
    rows = max(1, CHUNK // len(faces))
    points: list[Points] = []
    for start in range(0, len(edges), rows):
        hit, found = plane_crossings(check, side, slice(start, start + rows), limit - len(points))
        if hit:
            return True, []
        points.extend(found)
    return False, points


def surface_points(check: PairCheck, side: int) -> list[Points]:
    """The centres of body `side`'s faces that reach the overlap and lie inside the other body's
    bounding box, the deepest first, at most `SURFACE_PROBES`: the deepest are partitioned out
    before any is taken one by one."""
    corners, faces = check.corners[side], check.faces[side]
    centres = corners[faces].mean(axis=1)
    depth = check.depth_in_box(centres, 1 - side)
    if len(depth) > SURFACE_PROBES:
        top = np.argpartition(-depth, SURFACE_PROBES - 1)[:SURFACE_PROBES]
    else:
        top = np.arange(len(depth))
    deepest = top[np.argsort(-depth[top])]
    return [centres[k] for k in deepest if depth[k] > 0]


def shared_centre(check: PairCheck, budget: ProbeBudget) -> bool:
    """Whether a body's volume centre is firmly inside both bodies: two copies of one part."""
    return any(
        probe(check.centres[side], check, 1 - side, budget)
        and probe(check.centres[side], check, side, budget)
        for side in (0, 1)
    )


def interferes(check: PairCheck, budget: ProbeBudget) -> bool:
    """Whether the two bodies of `check` interpenetrate (module docstring). Its rim points are
    gathered only up to the probes the run has left. A pair that needs a probe once they are spent
    is tested for crossings only and counted in `budget.unprobed`."""
    rims: list[tuple[Points, int]] = []
    for side in (0, 1):
        hit, points = crossings(check, side, budget.left - len(rims))
        if hit:
            return True
        rims += [(point, 1 - side) for point in points]
    budget.short = budget.left <= 0
    if not budget.short:
        surface = [(point, 1 - side) for side in (0, 1) for point in surface_points(check, side)]
        if any(probe(point, check, other, budget) for point, other in surface):
            return True
        if shared_centre(check, budget):
            return True
        if any(probe(point, check, other, budget) for point, other in rims):
            return True
    budget.unprobed += budget.short
    return False


def interference(found: dict[str, Any]) -> Computed:
    """Every pair checked once. A pair that interferes is kept as its names, pose and depth, the
    first `MAX_NAMED` of them; the rest are counted, never held (R105)."""
    scene: MeshScene = found[SUBJECT]
    budget = ProbeBudget()
    named: list[JsonValue] = []
    hits, depth = 0, 0.0
    for check in pair_checks(scene.bodies, scene.poses):
        if not interferes(check, budget):
            continue
        hits, depth = hits + 1, max(depth, check.depth_m)
        if len(named) < MAX_NAMED:
            named.append(
                {
                    "bodies": [scene.bodies[index].name for index in check.pair],
                    "pose": check.pose,
                    "depth_mm": round(check.depth_m * M_TO_MM, 6),
                }
            )
    gaps = [f"{hits - MAX_NAMED} more interfering pairs not named"] * (hits > MAX_NAMED)
    if budget.left <= 0:
        gaps.append(
            f"the run's {MAX_PROBES} probes ran out: {budget.unprobed} pair checks after that were "
            "tested for crossings only"
        )
    return Computed(
        values={"interference_mm": SimValue(value=depth * M_TO_MM, unit="mm")},
        derived={
            "edge_face_tests": scene.tests,
            "probes": MAX_PROBES - budget.left,
            "interfering_pairs": named,
        },
        leaves_out=tuple(gaps),
    )


MESH: Final = Need(
    SUBJECT,
    "the part's `mesh` attr: {vertices}, the triangles in metres of its closed bodies facing "
    "outward; beside it `meshes` {name: {vertices}} for other bodies and `poses`, one "
    "{body: 4x4 rigid transform} or a list of at most "
    f"{MAX_POSE_SETS}; at most {MAX_BODIES} bodies, {MAX_TRIANGLES:,} triangles and "
    f"{MAX_EDGE_FACE_TESTS:,} edge-face tests",
    read_scene,
    record=lambda scene: scene.summary(),
)
INTERFERENCE: Final = Formula(
    "mesh_interference",
    (MESH,),
    ("interference_mm",),
    (
        UPPER_BOUND,
        "contact without interpenetration: bodies that only touch do not interfere",
        "clearance between bodies that do not touch",
        "poses between the stated pose sets: a joint range is checked only where it is sampled",
        "a body that intersects itself (pieces of one mesh that share an edge are one body)",
        "deformation under load",
    ),
    interference,
)
#: Rung 1's own bending formula (`deterministic_mech`), so a climb on a stress keeps its estimate.
BENDING: Final = next(f for f in DeterministicMech.formulas if f.name == "cantilever_bending")


class MeshInterference(ClosedForm):
    """The mesh check as a rung-3 provider, with rung 1's stress estimate beside it."""

    name = "mesh_interference"
    domain = "mechanical"
    rung = 3
    formulas = (INTERFERENCE, BENDING)

    def inputs_for(self, facts: Facts) -> dict[str, SimInput]:
        """The attrs the formulas read, and the `meshes` and `poses` read beside `mesh`."""
        extra = {a: SimInput(value=facts[a], source="known") for a in OPTIONAL if a in facts}
        return {**super().inputs_for(facts), **extra}
