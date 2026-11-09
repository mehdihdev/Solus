"""SOLUSDEV-321 P4-T3 — rung 3, the mesh check (docs/api/simulation.md §7).

Do a part's bodies interpenetrate, at one pose or through a sampled joint range? Bodies that only
touch do not. The work is bounded and counted, and a part whose stress sits near its yield at
rung 1 (the bracket at 85 %) climbs here and still gets its stress estimate. Boxes are given in
millimetres and stored in metres, each overlap worked by hand; the bracket is the real one
(`fixtures/sim_bracket.py`).
"""

from __future__ import annotations

import itertools
import math
import uuid
from typing import Any, Final

import numpy as np
import pytest
from conftest import requires_occt as _requires_occt
from fixtures.sim_bracket import NAMES, bracket_attrs
from solus_api.agent.interfaces import EntityRead, GraphContext
from solus_api.checkers.matrix_rule import RuleResult
from solus_api.graph import kinds
from solus_api.orchestration.config import SimulationConfig
from solus_api.simulation.providers import mesh_interference
from solus_api.simulation.providers.deterministic_mech import DeterministicMech
from solus_api.simulation.providers.mesh_interference import (
    MAX_BODIES,
    MAX_POSE_SETS,
    MeshInterference,
)
from solus_api.simulation.sim_capability import SimProvider, SimQuestion, SimResult
from solus_api.simulation.sim_ladder import LadderContext, should_simulate
from test_deterministic_mech import _box

#: conftest.py holds the one definition of when OCCT is missing; this only gives it its type.
requires_occt: pytest.MarkDecorator = _requires_occt
MM: Final = 0.001


def _cube(corner: tuple[float, float, float], size: tuple[float, float, float]) -> list[float]:
    """An axis-aligned box given in millimetres, as the nine floats per triangle, in metres."""
    (x, y, z), (dx, dy, dz) = corner, size
    return _box((x * MM, y * MM, z * MM), (dx * MM, dy * MM, dz * MM))


def _attrs(*bodies: list[float], **extra: Any) -> dict[str, Any]:
    """A subject whose `mesh` holds these bodies, one component each, beside any other attrs."""
    return {"mesh": {"vertices": [value for body in bodies for value in body]}, **extra}


def _moved(dx_mm: float = 0.0, dy_mm: float = 0.0, dz_mm: float = 0.0) -> list[float]:
    """A pose that only translates: a 4x4 row-major rigid transform, its translation in metres."""
    return [1.0, 0, 0, dx_mm * MM, 0, 1.0, 0, dy_mm * MM, 0, 0, 1.0, dz_mm * MM, 0, 0, 0, 1.0]


def _turned_about_z(degrees: float, dx_mm: float, dy_mm: float) -> list[float]:
    """A pose that turns about z and then translates."""
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [c, -s, 0, dx_mm * MM, s, c, 0, dy_mm * MM, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _run(attrs: dict[str, Any]) -> SimResult:
    provider = MeshInterference()
    return provider.run(provider.inputs_for(attrs))


def _question(quantity: str, attrs: dict[str, Any]) -> SimQuestion:
    return SimQuestion(subject_id=uuid.uuid4(), quantity=quantity, facts=attrs)


def _derived(result: SimResult, name: str) -> Any:
    entry = result.provenance.inputs[name]
    assert entry.source == "derived"
    return entry.value


def _depth(result: SimResult) -> float:
    value = result.values["interference_mm"]
    assert value.unit == "mm"
    return value.value


def _scene(result: SimResult) -> Any:
    """What the provenance records of the scene: its counts, never its geometry."""
    return result.provenance.inputs["mesh"].value


def test_overlapping_boxes_interfere() -> None:
    # [0, 20] mm^3 and [10, 30] mm^3 share [10, 20] mm^3. Either must move 10 mm along an axis to
    # clear the other: min(20 - 10, 30 - 0) = 10 on each axis.
    result = _run(_attrs(_cube((0, 0, 0), (20, 20, 20)), _cube((10, 10, 10), (20, 20, 20))))
    assert _depth(result) == pytest.approx(10.0)
    mesh = result.provenance.inputs["mesh"]
    assert (mesh.value, mesh.source) == ({"bodies": 2, "triangles": 24, "pose_sets": 1}, "known")
    assert _derived(result, "interfering_pairs") == [
        {"bodies": ["mesh#1", "mesh#2"], "pose": 0, "depth_mm": 10.0}
    ]
    assert 0 < _derived(result, "edge_face_tests") <= mesh_interference.MAX_EDGE_FACE_TESTS
    assert result.provenance.solver == "mesh_interference:mesh_interference"
    assert any("upper bound" in line for line in result.provenance.leaves_out)
    # no load, section or material: the stress estimate is the stated gap, not a guess
    assert "stress_mpa" not in result.values
    assert "stress_mpa, yield_fraction not computed: load, section, material unknown" in (
        result.provenance.leaves_out
    )
    # the same two boxes, as the subject and a named body beside it
    named = _run(
        {
            "mesh": {"vertices": _cube((0, 0, 0), (20, 20, 20))},
            "meshes": {"lid": {"vertices": _cube((10, 10, 10), (20, 20, 20))}},
        }
    )
    assert _depth(named) == pytest.approx(10.0)
    assert _derived(named, "interfering_pairs") == [
        {"bodies": ["mesh", "lid"], "pose": 0, "depth_mm": 10.0}
    ]


@pytest.mark.parametrize(
    "other",
    [
        pytest.param(_cube((20, 0, 0), (20, 20, 20)), id="face-on-face"),
        pytest.param(_cube((20, 20, 0), (20, 20, 20)), id="edge-on-edge"),
        pytest.param(_cube((20, 20, 20), (5, 5, 5)), id="corner-on-corner"),
        pytest.param(_cube((5, 5, 20), (10, 10, 5)), id="a-block-standing-on-the-top-face"),
        pytest.param(_cube((50, 0, 0), (20, 20, 20)), id="apart"),
    ],
)
def test_bodies_that_touch_or_stand_apart_do_not_interfere(other: list[float]) -> None:
    result = _run(_attrs(_cube((0, 0, 0), (20, 20, 20)), other))
    assert _depth(result) == 0.0
    assert _derived(result, "interfering_pairs") == []
    # their bounding boxes overlap with no depth, or not at all: no face is ever tested
    assert _derived(result, "edge_face_tests") == 0


def test_crossing_bars_interfere_though_no_corner_of_either_is_inside_the_other() -> None:
    # A bar along x, [0, 30] x [10, 20] x [0, 10] mm, and a thinner one along y,
    # [10, 20] x [0, 30] x [2, 8] mm. The y bar must rise or sink 8 mm to clear: min(10 - 2, 8 - 0)
    # in z, against 20 mm along x or y.
    along_x = _cube((0, 10, 0), (30, 10, 10))
    along_y = _cube((10, 0, 2), (10, 30, 6))
    result = _run(_attrs(along_x, along_y))
    assert _depth(result) == pytest.approx(8.0)
    assert _derived(result, "interfering_pairs")[0]["bodies"] == ["mesh#1", "mesh#2"]


@pytest.mark.parametrize(
    ("inner", "depth_mm"),
    [
        # [5, 15] mm^3 inside [0, 20] mm^3: no surface crosses another. To clear, the inner one
        # must move min(15 - 0, 20 - 5) = 15 mm.
        pytest.param(_cube((5, 5, 5), (10, 10, 10)), 15.0, id="held-inside"),
        # [0, 10] mm^3 in the corner of [0, 20] mm^3, three faces shared: min(10 - 0, 20 - 0).
        pytest.param(_cube((0, 0, 0), (10, 10, 10)), 10.0, id="in-a-corner"),
    ],
)
def test_a_body_inside_another_interferes(inner: list[float], depth_mm: float) -> None:
    result = _run(_attrs(_cube((0, 0, 0), (20, 20, 20)), inner))
    assert _depth(result) == pytest.approx(depth_mm)
    assert _derived(result, "interfering_pairs")[0]["depth_mm"] == pytest.approx(depth_mm)


def test_a_bar_that_grazes_an_edge_only_touches_it() -> None:
    """A bar turned 45 degrees about z whose front face meets the cube's vertical edge at (10, 10)
    mm: their bounding boxes overlap with depth, so faces are tested, but the bar only touches the
    edge. Moved half a millimetre toward the cube, it enters it."""
    cube = {"mesh": {"vertices": _cube((0, 0, 0), (10, 10, 10))}}
    # the bar is [0, 20] x [0, 5] x [5, 15] mm in its own frame; its front edge (y = 0) runs along
    # x + y = 20 mm in the world and passes (10, 10) mm at its middle
    bar = {"bar": {"vertices": _cube((0, 0, 5), (20, 5, 10))}}
    half = 10 / math.sqrt(2)
    touching = _turned_about_z(-45, 10 - half, 10 + half)
    grazes = _run({**cube, "meshes": bar, "poses": {"bar": touching}})
    assert _depth(grazes) == 0.0
    assert _derived(grazes, "edge_face_tests") > 0
    step = 0.5 / math.sqrt(2)
    entering = _turned_about_z(-45, 10 - half - step, 10 + half - step)
    enters = _run({**cube, "meshes": bar, "poses": {"bar": entering}})
    assert _depth(enters) > 0.0


def test_poses_place_the_bodies_and_a_joint_range_is_checked_pose_by_pose() -> None:
    box = _cube((0, 0, 0), (20, 20, 20))
    lid = _cube((0, 0, 0), (20, 20, 5))
    attrs = {"mesh": {"vertices": box}, "meshes": {"lid": {"vertices": lid}}}
    # laid on the box's top face it touches; with no pose it would fill the box's bottom 5 mm
    assert _depth(_run(attrs)) == pytest.approx(5.0)
    on_top = _run({**attrs, "poses": {"lid": _moved(dz_mm=20)}})
    assert _depth(on_top) == 0.0
    # a range sampled at three poses: on top, 2 mm into the box (min(20 - 18, 23 - 0) = 2), clear
    sweep = _run(
        {
            **attrs,
            "poses": [
                {"lid": _moved(dz_mm=20)},
                {"lid": _moved(dz_mm=18)},
                {"lid": _moved(dz_mm=30)},
            ],
        }
    )
    assert _depth(sweep) == pytest.approx(2.0)
    assert _scene(sweep)["pose_sets"] == 3
    assert _derived(sweep, "interfering_pairs") == [
        {"bodies": ["mesh", "lid"], "pose": 1, "depth_mm": 2.0}
    ]
    # a pose moves the subject's own bodies too: the box sunk 3 mm clears the lid on top
    sunk = _run({**attrs, "poses": {"mesh": _moved(dz_mm=-3), "lid": _moved(dz_mm=18)}})
    assert _depth(sunk) == 0.0


def test_the_work_is_counted_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    apart = _run(_attrs(_cube((0, 0, 0), (20, 20, 20)), _cube((50, 0, 0), (20, 20, 20))))
    assert _derived(apart, "edge_face_tests") == 0
    overlapping = _attrs(_cube((0, 0, 0), (20, 20, 20)), _cube((10, 10, 10), (20, 20, 20)))
    counted = _derived(_run(overlapping), "edge_face_tests")
    assert counted > 0
    # the run is planned before anything is tested: one test past the cap is refused, whole
    monkeypatch.setattr(mesh_interference, "MAX_EDGE_FACE_TESTS", counted - 1)
    lacks = MeshInterference().can_answer(_question("interference_mm", overlapping))
    assert lacks.names == ("mesh",)
    assert "edge-face tests" in lacks.missing[0].set_in
    monkeypatch.setattr(mesh_interference, "MAX_EDGE_FACE_TESTS", counted)
    assert _derived(_run(overlapping), "edge_face_tests") == counted


def _grid_box(
    cells: int, corner: tuple[float, float, float], size: tuple[float, float, float]
) -> list[float]:
    """A box in millimetres whose six faces are `cells` x `cells` grids of squares, two triangles
    a square, facing outward, as the mesh floats in metres."""
    low, span = np.array(corner) * MM, np.array(size) * MM
    vertices: list[float] = []
    for axis, top in itertools.product(range(3), (0, 1)):
        u, v = (k for k in range(3) if k != axis)
        for i, j in itertools.product(range(cells), repeat=2):
            square = []
            for du, dv in ((0, 0), (1, 0), (1, 1), (0, 1)):
                point = low.copy()
                point[axis] += top * span[axis]
                point[u] += (i + du) / cells * span[u]
                point[v] += (j + dv) / cells * span[v]
                square.append(point)
            a, b, c, d = square
            if np.cross(b - a, c - a)[axis] * (1 if top else -1) < 0:
                b, d = d, b
            vertices += [float(x) for corner_ in (a, b, c, a, c, d) for x in corner_]
    return vertices


def test_a_large_rim_is_cut_to_the_probe_bound_before_any_point_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R105: two boxes gridded every 2 mm, the second offset by 11 mm, so a half cell. A hundred
    edges of each cross the other's face planes exactly on its grid lines: crossings that meet a
    face only on its boundary. The work is cut to the probe bound inside the vectorised batch,
    before any probe point is built one by one, however large the rim is."""
    monkeypatch.setattr(mesh_interference, "MAX_PROBES", 16)
    bodies = mesh_interference.bodies_of(
        {
            "mesh": {"vertices": _grid_box(10, (0, 0, 0), (20, 20, 20))},
            "meshes": {"offset": {"vertices": _grid_box(10, (11, 11, 11), (20, 20, 20))}},
        }
    )
    assert bodies is not None
    [check] = list(mesh_interference.pair_checks(bodies, ({},)))
    # the whole rim, with a limit no rim reaches: no edge crosses a face's interior
    hit, every = mesh_interference.plane_crossings(check, 0, slice(None), 10**6)
    assert not hit and len(every) > 100
    hit, cut = mesh_interference.plane_crossings(check, 0, slice(None), 16)
    assert not hit and len(cut) == 16
    hit, gathered = mesh_interference.crossings(check, 0, 16)
    assert not hit and len(gathered) == 16
    # the run interferes (they share an 9 x 9 x 9 mm cube) and spends at most the bound
    result = _run(_half_cell_pair())
    assert _depth(result) == pytest.approx(9.0)
    assert 0 < _derived(result, "probes") <= 16


def _half_cell_pair(poses: int = 0) -> dict[str, Any]:
    """The rim-only pair above: two boxes gridded every 2 mm, the second 11 mm along each axis.
    With `poses`, the pair is checked that many times where it stands."""
    attrs: dict[str, Any] = {
        "mesh": {"vertices": _grid_box(10, (0, 0, 0), (20, 20, 20))},
        "meshes": {"offset": {"vertices": _grid_box(10, (11, 11, 11), (20, 20, 20))}},
    }
    return {**attrs, "poses": [{"offset": _moved()}] * poses} if poses else attrs


def test_the_probe_budget_is_the_runs_and_once_spent_no_probe_work_is_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R105, review Minor 1: the probes are the run's, never a pair's. The rim-only pair, checked
    at six poses with two probes for the whole run, interferes at the first two. Every pose after
    builds no probe point and checks none against a box, so six poses cost the run what two do,
    and the run says how many pair checks it tested for crossings only."""
    monkeypatch.setattr(mesh_interference, "MAX_PROBES", 2)
    work = {"gathered": 0, "boxed": 0}
    gather, box = mesh_interference.plane_crossings, mesh_interference.PairCheck.inside_box

    def gathering(check: Any, side: int, rows: slice, limit: int) -> Any:
        hit, points = gather(check, side, rows, limit)
        work["gathered"] += len(points)
        return hit, points

    def boxing(check: Any, points: Any, side: int) -> Any:
        work["boxed"] += np.ndim(points) == 1  # one probe point, not a vectorised batch
        return box(check, points, side)

    monkeypatch.setattr(mesh_interference, "plane_crossings", gathering)
    monkeypatch.setattr(mesh_interference.PairCheck, "inside_box", boxing)

    def costs(poses: int) -> tuple[dict[str, int], SimResult]:
        work.update(gathered=0, boxed=0)
        result = _run(_half_cell_pair(poses))
        return dict(work), result

    two, _ = costs(2)
    six, result = costs(6)
    assert six == two
    assert _derived(result, "probes") == 2
    assert [pair["pose"] for pair in _derived(result, "interfering_pairs")] == [0, 1]
    assert (
        "the run's 2 probes ran out: 4 pair checks after that were tested for crossings only"
        in result.provenance.leaves_out
    )


def test_many_interfering_pairs_are_counted_and_eight_are_named() -> None:
    # twelve 20 mm boxes, each 0.1 mm along x from the last: every one of the 66 pairs overlaps
    boxes = [_cube((0.1 * index, 0, 0), (20, 20, 20)) for index in range(12)]
    result = _run(_attrs(*boxes))
    assert len(_derived(result, "interfering_pairs")) == mesh_interference.MAX_NAMED
    assert "58 more interfering pairs not named" in result.provenance.leaves_out


def test_a_mesh_of_more_pieces_than_bodies_is_refused_before_they_are_built() -> None:
    # two thousand separate boxes in one mesh: the pieces are counted, never built, past the bound
    triangles = np.array(
        [_cube((30 * (index % 50), 30 * (index // 50), 0), (10, 10, 10)) for index in range(2000)]
    ).reshape(-1, 3, 3)
    assert mesh_interference.pieces_of(triangles, MAX_BODIES) is None
    pieces = mesh_interference.pieces_of(triangles, 2000)
    assert pieces is not None and len(pieces) == 2000


def _apart(count: int) -> dict[str, Any]:
    return _attrs(*(_cube((30 * index, 0, 0), (10, 10, 10)) for index in range(count)))


@pytest.mark.parametrize(
    "attrs",
    [
        pytest.param({}, id="no-mesh"),
        pytest.param(_attrs(_cube((0, 0, 0), (20, 20, 20))[:-18]), id="an-open-mesh"),
        pytest.param(_attrs(_cube((0, 0, 0), (20, 20, 20)), meshes=["lid"]), id="meshes-a-list"),
        pytest.param(
            _attrs(_cube((0, 0, 0), (20, 20, 20)), meshes={"lid lid": {"vertices": []}}),
            id="a-body-name-with-a-space",
        ),
        pytest.param(
            _attrs(
                _cube((0, 0, 0), (20, 20, 20)),
                meshes={"mesh": {"vertices": _cube((50, 0, 0), (5, 5, 5))}},
            ),
            id="a-body-named-like-the-subject",
        ),
        pytest.param(
            _attrs(
                _cube((0, 0, 0), (20, 20, 20)),
                meshes={"lid": {"vertices": _cube((50, 0, 0), (5, 5, 5))[:-9]}},
            ),
            id="an-open-named-body",
        ),
        pytest.param(_attrs(_cube((0, 0, 0), (20, 20, 20)), poses="up"), id="poses-a-string"),
        pytest.param(
            _attrs(_cube((0, 0, 0), (20, 20, 20)), poses={"lid": _moved()}),
            id="a-pose-for-no-body",
        ),
        pytest.param(
            _attrs(_cube((0, 0, 0), (20, 20, 20)), poses={"mesh": _moved()[:12]}),
            id="a-pose-of-twelve-numbers",
        ),
        pytest.param(
            _attrs(
                _cube((0, 0, 0), (20, 20, 20)),
                poses={"mesh": [2.0, 0, 0, 0, 0, 2.0, 0, 0, 0, 0, 2.0, 0, 0, 0, 0, 1.0]},
            ),
            id="a-pose-that-scales",
        ),
        pytest.param(
            _attrs(
                _cube((0, 0, 0), (20, 20, 20)),
                poses={"mesh": [-1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]},
            ),
            id="a-pose-that-mirrors",
        ),
        pytest.param(
            _attrs(
                _cube((0, 0, 0), (20, 20, 20)),
                poses={"mesh": [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0.5, 1.0]},
            ),
            id="a-pose-whose-last-row-is-not-0-0-0-1",
        ),
        pytest.param(
            _attrs(
                _cube((0, 0, 0), (20, 20, 20)),
                poses={"mesh": [float("nan"), *_moved()[1:]]},
            ),
            id="a-pose-with-nan",
        ),
        pytest.param(
            _attrs(_cube((0, 0, 0), (20, 20, 20)), poses={"mesh": [True, *_moved()[1:]]}),
            id="a-pose-with-a-bool",
        ),
        pytest.param(_apart(MAX_BODIES + 1), id="one-body-too-many"),
        pytest.param(
            _attrs(_cube((0, 0, 0), (20, 20, 20)), poses=[{}] * (MAX_POSE_SETS + 1)),
            id="one-pose-set-too-many",
        ),
    ],
)
def test_an_unusable_scene_is_a_missing_input_and_never_an_error(attrs: dict[str, Any]) -> None:
    lacks = MeshInterference().can_answer(_question("interference_mm", attrs))
    assert lacks.names == ("mesh",)
    assert lacks.covered == ()
    with pytest.raises(ValueError, match="nothing to compute"):
        _run(attrs)


def test_the_caps_take_their_own_value() -> None:
    assert _depth(_run(_apart(MAX_BODIES))) == 0.0
    poses = [{"mesh": _moved(dz_mm=float(index))} for index in range(MAX_POSE_SETS)]
    held = _run(_attrs(_cube((0, 0, 0), (20, 20, 20)), poses=poses))
    assert _scene(held)["pose_sets"] == MAX_POSE_SETS


@requires_occt
def test_85pct_bracket_runs_mesh_check_and_stress() -> None:
    part = EntityRead(
        id=uuid.uuid4(),
        kind=kinds.PART,
        domain="mechanical",
        name=NAMES["b"],
        attrs=bracket_attrs("b"),
    )
    rung_1 = DeterministicMech()
    first = rung_1.run(rung_1.inputs_for(part.attrs))
    judged = RuleResult(
        status="inconclusive",
        message="the estimate is near the yield",
        subjects=(part.id,),
        evidence={
            "quantity": "stress_mpa",
            "value": first.values["stress_mpa"].value,
            "limit": part.attrs["material"]["yield_mpa"],
            "unit": "MPa",
            "rung": 1,
        },
    )
    context = LadderContext(
        config=SimulationConfig(),
        graph=GraphContext(entities=[part], edges=[]),
        providers=(rung_1, MeshInterference()),
        available=frozenset({"deterministic_mech", "mesh_interference"}),
    )
    [proposal] = should_simulate([judged], trigger="rule", context=context)
    assert (proposal.target, proposal.rung, proposal.decision) == ("mesh_interference", 3, "run")
    assert proposal.reason == "stress_mpa is at 85% of its limit at rung 1: inside its 0.8 band"
    result = _run(part.attrs)
    # the plate (30 x 20 x 5 mm) and its two 4 x 4 x 12 mm pegs, which stand on it at z = 5 mm,
    # touch and do not interfere; every pair's bounding boxes meet with no depth, so no face is
    # tested
    assert _depth(result) == 0.0
    assert result.provenance.inputs["mesh"].value == {"bodies": 3, "triangles": 36, "pose_sets": 1}
    assert _derived(result, "interfering_pairs") == []
    assert _derived(result, "edge_face_tests") == 0
    # and rung 1's estimate runs beside it: 29.325 N m on a 30 x 5 mm section, 234.6 MPa
    assert result.values["stress_mpa"].value == pytest.approx(234.6)
    assert result.values["yield_fraction"].value == pytest.approx(0.85)
    assert result.provenance.solver == "mesh_interference:mesh_interference+cantilever_bending"
    assert result.provenance.inputs["material"].source == "known"
    assert "shear and axial stress" in result.provenance.leaves_out


def test_it_is_a_sim_provider_that_refuses_a_foreign_quantity() -> None:
    provider: SimProvider = MeshInterference()
    assert (provider.name, provider.domain, provider.rung) == ("mesh_interference", "mechanical", 3)
    assert provider.quantities == {"interference_mm", "stress_mpa", "yield_fraction"}
    with pytest.raises(ValueError, match="does not compute"):
        provider.can_answer(_question("mass_kg", {}))
    lacks = provider.can_answer(_question("interference_mm", {}))
    assert (lacks.names, lacks.covered) == (("mesh",), ())
    # the optional bodies and poses travel with the attrs the formulas read; nothing else does
    attrs = _attrs(
        _cube((0, 0, 0), (20, 20, 20)),
        meshes={"lid": {"vertices": _cube((50, 0, 0), (5, 5, 5))}},
        poses={"lid": _moved()},
        colour="red",
    )
    assert set(MeshInterference().inputs_for(attrs)) == {"mesh", "meshes", "poses"}
