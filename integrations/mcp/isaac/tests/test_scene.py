import sys
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

sys.path.insert(0, str(Path(__file__).parents[4]))


def test_limit_edit_uses_isaac6_separate_lower_upper() -> None:
    from integrations.mcp.isaac.solus.models import Model
    from integrations.mcp.isaac.solus.scene import NativeScene
    from integrations.mcp.isaac.tests.test_models import fixture

    class Robot:
        def __init__(self) -> None:
            self.lower = -1.0
            self.upper = 1.0

        def get_dof_limits(self, **kwargs: Any) -> tuple[_Array, _Array]:
            return _Array([[self.lower]]), _Array([[self.upper]])

        def set_dof_limits(
            self,
            *,
            lower: list[list[float]],
            upper: list[list[float]],
            indices: list[int],
            dof_indices: list[int],
        ) -> None:
            assert indices == [0] and dof_indices == [2]
            self.lower = lower[0][0]
            self.upper = upper[0][0]

    scene = NativeScene(None)
    model = Model.model_validate(fixture())
    scene.model = model
    scene.robot = Robot()
    identity = model.joints[0].entity_id
    scene.indices = {identity: 2}
    result = scene.set_joint_limits(identity, -0.5, 0.5)
    assert result["new_rad"] == [-0.5, 0.5]


def test_routine_cancellation_stops_before_another_physics_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from integrations.mcp.isaac.solus.models import Model, Routine
    from integrations.mcp.isaac.solus.scene import NativeScene
    from integrations.mcp.isaac.tests.test_models import fixture, routine

    scene = NativeScene(None)
    model = Model.model_validate(fixture())
    scene.model = model
    scene.indices = {joint.entity_id: index for index, joint in enumerate(model.joints)}
    monkeypatch.setattr(scene, "_joint_limits", lambda index: [-0.1, 0.1])
    monkeypatch.setattr(
        scene, "status", lambda: {"positions_rad": {joint.entity_id: 0.0 for joint in model.joints}}
    )
    events: list[str] = []
    scene.sim = SimpleNamespace(
        pause=lambda: events.append("paused"), step=lambda **kwargs: events.append("stepped")
    )
    with pytest.raises(TimeoutError, match="stopped"):
        scene.run(Routine.model_validate(routine(model)), lambda: True)
    assert events == ["paused"]


def test_import_preserves_collision_geometry_and_force_drives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import ModuleType

    from integrations.mcp.isaac.solus.models import Model
    from integrations.mcp.isaac.solus.scene import NativeScene
    from integrations.mcp.isaac.tests.test_models import fixture

    captured: dict[str, Any] = {}

    class ImportReachedError(Exception):
        pass

    def config(**kwargs: Any) -> None:
        captured.update(kwargs)
        raise ImportReachedError

    modules: dict[str, dict[str, Any]] = {
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


# --- SOLUSDEV-322 P4-T1: the user's own stage (vendor surface stubbed; unverified on hardware)


class _Array:
    def __init__(self, value: list[list[float]]) -> None:
        self.value = value

    def numpy(self) -> NDArray[np.float64]:
        return np.array(self.value)


class _Refs:
    def __init__(self, refs: list[str]) -> None:
        self.refs = refs

    def AddReference(self, path: str) -> bool:  # noqa: N802 — pxr surface
        self.refs.append(path)
        return True


class _Prim:
    def __init__(self, path: str, apis: Iterable[str] = (), type_name: str = "Xform") -> None:
        self._path = path
        self._apis = set(apis)
        self._type = type_name
        self.references: list[str] = []

    def GetPath(self) -> str:  # noqa: N802 — pxr surface
        return self._path

    def GetName(self) -> str:  # noqa: N802
        return self._path.rsplit("/", 1)[-1]

    def GetTypeName(self) -> str:  # noqa: N802
        return self._type

    def HasAPI(self, api: str) -> bool:  # noqa: N802
        return api in self._apis

    def IsValid(self) -> bool:  # noqa: N802
        return True

    def GetReferences(self) -> _Refs:  # noqa: N802
        return _Refs(self.references)


class _Layer:
    def __init__(self, exported: list[str]) -> None:
        self.exported = exported

    def Export(self, path: str) -> bool:  # noqa: N802
        self.exported.append(path)
        Path(path).write_bytes(b"#usda 1.0\n")
        return True


class _Stage:
    def __init__(self, prims: list[_Prim]) -> None:
        self.prims = prims
        self.exported: list[str] = []

    def Traverse(self) -> list[_Prim]:  # noqa: N802
        return list(self.prims)

    def DefinePrim(self, path: str, type_name: str = "Xform") -> _Prim:  # noqa: N802
        prim = _Prim(path, type_name=type_name)
        self.prims.append(prim)
        return prim

    def GetRootLayer(self) -> _Layer:  # noqa: N802
        return _Layer(self.exported)


class _Articulation:
    def __init__(self, path: str, resolve_paths: bool = False) -> None:
        self.path = path
        self.dof_names = ["shoulder", "elbow"]
        self.targets: list[tuple[float, int]] = []
        self.positions = [0.0, 0.1]

    def get_dof_positions(self, **kwargs: Any) -> _Array:
        return _Array([self.positions])

    def get_dof_velocities(self, **kwargs: Any) -> _Array:
        return _Array([[0.0, 0.0]])

    def get_dof_limits(self, **kwargs: Any) -> tuple[_Array, _Array]:
        return _Array([[-1.57, -1.57]]), _Array([[1.57, 1.57]])

    def set_dof_position_targets(
        self, targets: list[list[float]], *, indices: list[int], dof_indices: list[int]
    ) -> None:
        self.targets.append((targets[0][0], dof_indices[0]))
        self.positions[dof_indices[0]] = targets[0][0]


class _Sim:
    def __init__(self, **kwargs: Any) -> None:
        self.events: list[str] = []
        self.playing = True
        self.current_time = 0.0

    def initialize_physics(self) -> None:
        self.events.append("init")

    def play(self) -> None:
        self.playing = True
        self.events.append("play")

    def pause(self) -> None:
        self.playing = False
        self.events.append("pause")

    def stop(self) -> None:
        self.events.append("stop")

    def reset(self) -> None:
        self.events.append("reset")

    def step(self, render: bool = False) -> None:
        self.events.append("step")
        self.current_time += 1 / 60

    def is_playing(self) -> bool:
        return self.playing

    @classmethod
    def clear_instance(cls) -> None:
        pass


Vendor = tuple[list[str], dict[str, _Stage]]


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Vendor:
    from types import ModuleType

    stage_holder: dict[str, _Stage] = {}
    opened: list[str] = []

    def open_stage(path: str) -> bool:
        opened.append(path)
        stage_holder["stage"] = _Stage(
            [
                _Prim("/World"),
                _Prim("/World/arm", apis={"ArticulationRootAPI"}),
                _Prim("/World/cam", type_name="Camera"),
                _Prim("/World/arm/imu", type_name="IsaacImuSensor"),
            ]
        )
        return True

    context = SimpleNamespace(open_stage=open_stage, get_stage=lambda: stage_holder["stage"])
    modules = {
        "omni": SimpleNamespace(usd=SimpleNamespace(get_context=lambda: context)),
        "omni.usd": {"get_context": lambda: context},
        "isaacsim.core.api": {"SimulationContext": _Sim},
        "isaacsim.core.experimental.prims": {"Articulation": _Articulation},
        "isaacsim.core.utils.extensions": {"enable_extension": lambda name: None},
        "pxr": {
            "UsdPhysics": SimpleNamespace(ArticulationRootAPI="ArticulationRootAPI"),
            "Gf": SimpleNamespace(Vec3d=lambda *a: a, Vec3f=lambda *a: a),
            "UsdGeom": SimpleNamespace(
                XformCommonAPI=lambda prim: SimpleNamespace(
                    SetTranslate=lambda v: None, SetRotate=lambda v: None
                )
            ),
        },
    }
    for name, attrs in modules.items():
        module = ModuleType(name)
        module.__dict__.update(attrs if isinstance(attrs, dict) else vars(attrs))
        monkeypatch.setitem(sys.modules, name, module)
    return opened, stage_holder


def test_open_stage_find_articulations_control_sweep_and_export_use_the_documented_surface(
    vendor: Vendor, tmp_path: Path
) -> None:
    from integrations.mcp.isaac.solus.scene import NativeScene

    opened, holder = vendor
    scene = NativeScene(SimpleNamespaceApp())
    result = scene.open_stage(str(tmp_path / "bench.usda"))
    assert opened == [str(tmp_path / "bench.usda")]
    assert result == {"stage": "bench.usda", "prims": 4, "articulations": ["/World/arm"]}
    assert holder["stage"].exported == [], "opening never writes the file"
    found = scene.find_articulations()
    assert found == [{"path": "/World/arm", "name": "arm", "dofs": ["shoulder", "elbow"]}]
    state = scene.articulation_state("/World/arm")
    assert state["dofs"]["elbow"] == {
        "position_rad": 0.1,
        "velocity_rad_s": 0.0,
        "lower_rad": -1.57,
        "upper_rad": 1.57,
    }
    assert scene.control("pause", 1)["paused"] is True
    stepped = scene.control("step", 3)
    assert stepped["steps"] == 3 and scene.sim.events.count("step") >= 3
    assert scene.control("play", 1)["paused"] is False
    swept = scene.run_sweep("/World/arm", "elbow", [0.0, -0.01, -0.02], lambda: False)
    assert swept["steps"] == 3 and swept["final_position_rad"] == -0.02
    assert swept["min_rad"] == -0.02 and swept["max_rad"] == 0.0
    with pytest.raises(TimeoutError):
        scene.run_sweep("/World/arm", "elbow", [0.0], lambda: True)
    export = scene.export_stage(tmp_path / "out.usda")
    assert export["bytes"] == len(b"#usda 1.0\n") and holder["stage"].exported == [
        str(tmp_path / "out.usda")
    ]
    assert scene.status()["paused"] is True  # the cancelled sweep paused the stage
    spawned = scene.spawn_at(tmp_path / "robot.usd", "arm2", [0.1, 0.0, 0.0], [0.0, 0.0, 1.57])
    assert spawned["prim_path"] == "/World/arm2"
    assert holder["stage"].prims[-1].references == [str(tmp_path / "robot.usd")]
    with pytest.raises(ValueError):
        scene.articulation_state("/World/ghost")
    with pytest.raises(ValueError):
        scene.sensor_readings(["/World/ghost"])


def SimpleNamespaceApp() -> SimpleNamespace:  # noqa: N802 — a tiny SimulationApp stand-in
    return SimpleNamespace(update=lambda: None)


def test_png_encoder_produces_a_bounded_grayscale_png() -> None:
    import zlib

    from integrations.mcp.isaac.solus.scene import _png_gray

    data = _png_gray(2, 2, bytes([0, 64, 128, 255]))
    assert (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        and b"IHDR" in data
        and data.endswith(b"IEND\xaeB`\x82")
    )
    idat = data.index(b"IDAT")
    length = int.from_bytes(data[idat - 4 : idat], "big")
    assert zlib.decompress(data[idat + 4 : idat + 4 + length]) == b"\x00\x00\x40\x00\x80\xff"
    assert len(_png_gray(64, 64, bytes(64 * 64))) < 64 * 1024
