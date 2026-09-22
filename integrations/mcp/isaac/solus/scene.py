"""Version-specific Isaac 6 scene operations, imported only in the owned worker."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .models import LIMITS, Model, Routine, plan_routine


def grasp_outcome(
    contacts: list[dict[str, Any]],
    lift_m: float,
    *,
    retained_steps: int = 0,
    required_steps: int = 1,
    targets_reached: bool = False,
) -> dict[str, Any]:
    if not math.isfinite(lift_m) or any(
        not math.isfinite(c["force_n"]) or not math.isfinite(c.get("bottle_force_n", 0.0))
        for c in contacts
    ):
        raise ValueError("nonfinite physics readback")
    bottle_contact = any(
        c["valid"] is True
        and c.get("bottle_force_n", 0.0) > 0.01
        and c.get("bottle_contact") is True
        for c in contacts
    )
    return {
        "grasp_observed": lift_m >= 0.02
        and bottle_contact
        and targets_reached
        and required_steps > 0
        and retained_steps == required_steps,
        "bottle_lift_m": lift_m,
        "contacts": contacts,
        "retention_steps": retained_steps,
        "required_retention_steps": required_steps,
    }


class NativeScene:
    """Own one newly imported, pinned SO-101 scene; callers provide verified assets."""

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
        self.bottle: Any = None

    def invalidate_loaded_state(self) -> None:
        self.model = None
        self.links = {}
        self.indices = {}
        self.sensors = {}
        self.sensor_authors = {}
        self.bottle = None

    def load(self, model: Model, asset_dir: Path, output_dir: Path) -> dict[str, Any]:
        """Use only controller-owned verified closure/output; no public path input."""
        self.invalidate_loaded_state()
        from isaacsim.core.utils.extensions import enable_extension

        enable_extension("isaacsim.asset.importer.urdf")
        enable_extension("isaacsim.sensors.experimental.physics")
        import omni.usd
        from isaacsim.asset.importer.urdf import URDFImporter, URDFImporterConfig
        from isaacsim.core.api import SimulationContext
        from isaacsim.core.experimental.prims import Articulation, XformPrim
        from isaacsim.sensors.experimental.physics import Contact, ContactSensor
        from pxr import Gf, UsdGeom, UsdPhysics

        if self.sim is not None:
            self.sim.stop()
        imported = URDFImporter(
            URDFImporterConfig(
                urdf_path=str(asset_dir / "so101_new_calib.urdf"),
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
        bottle_path = "/SolusBottle"
        cylinder = UsdGeom.Cylinder.Define(self.stage, bottle_path)
        cylinder.CreateRadiusAttr(model.bottle.radius_m)
        cylinder.CreateHeightAttr(model.bottle.height_m)
        cylinder.AddTranslateOp().Set(Gf.Vec3d(*model.bottle.translation_m))
        UsdPhysics.RigidBodyAPI.Apply(cylinder.GetPrim())
        UsdPhysics.CollisionAPI.Apply(cylinder.GetPrim())
        UsdPhysics.MassAPI.Apply(cylinder.GetPrim()).CreateMassAttr(model.bottle.mass_kg)
        self.bottle = XformPrim(bottle_path, resolve_paths=False)
        ground = UsdGeom.Cube.Define(self.stage, "/SolusGround")
        ground.CreateSizeAttr(1.0)
        ground.AddScaleOp().Set(Gf.Vec3f(2.0, 2.0, 0.02))
        ground.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, -0.01))
        UsdPhysics.CollisionAPI.Apply(ground.GetPrim())
        SimulationContext.clear_instance()
        self.sim = SimulationContext(
            physics_dt=1 / 60, rendering_dt=1 / 60, stage_units_in_meters=1.0
        )
        self.robot = Articulation("/so101_new_calib", resolve_paths=False)
        self.sim.initialize_physics()
        self.sim.play()
        for _ in range(5):
            self.sim.step(render=False)
        self.indices = {
            x.entity_id: int(self.robot.get_dof_indices([x.name]).numpy()[0]) for x in model.joints
        }
        if len(set(self.indices.values())) != 6:
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
        bottle_position = self.bottle.get_world_poses(indices=[0])[0].numpy()[0].tolist()
        return {
            "loaded": True,
            "positions_rad": positions,
            "link_bindings": self.links,
            "limits_rad": {
                identity: self._joint_limits(index) for identity, index in self.indices.items()
            },
            "sensor_poses": sensor_poses,
            "bottle_position_m": bottle_position,
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
        name = next(j.name for j in self.model.joints if j.entity_id == entity_id)
        if (
            not math.isfinite(lower)
            or not math.isfinite(upper)
            or not LIMITS[name][0] <= lower < upper <= LIMITS[name][1]
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

    def _bottle_contacts(self) -> list[dict[str, Any]]:
        if self.model is None:
            raise ValueError("model unavailable")
        contacts = []
        jaw_ids = {
            x.entity_id
            for x in self.model.links
            if x.name in ("gripper_link", "moving_jaw_so101_v1_link")
        }
        for spec in self.model.sensors:
            if spec.parent_link_entity_id not in jaw_ids:
                continue
            sensor = self.sensors[spec.entity_id]
            reading = sensor.get_sensor_reading()
            frame = sensor.get_data()
            jaw_path = self.links[spec.parent_link_entity_id]
            bottle_impulses = []
            for contact in frame.get("contacts", []):
                if {contact.get("body0"), contact.get("body1")} != {jaw_path, "/SolusBottle"}:
                    continue
                impulse = contact["impulse"]
                if len(impulse) != 3 or any(not math.isfinite(float(value)) for value in impulse):
                    raise ValueError("invalid contact impulse")
                bottle_impulses.append(math.hypot(*(float(value) for value in impulse)))
            bottle_force = math.fsum(bottle_impulses) * 60.0
            force = float(reading.value)
            if not math.isfinite(force):
                raise ValueError("nonfinite physics readback")
            contacts.append(
                {
                    "entity_id": spec.entity_id,
                    "valid": bool(reading.is_valid),
                    "force_n": force,
                    "bottle_contact": bool(bottle_impulses),
                    "bottle_force_n": bottle_force,
                }
            )
        return contacts

    def run(self, routine: Routine, cancelled: Any) -> dict[str, Any]:
        import time

        if self.model is None:
            raise ValueError("model unavailable")
        targets = plan_routine(self.model, routine, self.status()["positions_rad"])
        for bound in routine.joints:
            limits = self._joint_limits(self.indices[bound.joint_entity_id])
            if bound.lower < float(limits[0]) - 1e-6 or bound.upper > float(limits[1]) + 1e-6:
                raise ValueError("range exceeds simulated limits")
        initial = float(self.bottle.get_world_poses(indices=[0])[0].numpy()[0][2])
        deadline = time.monotonic() + 35
        required_steps = (len(targets) - 2 * len(targets) // 3) // 5
        retained_steps = 0
        phases = []
        phase_ends = {
            len(targets) * (index + 1) // 3: phase
            for index, phase in enumerate(("approach", "close", "lift"))
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
                phases.append(
                    {
                        "phase": phase_ends[step + 1],
                        "step": step + 1,
                        "positions_rad": self.status()["positions_rad"],
                        "bottle_position_m": self.bottle.get_world_poses(indices=[0])[0]
                        .numpy()[0]
                        .tolist(),
                        "contacts": self._bottle_contacts(),
                    }
                )
            if step >= len(targets) - required_steps:
                lift = float(self.bottle.get_world_poses(indices=[0])[0].numpy()[0][2]) - initial
                contact = self._bottle_contacts()
                if grasp_outcome(
                    contact, lift, retained_steps=1, required_steps=1, targets_reached=True
                )["grasp_observed"]:
                    retained_steps += 1
        final = float(self.bottle.get_world_poses(indices=[0])[0].numpy()[0][2])
        contacts = self._bottle_contacts()
        actual = self.status()["positions_rad"]
        errors = {identity: actual[identity] - value for identity, value in targets[-1].items()}
        reached = all(abs(error) <= 0.01 for error in errors.values())
        return {
            "targets_reached": reached,
            "target_errors_rad": errors,
            **grasp_outcome(
                contacts,
                final - initial,
                retained_steps=retained_steps,
                required_steps=required_steps,
                targets_reached=reached,
            ),
            "steps": len(targets),
            "phases": phases,
            "positions_rad": self.status()["positions_rad"],
        }
