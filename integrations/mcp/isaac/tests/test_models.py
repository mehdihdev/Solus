import sys
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.models import Model, Routine, plan_routine


def fixture():
    from integrations.mcp.isaac.tests.test_generic_models import fixture as generic

    data = generic()
    data["sensors"] = [
        {
            "entity_id": str(UUID(int=40)),
            "parent_link_entity_id": data["links"][-1]["entity_id"],
            "kind": "contact",
            "translation_m": [0.0, 0.0, 0.0],
            "orientation_wxyz": [1.0, 0.0, 0.0, 0.0],
            "radius_m": 0.01,
        }
    ]
    return data


def test_valid_model():
    assert Model.model_validate(fixture()).asset.urdf_path == "robot.urdf"


@pytest.mark.parametrize("bad", [True, "0.1", float("nan"), float("inf")])
def test_strict_pose(bad):
    data = fixture()
    data["sensors"][0]["translation_m"][0] = bad
    with pytest.raises(ValidationError):
        Model.model_validate(data)


@pytest.mark.parametrize(
    "mutation", ["duplicate", "missing", "foreign_parent", "quaternion", "extra", "foreign_asset"]
)
def test_model_rejects_unsafe_bindings(mutation):
    data = fixture()
    if mutation == "duplicate":
        data["joints"][0]["entity_id"] = data["links"][0]["entity_id"]
    elif mutation == "missing":
        data["links"].pop()
    elif mutation == "foreign_parent":
        data["sensors"][0]["parent_link_entity_id"] = str(UUID(int=999))
    elif mutation == "quaternion":
        data["sensors"][0]["orientation_wxyz"] = [2.0, 0.0, 0.0, 0.0]
    elif mutation == "extra":
        data["script"] = "evil.py"
    else:
        data["asset"] = "https://evil.test/robot.usd"
    with pytest.raises(ValidationError):
        Model.model_validate(data)


def routine(model):
    positions = [{"joint_entity_id": j.entity_id, "position_rad": 0.05} for j in model.joints]
    return {
        "routine": "joint_trajectory",
        "duration_s": 6.0,
        "joints": [
            {"joint_entity_id": j.entity_id, "lower": -0.1, "upper": 0.1} for j in model.joints
        ],
        "waypoints": [{"positions": positions} for _ in range(3)],
    }


def test_bounded_plan():
    model = Model.model_validate(fixture())
    plan = plan_routine(
        model, Routine.model_validate(routine(model)), {j.entity_id: 0.0 for j in model.joints}
    )
    assert len(plan) == 360
    assert plan[-1] == {j.entity_id: 0.05 for j in model.joints}


@pytest.mark.parametrize(
    "mutation", ["missing_phase", "missing_joint", "range", "speed", "foreign", "nan"]
)
def test_bad_routine(mutation):
    model = Model.model_validate(fixture())
    data = routine(model)
    if mutation == "missing_phase":
        data["waypoints"] = []
    elif mutation == "missing_joint":
        data["waypoints"][0]["positions"] = data["waypoints"][0]["positions"][:-1]
    elif mutation == "range":
        data["joints"][0]["upper"] = 8.0
    elif mutation == "speed":
        data["duration_s"] = 0.1
    elif mutation == "foreign":
        data["joints"][0]["joint_entity_id"] = str(UUID(int=999))
    else:
        data["waypoints"][0]["positions"][0]["position_rad"] = float("nan")
    with pytest.raises((ValidationError, ValueError)):
        plan_routine(model, Routine.model_validate(data), {j.entity_id: 0.0 for j in model.joints})


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_schema_version_is_actual_integer(value):
    data = fixture()
    data["schema_version"] = value
    with pytest.raises(ValidationError):
        Model.model_validate(data)


def test_each_phase_has_settling_hold_inside_duration():
    model = Model.model_validate(fixture())
    data = routine(model)
    for index, waypoint in enumerate(data["waypoints"]):
        waypoint["positions"] = [
            {"joint_entity_id": j.entity_id, "position_rad": 0.02 * (index + 1)}
            for j in model.joints
        ]
    plan = plan_routine(
        model, Routine.model_validate(data), {j.entity_id: 0.0 for j in model.joints}
    )
    assert len(plan) == 360
    for index in range(3):
        held = plan[(index + 1) * 120 - 24 : (index + 1) * 120]
        assert all(target == held[-1] for target in held)


def test_speed_includes_reserved_settling_time():
    model = Model.model_validate(fixture())
    data = routine(model)
    data["duration_s"] = 1.0
    # 0.075 rad / (20 / 60) fits the old limit, but / (16 / 60) exceeds it.
    for waypoint in data["waypoints"]:
        waypoint["positions"] = [
            {"joint_entity_id": j.entity_id, "position_rad": 0.075} for j in model.joints
        ]
    with pytest.raises(ValueError, match="speed"):
        plan_routine(model, Routine.model_validate(data), {j.entity_id: 0.0 for j in model.joints})
