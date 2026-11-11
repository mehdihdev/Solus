"""SOL-visible argument models for the owned `gazebo.*` wrappers (SOLUSDEV-322 P3-T4).

They mirror the fork's `tool_args.py` (integrations/mcp/gazebo) with one difference: `spawn`
binds a graph `simulation_model` entity (`model_entity_id`), never a digest — the wrapper
resolves the model and pushes its verified files itself. `put_asset` has no public model: the
chunk push is the wrapper's own internal step.

Every name that can end up in an argv or a protobuf text-format request (`world`, `model`,
`joint`, spawn `name`) is a plain identifier: no leading ``-`` (never an option), no quotes,
braces, colons, backslashes or whitespace. Root-relative paths (`world_ref`, `dest`) are plain
components joined by ``/``. Unknown fields are refused, nothing is coerced, numbers are finite
and bounded, floats are dumped as floats so the fork's strict models accept them.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import Field, StringConstraints

from solus_api.agent.tools.isaac_models import Empty, EntityId, Number, Strict

_NAME = r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$"
_PART = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
_REL_PATH = rf"^{_PART}(/{_PART}){{0,15}}$"
MAX_TARGETS: Final = 16

Name = Annotated[str, StringConstraints(pattern=_NAME)]
RelPath = Annotated[str, StringConstraints(pattern=_REL_PATH, max_length=512)]
SessionId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9-]{1,80}$")]
Finite = Annotated[Number, Field(ge=-1e6, le=1e6)]
Vec3 = Annotated[list[Finite], Field(min_length=3, max_length=3)]
FamilyName = Literal["classic", "ignition", "gz"]


class OpenWorld(Strict):
    world_ref: RelPath
    family: FamilyName | None = None
    gui: bool = False
    dry_run: bool = False


class Attach(Strict):
    family: FamilyName
    world: Name


class GzSession(Strict):
    session_id: SessionId


class ListModels(GzSession):
    pass


class GzPose(Strict):
    xyz: Vec3 = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rpy: Vec3 = Field(default_factory=lambda: [0.0, 0.0, 0.0])


class Spawn(GzSession):
    model_entity_id: EntityId
    name: Name
    pose: GzPose = Field(default_factory=GzPose)
    dry_run: bool = False


class JointState(GzSession):
    model: Name
    joints: list[Name] | None = Field(default=None, max_length=MAX_TARGETS)
    window_s: Annotated[Number, Field(ge=0.0, le=10.0)] = 1.0


class GzTarget(Strict):
    joint: Name
    position_rad: Finite


class SetJointTargets(GzSession):
    model: Name
    targets: list[GzTarget] = Field(min_length=1, max_length=MAX_TARGETS)
    dry_run: bool = False


class Control(GzSession):
    action: Literal["pause", "play", "step", "reset"]
    steps: int = Field(default=1, ge=1, le=10_000)
    reset_scope: Literal["all", "time", "model_only"] = "all"
    dry_run: bool = False


class GzWaypoint(Strict):
    t_s: Annotated[Number, Field(ge=0.0, le=60.0)]
    positions: dict[Name, Finite] = Field(min_length=1, max_length=MAX_TARGETS)


class GzSweep(Strict):
    joint: Name
    lower: Finite
    upper: Finite
    speed_rad_s: Annotated[Number, Field(gt=0.0, le=1e3)]


class RunRoutine(GzSession):
    model: Name
    routine: Literal["joint_trajectory", "sweep"]
    duration_s: Annotated[Number, Field(ge=1.0, le=60.0)]
    joints: list[Name] | None = Field(default=None, max_length=MAX_TARGETS)
    waypoints: list[GzWaypoint] | None = Field(default=None, max_length=MAX_TARGETS)
    sweep: GzSweep | None = None
    dry_run: bool = False


class StopWorld(GzSession):
    dry_run: bool = False


class SaveWorld(GzSession):
    dest: RelPath
    dry_run: bool = False


PUBLIC_MODELS: Final[dict[str, type[Strict]]] = {
    "probe": Empty,
    "list_worlds": Empty,
    "open_world": OpenWorld,
    "attach": Attach,
    "list_models": ListModels,
    "spawn": Spawn,
    "joint_state": JointState,
    "set_joint_targets": SetJointTargets,
    "control": Control,
    "run_routine": RunRoutine,
    "stop": StopWorld,
    "save_world": SaveWorld,
}
#: Reads: no preview, no gate, passed to the fork as parsed.
READ_ONLY: Final = frozenset({"probe", "list_worlds", "list_models", "joint_state"})
#: Writers: complete dry-run preview before every native call; gated per call (`save_world`
#: statically). `attach` is neither: a read-only registration the ledger records as the user's.
WRITERS: Final = frozenset(
    {"open_world", "spawn", "set_joint_targets", "control", "run_routine", "stop", "save_world"}
)
