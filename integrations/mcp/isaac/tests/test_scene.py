import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.scene import grasp_outcome


def test_contact_and_lift_required():
    assert grasp_outcome(
        [{"valid": True, "force_n": 0.2, "bottle_force_n": 0.2, "bottle_contact": True}],
        0.03,
        retained_steps=1,
        required_steps=1,
        targets_reached=True,
    )["grasp_observed"]
    assert not grasp_outcome([{"valid": True, "force_n": 0.0}], 0.03)["grasp_observed"]
    assert not grasp_outcome([{"valid": True, "force_n": 0.2}], 0.0)["grasp_observed"]
    assert not grasp_outcome([{"valid": False, "force_n": 0.2}], 0.03)["grasp_observed"]


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_readback_refused(value):
    with pytest.raises(ValueError):
        grasp_outcome([{"valid": True, "force_n": value}], 0.03)
    with pytest.raises(ValueError):
        grasp_outcome([], value)


def test_limit_edit_uses_isaac6_separate_lower_upper():
    import numpy as np

    from integrations.mcp.isaac.solus.models import Model
    from integrations.mcp.isaac.solus.scene import NativeScene
    from integrations.mcp.isaac.tests.test_models import fixture

    class Array:
        def __init__(self, value):
            self.value = value

        def numpy(self):
            return np.array(self.value)

    class Robot:
        def __init__(self):
            self.lower = -1.0
            self.upper = 1.0

        def get_dof_limits(self, **kwargs):
            return Array([[self.lower]]), Array([[self.upper]])

        def set_dof_limits(self, *, lower, upper, indices, dof_indices):
            assert indices == [0] and dof_indices == [2]
            self.lower = lower[0][0]
            self.upper = upper[0][0]

    scene = NativeScene(None)
    scene.model = Model.model_validate(fixture())
    scene.robot = Robot()
    identity = scene.model.joints[0].entity_id
    scene.indices = {identity: 2}
    result = scene.set_joint_limits(identity, -0.5, 0.5)
    assert result["new_rad"] == [-0.5, 0.5]


def test_incidental_contact_does_not_establish_bottle_grasp():
    result = grasp_outcome([{"valid": True, "force_n": 0.2, "bottle_contact": False}], 0.03)
    assert not result["grasp_observed"]


def test_transient_contact_requires_full_retention_and_tracking():
    contacts = [{"valid": True, "force_n": 0.2, "bottle_force_n": 0.2, "bottle_contact": True}]
    assert not grasp_outcome(
        contacts, 0.03, retained_steps=23, required_steps=24, targets_reached=True
    )["grasp_observed"]
    assert not grasp_outcome(
        contacts, 0.03, retained_steps=24, required_steps=24, targets_reached=False
    )["grasp_observed"]
    result = grasp_outcome(
        contacts, 0.03, retained_steps=24, required_steps=24, targets_reached=True
    )
    assert result["grasp_observed"]
    assert result["retention_steps"] == result["required_retention_steps"] == 24


@pytest.mark.parametrize(
    "bodies, expected",
    [
        (("/robot/jaw", "/SolusBottle"), True),
        (("/SolusBottle", "/robot/jaw"), True),
        (("/robot/jaw", "/SolusGround"), False),
        (("/other/jaw", "/SolusBottle"), False),
    ],
)
def test_contact_identity_matches_bottle_and_bound_jaw(bodies, expected):
    from types import SimpleNamespace

    from integrations.mcp.isaac.solus.models import Model
    from integrations.mcp.isaac.solus.scene import NativeScene
    from integrations.mcp.isaac.tests.test_models import fixture

    scene = NativeScene(None)
    scene.model = Model.model_validate(fixture())
    sensor = scene.model.sensors[0]
    scene.links[sensor.parent_link_entity_id] = "/robot/jaw"
    scene.sensors[sensor.entity_id] = SimpleNamespace(
        get_sensor_reading=lambda: SimpleNamespace(is_valid=True, value=1.0),
        get_data=lambda: {
            "contacts": [{"body0": bodies[0], "body1": bodies[1], "impulse": [0.01, 0.0, 0.0]}]
        },
    )
    observed = scene._bottle_contacts()[0]
    assert observed["bottle_contact"] is expected
    assert observed["bottle_force_n"] == pytest.approx(0.6 if expected else 0.0)


@pytest.mark.parametrize("drop_step, expected", [(None, True), (350, False)])
def test_routine_requires_contact_through_entire_final_hold(drop_step, expected):
    from types import SimpleNamespace

    import numpy as np

    from integrations.mcp.isaac.solus.models import Model, Routine
    from integrations.mcp.isaac.solus.scene import NativeScene
    from integrations.mcp.isaac.tests.test_models import fixture, routine

    scene = NativeScene(None)
    scene.model = Model.model_validate(fixture())
    scene.indices = {joint.entity_id: index for index, joint in enumerate(scene.model.joints)}
    steps = []
    scene._joint_limits = lambda index: [-0.1, 0.1]
    scene.status = lambda: {
        "positions_rad": {joint.entity_id: 0.05 if steps else 0.0 for joint in scene.model.joints}
    }
    scene.robot = SimpleNamespace(set_dof_position_targets=lambda *args, **kwargs: None)
    scene.sim = SimpleNamespace(step=lambda **kwargs: steps.append(1))
    scene.bottle = SimpleNamespace(
        get_world_poses=lambda **kwargs: (
            SimpleNamespace(numpy=lambda: np.array([[0.0, 0.0, 0.03 if steps else 0.0]])),
            None,
        )
    )
    scene._bottle_contacts = lambda: [
        {
            "valid": True,
            "force_n": 1.0,
            "bottle_force_n": 1.0,
            "bottle_contact": len(steps) != drop_step,
        }
    ]
    result = scene.run(Routine.model_validate(routine(scene.model)), lambda: False)
    assert result["grasp_observed"] is expected
    assert [entry["phase"] for entry in result["phases"]] == ["approach", "close", "lift"]
    assert [entry["step"] for entry in result["phases"]] == [120, 240, 360]
    assert result["steps"] == len(steps) == 360
    assert result["retention_steps"] == (24 if expected else 23)


def test_routine_cancellation_stops_before_another_physics_step():
    from types import SimpleNamespace

    import numpy as np

    from integrations.mcp.isaac.solus.models import Model, Routine
    from integrations.mcp.isaac.solus.scene import NativeScene
    from integrations.mcp.isaac.tests.test_models import fixture, routine

    scene = NativeScene(None)
    scene.model = Model.model_validate(fixture())
    scene.indices = {joint.entity_id: index for index, joint in enumerate(scene.model.joints)}
    scene._joint_limits = lambda index: [-0.1, 0.1]
    scene.status = lambda: {"positions_rad": {joint.entity_id: 0.0 for joint in scene.model.joints}}
    events = []
    scene.sim = SimpleNamespace(
        pause=lambda: events.append("paused"), step=lambda **kwargs: events.append("stepped")
    )
    scene.bottle = SimpleNamespace(
        get_world_poses=lambda **kwargs: (
            SimpleNamespace(numpy=lambda: np.array([[0.0, 0.0, 0.0]])),
            None,
        )
    )
    with pytest.raises(TimeoutError, match="stopped"):
        scene.run(Routine.model_validate(routine(scene.model)), lambda: True)
    assert events == ["paused"]


def test_import_preserves_gripper_concavities_and_calibrated_force_drives(monkeypatch, tmp_path):
    from types import ModuleType, SimpleNamespace

    from integrations.mcp.isaac.solus.models import Model
    from integrations.mcp.isaac.solus.scene import NativeScene
    from integrations.mcp.isaac.tests.test_models import fixture

    captured = {}

    class ImportReachedError(Exception):
        pass

    def config(**kwargs):
        captured.update(kwargs)
        raise ImportReachedError

    modules = {
        "isaacsim.core.utils.extensions": {"enable_extension": lambda name: None},
        "isaacsim.asset.importer.urdf": {"URDFImporter": object, "URDFImporterConfig": config},
        "isaacsim.core.api": {"SimulationContext": object},
        "isaacsim.core.experimental.prims": {"Articulation": object, "XformPrim": object},
        "isaacsim.sensors.experimental.physics": {"Contact": object, "ContactSensor": object},
        "pxr": {"Gf": object, "UsdGeom": object, "UsdPhysics": object},
        "omni": {"usd": SimpleNamespace()},
        "omni.usd": {},
    }
    for name, attrs in modules.items():
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    with pytest.raises(ImportReachedError):
        NativeScene(None).load(Model.model_validate(fixture()), tmp_path, tmp_path)
    assert captured["collision_type"] == "Convex Decomposition"
    assert captured["joint_drive_type"] == "force"
    assert captured["override_joint_stiffness"] == 400.0
    assert captured["override_joint_damping"] == 20.0


def test_other_object_force_cannot_substitute_for_bottle_force():
    contact = {"valid": True, "force_n": 10.0, "bottle_force_n": 0.0, "bottle_contact": True}
    assert not grasp_outcome(
        [contact], 0.03, retained_steps=24, required_steps=24, targets_reached=True
    )["grasp_observed"]
