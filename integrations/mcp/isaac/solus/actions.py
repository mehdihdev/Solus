"""Strict native actions with complete previews and generation invalidation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from .artifacts import RevisionStore
from .assets import copy_verified_assets, verify_assets
from .models import LIMITS, EntityId, Model, Number, Quat, Routine, Strict, Vec3, plan_routine


class MutationUnverifiedError(ValueError):
    def __init__(self, generation: int | None = None) -> None:
        super().__init__("mutation_unverified")
        self.result: dict[str, Any] = {
            "ok": False,
            "reason": "mutation_unverified",
            "execution_started": True,
            "uncertain": True,
            "scene_generation": generation,
        }


class State(Strict):
    graph_digest: str
    expected_scene_generation: Annotated[int, Field(ge=0, le=1000)]
    dry_run: bool


class Load(State):
    model_entity_id: EntityId
    resolved_model: Model


class Limits(State):
    entity_id: EntityId
    lower: Number
    upper: Number


class Pose(State):
    entity_id: EntityId
    translation_m: Vec3
    orientation_wxyz: Quat


class Run(State):
    routine_spec: Routine


SCHEMAS: dict[str, type[State]] = {
    "load_model": Load,
    "set_joint_limits": Limits,
    "set_sensor_pose": Pose,
    "run_routine": Run,
}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _rows(value: dict[str, Any], prefix: str = "") -> list[dict[str, Any]]:
    rows = []
    for key, item in value.items():
        label = prefix + key
        if isinstance(item, list):
            for index, entry in enumerate(item):
                if isinstance(entry, dict):
                    rows.extend(_rows({str(index): entry}, label + "."))
                else:
                    rows.append(
                        {
                            "label": label + "." + str(index),
                            "before": None,
                            "after": json.dumps(entry),
                        }
                    )
        else:
            after = json.dumps(item, sort_keys=True, separators=(",", ":"))
            if isinstance(item, dict) and len(after) > 400:
                rows.extend(_rows(item, label + "."))
                continue
            if len(after) > 400 or len(label) > 200:
                raise ValueError("preview too large")
            rows.append(
                {
                    "label": label,
                    "before": None,
                    "after": re.sub(
                        r"\b[0-9a-f]{64}\b",
                        lambda match: ":".join(match[0][i : i + 16] for i in range(0, 64, 16)),
                        after,
                    ),
                }
            )
    return rows


class ActionEngine:
    def __init__(
        self,
        scene: Any,
        asset_dir: Path,
        private_dir: Path,
        *,
        revision_store: RevisionStore | None = None,
    ) -> None:
        self.scene = scene
        self.revision_store = revision_store
        self.asset_dir = asset_dir
        self.private_dir = private_dir
        self.generation = 0
        self.graph_digest: str | None = None
        self.model: Model | None = None
        self.model_entity_id: str | None = None

    def status(self) -> dict[str, Any]:
        return {
            "scene_generation": self.generation,
            "graph_digest": self.graph_digest,
            "model_entity_id": self.model_entity_id,
            **self.scene.status(),
        }

    def dispatch(self, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if operation not in SCHEMAS:
            raise ValueError("unknown action")
        action = SCHEMAS[operation].model_validate(arguments)
        if action.expected_scene_generation != self.generation:
            raise ValueError("stale scene")
        if not re.fullmatch("[0-9a-f]{64}", action.graph_digest):
            raise ValueError("invalid graph digest")
        if not isinstance(action, Load) and action.graph_digest != self.graph_digest:
            raise ValueError("stale graph")
        data = action.model_dump(exclude={"dry_run"})
        rows, before = self._preview(action, data)
        self._verify_load(action)
        fingerprint = _digest({"operation": operation, "arguments": data, "before": before})
        if action.dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "preview": rows,
                "fingerprint": fingerprint,
                "scene_generation": self.generation,
            }
        return self._apply(action, fingerprint)

    def _apply(self, action: State, fingerprint: str) -> dict[str, Any]:
        # Invalidate the old generation before any effect, including uncertain failures.
        self.generation += 1
        try:
            result = self._execute(action)
        except Exception as error:  # invalidate state when a vendor API fails unexpectedly
            if isinstance(action, Load):
                self.model = None
                self.model_entity_id = None
                self.graph_digest = None
                self.scene.invalidate_loaded_state()
            raise MutationUnverifiedError(self.generation) from error
        artifact: dict[str, Any] | None = None
        if self.revision_store is not None:
            try:
                artifact = self.revision_store.publish(
                    self.generation,
                    {
                        "schema_version": 1,
                        "model_entity_id": self.model_entity_id,
                        "graph_digest": self.graph_digest,
                        "action": action.model_dump(),
                        "readback": result,
                        "fingerprint": fingerprint,
                    },
                )
            except (OSError, ValueError):
                artifact = {
                    "saved": False,
                    "reason": "publication_failed",
                    "relative_path": self.revision_store.relative_path(self.generation),
                }
        return {
            "ok": True,
            "artifact": artifact,
            "scene_generation": self.generation,
            "graph_digest": self.graph_digest,
            "model_entity_id": self.model_entity_id,
            "fingerprint": fingerprint,
            "readback": result,
        }

    def _execute(self, action: State) -> dict[str, Any]:
        result: dict[str, Any]
        if isinstance(action, Load):
            manifest = json.loads(Path(__file__).with_name("so101_manifest.json").read_text())
            digest = verify_assets(self.asset_dir, manifest)
            if digest != action.resolved_model.asset_sha256:
                raise ValueError("asset digest mismatch")
            copied = self.private_dir / ("assets-" + str(self.generation))
            copy_verified_assets(self.asset_dir, manifest, copied)
            result = self.scene.load(
                action.resolved_model,
                copied,
                self.private_dir / ("scene-" + str(self.generation)),
            )
            self.model = action.resolved_model
            self.model_entity_id = action.model_entity_id
            self.graph_digest = action.graph_digest
        elif isinstance(action, Limits):
            result = self.scene.set_joint_limits(action.entity_id, action.lower, action.upper)
        elif isinstance(action, Pose):
            result = self.scene.set_sensor_pose(
                action.entity_id, action.translation_m, action.orientation_wxyz
            )
        elif isinstance(action, Run):
            result = self.scene.run(action.routine_spec, lambda: False)
        else:
            raise ValueError("unknown action")
        return result

    def _validate_edit(self, action: State, before: dict[str, Any]) -> None:
        if isinstance(action, Load):
            return
        if self.model is None:
            raise ValueError("model unavailable")
        if isinstance(action, Limits):
            match = next(
                (joint for joint in self.model.joints if joint.entity_id == action.entity_id), None
            )
            if (
                match is None
                or not LIMITS[match.name][0] <= action.lower < action.upper <= LIMITS[match.name][1]
            ):
                raise ValueError("invalid joint limits")
        elif isinstance(action, Pose):
            sensor = next(
                (sensor for sensor in self.model.sensors if sensor.entity_id == action.entity_id),
                None,
            )
            if sensor is None:
                raise ValueError("sensor unavailable")
            type(sensor).model_validate(
                {
                    **sensor.model_dump(),
                    "translation_m": action.translation_m,
                    "orientation_wxyz": action.orientation_wxyz,
                }
            )
        elif isinstance(action, Run):
            plan_routine(self.model, action.routine_spec, before["positions_rad"])
            for bound in action.routine_spec.joints:
                lower, upper = before["limits_rad"][bound.joint_entity_id]
                if bound.lower < lower - 1e-6 or bound.upper > upper + 1e-6:
                    raise ValueError("range exceeds simulated limits")

    def _verify_load(self, action: State) -> None:
        if isinstance(action, Load):
            manifest = json.loads(Path(__file__).with_name("so101_manifest.json").read_text())
            if verify_assets(self.asset_dir, manifest) != action.resolved_model.asset_sha256:
                raise ValueError("asset digest mismatch")

    def _routine_rows(self, action: Run) -> list[dict[str, Any]]:
        if self.model is None:
            raise ValueError("model unavailable")
        names = {joint.entity_id: joint.name for joint in self.model.joints}
        rows = _rows(
            {
                "graph_digest": action.graph_digest,
                "expected_scene_generation": action.expected_scene_generation,
                "routine": action.routine_spec.routine,
                "timing": {
                    "duration_s": action.routine_spec.duration_s,
                    "physics_steps": int(action.routine_spec.duration_s * 60),
                    "maximum_target_speed_rad_s": 0.25,
                },
                "grasp_criteria": {
                    "phase_settling_fraction": 0.2,
                    "bottle_specific_contact": True,
                    "minimum_lift_m": 0.02,
                    "final_joint_error_rad": 0.01,
                    "bottle_contact_and_lift_entire_final_hold": True,
                },
                "stop_behavior": "Stop stepping on cancellation or timeout; no automatic replay",
            }
        )
        for bound in action.routine_spec.joints:
            if bound.joint_entity_id not in names:
                raise ValueError("joint unavailable")
            rows.extend(
                _rows(
                    {
                        "joint_range": {
                            "entity_id": bound.joint_entity_id,
                            "name": names[bound.joint_entity_id],
                            "lower_rad": bound.lower,
                            "upper_rad": bound.upper,
                        }
                    }
                )
            )
        for waypoint in action.routine_spec.waypoints:
            if any(position.joint_entity_id not in names for position in waypoint.positions):
                raise ValueError("joint unavailable")
            rows.extend(
                _rows(
                    {
                        waypoint.phase + "_positions_rad": {
                            names[position.joint_entity_id]: position.position_rad
                            for position in waypoint.positions
                        }
                    }
                )
            )
        return rows

    def _preview(
        self, action: State, data: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if isinstance(action, Load):
            rows = _rows({k: v for k, v in data.items() if k != "resolved_model"}) + _rows(
                action.resolved_model.model_dump()
            )
        elif isinstance(action, Run):
            rows = self._routine_rows(action)
        else:
            rows = _rows(data)
        before = self.status()
        self._validate_edit(action, before)
        rows.extend(
            _rows(
                {key: value for key, value in before.items() if key != "link_bindings"}, "Observed."
            )
        )
        if "link_bindings" in before:
            inventory_digest = _digest(before["link_bindings"])
            rows.append(
                {
                    "label": "Unchanged link inventory",
                    "before": ":".join(inventory_digest[i : i + 16] for i in range(0, 64, 16)),
                    "after": None,
                }
            )
        if self.revision_store is not None:
            rows.append(
                {
                    "label": "Simulator revision",
                    "before": None,
                    "after": self.revision_store.relative_path(self.generation + 1),
                }
            )
        if len(rows) > 40:
            raise ValueError("preview too large")
        return rows, before
