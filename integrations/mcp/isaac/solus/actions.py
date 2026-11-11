"""Strict native actions with complete previews and generation invalidation.

Two surfaces share one engine (SOLUSDEV-322 P4-T1):

- graph-bound (`load_model`, `set_joint_limits`, `set_sensor_pose`, `run_routine` with a
  `joint_trajectory`): :class:`State` actions carry the graph digest the API resolved;
- the user's own stage (`open_stage`, `spawn_at`, `control`, `save_stage`, `run_routine` with
  a `sweep`; the reads `find_articulations`, `read_state`): :class:`StageState` actions carry
  only the scene generation, since no graph model is bound.

Every mutation honours ``dry_run`` with a complete preview, bumps the generation before any
effect, and reports an unverified mutation as uncertain, never as success.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Final

from pydantic import Field

from .artifacts import RevisionStore
from .assets import ModelStore, copy_verified_assets, model_asset_directory, read_under_fd
from .models import (
    EntityId,
    FindArticulations,
    Model,
    Number,
    Quat,
    ReadState,
    RelPath,
    Routine,
    SaveStage,
    SpawnAt,
    StageControl,
    Strict,
    Sweep,
    Vec3,
    plan_routine,
    sweep_targets,
)
from .urdf import STORE_MESH_SUFFIXES, check_urdf, movable_joint_names, validate_urdf

MAX_FRAME_B64: Final = 64 * 1024
ROUTINE_GRACE_S: Final = 10.0


class RefusedError(ValueError):
    """A typed refusal the worker answers with as-is (`{ok: false, code, reason}`); it is raised
    before any effect, so no scene generation is spent and nothing crosses the wire as an
    exception."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(code)
        self.result: dict[str, Any] = {"ok": False, "code": code, "reason": reason}


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


class StageState(Strict):
    expected_scene_generation: Annotated[int, Field(ge=0, le=1000)]
    dry_run: bool


class State(StageState):
    graph_digest: str


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


class Run(StageState):
    graph_digest: str | None = None  # required by a joint trajectory, absent for a sweep
    routine_spec: Routine


class OpenStageAction(StageState):
    # Resolved by the controller from a confined `SOLUS_SIM_ROOTS` root, never a tool input.
    stage_path: Annotated[str, Field(min_length=1, max_length=4096)]
    stage_ref: RelPath


class SpawnAtAction(StageState, SpawnAt):
    pass


class ControlAction(StageState, StageControl):
    pass


class SaveStageAction(StageState, SaveStage):
    dest_state: Annotated[str, Field(max_length=64)] = "absent"  # the controller's observation


SCHEMAS: dict[str, type[StageState]] = {
    "load_model": Load,
    "set_joint_limits": Limits,
    "set_sensor_pose": Pose,
    "run_routine": Run,
    "open_stage": OpenStageAction,
    "spawn_at": SpawnAtAction,
    "control": ControlAction,
    "save_stage": SaveStageAction,
}
READS: dict[str, type[Strict]] = {
    "find_articulations": FindArticulations,
    "read_state": ReadState,
}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _chunked(digest: str) -> str:
    return ":".join(digest[i : i + 16] for i in range(0, 64, 16))


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
                    "after": re.sub(r"\b[0-9a-f]{64}\b", lambda m: _chunked(m[0]), after),
                }
            )
    return rows


def _row(label: str, before: str | None, after: str | None) -> dict[str, Any]:
    return {"label": label, "before": before, "after": after}


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
        self.store = ModelStore(asset_dir)
        self.generation = 0
        self.graph_digest: str | None = None
        self.model: Model | None = None
        self.model_entity_id: str | None = None
        self.stage_ref: str | None = None
        self._executors: dict[type[StageState], Callable[[Any], dict[str, Any]]] = {
            Load: self._do_load,
            Limits: self._do_limits,
            Pose: self._do_pose,
            Run: self._do_run,
            OpenStageAction: self._do_open_stage,
            SpawnAtAction: self._do_spawn_at,
            ControlAction: self._do_control,
            SaveStageAction: self._do_save_stage,
        }

    def status(self) -> dict[str, Any]:
        return {
            "scene_generation": self.generation,
            "graph_digest": self.graph_digest,
            "model_entity_id": self.model_entity_id,
            "stage_ref": self.stage_ref,
            **self.scene.status(),
        }

    # --- dispatch ----------------------------------------------------------------------------

    def dispatch(self, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if operation in READS:
            return self._read(operation, READS[operation].model_validate(arguments))
        if operation not in SCHEMAS:
            raise ValueError("unknown action")
        action = SCHEMAS[operation].model_validate(arguments)
        if action.expected_scene_generation != self.generation:
            raise ValueError("stale scene")
        self._check_graph(action)
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

    def _check_graph(self, action: StageState) -> None:
        digest = getattr(action, "graph_digest", None)
        if isinstance(action, Run) and action.routine_spec.routine == "sweep":
            if digest is not None:
                raise ValueError("a sweep binds no graph digest")
            return
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            if isinstance(action, (State, Run)):
                raise ValueError("invalid graph digest")
            return
        if not isinstance(action, Load) and digest != self.graph_digest:
            raise ValueError("stale graph")

    def _read(self, operation: str, args: Strict) -> dict[str, Any]:
        if operation == "find_articulations":
            payload: dict[str, Any] = {"articulations": self.scene.find_articulations()}
        else:
            payload = self._read_state(args)  # type: ignore[arg-type]
        return {"ok": True, **payload, "scene_generation": self.generation}

    def _read_state(self, args: ReadState) -> dict[str, Any]:
        path = args.articulation
        if path is None:
            found = self.scene.find_articulations()
            path = found[0]["path"] if found else None
        camera = self.scene.camera_frame() if args.camera_frame else None
        if camera is not None and len(camera.get("frame_png_b64") or "") > MAX_FRAME_B64:
            camera = {**camera, "frame_png_b64": None, "frame_dropped": "over the 64 KiB bound"}
        return {
            "articulation": self.scene.articulation_state(path) if path else None,
            "sensors": self.scene.sensor_readings(list(args.sensors)) if args.sensors else [],
            "camera": camera,
            "paused": bool(self.scene.status().get("paused", False)),
        }

    # --- apply -------------------------------------------------------------------------------

    def _apply(self, action: StageState, fingerprint: str) -> dict[str, Any]:
        # Invalidate the old generation before any effect, including uncertain failures.
        self.generation += 1
        try:
            result = self._execute(action)
        except Exception as error:  # invalidate state when a vendor API fails unexpectedly
            if isinstance(action, (Load, OpenStageAction)):
                self._forget_model()
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

    def _forget_model(self) -> None:
        self.model = None
        self.model_entity_id = None
        self.graph_digest = None

    def _execute(self, action: StageState) -> dict[str, Any]:
        for kind, executor in self._executors.items():
            if isinstance(action, kind):
                return executor(action)
        raise ValueError("unknown action")

    def _do_load(self, action: Load) -> dict[str, Any]:
        copied = self.private_dir / ("assets-" + str(self.generation))
        self._copy_model(action.resolved_model, copied)
        result: dict[str, Any] = self.scene.load(
            action.resolved_model, copied, self.private_dir / ("scene-" + str(self.generation))
        )
        self.model = action.resolved_model
        self.model_entity_id = action.model_entity_id
        self.graph_digest = action.graph_digest
        return result

    def _do_limits(self, action: Limits) -> dict[str, Any]:
        result: dict[str, Any] = self.scene.set_joint_limits(
            action.entity_id, action.lower, action.upper
        )
        return result

    def _do_pose(self, action: Pose) -> dict[str, Any]:
        result: dict[str, Any] = self.scene.set_sensor_pose(
            action.entity_id, action.translation_m, action.orientation_wxyz
        )
        return result

    def _do_run(self, action: Run) -> dict[str, Any]:
        spec = action.routine_spec
        if spec.sweep is None:
            result: dict[str, Any] = self.scene.run(spec, lambda: False)
            return result
        start = self._sweep_dof(spec.sweep)["position_rad"]
        targets = sweep_targets(spec.sweep, spec.duration_s, start=start)
        result = self.scene.run_sweep(
            spec.sweep.articulation, spec.sweep.joint, targets, lambda: False
        )
        return result

    def _do_open_stage(self, action: OpenStageAction) -> dict[str, Any]:
        self._forget_model()
        result: dict[str, Any] = self.scene.open_stage(action.stage_path)
        self.stage_ref = action.stage_ref
        return result

    def _do_spawn_at(self, action: SpawnAtAction) -> dict[str, Any]:
        copied = self.private_dir / ("spawn-" + str(self.generation))
        model_file, joints = self._copy_stored(action.model_sha256, copied)
        result: dict[str, Any] = self.scene.spawn_at(
            copied / model_file, action.name, list(action.pose.xyz), list(action.pose.rpy)
        )
        return {**result, "model_file": model_file, "urdf_joints": joints}

    def _do_control(self, action: ControlAction) -> dict[str, Any]:
        result: dict[str, Any] = self.scene.control(action.action, action.steps)
        return result

    def _do_save_stage(self, action: SaveStageAction) -> dict[str, Any]:
        return self._export(action)

    # --- model closures ----------------------------------------------------------------------

    def _copy_model(self, model: Model, destination: Path) -> None:
        with model_asset_directory(self.asset_dir, model.asset.sha256) as source:
            digest = copy_verified_assets(source, model.asset.files, destination)
        if digest != model.asset.sha256:
            raise ValueError("asset digest mismatch")
        validate_urdf(model, destination)

    def _copy_stored(self, sha256: str, destination: Path) -> tuple[str, list[str]]:
        """A Solus-pushed model from the verified store into a private directory; the model
        file name and its movable joints. Only the URDF models Solus generated are spawned: a
        stored USD is refused before any scene call (the user's own USD is a stage to open)."""
        with self.store.verified(sha256) as stored:
            model_file = stored.model_file
            if not model_file.lower().endswith(".urdf"):
                raise RefusedError(
                    "unsupported_model_type",
                    "Solus spawns only the URDF models it generated; open the user's own USD "
                    "through open_stage instead",
                )
            source = Path(f"/proc/self/fd/{stored.fd}/.")
            if copy_verified_assets(source, stored.manifest, destination) != sha256:
                raise ValueError("asset digest mismatch")
            robot = check_urdf(
                read_under_fd(stored.fd, model_file),
                model_file,
                stored.manifest,
                mesh_suffixes=STORE_MESH_SUFFIXES,
            )
        return model_file, movable_joint_names(robot)

    def _verify_load(self, action: StageState) -> None:
        if isinstance(action, Load):
            with tempfile.TemporaryDirectory(dir=self.private_dir) as temporary:
                self._copy_model(action.resolved_model, Path(temporary) / "assets")

    def _export(self, action: SaveStageAction) -> dict[str, Any]:
        """Export the open stage into the private directory; the controller copies it into the
        confined root. A preview exports too (it reports the size) and touches no user file."""
        name = f"stage-export-{self.generation}{PurePosixPath(action.dest).suffix}"
        info: dict[str, Any] = self.scene.export_stage(self.private_dir / name)
        return {"export": name, **info}

    # --- validation and previews ---------------------------------------------------------------

    def _sweep_dof(self, sweep: Sweep) -> dict[str, float]:
        state = self.scene.articulation_state(sweep.articulation)
        dof = state["dofs"].get(sweep.joint)
        if dof is None:
            raise ValueError("joint unavailable")
        if not dof["lower_rad"] - 1e-6 <= sweep.lower < sweep.upper <= dof["upper_rad"] + 1e-6:
            raise ValueError("sweep range exceeds the articulation limits")
        if not sweep.lower - 1e-6 <= dof["position_rad"] <= sweep.upper + 1e-6:
            raise ValueError("observed position outside the sweep range")
        return dict(dof)

    def _validate_edit(self, action: StageState, before: dict[str, Any]) -> None:
        if isinstance(action, Run) and action.routine_spec.sweep is not None:
            self._sweep_dof(action.routine_spec.sweep)
        elif isinstance(action, SaveStageAction):
            if self.stage_ref is None and not before.get("stage"):
                raise ValueError("no stage is open")
        elif isinstance(action, (Limits, Pose, Run)):
            if self.model is None:
                raise ValueError("model unavailable")
            self._validate_graph_edit(action, self.model, before)

    @staticmethod
    def _validate_graph_edit(action: StageState, model: Model, before: dict[str, Any]) -> None:
        if isinstance(action, Limits):
            match = next((j for j in model.joints if j.entity_id == action.entity_id), None)
            if (
                match is None
                or not match.lower_rad <= action.lower < action.upper <= match.upper_rad
            ):
                raise ValueError("invalid joint limits")
        elif isinstance(action, Pose):
            sensor = next((s for s in model.sensors if s.entity_id == action.entity_id), None)
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
            plan_routine(model, action.routine_spec, before["positions_rad"])
            for bound in action.routine_spec.joints:
                lower, upper = before["limits_rad"][bound.joint_entity_id]
                if bound.lower < lower - 1e-6 or bound.upper > upper + 1e-6:
                    raise ValueError("range exceeds simulated limits")

    def _routine_rows(self, action: Run) -> list[dict[str, Any]]:
        spec = action.routine_spec
        if spec.sweep is not None:
            return self._sweep_rows(spec, spec.sweep)
        if self.model is None:
            raise ValueError("model unavailable")
        names = {joint.entity_id: joint.name for joint in self.model.joints}
        rows = _rows(
            {
                "graph_digest": action.graph_digest,
                "expected_scene_generation": action.expected_scene_generation,
                "routine": spec.routine,
                "timing": {
                    "duration_s": spec.duration_s,
                    "physics_steps": int(spec.duration_s * 60),
                    "maximum_target_speed_rad_s": 0.25,
                },
                "tracking_criteria": {
                    "segment_settling_fraction": 0.2,
                    "final_joint_error_rad": 0.01,
                },
                "stop_behavior": "Stop stepping on cancellation or timeout; no automatic replay",
            }
        )
        for bound in spec.joints:
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
        for index, waypoint in enumerate(spec.waypoints):
            if any(position.joint_entity_id not in names for position in waypoint.positions):
                raise ValueError("joint unavailable")
            rows.extend(
                _rows(
                    {
                        f"waypoint_{index + 1}_positions_rad": {
                            names[position.joint_entity_id]: position.position_rad
                            for position in waypoint.positions
                        }
                    }
                )
            )
        return rows

    def _sweep_rows(self, spec: Routine, sweep: Sweep) -> list[dict[str, Any]]:
        dof = self._sweep_dof(sweep)
        return [
            _row("Routine", None, f"sweep {sweep.articulation} / {sweep.joint}"),
            _row("Range", None, f"{sweep.lower:.4f} .. {sweep.upper:.4f} rad (triangle)"),
            _row("Speed", None, f"{sweep.speed_rad_s:.4f} rad/s (cap 0.25)"),
            _row(
                "Timing",
                None,
                f"{spec.duration_s:g} s, {int(spec.duration_s * 60)} physics steps, wall time "
                f"≤ {spec.duration_s + ROUTINE_GRACE_S:g} s",
            ),
            _row("Observed position", f"{dof['position_rad']:.4f} rad", None),
            _row(
                "Articulation limits",
                f"{dof['lower_rad']:.4f} .. {dof['upper_rad']:.4f} rad",
                None,
            ),
            _row("Stop behavior", None, "Stop stepping on cancellation or timeout; no replay"),
        ]

    def _stage_rows(self, action: StageState, data: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(action, OpenStageAction):
            return [_row("Stage", None, action.stage_ref)]
        if isinstance(action, SpawnAtAction):
            with tempfile.TemporaryDirectory(dir=self.private_dir) as temporary:
                model_file, joints = self._copy_stored(
                    action.model_sha256, Path(temporary) / "assets"
                )
            return [
                _row("Model", None, f"{model_file} ({_chunked(action.model_sha256)})"),
                _row("Name in stage", None, action.name),
                _row("Pose", None, f"xyz={action.pose.xyz} rpy={action.pose.rpy}"),
                _row("Joints", None, ", ".join(joints)),
            ]
        if isinstance(action, ControlAction):
            after = (
                f"step {action.steps} iteration(s) (the stage pauses first)"
                if action.action == "step"
                else action.action
            )
            return [_row("Simulation", None, after)]
        if isinstance(action, SaveStageAction):
            export = self._export(action)
            return [
                _row("Destination", action.dest_state, action.dest),
                _row(
                    "Bytes", None, f"{export['bytes']} bytes ({PurePosixPath(action.dest).suffix})"
                ),
                _row("Source", None, f"the open stage ({self.stage_ref or 'unnamed'})"),
            ]
        return _rows(data)

    def _preview(
        self, action: StageState, data: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        before = self.status()
        self._validate_edit(action, before)
        if isinstance(action, Load):
            rows = _rows({k: v for k, v in data.items() if k != "resolved_model"}) + _rows(
                action.resolved_model.model_dump()
            )
        elif isinstance(action, Run):
            rows = self._routine_rows(action)
        elif isinstance(action, (Limits, Pose)):
            rows = _rows(data)
        else:
            rows = self._stage_rows(action, data)
        rows.extend(
            _rows(
                {key: value for key, value in before.items() if key != "link_bindings"}, "Observed."
            )
        )
        if "link_bindings" in before:
            inventory_digest = _digest(before["link_bindings"])
            rows.append(_row("Unchanged link inventory", _chunked(inventory_digest), None))
        if self.revision_store is not None:
            rows.append(
                _row(
                    "Simulator revision",
                    None,
                    self.revision_store.relative_path(self.generation + 1),
                )
            )
        if len(rows) > 40:
            raise ValueError("preview too large")
        return rows, before
