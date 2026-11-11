"""Version-specific Isaac scene operations, imported only in the owned worker.

The stage-mode surface below the graph-bound one (SOLUSDEV-322 P4-T1: `open_stage`,
`find_articulations`, `articulation_state`, `sensor_readings`, `camera_frame`, `spawn_at`,
`control`, `run_sweep`, `export_stage`) targets the Isaac 4.x/5.x `isaacsim.*` / `pxr` API
already used by `load`. It is UNVERIFIED ON HARDWARE: this fork was built on an aarch64 host
where Isaac Sim does not run; every call is exercised against stubs (tests/test_scene.py) and
the fixture runtime only (PROVENANCE.md).
"""

from __future__ import annotations

import base64
import hashlib
import math
import struct
import time
import zlib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final

from .models import Model, Routine, plan_routine

ROUTINE_GRACE_S: Final = 10.0
MAX_ARTICULATIONS: Final = 32
FRAME_SIDE_PX: Final = 64


class NativeScene:
    """Own one graph-bound scene imported from a validated private asset closure."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.model: Model | None = None
        self.robot: Any = None
        self.sim: Any = None
        self.sensors: dict[str, Any] = {}
        self.sensor_authors: dict[str, Any] = {}
        self.links: dict[str, str] = {}
        self.indices: dict[str, int] = {}
        self.stage: Any = None
        self.stage_name: str | None = None
        self._handles: dict[str, Any] = {}

    def invalidate_loaded_state(self) -> None:
        self.model = None
        self.links = {}
        self.indices = {}
        self.sensors = {}
        self.sensor_authors = {}

    def load(self, model: Model, asset_dir: Path, output_dir: Path) -> dict[str, Any]:
        """Use only controller-owned verified closure/output; no public path input."""
        self.invalidate_loaded_state()
        from isaacsim.core.utils.extensions import enable_extension

        enable_extension("isaacsim.asset.importer.urdf")
        enable_extension("isaacsim.sensors.experimental.physics")
        import omni.usd
        from isaacsim.core.api import SimulationContext
        from isaacsim.core.experimental.prims import Articulation
        from isaacsim.sensors.experimental.physics import Contact, ContactSensor
        from pxr import Gf, UsdGeom, UsdPhysics

        if self.sim is not None:
            self.sim.stop()
        imported = self._import_urdf(asset_dir / model.asset.urdf_path, output_dir)
        omni.usd.get_context().open_stage(imported)
        for _ in range(5):
            self.app.update()
        self.stage = omni.usd.get_context().get_stage()
        rigid = {
            p.GetName(): str(p.GetPath())
            for p in self.stage.Traverse()
            if p.HasAPI(UsdPhysics.RigidBodyAPI)
        }
        if set(rigid) != {x.name for x in model.links}:
            raise ValueError("imported link mismatch")
        self.links = {x.entity_id: rigid[x.name] for x in model.links}
        self.sensors = {}
        self.sensor_authors = {}
        for sensor in model.sensors:
            path = (
                self.links[sensor.parent_link_entity_id]
                + "/contact_"
                + sensor.entity_id.replace("-", "")
            )
            author = Contact.create(
                path,
                translations=[sensor.translation_m],
                orientations=[sensor.orientation_wxyz],
                radius=sensor.radius_m,
                min_threshold=0.0,
                max_threshold=1000.0,
            )
            self.sensor_authors[sensor.entity_id] = author
            self.sensors[sensor.entity_id] = ContactSensor(author)
            self.sensors[sensor.entity_id].add_raw_contact_data_to_frame()
        ground = UsdGeom.Cube.Define(self.stage, "/SolusGround")
        ground.CreateSizeAttr(1.0)
        ground.AddScaleOp().Set(Gf.Vec3f(2.0, 2.0, 0.02))
        ground.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, -0.01))
        UsdPhysics.CollisionAPI.Apply(ground.GetPrim())
        SimulationContext.clear_instance()
        self.sim = SimulationContext(
            physics_dt=1 / 60, rendering_dt=1 / 60, stage_units_in_meters=1.0
        )
        articulations = [
            str(prim.GetPath())
            for prim in self.stage.Traverse()
            if prim.HasAPI(UsdPhysics.ArticulationRootAPI)
        ]
        if len(articulations) != 1:
            raise ValueError("exactly one imported articulation required")
        self.robot = Articulation(articulations[0], resolve_paths=False)
        self.sim.initialize_physics()
        self.sim.play()
        for _ in range(5):
            self.sim.step(render=False)
        self.indices = {
            x.entity_id: int(self.robot.get_dof_indices([x.name]).numpy()[0]) for x in model.joints
        }
        if len(set(self.indices.values())) != len(model.joints):
            raise ValueError("imported DOF mismatch")
        self.model = model
        return self.status()

    @staticmethod
    def _import_urdf(urdf_path: Path, usd_path: Path) -> str:
        """The one importer configuration of this fork; returns the imported USD path."""
        from isaacsim.asset.importer.urdf import URDFImporter, URDFImporterConfig

        imported: str = URDFImporter(
            URDFImporterConfig(
                urdf_path=str(urdf_path),
                usd_path=str(usd_path),
                fix_base=True,
                merge_fixed_joints=False,
                run_asset_transformer=False,
                joint_target_type="position",
                joint_drive_type="force",
                collision_type="Convex Decomposition",
                override_joint_stiffness=400.0,
                override_joint_damping=20.0,
            )
        ).import_urdf()
        return imported

    def _stage_status(self) -> dict[str, Any]:
        return {
            "stage": self.stage_name,
            "paused": (not self.sim.is_playing()) if self.sim is not None else None,
        }

    def status(self) -> dict[str, Any]:
        if self.model is None:
            return {"loaded": False, **self._stage_status()}
        positions = {
            key: float(self.robot.get_dof_positions(indices=[0], dof_indices=[index]).numpy()[0][0])
            for key, index in self.indices.items()
        }
        if any(not math.isfinite(x) for x in positions.values()):
            raise ValueError("nonfinite joint readback")
        sensor_poses = {}
        for identity, author in self.sensor_authors.items():
            position, orientation = author.get_local_poses(indices=[0])
            sensor_poses[identity] = {
                "translation_m": position.numpy()[0].tolist(),
                "orientation_wxyz": orientation.numpy()[0].tolist(),
            }
        return {
            "loaded": True,
            "positions_rad": positions,
            "link_bindings": self.links,
            "limits_rad": {
                identity: self._joint_limits(index) for identity, index in self.indices.items()
            },
            "sensor_poses": sensor_poses,
            **self._stage_status(),
        }

    def _joint_limits(self, index: int) -> list[float]:
        lower, upper = self.robot.get_dof_limits(indices=[0], dof_indices=[index])
        values = [float(lower.numpy()[0][0]), float(upper.numpy()[0][0])]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("nonfinite limit readback")
        return values

    def set_joint_limits(self, entity_id: str, lower: float, upper: float) -> dict[str, Any]:
        if self.model is None or entity_id not in self.indices:
            raise ValueError("joint unavailable")
        joint = next(j for j in self.model.joints if j.entity_id == entity_id)
        if (
            not math.isfinite(lower)
            or not math.isfinite(upper)
            or not joint.lower_rad <= lower < upper <= joint.upper_rad
        ):
            raise ValueError("invalid joint limits")
        index = self.indices[entity_id]
        old = self._joint_limits(index)
        self.robot.set_dof_limits(
            lower=[[lower]], upper=[[upper]], indices=[0], dof_indices=[index]
        )
        new = self._joint_limits(index)
        if abs(new[0] - lower) > 1e-6 or abs(new[1] - upper) > 1e-6:
            raise ValueError("limit readback mismatch")
        return {"entity_id": entity_id, "old_rad": old, "new_rad": new}

    def set_sensor_pose(
        self, entity_id: str, translation: list[float], orientation: list[float]
    ) -> dict[str, Any]:
        if self.model is None or entity_id not in self.sensor_authors:
            raise ValueError("sensor unavailable")
        sensor = next(s for s in self.model.sensors if s.entity_id == entity_id)
        validated = type(sensor).model_validate(
            {**sensor.model_dump(), "translation_m": translation, "orientation_wxyz": orientation}
        )
        author = self.sensor_authors[entity_id]
        author.set_local_poses(
            translations=[validated.translation_m],
            orientations=[validated.orientation_wxyz],
            indices=[0],
        )
        pos, quat = author.get_local_poses(indices=[0])
        actual_pos = pos.numpy()[0].tolist()
        actual_quat = quat.numpy()[0].tolist()
        if (
            any(abs(a - b) > 1e-6 for a, b in zip(actual_pos, translation, strict=True))
            or abs(abs(sum(a * b for a, b in zip(actual_quat, orientation, strict=True))) - 1)
            > 1e-6
        ):
            raise ValueError("sensor pose readback mismatch")
        return {
            "entity_id": entity_id,
            "translation_m": actual_pos,
            "orientation_wxyz": actual_quat,
        }

    def run(self, routine: Routine, cancelled: Any) -> dict[str, Any]:
        if self.model is None:
            raise ValueError("model unavailable")
        targets = plan_routine(self.model, routine, self.status()["positions_rad"])
        for bound in routine.joints:
            limits = self._joint_limits(self.indices[bound.joint_entity_id])
            if bound.lower < float(limits[0]) - 1e-6 or bound.upper > float(limits[1]) + 1e-6:
                raise ValueError("range exceeds simulated limits")
        deadline = time.monotonic() + routine.duration_s + ROUTINE_GRACE_S
        waypoints = []
        phase_ends = {
            len(targets) * (index + 1) // len(routine.waypoints): index + 1
            for index in range(len(routine.waypoints))
        }
        for step, target in enumerate(targets):
            if cancelled() or time.monotonic() > deadline:
                self.sim.pause()
                raise TimeoutError("routine stopped")
            for identity, value in target.items():
                self.robot.set_dof_position_targets(
                    [[value]], indices=[0], dof_indices=[self.indices[identity]]
                )
            self.sim.step(render=False)
            if step + 1 in phase_ends:
                waypoints.append(
                    {
                        "waypoint": phase_ends[step + 1],
                        "step": step + 1,
                        "positions_rad": self.status()["positions_rad"],
                    }
                )
        actual = self.status()["positions_rad"]
        errors = {identity: actual[identity] - value for identity, value in targets[-1].items()}
        reached = all(abs(error) <= 0.01 for error in errors.values())
        return {
            "targets_reached": reached,
            "target_errors_rad": errors,
            "steps": len(targets),
            "waypoints": waypoints,
            "positions_rad": self.status()["positions_rad"],
        }

    # --- the user's own stage (SOLUSDEV-322 P4-T1) — UNVERIFIED ON HARDWARE -----------------

    def open_stage(self, path: str) -> dict[str, Any]:
        """Open the user's stage read-only (`omni.usd` context); nothing is saved back."""
        import omni.usd
        from isaacsim.core.api import SimulationContext

        self.invalidate_loaded_state()
        self._handles = {}
        if self.sim is not None:
            self.sim.stop()
        if not omni.usd.get_context().open_stage(path):
            raise ValueError("stage failed to open")
        for _ in range(5):
            self.app.update()
        self.stage = omni.usd.get_context().get_stage()
        self.stage_name = Path(path).name
        SimulationContext.clear_instance()
        self.sim = SimulationContext(
            physics_dt=1 / 60, rendering_dt=1 / 60, stage_units_in_meters=1.0
        )
        self.sim.initialize_physics()
        return {
            "stage": self.stage_name,
            "prims": sum(1 for _ in self.stage.Traverse()),
            "articulations": [a["path"] for a in self.find_articulations()],
        }

    def _prims(self) -> dict[str, Any]:
        if self.stage is None:
            raise ValueError("no stage is open")
        return {str(prim.GetPath()): prim for prim in self.stage.Traverse()}

    def _handle(self, path: str) -> Any:
        from isaacsim.core.experimental.prims import Articulation
        from pxr import UsdPhysics

        if path not in self._handles:
            prim = self._prims().get(path)
            if prim is None or not prim.HasAPI(UsdPhysics.ArticulationRootAPI):
                raise ValueError("articulation unavailable")
            self._handles[path] = Articulation(path, resolve_paths=False)
        return self._handles[path]

    def find_articulations(self) -> list[dict[str, Any]]:
        """Every `UsdPhysics.ArticulationRootAPI` prim of the stage (the fork's `load` once
        required exactly one; the user's own stage may carry any number, bounded)."""
        from pxr import UsdPhysics

        found = []
        for path, prim in self._prims().items():
            if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
                found.append(
                    {
                        "path": path,
                        "name": prim.GetName(),
                        "dofs": list(self._handle(path).dof_names),
                    }
                )
            if len(found) > MAX_ARTICULATIONS:
                raise ValueError("too many articulations")
        return found

    def _dof_position(self, handle: Any, index: int) -> float:
        value = float(handle.get_dof_positions().numpy()[0][index])
        if not math.isfinite(value):
            raise ValueError("nonfinite joint readback")
        return value

    def articulation_state(self, path: str) -> dict[str, Any]:
        handle = self._handle(path)
        positions = handle.get_dof_positions().numpy()[0]
        velocities = handle.get_dof_velocities().numpy()[0]
        lower, upper = handle.get_dof_limits()
        lower, upper = lower.numpy()[0], upper.numpy()[0]
        dofs: dict[str, dict[str, float]] = {}
        for index, name in enumerate(handle.dof_names):
            values = {
                "position_rad": float(positions[index]),
                "velocity_rad_s": float(velocities[index]),
                "lower_rad": float(lower[index]),
                "upper_rad": float(upper[index]),
            }
            if any(not math.isfinite(v) for v in values.values()):
                raise ValueError("nonfinite joint readback")
            dofs[str(name)] = values
        return {"path": path, "dofs": dofs}

    def sensor_readings(self, paths: Sequence[str]) -> list[dict[str, Any]]:
        """IMU and contact readings by prim path; a camera prim reports metadata only."""
        prims = self._prims()
        readings: list[dict[str, Any]] = []
        for path in paths:
            prim = prims.get(path)
            kind = prim.GetTypeName() if prim is not None else None
            if kind == "IsaacImuSensor":
                from isaacsim.sensors.physics import IMUSensor

                frame = IMUSensor(prim_path=path).get_current_frame()
                readings.append(
                    {
                        "path": path,
                        "kind": "imu",
                        "lin_acc_m_s2": [float(v) for v in frame["lin_acc"]],
                        "ang_vel_rad_s": [float(v) for v in frame["ang_vel"]],
                        "orientation_wxyz": [float(v) for v in frame["orientation"]],
                    }
                )
            elif kind == "IsaacContactSensor":
                from isaacsim.sensors.physics import ContactSensor

                frame = ContactSensor(prim_path=path).get_current_frame()
                readings.append(
                    {
                        "path": path,
                        "kind": "contact",
                        "in_contact": bool(frame["in_contact"]),
                        "force_n": float(frame["force"]),
                    }
                )
            elif kind == "Camera":
                readings.append({"path": path, "kind": "camera"})
            else:
                raise ValueError("sensor unavailable")
        return readings

    def camera_frame(self) -> dict[str, Any] | None:
        """Metadata of the first camera prim plus ONE small grayscale frame (≤ 64×64 PNG)."""
        cameras = [p for p, prim in self._prims().items() if prim.GetTypeName() == "Camera"]
        if not cameras:
            return None
        from isaacsim.sensors.camera import Camera

        camera = Camera(prim_path=cameras[0], resolution=(FRAME_SIDE_PX, FRAME_SIDE_PX))
        camera.initialize()
        self.sim.step(render=True)
        rgba = camera.get_rgba()
        height, width = int(rgba.shape[0]), int(rgba.shape[1])
        gray = bytes(
            int(sum(float(c) for c in rgba[y][x][:3]) / 3) & 0xFF
            for y in range(height)
            for x in range(width)
        )
        png = _png_gray(width, height, gray)
        return {
            "path": cameras[0],
            "width": width,
            "height": height,
            "frame_png_b64": base64.b64encode(png).decode(),
            "frame_sha256": hashlib.sha256(png).hexdigest(),
        }

    def spawn_at(
        self, model_file: Path, name: str, xyz: Sequence[float], rpy: Sequence[float]
    ) -> dict[str, Any]:
        """Reference a verified model (URDF imported privately, or USD as-is) under
        `/World/<name>` at the pose; the model bytes come from the engine's private copy."""
        from pxr import Gf, UsdGeom

        prim_path = f"/World/{name}"
        if prim_path in self._prims():
            raise ValueError("a prim with that name already exists")
        source = str(model_file)
        if model_file.suffix.lower() == ".urdf":
            source = self._import_urdf(model_file, model_file.parent / "usd")
        prim = self.stage.DefinePrim(prim_path, "Xform")
        if not prim.GetReferences().AddReference(source):
            raise ValueError("model reference refused")
        xform = UsdGeom.XformCommonAPI(prim)
        xform.SetTranslate(Gf.Vec3d(*(float(v) for v in xyz)))
        xform.SetRotate(Gf.Vec3f(*(math.degrees(float(v)) for v in rpy)))
        for _ in range(5):
            self.app.update()
        self._handles = {}
        dofs = [a["dofs"] for a in self.find_articulations() if a["path"].startswith(prim_path)]
        return {"prim_path": prim_path, "dofs": dofs[0] if dofs else []}

    def control(self, action: str, steps: int) -> dict[str, Any]:
        if self.sim is None:
            raise ValueError("no stage is open")
        if action == "pause":
            self.sim.pause()
        elif action == "play":
            self.sim.play()
        elif action == "step":
            self.sim.pause()
            for _ in range(steps):
                self.sim.step(render=False)
        else:
            self.sim.reset()
        return {
            "action": action,
            "steps": steps,
            "paused": not self.sim.is_playing(),
            "sim_time_s": float(self.sim.current_time),
        }

    def run_sweep(
        self, path: str, joint: str, targets: Sequence[float], cancelled: Callable[[], bool]
    ) -> dict[str, Any]:
        handle = self._handle(path)
        names = [str(n) for n in handle.dof_names]
        if joint not in names:
            raise ValueError("joint unavailable")
        index = names.index(joint)
        deadline = time.monotonic() + len(targets) / 60 + ROUTINE_GRACE_S
        samples = []
        for step, target in enumerate(targets):
            if cancelled() or time.monotonic() > deadline:
                self.sim.pause()
                raise TimeoutError("routine stopped")
            handle.set_dof_position_targets([[target]], indices=[0], dof_indices=[index])
            self.sim.step(render=False)
            if (step + 1) % 60 == 0:
                samples.append(
                    {"step": step + 1, "position_rad": self._dof_position(handle, index)}
                )
        return {
            "steps": len(targets),
            "final_position_rad": self._dof_position(handle, index),
            "min_rad": min(targets),
            "max_rad": max(targets),
            "samples": samples,
        }

    def export_stage(self, dest: Path) -> dict[str, Any]:
        """Export the root layer into the engine's PRIVATE directory; the controller alone
        copies it into a confined root (`save_stage`)."""
        if self.stage is None:
            raise ValueError("no stage is open")
        if not self.stage.GetRootLayer().Export(str(dest)):
            raise ValueError("stage export failed")
        if dest.stat().st_size > 20_000_000:
            raise ValueError("exported stage too large")
        data = dest.read_bytes()
        return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _png_gray(width: int, height: int, pixels: bytes) -> bytes:
    """A minimal 8-bit grayscale PNG (stdlib only) for the one bounded camera frame."""
    if len(pixels) != width * height:
        raise ValueError("pixel buffer does not match the frame size")

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + pixels[y * width : (y + 1) * width] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
