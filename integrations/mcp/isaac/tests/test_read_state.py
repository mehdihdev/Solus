"""`read_state` and `find_articulations` on the user's own stage: articulation DOFs, IMU and
contact readings, camera metadata plus one bounded frame — reads, through the real engine over
the fake scene. `Sensor.kind` widens to contact|imu|camera."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.actions import ActionEngine
from integrations.mcp.isaac.solus.models import ReadState, Sensor
from integrations.mcp.isaac.tests.conftest import ARM, CAMERA, CONTACT, IMU, FakeScene


def sensor(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "entity_id": str(UUID(int=40)),
        "parent_link_entity_id": str(UUID(int=3)),
        "kind": "contact",
        "translation_m": [0.0, 0.0, 0.0],
        "orientation_wxyz": [1.0, 0.0, 0.0, 0.0],
        "radius_m": 0.01,
    }
    data.update(overrides)
    return data


def test_sensor_kind_widens_to_imu_and_camera_and_contact_keeps_its_radius() -> None:
    assert Sensor.model_validate(sensor()).kind == "contact"
    assert Sensor.model_validate(sensor(kind="imu", radius_m=None)).radius_m is None
    assert Sensor.model_validate(sensor(kind="camera", radius_m=None)).kind == "camera"
    assert Sensor.model_validate(sensor(kind="imu")).radius_m == 0.01  # tolerated, unused
    with pytest.raises(ValidationError):
        Sensor.model_validate(sensor(radius_m=None))  # a contact sensor needs its radius
    with pytest.raises(ValidationError):
        Sensor.model_validate(sensor(kind="lidar"))


@pytest.mark.parametrize(
    "bad",
    [
        {"articulation": "World/arm"},
        {"articulation": "/World/-x"},
        {"sensors": ["/World/a b"]},
        {"sensors": [f"/World/s{i}" for i in range(9)]},
        {"camera_frame": "yes"},
        {"camera_frame": 1},
        {"script": "evil.py"},
    ],
)
def test_read_state_arguments_are_strict(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ReadState.model_validate(bad)
    assert ReadState.model_validate({}).camera_frame is False


def _engine(tmp_path: Path) -> tuple[FakeScene, ActionEngine]:
    scene = FakeScene()
    engine = ActionEngine(scene, tmp_path, tmp_path)
    scene.open_stage(str(tmp_path / "bench.usda"))
    return scene, engine


def test_find_articulations_lists_every_articulation_root(tmp_path: Path) -> None:
    scene, engine = _engine(tmp_path)
    scene.spawn_at(tmp_path / "robot.urdf", "arm2", [0.0] * 3, [0.0] * 3)
    result = engine.dispatch("find_articulations", {})
    assert result["ok"] is True
    assert [a["path"] for a in result["articulations"]] == [ARM, "/World/arm2"]
    assert result["articulations"][0]["dofs"] == ["shoulder", "elbow"]
    assert engine.generation == 0, "a read never bumps the scene generation"
    with pytest.raises(ValidationError):
        engine.dispatch("find_articulations", {"path": "/World"})


def test_read_state_returns_dofs_sensors_and_one_bounded_camera_frame(tmp_path: Path) -> None:
    scene, engine = _engine(tmp_path)
    result = engine.dispatch(
        "read_state", {"articulation": ARM, "sensors": [IMU, CONTACT], "camera_frame": True}
    )
    assert result["ok"] is True and result["paused"] is False
    dofs = result["articulation"]["dofs"]
    assert set(dofs) == {"shoulder", "elbow"}
    assert set(dofs["elbow"]) == {"position_rad", "velocity_rad_s", "lower_rad", "upper_rad"}
    kinds = {reading["path"]: reading["kind"] for reading in result["sensors"]}
    assert kinds == {IMU: "imu", CONTACT: "contact"}
    camera = result["camera"]
    assert camera["path"] == CAMERA and (camera["width"], camera["height"]) == (2, 2)
    assert isinstance(camera["frame_png_b64"], str) and len(camera["frame_png_b64"]) <= 64 * 1024
    assert engine.generation == 0


def test_read_state_defaults_to_the_only_articulation_and_no_frame(tmp_path: Path) -> None:
    scene, engine = _engine(tmp_path)
    result = engine.dispatch("read_state", {})
    assert result["articulation"]["path"] == ARM
    assert result["sensors"] == [] and result["camera"] is None
    scene.articulations = {}
    assert engine.dispatch("read_state", {})["articulation"] is None


def test_read_state_of_an_unknown_prim_is_refused_without_a_vendor_call(tmp_path: Path) -> None:
    scene, engine = _engine(tmp_path)
    for arguments in ({"articulation": "/World/ghost"}, {"sensors": ["/World/ghost"]}):
        with pytest.raises(ValueError):
            engine.dispatch("read_state", arguments)
    assert ("control", "pause", 1) not in scene.calls
