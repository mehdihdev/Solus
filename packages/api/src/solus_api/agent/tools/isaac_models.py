"""Strict graph bindings and bounded, generic joint trajectories."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self
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


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Binding(Strict):
    entity_id: EntityId
    name: Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")]


class Sensor(Strict):
    entity_id: EntityId
    parent_link_entity_id: EntityId
    kind: Literal["contact"]
    translation_m: Vec3
    orientation_wxyz: Quat
    radius_m: Annotated[Number, Field(ge=0.001, le=0.05)]

    @model_validator(mode="after")
    def unit_quaternion(self) -> Self:
        if abs(math.sqrt(sum(v * v for v in self.orientation_wxyz)) - 1) > 1e-6:
            raise ValueError("unit quaternion required")
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


class RoutineSpec(Strict):
    routine: Literal["joint_trajectory"]
    duration_s: Annotated[Number, Field(ge=1, le=30)]
    joints: Annotated[list[Range], Field(min_length=1, max_length=16)]
    waypoints: Annotated[list[Waypoint], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def exact_targets(self) -> Self:
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
