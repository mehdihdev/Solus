"""Strict graph bindings and bounded, deterministic SO-101 trajectories."""

from __future__ import annotations

import math
import re
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

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
    name: str


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


class Bottle(Strict):
    entity_id: EntityId
    translation_m: Vec3
    radius_m: Annotated[Number, Field(ge=0.01, le=0.1)]
    height_m: Annotated[Number, Field(ge=0.03, le=0.4)]
    mass_kg: Annotated[Number, Field(ge=0.01, le=2)]


class Model(Strict):
    schema_version: Annotated[Literal[1], BeforeValidator(actual_integer)]
    asset: Literal["so101_new_calib_v1"]
    asset_sha256: str
    links: Annotated[list[Binding], Field(min_length=8, max_length=8)]
    joints: Annotated[list[Binding], Field(min_length=6, max_length=6)]
    sensors: Annotated[list[Sensor], Field(min_length=1, max_length=4)]
    bottle: Bottle

    @model_validator(mode="after")
    def bindings(self) -> Self:
        if not re.fullmatch("[0-9a-f]{64}", self.asset_sha256):
            raise ValueError("asset digest required")
        if {x.name for x in self.links} != set(LINKS) or {x.name for x in self.joints} != set(
            LIMITS
        ):
            raise ValueError("exact SO-101 binding set required")
        ids = [x.entity_id for x in self.links + self.joints]
        ids += [x.entity_id for x in self.sensors] + [self.bottle.entity_id]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate entity binding")
        if any(
            s.parent_link_entity_id not in {x.entity_id for x in self.links} for s in self.sensors
        ):
            raise ValueError("sensor parent outside model")
        return self


class Range(Strict):
    joint_entity_id: EntityId
    lower: Number
    upper: Number


class Position(Strict):
    joint_entity_id: EntityId
    position_rad: Number


class Waypoint(Strict):
    phase: Literal["approach", "close", "lift"]
    positions: Annotated[list[Position], Field(min_length=6, max_length=6)]


class Routine(Strict):
    routine: Literal["grasp_bottle"]
    duration_s: Annotated[Number, Field(ge=1, le=30)]
    joints: Annotated[list[Range], Field(min_length=6, max_length=6)]
    waypoints: Annotated[list[Waypoint], Field(min_length=3, max_length=3)]


def _check_ranges(
    names: dict[str, str], ranges: dict[str, tuple[float, float]], observed: dict[str, float]
) -> None:
    for identity, (lower, upper) in ranges.items():
        hard_lower, hard_upper = LIMITS[names[identity]]
        if not hard_lower <= lower < upper <= hard_upper:
            raise ValueError("range exceeds model limits")
        if not math.isfinite(observed[identity]) or not lower <= observed[identity] <= upper:
            raise ValueError("observed position outside requested range")


def plan_routine(
    model: Model, routine: Routine, observed: dict[str, float]
) -> list[dict[str, float]]:
    """Validate every phase before returning any targets; radians throughout."""
    names = {j.entity_id: j.name for j in model.joints}
    ranges = {r.joint_entity_id: (r.lower, r.upper) for r in routine.joints}
    if set(ranges) != set(names) or set(observed) != set(names):
        raise ValueError("exact joint set required")
    _check_ranges(names, ranges, observed)
    if [w.phase for w in routine.waypoints] != ["approach", "close", "lift"]:
        raise ValueError("ordered approach/close/lift phases required")
    count = int(routine.duration_s * 60)
    if not 60 <= count <= 1800:
        raise ValueError("step limit")
    targets = []
    previous = dict(observed)
    for index, waypoint in enumerate(routine.waypoints):
        final = {p.joint_entity_id: p.position_rad for p in waypoint.positions}
        if set(final) != set(names):
            raise ValueError("exact waypoint joint set required")
        steps = (count * (index + 1) // 3) - (count * index // 3)
        moving_steps = steps - steps // 5
        for identity, value in final.items():
            lower, upper = ranges[identity]
            if (
                not lower <= value <= upper
                or abs(value - previous[identity]) / (moving_steps / 60) > 0.25 + 1e-12
            ):
                raise ValueError("target range or speed exceeded")
        for step in range(1, steps + 1):
            targets.append(
                {
                    key: final[key]
                    if step >= moving_steps
                    else previous[key] + (final[key] - previous[key]) * step / moving_steps
                    for key in names
                }
            )
        previous = final
    return targets
