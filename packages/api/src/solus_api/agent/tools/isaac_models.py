"""Cloud-owned Isaac schemas; companion advertisements never grant new inputs."""

import math
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

ASSET_SHA256 = "a1be9138359e044a007a4981817f3a8783fca47985b424f3fa9ca3d02e12b5b9"
LINKS = (
    "base_link",
    "shoulder_link",
    "upper_arm_link",
    "lower_arm_link",
    "wrist_link",
    "gripper_link",
    "gripper_frame_link",
    "moving_jaw_so101_v1_link",
)
LIMITS = {
    "shoulder_pan": (-1.91986, 1.91986),
    "shoulder_lift": (-1.74533, 1.74533),
    "elbow_flex": (-1.69, 1.69),
    "wrist_flex": (-1.65806, 1.65806),
    "wrist_roll": (-2.74385, 2.84121),
    "gripper": (-0.174533, 1.74533),
}


def _finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite number required")
    return float(value)


def _uuid(value: object) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("canonical UUID required")
    return value


def _unit(value: list[float]) -> list[float]:
    if abs(math.hypot(*value) - 1) > 1e-6:
        raise ValueError("unit quaternion required")
    return value


Number = Annotated[float, BeforeValidator(_finite)]
Identity = Annotated[
    str, BeforeValidator(_uuid), Field(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
]
Vector = Annotated[list[Annotated[Number, Field(ge=-10, le=10)]], Field(min_length=3, max_length=3)]
Quaternion = Annotated[list[Number], Field(min_length=4, max_length=4)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Empty(Strict):
    pass


class Start(Strict):
    dry_run: bool = False


class Session(Start):
    session_id: Identity


class Load(Session):
    model_entity_id: Identity


class JointLimits(Session):
    joint_entity_id: Identity
    lower: Number
    upper: Number

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.lower >= self.upper:
            raise ValueError("ordered limits required")
        return self


class SensorPose(Session):
    sensor_entity_id: Identity
    translation_m: Vector
    orientation_wxyz: Quaternion

    @model_validator(mode="after")
    def quaternion(self) -> Self:
        _unit(self.orientation_wxyz)
        return self


class JointRange(Strict):
    joint_entity_id: Identity
    lower: Number
    upper: Number


class Position(Strict):
    joint_entity_id: Identity
    position_rad: Number


class Waypoint(Strict):
    phase: Literal["approach", "close", "lift"]
    positions: Annotated[list[Position], Field(min_length=6, max_length=6)]


class Routine(Session):
    routine: Literal["grasp_bottle"]
    duration_s: Annotated[Number, Field(ge=1, le=30)]
    joints: Annotated[list[JointRange], Field(min_length=6, max_length=6)]
    waypoints: Annotated[list[Waypoint], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def exact_targets(self) -> Self:
        ids = {j.joint_entity_id for j in self.joints}
        if len(ids) != 6 or any(j.lower >= j.upper for j in self.joints):
            raise ValueError("six distinct ordered joint ranges required")
        if [w.phase for w in self.waypoints] != ["approach", "close", "lift"]:
            raise ValueError("ordered routine phases required")
        for waypoint in self.waypoints:
            if {p.joint_entity_id for p in waypoint.positions} != ids:
                raise ValueError("complete waypoint joint set required")
        return self


class Binding(Strict):
    entity_id: Identity
    name: Annotated[str, Field(min_length=1, max_length=64)]


class Sensor(Strict):
    entity_id: Identity
    parent_link_entity_id: Identity
    kind: Literal["contact"]
    translation_m: Vector
    orientation_wxyz: Quaternion
    radius_m: Annotated[Number, Field(ge=0.001, le=0.05)]

    @model_validator(mode="after")
    def quaternion(self) -> Self:
        _unit(self.orientation_wxyz)
        return self


class Bottle(Strict):
    entity_id: Identity
    translation_m: Vector
    radius_m: Annotated[Number, Field(ge=0.01, le=0.1)]
    height_m: Annotated[Number, Field(ge=0.03, le=0.4)]
    mass_kg: Annotated[Number, Field(ge=0.01, le=2)]


def _version(value: object) -> int:
    if type(value) is not int or value != 1:
        raise ValueError("schema version 1 required")
    return value


class SimulationModel(Strict):
    schema_version: Annotated[Literal[1], BeforeValidator(_version)]
    asset: Literal["so101_new_calib_v1"]
    asset_sha256: Literal["a1be9138359e044a007a4981817f3a8783fca47985b424f3fa9ca3d02e12b5b9"]
    links: Annotated[list[Binding], Field(min_length=8, max_length=8)]
    joints: Annotated[list[Binding], Field(min_length=6, max_length=6)]
    sensors: Annotated[list[Sensor], Field(min_length=1, max_length=4)]
    bottle: Bottle

    @model_validator(mode="after")
    def exact_bindings(self) -> Self:
        if {x.name for x in self.links} != set(LINKS) or {x.name for x in self.joints} != set(
            LIMITS
        ):
            raise ValueError("exact pinned topology required")
        ids = self.entity_ids()
        if len(ids) != len(set(ids)) or any(
            s.parent_link_entity_id not in {x.entity_id for x in self.links} for s in self.sensors
        ):
            raise ValueError("distinct model bindings and bound sensor parents required")
        return self

    def entity_ids(self) -> list[str]:
        return (
            [x.entity_id for x in self.links]
            + [x.entity_id for x in self.joints]
            + [x.entity_id for x in self.sensors]
            + [self.bottle.entity_id]
        )


PUBLIC_MODELS: dict[str, type[Strict]] = {
    "probe": Empty,
    "status": Empty,
    "start": Start,
    "stop": Session,
    "load_model": Load,
    "set_joint_limits": JointLimits,
    "set_sensor_pose": SensorPose,
    "run_routine": Routine,
}
