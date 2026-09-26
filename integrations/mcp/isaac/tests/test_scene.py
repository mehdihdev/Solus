import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))


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


def test_routine_cancellation_stops_before_another_physics_step():
    from types import SimpleNamespace

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
    with pytest.raises(TimeoutError, match="stopped"):
        scene.run(Routine.model_validate(routine(scene.model)), lambda: True)
    assert events == ["paused"]


def test_import_preserves_collision_geometry_and_force_drives(monkeypatch, tmp_path):
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
