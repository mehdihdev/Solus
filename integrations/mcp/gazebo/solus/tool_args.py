"""Strict argument models for the 13 `gazebo.*` tools (allowlist.yaml).

Every name that can end up in an argv or a protobuf text-format request (`world`, `model`,
`joint`, spawn `name`) is a plain identifier: no leading ``-`` (never an option), no quotes,
braces, colons, backslashes or whitespace (never text-format syntax). Root-relative paths
(`world_ref`, `dest`, asset `path`) are plain components joined by ``/``. Unknown fields are
refused (`extra="forbid"`), nothing is coerced (`strict=True`: `"3"` is not 3 and `"false"` is
not False), numbers are bounded and finite.
"""

from __future__ import annotations

import re
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

_NAME = r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$"
_PART = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
_REL_PATH = rf"^{_PART}(/{_PART}){{0,15}}$"
_B64 = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")
MAX_DATA_B64: Final = 96 * 1024
MAX_TARGETS: Final = 16
MAX_MANIFEST_FILES: Final = 32

Name = Annotated[str, StringConstraints(pattern=_NAME)]
RelPath = Annotated[str, StringConstraints(pattern=_REL_PATH, max_length=512)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SessionId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9-]{1,80}$")]
Finite = Annotated[float, Field(allow_inf_nan=False, ge=-1e6, le=1e6)]
Vec3 = Annotated[list[Finite], Field(min_length=3, max_length=3)]
FamilyName = Literal["classic", "ignition", "gz"]


class StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProbeArgs(StrictArgs):
    pass


class ListWorldsArgs(StrictArgs):
    pass


class OpenWorldArgs(StrictArgs):
    world_ref: RelPath
    family: FamilyName | None = None
    gui: bool = False
    dry_run: bool = False


class AttachArgs(StrictArgs):
    family: FamilyName
    world: Name


class ListModelsArgs(StrictArgs):
    session_id: SessionId


class SpawnPose(StrictArgs):
    xyz: Vec3 = [0.0, 0.0, 0.0]
    rpy: Vec3 = [0.0, 0.0, 0.0]


class SpawnArgs(StrictArgs):
    session_id: SessionId
    model_sha256: Sha256
    name: Name
    pose: SpawnPose = SpawnPose()
    dry_run: bool = False


class JointStateArgs(StrictArgs):
    session_id: SessionId
    model: Name
    joints: list[Name] | None = Field(default=None, max_length=MAX_TARGETS)
    window_s: float = Field(default=1.0, ge=0.0, le=10.0, allow_inf_nan=False)


class JointTarget(StrictArgs):
    joint: Name
    position_rad: Finite


class SetJointTargetsArgs(StrictArgs):
    session_id: SessionId
    model: Name
    targets: list[JointTarget] = Field(min_length=1, max_length=MAX_TARGETS)
    dry_run: bool = False


class ControlArgs(StrictArgs):
    session_id: SessionId
    action: Literal["pause", "play", "step", "reset"]
    steps: int = Field(default=1, ge=1, le=10_000)
    reset_scope: Literal["all", "time", "model_only"] = "all"
    dry_run: bool = False


class TrajectoryWaypoint(StrictArgs):
    t_s: Finite = Field(ge=0.0)
    positions: dict[Name, Finite] = Field(min_length=1, max_length=MAX_TARGETS)


class SweepSpec(StrictArgs):
    joint: Name
    lower: Finite
    upper: Finite
    speed_rad_s: Finite = Field(gt=0.0)


class RunRoutineArgs(StrictArgs):
    session_id: SessionId
    model: Name
    routine: Literal["joint_trajectory", "sweep"]
    duration_s: float = Field(ge=1.0, le=60.0, allow_inf_nan=False)
    joints: list[Name] | None = Field(default=None, max_length=MAX_TARGETS)
    waypoints: list[TrajectoryWaypoint] | None = Field(default=None, max_length=MAX_TARGETS)
    sweep: SweepSpec | None = None
    dry_run: bool = False


class StopArgs(StrictArgs):
    session_id: SessionId
    dry_run: bool = False


class SaveWorldArgs(StrictArgs):
    session_id: SessionId
    dest: RelPath
    dry_run: bool = False


class PutAssetArgs(StrictArgs):
    sha256: Sha256
    path: RelPath
    index: int = Field(ge=0, le=100_000)
    total: int = Field(ge=1, le=100_000)
    data_b64: str = Field(max_length=MAX_DATA_B64)
    manifest: dict[RelPath, Sha256] | None = Field(
        default=None, min_length=1, max_length=MAX_MANIFEST_FILES
    )

    @model_validator(mode="after")
    def _chunk_shape(self) -> PutAssetArgs:
        if _B64.fullmatch(self.data_b64) is None or len(self.data_b64) % 4:
            raise ValueError("data_b64 is not base64")
        if self.index >= self.total:
            raise ValueError("chunk index past total")
        return self


ARG_MODELS: Final[dict[str, type[StrictArgs]]] = {
    "probe": ProbeArgs,
    "list_worlds": ListWorldsArgs,
    "open_world": OpenWorldArgs,
    "attach": AttachArgs,
    "list_models": ListModelsArgs,
    "spawn": SpawnArgs,
    "joint_state": JointStateArgs,
    "set_joint_targets": SetJointTargetsArgs,
    "control": ControlArgs,
    "run_routine": RunRoutineArgs,
    "stop": StopArgs,
    "save_world": SaveWorldArgs,
    "put_asset": PutAssetArgs,
}
