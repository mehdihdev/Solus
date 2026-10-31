"""SOLUSDEV-321 P4-T2 — rung 1, robot kinematics: forward kinematics over the scene parser's joint
tree, the reach, and a bounded joint-limit sweep (docs/api/simulation.md §6).

The model is the scene model's (`livebench/scene/parser.py`): `model.joints`, each
`{name, type, parent, child, xyz, rpy, axis, lower, upper}`, in metres and radians. A joint's
`xyz` and `rpy` place its child link in its parent's frame at zero (`rpy` are the URDF fixed axes,
R = Rz(yaw) Ry(pitch) Rx(roll)), and it then turns about its `axis` or slides along it. The root
link's frame is the base.

The base is the tree's root link. The tip is the leaf link behind the most movable joints (the
longest kinematic chain: a fixed mast does not outrank an arm), then the deepest, then the first in
joint order. Both are derived inputs (`root_link`, `tip_link`), named in every provenance. Only the
root-to-tip branch is evaluated: when the tree has other leaves, `leaves_out` names them, and it
names the leaves that tie for the tip.

- `forward_kinematics` gives `tip_x_m`, `tip_y_m` and `tip_z_m` for the `joint_positions` it is
  given: one value for every movable joint from the root to the tip.
- `joint_sweep` gives `reach_m` and `sweep_span_m`. The sweep takes each movable joint from its
  lower limit to its upper in `SWEEP_STEPS` steps, with the others at neutral (zero, or the
  nearest limit); a continuous joint is swept over one turn. `reach_m` is the farthest the tip is
  from the base anywhere in the sweep, and `sweep_span_m` the widest distance between two points
  the tip reaches while a single joint is swept.

A CAD twin (`livebench/scene/cad_import.py`) keeps `joints: []` and lists its moving mates as
`model.candidate_joints`, whose axis and origin are unknown. What it lacks is then named
`mate_frame`, not `joints` (SOLUSDEV-321 P4-T4, R113): nothing is computed from a mate with no
frame.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from solus_api.livebench.findings.rules.rule_base import FactNeed, shown
from solus_api.simulation.providers import (
    ClosedForm,
    Computed,
    Facts,
    Formula,
    Need,
    list_of,
    real_number,
)
from solus_api.simulation.sim_capability import MissingInputs, SimQuestion, SimValue

type Matrix = NDArray[np.float64]

#: The parser's own bounds on a model: its joints, and the length of a name.
MAX_JOINTS: Final = 128
MAX_NAME: Final = 128
KINDS: Final = frozenset({"fixed", "revolute", "continuous", "prismatic"})
#: Steps per joint in the limit sweep: odd, so a joint that is symmetric about zero visits zero.
SWEEP_STEPS: Final = 9
#: How many link names a line of text lists before it counts the rest.
MAX_NAMED: Final = 8
#: An axis shorter than this is no axis (the parser refuses it too).
MIN_AXIS: Final = 1e-12
TRIPLE: Final = range(3, 4)


@dataclass(frozen=True, eq=False)
class ChainJoint:
    """One joint of the chain from the root to the tip. `origin` is its child's frame in its
    parent's at zero (4 x 4), `axis` a unit vector, and `low` and `high` the ends of its sweep."""

    name: str
    kind: str
    origin: Matrix
    axis: Matrix
    low: float
    high: float

    @property
    def movable(self) -> bool:
        return self.kind != "fixed"

    @property
    def neutral(self) -> float:
        """Zero, or the nearest limit when zero is out of range."""
        return min(max(0.0, self.low), self.high)


@dataclass(frozen=True, eq=False)
class Chain:
    """The root-to-tip chain of a model's tree: its `path` of joints, and the names of every joint
    the model has. A tree that branches has more than one leaf link. `ignored` holds the leaves
    the chain does not end at, whose branches nothing here evaluates, and `tied` the leaves that
    tie with the tip for the most movable joints (empty unless several do)."""

    root: str
    tip: str
    path: tuple[ChainJoint, ...]
    names: frozenset[str]
    ignored: tuple[str, ...] = ()
    tied: tuple[str, ...] = ()

    @property
    def movable(self) -> tuple[ChainJoint, ...]:
        return tuple(joint for joint in self.path if joint.movable)


def name_of(value: object) -> str | None:
    """`value` as a link or joint name: a non-empty string of at most `MAX_NAME` characters."""
    return value if isinstance(value, str) and 0 < len(value) <= MAX_NAME else None


def origin_of(xyz: list[float], rpy: list[float]) -> Matrix:
    """The 4 x 4 transform of a child frame placed at `xyz` and turned by `rpy`."""
    cr, sr = math.cos(rpy[0]), math.sin(rpy[0])
    cp, sp = math.cos(rpy[1]), math.sin(rpy[1])
    cy, sy = math.cos(rpy[2]), math.sin(rpy[2])
    origin = np.eye(4)
    origin[:3, :3] = [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]
    origin[:3, 3] = xyz
    return origin


def unit_axis(raw: object, kind: str) -> Matrix | None:
    """A joint's axis as a unit vector. A fixed joint has none to state; any other needs three
    numbers that are not all zero."""
    if kind == "fixed":
        return np.array([0.0, 0.0, 1.0])
    axis = list_of(raw, real_number, TRIPLE)
    norm = math.hypot(*axis) if axis is not None else 0.0
    return np.array(axis) / norm if axis is not None and norm >= MIN_AXIS else None


def limits_of(raw: Mapping[str, Any], kind: str) -> tuple[float, float] | None:
    """The ends of a joint's sweep: its limits, one turn for a continuous joint, nothing for a
    fixed one. None when a limited joint states no ordered pair of limits."""
    if kind == "fixed":
        return 0.0, 0.0
    if kind == "continuous":
        return -math.pi, math.pi
    low, high = real_number(raw.get("lower")), real_number(raw.get("upper"))
    return (low, high) if low is not None and high is not None and low <= high else None


def joint_of(raw: object) -> tuple[str, str, ChainJoint] | None:
    """One scene-model joint as (parent link, child link, joint); None when it is malformed."""
    if not isinstance(raw, Mapping):
        return None
    name, parent, child = (name_of(raw.get(key)) for key in ("name", "parent", "child"))
    kind = raw.get("type")
    if name is None or parent is None or child is None:
        return None
    if not isinstance(kind, str) or kind not in KINDS:
        return None
    xyz = list_of(raw.get("xyz"), real_number, TRIPLE)
    rpy = list_of(raw.get("rpy"), real_number, TRIPLE)
    axis, limits = unit_axis(raw.get("axis"), kind), limits_of(raw, kind)
    if xyz is None or rpy is None or axis is None or limits is None:
        return None
    return parent, child, ChainJoint(name, kind, origin_of(xyz, rpy), axis, *limits)


def tree_of(items: list[tuple[str, str, ChainJoint]]) -> Chain | None:
    """The tree the joints make: one root link, and every other link with one parent and
    reachable from the root. Its tip is the leaf behind the most movable joints (the longest
    kinematic chain: a fixed mast is rigid, not a chain), then the deepest, then the first in joint
    order; the chain is the joints from the root to it."""
    by_child = {child: (parent, joint) for parent, child, joint in items}
    if len(by_child) != len(items) or len({joint.name for *_, joint in items}) != len(items):
        return None  # a link with two parents, or a joint named twice
    roots = {parent for parent, *_ in items} - by_child.keys()
    if len(roots) != 1:
        return None
    (root,) = roots
    children: dict[str, list[str]] = {}
    for parent, child, _ in items:
        children.setdefault(parent, []).append(child)
    order, depth, moving = [root], {root: 0}, {root: 0}
    for link in order:
        for child in children.get(link, ()):
            depth[child] = depth[link] + 1
            moving[child] = moving[link] + by_child[child][1].movable
            order.append(child)
    if len(order) != len(items) + 1:
        return None  # links a cycle holds cannot be reached from the root
    leaves = [c for _, c, _ in items if c not in children]
    rank = {leaf: (moving[leaf], depth[leaf]) for leaf in leaves}
    # ponytail: the leaf behind the most movable joints stands for the tip; an `end_effector` attr
    # would name it when leaves tie (a gripper's two fingers, two arms).
    tip = max(leaves, key=rank.__getitem__)
    tied = tuple(leaf for leaf in leaves if rank[leaf] == rank[tip])
    path: list[ChainJoint] = []
    link = tip
    while link != root:
        link, joint = by_child[link]
        path.append(joint)
    names = frozenset(joint.name for *_, joint in items)
    ignored = tuple(leaf for leaf in leaves if leaf != tip)
    return Chain(root, tip, tuple(reversed(path)), names, ignored, tied if len(tied) > 1 else ())


def read_chain(facts: Facts) -> Chain | None:
    """The chain of the scene model's `joints`; None when the model has none (a CAD import) or
    its joints do not make one tree."""
    model = facts.get("model")
    raw = model.get("joints") if isinstance(model, Mapping) else None
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_JOINTS:
        return None
    items = [joint_of(item) for item in raw]
    return None if None in items else tree_of([item for item in items if item is not None])


def read_pose(facts: Facts) -> dict[str, float] | None:
    """The `joint_positions` attr: a number for every movable joint of the chain, and only for
    joints the model has (one off the path to the tip may be stated, and need not be)."""
    chain, raw = read_chain(facts), facts.get("joint_positions")
    if chain is None or not isinstance(raw, Mapping):
        return None
    pose: dict[str, float] = {}
    for name, value in raw.items():
        position = real_number(value)
        if name not in chain.names or position is None:
            return None
        pose[name] = position
    return pose if all(joint.name in pose for joint in chain.movable) else None


def joint_motion(joint: ChainJoint, values: Matrix) -> Matrix:
    """What one joint does for each of `values`: a turn about its axis (Rodrigues) or a slide
    along it, as n 4 x 4 transforms."""
    motion = np.tile(np.eye(4), (len(values), 1, 1))
    if joint.kind == "prismatic":
        motion[:, :3, 3] = values[:, None] * joint.axis
        return motion
    x, y, z = joint.axis
    cross = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    sin, cos = np.sin(values)[:, None, None], np.cos(values)[:, None, None]
    motion[:, :3, :3] = np.eye(3) + sin * cross + (1.0 - cos) * (cross @ cross)
    return motion


def fk(chain: Chain, positions: Matrix) -> Matrix:
    """The tip's position in the root's frame (m) for each row of `positions`, which holds one
    value per movable joint of the chain: n x dof in, n x 3 out."""
    transform = np.tile(np.eye(4), (len(positions), 1, 1))
    column = 0
    for joint in chain.path:
        transform = transform @ joint.origin
        if joint.movable:
            transform = transform @ joint_motion(joint, positions[:, column])
            column += 1
    return transform[:, :3, 3]


def sweep_configs(chain: Chain) -> Matrix:
    """The poses the limit sweep visits, a row each: the neutral pose, then `SWEEP_STEPS` poses for
    every movable joint, which takes its steps from its lower limit to its upper."""
    # ponytail: one joint at a time from neutral, so the reach found is a lower bound; a grid over
    # the joints (or a rung-3 job) is the upgrade when a folded neutral pose hides the reach.
    movable = chain.movable
    neutral = np.array([joint.neutral for joint in movable], dtype=np.float64)
    rows = [neutral[None, :]]
    for column, joint in enumerate(movable):
        swept = np.tile(neutral, (SWEEP_STEPS, 1))
        swept[:, column] = np.linspace(joint.low, joint.high, SWEEP_STEPS)
        rows.append(swept)
    return np.vstack(rows)


def diameter_of(points: Matrix) -> float:
    """The widest distance between two of `points`."""
    return float(np.linalg.norm(points[:, None, :] - points[None, :, :], axis=-1).max())


def label(name: str) -> str:
    """A link or joint name as a result shows it: redacted, on one printable line of at most 80
    characters, and `?` when nothing printable is left. A name is untrusted text."""
    return shown(name) or "?"


def named(links: tuple[str, ...]) -> str:
    """Link names for a line of text: the first `MAX_NAMED`, then a count of the rest."""
    text = ", ".join(label(link) for link in links[:MAX_NAMED])
    return f"{text} and {len(links) - MAX_NAMED} more" if len(links) > MAX_NAMED else text


def branch_notes(chain: Chain) -> tuple[str, ...]:
    """What a run leaves out of a tree that branches: the branches it did not evaluate, and the
    leaf it took as the tip when several tie."""
    notes: list[str] = []
    if chain.ignored:
        notes.append(
            "only the root-to-tip branch is evaluated; other branches ignored "
            f"(leaves: {named(chain.ignored)})"
        )
    if chain.tied:
        notes.append(
            f"the tip is ambiguous: {len(chain.tied)} leaves tie for the most movable joints "
            f"({named(chain.tied)}); the first in joint order, {label(chain.tip)}, was taken"
        )
    return tuple(notes)


def joint_sweep(found: dict[str, Any]) -> Computed:
    chain: Chain = found["joints"]
    configs = sweep_configs(chain)
    tips = fk(chain, configs)
    spans = [
        diameter_of(tips[1 + column * SWEEP_STEPS : 1 + (column + 1) * SWEEP_STEPS])
        for column in range(configs.shape[1])
    ]
    return Computed(
        values={
            "reach_m": SimValue(value=float(np.linalg.norm(tips, axis=1).max()), unit="m"),
            "sweep_span_m": SimValue(value=max(spans, default=0.0), unit="m"),
        },
        derived={
            "root_link": label(chain.root),
            "tip_link": label(chain.tip),
            "configs_evaluated": len(configs),
        },
        assumed={"sweep_steps": SWEEP_STEPS},
        leaves_out=branch_notes(chain),
    )


def forward_kinematics(found: dict[str, Any]) -> Computed:
    chain: Chain = found["joints"]
    pose = found["joint_positions"]
    positions = np.array([[pose[joint.name] for joint in chain.movable]], dtype=np.float64)
    x, y, z = fk(chain, positions.reshape(1, -1))[0]
    return Computed(
        values={
            "tip_x_m": SimValue(value=float(x), unit="m"),
            "tip_y_m": SimValue(value=float(y), unit="m"),
            "tip_z_m": SimValue(value=float(z), unit="m"),
        },
        derived={"root_link": label(chain.root), "tip_link": label(chain.tip)},
        leaves_out=branch_notes(chain),
    )


def chain_summary(chain: Chain) -> dict[str, Any]:
    """What a provenance states of the joints: how many the model has, and the path to the tip."""
    return {"count": len(chain.names), "path": [label(joint.name) for joint in chain.path]}


def labelled_pose(pose: dict[str, float]) -> dict[str, Any]:
    """The stated positions, each joint under the name a result shows."""
    return {label(name): position for name, position in pose.items()}


JOINTS: Final = Need(
    "joints",
    "the scene model's `joints` (a URDF or MJCF import; a CAD import has none): one tree from a "
    "single root link",
    read_chain,
    attr="model",
    record=chain_summary,
)
POSE: Final = Need(
    "joint_positions",
    "the `joint_positions` attr: a value (rad, or m for a prismatic joint) for every movable "
    "joint from the root to the tip",
    read_pose,
    record=labelled_pose,
)
#: What a CAD twin's kinematics lack in place of `joints` (SOLUSDEV-321 P4-T4, R113).
MATE_FRAME: Final = FactNeed(
    name="mate_frame",
    set_in=(
        "the frames (axis and origin) of the moving CAD mates the scene model lists as "
        "`candidate_joints`; a CAD import reads which parts a mate joins, not its frame"
    ),
)


def is_twin(facts: Facts) -> bool:
    """A CAD twin: a scene model with no usable joint tree that lists moving mates beside it, as
    `model.candidate_joints` (`livebench/scene/cad_import.py`)."""
    model = facts.get("model")
    listed = model.get("candidate_joints") if isinstance(model, Mapping) else None
    return isinstance(listed, list) and bool(listed) and read_chain(facts) is None


class DeterministicRobot(ClosedForm):
    """The kinematics closed forms as a rung-1 provider."""

    name = "deterministic_robot"
    domain = "mechanical"

    def can_answer(self, question: SimQuestion) -> MissingInputs:
        """What every closed form answers, except that a CAD twin lacks its mates' frame rather
        than joints: which parts each moving mate joins is known."""
        lacks = super().can_answer(question)
        if not is_twin(question.facts):
            return lacks
        return MissingInputs(
            missing=tuple(
                MATE_FRAME if need.name == JOINTS.name else need for need in lacks.missing
            ),
            derivable=lacks.derivable,
            covered=lacks.covered,
        )

    formulas = (
        Formula(
            "joint_sweep",
            (JOINTS,),
            ("reach_m", "sweep_span_m"),
            (
                "link geometry: only the frames' origins are swept",
                "joints swept one at a time, so the reach is a lower bound",
                "self-collision and obstacles",
                "joint velocity and torque limits",
                "a continuous joint is swept over one turn",
            ),
            joint_sweep,
        ),
        Formula(
            "forward_kinematics",
            (JOINTS, POSE),
            ("tip_x_m", "tip_y_m", "tip_z_m"),
            (
                "link geometry: only the tip frame's origin",
                "joint limits are not enforced on the stated positions",
                "joint backlash and link flex",
                "the tip's orientation",
            ),
            forward_kinematics,
        ),
    )
