"""Strict graph bindings, bounded joint trajectories and sweeps, and the user's own stages.

SOLUSDEV-322 P4-T2: the SOL-visible shapes mirror the Isaac fork's `solus/models.py`. Every
name that can reach argv or a USD prim path is a plain identifier (never an option, never path
syntax); root-relative paths (`stage_ref`, `dest`) are plain components joined by ``/`` and are
confined by the fork; `spawn_at` binds a graph `simulation_model` entity, never a digest.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import PurePosixPath
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite number required")
    return float(value)


def uuid_text(value: object) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("canonical UUID required")
    return value


def actual_integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("actual integer required")
    return value


Number = Annotated[float, BeforeValidator(finite)]
EntityId = Annotated[str, BeforeValidator(uuid_text)]
Vec3 = Annotated[list[Annotated[Number, Field(ge=-10, le=10)]], Field(min_length=3, max_length=3)]
Quat = Annotated[list[Number], Field(min_length=4, max_length=4)]
_PART = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
_PRIM = r"[A-Za-z_][A-Za-z0-9_]*"
Name = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")]
RelPath = Annotated[str, Field(pattern=rf"^{_PART}(/{_PART}){{0,15}}$", max_length=512)]
PrimPath = Annotated[str, Field(pattern=rf"^/{_PRIM}(/{_PRIM}){{0,31}}$", max_length=512)]
MAX_ROUTINE_S: Final = 60
MAX_TARGET_SPEED_RAD_S: Final = 0.25
MAX_SENSORS_READ: Final = 8


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Binding(Strict):
    entity_id: EntityId
    name: Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")]


class Sensor(Strict):
    entity_id: EntityId
    parent_link_entity_id: EntityId
    kind: Literal["contact", "imu", "camera"]
    translation_m: Vec3
    orientation_wxyz: Quat
    radius_m: Annotated[Number, Field(ge=0.001, le=0.05)] | None = None  # contact only

    @model_validator(mode="after")
    def unit_quaternion(self) -> Self:
        if abs(math.sqrt(sum(v * v for v in self.orientation_wxyz)) - 1) > 1e-6:
            raise ValueError("unit quaternion required")
        if self.kind == "contact" and self.radius_m is None:
            raise ValueError("a contact sensor needs its sensing radius")
        return self


def safe_path(value: str) -> bool:
    parts = PurePosixPath(value).parts
    return (
        bool(parts)
        and str(PurePosixPath(value)) == value
        and not value.startswith("/")
        and all(
            part not in (".", "..") and re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts
        )
    )


class Asset(Strict):
    urdf_path: Annotated[str, Field(min_length=1, max_length=256)]
    files: Annotated[dict[str, str], Field(min_length=1, max_length=32)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def closure(self) -> Self:
        if (
            not safe_path(self.urdf_path)
            or not self.urdf_path.endswith(".urdf")
            or self.urdf_path not in self.files
        ):
            raise ValueError("manifested relative URDF required")
        if any(
            not safe_path(path) or len(path) > 256 or not re.fullmatch(r"[0-9a-f]{64}", digest)
            for path, digest in self.files.items()
        ):
            raise ValueError("invalid asset manifest")
        if any(path != self.urdf_path and not path.endswith(".stl") for path in self.files):
            raise ValueError("only URDF and STL assets supported")
        digest = hashlib.sha256(
            json.dumps(self.files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if digest != self.sha256:
            raise ValueError("asset manifest digest mismatch")
        return self


class Joint(Binding):
    parent_link_entity_id: EntityId
    child_link_entity_id: EntityId
    lower_rad: Annotated[Number, Field(ge=-100, le=100)]
    upper_rad: Annotated[Number, Field(ge=-100, le=100)]


class SimulationModel(Strict):
    schema_version: Annotated[Literal[2], BeforeValidator(actual_integer)]
    asset: Asset
    links: Annotated[list[Binding], Field(min_length=2, max_length=32)]
    joints: Annotated[list[Joint], Field(min_length=1, max_length=16)]
    sensors: Annotated[list[Sensor], Field(max_length=4)] = Field(default_factory=list)

    def entity_ids(self) -> list[str]:
        return (
            [item.entity_id for item in self.links]
            + [item.entity_id for item in self.joints]
            + [item.entity_id for item in self.sensors]
        )

    @model_validator(mode="after")
    def bindings(self) -> Self:
        ids = self.entity_ids()
        links = {link.entity_id for link in self.links}
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate entity binding")
        if len({link.name for link in self.links}) != len(self.links) or len(
            {joint.name for joint in self.joints}
        ) != len(self.joints):
            raise ValueError("duplicate binding name")
        if any(sensor.parent_link_entity_id not in links for sensor in self.sensors):
            raise ValueError("sensor parent outside model")
        children: set[str] = set()
        parents: dict[str, str] = {}
        for joint in self.joints:
            if (
                not joint.lower_rad < joint.upper_rad
                or joint.parent_link_entity_id not in links
                or joint.child_link_entity_id not in links
            ):
                raise ValueError("invalid joint limits or link binding")
            if joint.child_link_entity_id in children:
                raise ValueError("multiple parents")
            children.add(joint.child_link_entity_id)
            parents[joint.child_link_entity_id] = joint.parent_link_entity_id
        for child in parents:
            seen: set[str] = set()
            while child in parents:
                if child in seen:
                    raise ValueError("cyclic joint topology")
                seen.add(child)
                child = parents[child]
        return self


class Range(Strict):
    joint_entity_id: EntityId
    lower: Number
    upper: Number


class Position(Strict):
    joint_entity_id: EntityId
    position_rad: Number


class Waypoint(Strict):
    positions: Annotated[list[Position], Field(min_length=1, max_length=16)]


class Sweep(Strict):
    """A triangle between two limits of ONE joint of an articulation in the user's own stage."""

    articulation: PrimPath
    joint: Name
    lower: Number
    upper: Number
    speed_rad_s: Annotated[Number, Field(gt=0, le=MAX_TARGET_SPEED_RAD_S)]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.lower >= self.upper:
            raise ValueError("ordered sweep range required")
        return self


class RoutineSpec(Strict):
    routine: Literal["joint_trajectory", "sweep"]
    duration_s: Annotated[Number, Field(ge=1, le=MAX_ROUTINE_S)]
    joints: Annotated[list[Range], Field(max_length=16)] = Field(default_factory=list)
    waypoints: Annotated[list[Waypoint], Field(max_length=16)] = Field(default_factory=list)
    sweep: Sweep | None = None

    @model_validator(mode="after")
    def exact_targets(self) -> Self:
        if self.routine == "sweep":
            if self.sweep is None or self.joints or self.waypoints:
                raise ValueError("a sweep carries exactly its sweep spec")
            return self
        if self.sweep is not None or not self.joints or not self.waypoints:
            raise ValueError("a joint trajectory carries joint ranges and waypoints")
        ids = {joint.joint_entity_id for joint in self.joints}
        if len(ids) != len(self.joints) or any(joint.lower >= joint.upper for joint in self.joints):
            raise ValueError("distinct ordered joint ranges required")
        for waypoint in self.waypoints:
            targets = {position.joint_entity_id for position in waypoint.positions}
            if targets != ids or len(targets) != len(waypoint.positions):
                raise ValueError("exact waypoint joint set required")
        return self


class Empty(Strict):
    pass


class Start(Strict):
    dry_run: bool = False


class Session(Start):
    session_id: EntityId


class Load(Session):
    model_entity_id: EntityId


class JointLimits(Session):
    joint_entity_id: EntityId
    lower: Number
    upper: Number

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.lower >= self.upper:
            raise ValueError("ordered limits required")
        return self


class SensorPose(Session):
    sensor_entity_id: EntityId
    translation_m: Vec3
    orientation_wxyz: Quat

    @model_validator(mode="after")
    def quaternion(self) -> Self:
        if abs(math.hypot(*self.orientation_wxyz) - 1) > 1e-6:
            raise ValueError("unit quaternion required")
        return self


class Routine(Session, RoutineSpec):
    pass


# --- the user's own stage (SOLUSDEV-322 P4-T2) ----------------------------------------------
# Reads name the session only; stage actions carry `dry_run` like every other writer. The fork
# adds `expected_scene_generation` (from `status`) and, for `spawn_at`, the resolved digest.


class SessionRef(Strict):
    session_id: EntityId


class OpenStage(Start):
    stage_ref: RelPath


class FindArticulations(SessionRef):
    pass


class SpawnPose(Strict):
    xyz: Vec3 = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rpy: Vec3 = Field(default_factory=lambda: [0.0, 0.0, 0.0])


class SpawnAt(Session):
    model_entity_id: EntityId
    name: Name
    pose: SpawnPose = Field(default_factory=SpawnPose)


class ReadState(SessionRef):
    articulation: PrimPath | None = None
    sensors: Annotated[list[PrimPath], Field(max_length=MAX_SENSORS_READ)] = Field(
        default_factory=list
    )
    camera_frame: bool = False


class StageControl(Session):
    action: Literal["pause", "play", "step", "reset"]
    steps: Annotated[int, BeforeValidator(actual_integer), Field(ge=1, le=10_000)] = 1


class SaveStage(Session):
    dest: RelPath

    @model_validator(mode="after")
    def writable_suffix(self) -> Self:
        if PurePosixPath(self.dest).suffix not in (".usd", ".usda", ".usdc"):
            raise ValueError("a stage is saved as .usd, .usda or .usdc")
        return self


PUBLIC_MODELS: dict[str, type[Strict]] = {
    "probe": Empty,
    "status": Empty,
    "start": Start,
    "stop": Session,
    "load_model": Load,
    "set_joint_limits": JointLimits,
    "set_sensor_pose": SensorPose,
    "run_routine": Routine,
    "list_stages": Empty,
    "open_stage": OpenStage,
    "find_articulations": FindArticulations,
    "spawn_at": SpawnAt,
    "read_state": ReadState,
    "control": StageControl,
    "save_stage": SaveStage,
}
#: Reads: no preview, no gate, passed to the fork as parsed.
READ_ONLY: Final = frozenset({"probe", "status", "list_stages", "find_articulations", "read_state"})
