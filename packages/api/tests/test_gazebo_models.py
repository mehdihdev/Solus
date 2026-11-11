"""SOL-visible `gazebo.*` argument models (SOLUSDEV-322 P3-T4): strict, bounded, option-safe."""

from typing import Any

import pytest
from pydantic import ValidationError
from solus_api.agent.tools.gazebo_models import (
    PUBLIC_MODELS,
    READ_ONLY,
    WRITERS,
    Control,
    RunRoutine,
    SetJointTargets,
    Spawn,
)

SESSION = "0a7d9d1e-4b4b-4a1c-9b1e-3c3d1f2e5a6b"
MODEL = "6f1e2d3c-4b5a-4c6d-8e9f-0a1b2c3d4e5f"


def test_every_public_model_is_strict_and_closed() -> None:
    assert set(PUBLIC_MODELS) == {
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
    }
    assert "put_asset" not in PUBLIC_MODELS, "the chunk push is never SOL-visible"
    assert WRITERS | READ_ONLY | {"attach"} == set(PUBLIC_MODELS)
    for name, model in PUBLIC_MODELS.items():
        schema = model.model_json_schema()
        assert schema["additionalProperties"] is False, name
        with pytest.raises(ValidationError):
            model.model_validate({"script": "bad"})


def test_spawn_binds_a_graph_model_never_a_digest() -> None:
    props = Spawn.model_json_schema()["properties"]
    assert "model_entity_id" in props and "model_sha256" not in props
    with pytest.raises(ValidationError):
        Spawn.model_validate({"session_id": SESSION, "model_entity_id": "a" * 64, "name": "arm"})
    spawn = Spawn.model_validate({"session_id": SESSION, "model_entity_id": MODEL, "name": "arm"})
    assert spawn.pose.xyz == [0.0, 0.0, 0.0] and spawn.dry_run is False


@pytest.mark.parametrize(
    "bad", ["-x", "--help", "a b", 'a"b', "a{b", "a:b", "a\\b", "", "x" * 65, "a/b"]
)
def test_names_that_could_become_options_or_text_format_are_refused(bad: str) -> None:
    with pytest.raises(ValidationError):
        Spawn.model_validate({"session_id": SESSION, "model_entity_id": MODEL, "name": bad})
    with pytest.raises(ValidationError):
        SetJointTargets.model_validate(
            {"session_id": SESSION, "model": "arm", "targets": [{"joint": bad, "position_rad": 0}]}
        )


@pytest.mark.parametrize("bad", ["/etc/passwd", "../x.sdf", "a/../b", ".hidden/x", "a//b", "-x"])
def test_paths_are_plain_root_relative_components(bad: str) -> None:
    with pytest.raises(ValidationError):
        PUBLIC_MODELS["open_world"].model_validate({"world_ref": bad})
    with pytest.raises(ValidationError):
        PUBLIC_MODELS["save_world"].model_validate({"session_id": SESSION, "dest": bad})


def test_numbers_are_finite_bounded_and_dumped_as_floats() -> None:
    targets = SetJointTargets.model_validate(
        {"session_id": SESSION, "model": "arm", "targets": [{"joint": "j1", "position_rad": 1}]}
    )
    assert targets.model_dump()["targets"][0]["position_rad"] == 1.0
    for value in (float("nan"), float("inf"), "1", True):
        with pytest.raises(ValidationError):
            SetJointTargets.model_validate(
                {
                    "session_id": SESSION,
                    "model": "arm",
                    "targets": [{"joint": "j1", "position_rad": value}],
                }
            )
    too_many: list[dict[str, Any]] = [{"joint": f"j{i}", "position_rad": 0.0} for i in range(17)]
    with pytest.raises(ValidationError):
        SetJointTargets.model_validate({"session_id": SESSION, "model": "arm", "targets": too_many})
    with pytest.raises(ValidationError):
        Control.model_validate({"session_id": SESSION, "action": "step", "steps": 10_001})
    with pytest.raises(ValidationError):
        Control.model_validate({"session_id": SESSION, "action": "step", "steps": "3"})
    assert Control.model_validate({"session_id": SESSION, "action": "pause"}).steps == 1
    with pytest.raises(ValidationError):
        RunRoutine.model_validate(
            {"session_id": SESSION, "model": "arm", "routine": "sweep", "duration_s": 61}
        )
    routine = RunRoutine.model_validate(
        {"session_id": SESSION, "model": "arm", "routine": "sweep", "duration_s": 5}
    )
    assert routine.model_dump()["duration_s"] == 5.0


@pytest.mark.parametrize("bad", ["", "x" * 81, "a b", "attached/1", "a.b"])
def test_session_ids_are_plain_tokens(bad: str) -> None:
    with pytest.raises(ValidationError):
        PUBLIC_MODELS["stop"].model_validate({"session_id": bad})
    assert PUBLIC_MODELS["stop"].model_validate({"session_id": "attached-" + SESSION})
