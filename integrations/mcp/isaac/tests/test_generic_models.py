"""Two independent robot structures exercise generic model and URDF contracts."""

import hashlib
import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from integrations.mcp.isaac.solus.models import Model


def fixture(count=1):
    links = [{"entity_id": str(UUID(int=i + 1)), "name": f"segment_{i}"} for i in range(count + 1)]
    joints = [
        {
            "entity_id": str(UUID(int=i + 20)),
            "name": f"axis_{i}",
            "parent_link_entity_id": links[i]["entity_id"],
            "child_link_entity_id": links[i + 1]["entity_id"],
            "lower_rad": -1.0,
            "upper_rad": 1.0,
        }
        for i in range(count)
    ]
    files = {"robot.urdf": "a" * 64}
    return {
        "schema_version": 2,
        "asset": {
            "urdf_path": "robot.urdf",
            "files": files,
            "sha256": hashlib.sha256(
                json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        },
        "links": links,
        "joints": joints,
        "sensors": [],
    }


@pytest.mark.parametrize("count", [1, 3])
def test_distinct_models_need_no_builtin_robot(count):
    model = Model.model_validate(fixture(count))
    assert len(model.joints) == count
    assert model.sensors == []


@pytest.mark.parametrize(
    "change", ["legacy", "digest", "traversal", "duplicate", "foreign", "limits"]
)
def test_invalid_model_refused(change):
    data = fixture()
    if change == "legacy":
        data["schema_version"] = 1
    elif change == "digest":
        data["asset"]["sha256"] = "0" * 64
    elif change == "traversal":
        data["asset"]["urdf_path"] = "../robot.urdf"
    elif change == "duplicate":
        data["joints"][0]["entity_id"] = data["links"][0]["entity_id"]
    elif change == "foreign":
        data["joints"][0]["parent_link_entity_id"] = str(UUID(int=999))
    else:
        data["joints"][0]["upper_rad"] = -2.0
    with pytest.raises(ValidationError):
        Model.model_validate(data)


def urdf(count=1):
    links = "".join(f'<link name="segment_{i}"/>' for i in range(count + 1))
    joints = "".join(
        f'<joint name="axis_{i}" type="revolute"><parent link="segment_{i}"/>'
        f'<child link="segment_{i + 1}"/><limit lower="-1" upper="1"'
        ' effort="1" velocity="1"/></joint>'
        for i in range(count)
    )
    return f'<robot name="fixture">{links}{joints}</robot>'.encode()


def materialized(tmp_path, data, content):
    data["asset"]["files"] = {"robot.urdf": hashlib.sha256(content).hexdigest()}
    data["asset"]["sha256"] = hashlib.sha256(
        json.dumps(data["asset"]["files"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    root = tmp_path / ".solus/isaac/models" / data["asset"]["sha256"]
    root.mkdir(parents=True)
    (root / "robot.urdf").write_bytes(content)
    return Model.model_validate(data), root


@pytest.mark.parametrize("count", [1, 3])
def test_private_copy_and_urdf_validation_for_two_robots(tmp_path, count):
    from integrations.mcp.isaac.solus.actions import ActionEngine

    model, source = materialized(tmp_path, fixture(count), urdf(count))
    destination = tmp_path / "private"
    ActionEngine(None, tmp_path, tmp_path)._copy_model(model, destination)
    assert (destination / "robot.urdf").read_bytes() == (source / "robot.urdf").read_bytes()


@pytest.mark.parametrize(
    "bad",
    [
        b'<!DOCTYPE robot><robot name="fixture"/>',
        urdf().replace(b'<robot name="fixture">', b'<robot name="fixture"><plugin/>'),
        urdf().replace(b'<link name="segment_0"/>', b'<link name="segment_0" script="evil.py"/>'),
        urdf().replace(b'upper="1"', b'upper="2"'),
        urdf().replace(
            b'<link name="segment_0"/>', b'<link name="segment_0"><robot name="nested"/></link>'
        ),
        urdf().replace(b'name="fixture"', b'name="bad.*"'),
        urdf().replace(b'type="revolute"', b'type="continuous"'),
        urdf().replace(
            b'<link name="segment_0"/>',
            b'<link name="segment_0"><visual><geometry><mesh filename="package://evil/model.stl"/></geometry></visual></link>',
        ),
    ],
)
def test_unsafe_or_graph_mismatched_urdf_refused(tmp_path, bad):
    from integrations.mcp.isaac.solus.actions import ActionEngine

    model, _ = materialized(tmp_path, fixture(), bad)
    with pytest.raises(ValueError):
        ActionEngine(None, tmp_path, tmp_path)._copy_model(model, tmp_path / "private")


def test_intermediate_asset_symlink_refused(tmp_path):
    from integrations.mcp.isaac.solus.assets import model_asset_directory

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / ".solus").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError):
        with model_asset_directory(tmp_path, "a" * 64):
            pytest.fail("unsafe directory opened")


def test_manifest_change_refused_before_import(tmp_path):
    from integrations.mcp.isaac.solus.actions import ActionEngine

    model, root = materialized(tmp_path, fixture(), urdf())
    (root / "robot.urdf").write_bytes(b"changed")
    with pytest.raises(ValueError):
        ActionEngine(None, tmp_path, tmp_path)._copy_model(model, tmp_path / "private")


@pytest.mark.parametrize(
    "encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be"]
)
def test_encoded_dtd_cannot_bypass_declaration_guard(tmp_path, encoding):
    from integrations.mcp.isaac.solus.actions import ActionEngine

    document = '<!DOCTYPE robot [<!ENTITY alias "fixture">]>' + urdf().decode().replace(
        'name="fixture"', 'name="&alias;"'
    )
    model, _ = materialized(tmp_path, fixture(), document.encode(encoding))
    with pytest.raises(ValueError):
        ActionEngine(None, tmp_path, tmp_path)._copy_model(model, tmp_path / "private")


def test_fifo_asset_refused_without_waiting_for_writer(tmp_path):
    import os
    import subprocess
    import sys

    os.mkfifo(tmp_path / "robot.urdf")
    code = """
import sys
from pathlib import Path
from integrations.mcp.isaac.solus.assets import verify_assets, copy_verified_assets
root = Path(sys.argv[1])
manifest = {"robot.urdf": "a" * 64}
for action in (
    lambda: verify_assets(root, manifest),
    lambda: copy_verified_assets(root, manifest, root / "private"),
):
    try:
        action()
    except ValueError:
        continue
    raise AssertionError("FIFO accepted")
"""
    subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=True, timeout=3)


@pytest.mark.parametrize("count", [1, 3])
def test_native_and_cloud_schema_parity(count):
    from solus_api.agent.tools.isaac_models import SimulationModel

    data = fixture(count)
    assert (
        Model.model_validate(data).model_dump() == SimulationModel.model_validate(data).model_dump()
    )


@pytest.mark.parametrize("count", [1, 3])
def test_generic_trajectory_reports_tracking_without_object_claims(count):
    from types import SimpleNamespace

    from integrations.mcp.isaac.solus.models import Routine
    from integrations.mcp.isaac.solus.scene import NativeScene
    from integrations.mcp.isaac.tests.test_models import routine

    scene = NativeScene(None)
    scene.model = Model.model_validate(fixture(count))
    scene.indices = {joint.entity_id: index for index, joint in enumerate(scene.model.joints)}
    steps = []
    scene._joint_limits = lambda index: [-1.0, 1.0]
    scene.status = lambda: {
        "positions_rad": {joint.entity_id: 0.05 if steps else 0.0 for joint in scene.model.joints}
    }
    scene.robot = SimpleNamespace(set_dof_position_targets=lambda *args, **kwargs: None)
    scene.sim = SimpleNamespace(step=lambda **kwargs: steps.append(1))
    result = scene.run(Routine.model_validate(routine(scene.model)), lambda: False)
    assert result["targets_reached"] is True
    assert set(result) == {
        "targets_reached",
        "target_errors_rad",
        "steps",
        "waypoints",
        "positions_rad",
    }
    assert result["steps"] == len(steps) == 360
    assert [entry["step"] for entry in result["waypoints"]] == [120, 240, 360]


@pytest.mark.parametrize(
    "declaration",
    [
        b'<?xml version="1.0" encoding="utf-8"?>',
        b'<?xml\nversion="1.0"\nencoding="utf-8"?>\n',
        b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>",
        b'\xef\xbb\xbf<?xml version="1.0"?>',
    ],
)
def test_standard_utf8_xml_declarations_are_supported(tmp_path, declaration):
    from integrations.mcp.isaac.solus.actions import ActionEngine

    model, _ = materialized(tmp_path, fixture(), declaration + urdf())
    ActionEngine(None, tmp_path, tmp_path)._copy_model(model, tmp_path / "private")


@pytest.mark.parametrize(
    "declaration",
    [
        b'<?xml version="1.0" encoding="utf-16"?>',
        b'<?xml version="1.0"?><?external file="secret"?>',
        b' <?xml version="1.0"?>',
    ],
)
def test_unsupported_or_misplaced_declarations_are_refused(tmp_path, declaration):
    from integrations.mcp.isaac.solus.actions import ActionEngine

    model, _ = materialized(tmp_path, fixture(), declaration + urdf())
    with pytest.raises(ValueError):
        ActionEngine(None, tmp_path, tmp_path)._copy_model(model, tmp_path / "private")
