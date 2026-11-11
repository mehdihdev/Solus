"""Strict graph bindings and bounded, generic joint trajectories."""

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
# SOLUSDEV-322 P4-T1: names that may reach argv or USD paths are plain identifiers (never an
# option, never path syntax); root-relative paths are plain components joined by "/".
_PART = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
_PRIM = r"[A-Za-z_][A-Za-z0-9_]*"
Name = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")]
RelPath = Annotated[str, Field(pattern=rf"^{_PART}(/{_PART}){{0,15}}$", max_length=512)]
PrimPath = Annotated[str, Field(pattern=rf"^/{_PRIM}(/{_PRIM}){{0,31}}$", max_length=512)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MAX_ROUTINE_S: Final = 60
MAX_TARGET_SPEED_RAD_S: Final = 0.25
MAX_DATA_B64: Final = 96 * 1024
MAX_MANIFEST_FILES: Final = 32
MAX_SENSORS_READ: Final = 8
_B64 = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")


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


class Model(Strict):
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


class Routine(Strict):
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


def _check_ranges(
    limits: dict[str, tuple[float, float]],
    ranges: dict[str, tuple[float, float]],
    observed: dict[str, float],
) -> None:
    for identity, (lower, upper) in ranges.items():
        hard_lower, hard_upper = limits[identity]
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
    if len(ranges) != len(routine.joints):
        raise ValueError("duplicate joint range")
    _check_ranges({j.entity_id: (j.lower_rad, j.upper_rad) for j in model.joints}, ranges, observed)
    count = int(routine.duration_s * 60)
    if not 60 <= count <= MAX_ROUTINE_S * 60:
        raise ValueError("step limit")
    targets = []
    previous = dict(observed)
    for index, waypoint in enumerate(routine.waypoints):
        final = {p.joint_entity_id: p.position_rad for p in waypoint.positions}
        if set(final) != set(names) or len(final) != len(waypoint.positions):
            raise ValueError("exact waypoint joint set required")
        segments = len(routine.waypoints)
        steps = (count * (index + 1) // segments) - (count * index // segments)
        moving_steps = steps - steps // 5
        for identity, value in final.items():
            lower, upper = ranges[identity]
            if (
                not lower <= value <= upper
                or abs(value - previous[identity]) / (moving_steps / 60)
                > MAX_TARGET_SPEED_RAD_S + 1e-12
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


def sweep_targets(sweep: Sweep, duration_s: float, *, start: float) -> list[float]:
    """60 Hz positions: from ``start`` toward ``lower``, then a triangle between the two limits
    at ``speed_rad_s``; never outside them, never faster than the speed. ``start`` must already
    lie inside the range (the observed position the preview showed); float noise within 1e-6
    is clamped onto the nearest bound."""
    if not math.isfinite(start) or not sweep.lower - 1e-6 <= start <= sweep.upper + 1e-6:
        raise ValueError("observed position outside the sweep range")
    step = sweep.speed_rad_s / 60
    targets: list[float] = []
    position, goal = min(max(start, sweep.lower), sweep.upper), sweep.lower
    for _ in range(int(duration_s * 60)):
        if abs(goal - position) <= step:
            position = goal
            goal = sweep.upper if goal == sweep.lower else sweep.lower
        else:
            position += step if goal > position else -step
        targets.append(position)
    return targets


# --- the user's own stage (SOLUSDEV-322 P4-T1): pure argument shapes --------------------------
# `actions.py` adds the scene-generation guard and `dry_run` for the worker; `server.py` adds
# `session_id` for the wire. `stage_ref` / `dest` / asset `path` are root-relative and are
# confined by `stages.py` and `assets.py`; `name` and prim paths are plain identifiers.


class ListStages(Strict):
    pass


class OpenStage(Strict):
    stage_ref: RelPath


class FindArticulations(Strict):
    pass


class SpawnAtPose(Strict):
    xyz: Vec3 = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rpy: Vec3 = Field(default_factory=lambda: [0.0, 0.0, 0.0])


class SpawnAt(Strict):
    model_sha256: Sha256
    name: Name
    pose: SpawnAtPose = Field(default_factory=SpawnAtPose)


class ReadState(Strict):
    articulation: PrimPath | None = None
    sensors: Annotated[list[PrimPath], Field(max_length=MAX_SENSORS_READ)] = Field(
        default_factory=list
    )
    camera_frame: bool = False


class StageControl(Strict):
    action: Literal["pause", "play", "step", "reset"]
    steps: Annotated[int, BeforeValidator(actual_integer), Field(ge=1, le=10_000)] = 1


class SaveStage(Strict):
    dest: RelPath

    @model_validator(mode="after")
    def writable_suffix(self) -> Self:
        if PurePosixPath(self.dest).suffix not in (".usd", ".usda", ".usdc"):
            raise ValueError("a stage is saved as .usd, .usda or .usdc")
        return self


class PutAsset(Strict):
    sha256: Sha256
    path: RelPath
    index: Annotated[int, BeforeValidator(actual_integer), Field(ge=0, le=100_000)]
    total: Annotated[int, BeforeValidator(actual_integer), Field(ge=1, le=100_000)]
    data_b64: Annotated[str, Field(max_length=MAX_DATA_B64)]
    manifest: (
        Annotated[dict[RelPath, Sha256], Field(min_length=1, max_length=MAX_MANIFEST_FILES)] | None
    ) = None

    @model_validator(mode="after")
    def chunk_shape(self) -> Self:
        if _B64.fullmatch(self.data_b64) is None or len(self.data_b64) % 4:
            raise ValueError("data_b64 is not base64")
        if self.index >= self.total:
            raise ValueError("chunk index past total")
        return self
