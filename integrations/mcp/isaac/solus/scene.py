"""Version-specific Isaac 6 scene operations, imported only in the owned worker."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .models import Model, Routine, plan_routine


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
        from isaacsim.asset.importer.urdf import URDFImporter, URDFImporterConfig
        from isaacsim.core.api import SimulationContext
        from isaacsim.core.experimental.prims import Articulation
        from isaacsim.sensors.experimental.physics import Contact, ContactSensor
        from pxr import Gf, UsdGeom, UsdPhysics

        if self.sim is not None:
            self.sim.stop()
        imported = URDFImporter(
            URDFImporterConfig(
                urdf_path=str(asset_dir / model.asset.urdf_path),
                usd_path=str(output_dir),
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

    def status(self) -> dict[str, Any]:
        if self.model is None:
            return {"loaded": False}
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
        import time

        if self.model is None:
            raise ValueError("model unavailable")
        targets = plan_routine(self.model, routine, self.status()["positions_rad"])
        for bound in routine.joints:
            limits = self._joint_limits(self.indices[bound.joint_entity_id])
            if bound.lower < float(limits[0]) - 1e-6 or bound.upper > float(limits[1]) + 1e-6:
                raise ValueError("range exceeds simulated limits")
        deadline = time.monotonic() + 35
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
