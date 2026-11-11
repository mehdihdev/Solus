"""Strict tool argument models: unknown fields, option-shaped names and
text-format metacharacters are refused before any argv is built."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from integrations.mcp.gazebo.solus import tool_args as ta


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        ta.ProbeArgs.model_validate({"extra": 1})
    with pytest.raises(ValidationError):
        ta.OpenWorldArgs.model_validate({"world_ref": "a.sdf", "shell": "sh"})


@pytest.mark.parametrize(
    "name",
    ["-x", "--pos-t", "a b", 'a"b', "a{b}", "a:b", "a\\b", "a\nb", "a'b", "a<b>", "", "x" * 65],
)
def test_names_that_could_become_options_or_textformat_are_refused(name: str) -> None:
    with pytest.raises(ValidationError):
        ta.JointStateArgs.model_validate({"session_id": "s1", "model": name, "window_s": 1.0})
    with pytest.raises(ValidationError):
        ta.AttachArgs.model_validate({"family": "gz", "world": name})


@pytest.mark.parametrize(
    "ref", ["../w.sdf", "/abs/w.sdf", "a/../w.sdf", "-w.sdf", "a//b.sdf", "x:y"]
)
def test_world_ref_and_dest_refuse_traversal_and_options(ref: str) -> None:
    with pytest.raises(ValidationError):
        ta.OpenWorldArgs.model_validate({"world_ref": ref})
    with pytest.raises(ValidationError):
        ta.SaveWorldArgs.model_validate({"session_id": "s1", "dest": ref})


def test_happy_paths_parse() -> None:
    assert ta.OpenWorldArgs.model_validate({"world_ref": "worlds/shapes.sdf"}).family is None
    spawn = ta.SpawnArgs.model_validate(
        {
            "session_id": "0f3e2a1c-1111-4222-8333-444455556666",
            "model_sha256": "a" * 64,
            "name": "so101",
            "pose": {"xyz": [0, 0, 0.1], "rpy": [0, 0, 1.57]},
        }
    )
    assert spawn.pose.xyz == [0.0, 0.0, 0.1] and spawn.dry_run is False
    targets = ta.SetJointTargetsArgs.model_validate(
        {
            "session_id": "attached-abc",
            "model": "m",
            "targets": [{"joint": "j1", "position_rad": 0.5}],
        }
    )
    assert targets.targets[0].joint == "j1"
    ctl = ta.ControlArgs.model_validate({"session_id": "s", "action": "step", "steps": 10})
    assert ctl.reset_scope == "all"


def test_numeric_bounds_and_nonfinite_values_are_refused() -> None:
    with pytest.raises(ValidationError):
        ta.SpawnArgs.model_validate(
            {
                "session_id": "s",
                "model_sha256": "a" * 64,
                "name": "m",
                "pose": {"xyz": [0, 0, float("nan")], "rpy": [0, 0, 0]},
            }
        )
    with pytest.raises(ValidationError):
        ta.ControlArgs.model_validate({"session_id": "s", "action": "step", "steps": 0})
    with pytest.raises(ValidationError):
        ta.ControlArgs.model_validate({"session_id": "s", "action": "step", "steps": 10_001})
    with pytest.raises(ValidationError):
        ta.JointStateArgs.model_validate({"session_id": "s", "model": "m", "window_s": 11})
    with pytest.raises(ValidationError):
        ta.RunRoutineArgs.model_validate(
            {"session_id": "s", "model": "m", "routine": "sweep", "duration_s": 61}
        )
    with pytest.raises(ValidationError):
        ta.SetJointTargetsArgs.model_validate(
            {
                "session_id": "s",
                "model": "m",
                "targets": [{"joint": f"j{i}", "position_rad": 0} for i in range(17)],
            }
        )


def test_put_asset_chunk_bounds() -> None:
    ok = ta.PutAssetArgs.model_validate(
        {
            "sha256": "b" * 64,
            "path": "so101.urdf",
            "index": 0,
            "total": 1,
            "data_b64": "QUJD",
            "manifest": {"so101.urdf": "c" * 64},
        }
    )
    assert ok.manifest == {"so101.urdf": "c" * 64}
    with pytest.raises(ValidationError):
        ta.PutAssetArgs.model_validate(
            {
                "sha256": "b" * 64,
                "path": "a.urdf",
                "index": 0,
                "total": 1,
                "data_b64": "A" * (96 * 1024 + 4),
            }
        )
    with pytest.raises(ValidationError):
        ta.PutAssetArgs.model_validate(
            {
                "sha256": "b" * 64,
                "path": "a.urdf",
                "index": 0,
                "total": 1,
                "data_b64": "not base64!",
            }
        )
    with pytest.raises(ValidationError):
        ta.PutAssetArgs.model_validate(
            {"sha256": "b" * 64, "path": "../a.urdf", "index": 0, "total": 1, "data_b64": "QUJD"}
        )
    with pytest.raises(ValidationError):
        ta.PutAssetArgs.model_validate(
            {"sha256": "b" * 64, "path": "a.urdf", "index": 2, "total": 1, "data_b64": "QUJD"}
        )


def test_every_tool_has_an_arg_model() -> None:
    assert set(ta.ARG_MODELS) == {
        "probe",
        "list_worlds",
        "open_world",
        "attach",
        "list_models",
        "spawn",
        "joint_state",
        "set_joint_targets",
        "control",
        "run_routine",
        "stop",
        "save_world",
        "put_asset",
    }
    assert all(issubclass(m, ta.StrictArgs) for m in ta.ARG_MODELS.values())
