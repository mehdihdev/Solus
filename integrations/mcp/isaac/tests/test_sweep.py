"""The `sweep` routine: 1–60 s, speed capped at the fork's target-speed bound, a triangle
between two limits that never leaves them; `joint_trajectory` keeps its exact shape and gains
the same 60 s ceiling."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.models import (
    MAX_ROUTINE_S,
    MAX_TARGET_SPEED_RAD_S,
    Model,
    Routine,
    Sweep,
    plan_routine,
    sweep_targets,
)
from integrations.mcp.isaac.tests.test_models import fixture, routine


def sweep(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "routine": "sweep",
        "duration_s": 4.0,
        "sweep": {
            "articulation": "/World/arm",
            "joint": "elbow",
            "lower": -0.5,
            "upper": 0.5,
            "speed_rad_s": 0.25,
        },
    }
    data.update(overrides)
    return data


def test_sweep_bounds_1_to_60_s_and_speed_cap() -> None:
    assert MAX_ROUTINE_S == 60 and MAX_TARGET_SPEED_RAD_S == 0.25
    for duration in (1, 1.0, 60, 60.0):
        assert Routine.model_validate(sweep(duration_s=duration)).duration_s == duration
    for bad_duration in (0.5, 0, 60.5, 61, "4"):
        with pytest.raises(ValidationError):
            Routine.model_validate(sweep(duration_s=bad_duration))
    spec = sweep()
    spec["sweep"] = {**spec["sweep"], "speed_rad_s": MAX_TARGET_SPEED_RAD_S + 0.01}
    with pytest.raises(ValidationError):
        Routine.model_validate(spec)
    for bad in ({"speed_rad_s": 0.0}, {"speed_rad_s": -0.1}, {"lower": 0.5, "upper": 0.5}):
        spec = sweep()
        spec["sweep"] = {**spec["sweep"], **bad}
        with pytest.raises(ValidationError):
            Routine.model_validate(spec)


@pytest.mark.parametrize(
    "articulation", ["World/arm", "/World/-x", "/World/a b", "/", "/World/arm/", "/W{orld"]
)
def test_sweep_articulation_is_a_plain_prim_path(articulation: str) -> None:
    spec = sweep()
    spec["sweep"] = {**spec["sweep"], "articulation": articulation}
    with pytest.raises(ValidationError):
        Routine.model_validate(spec)


def test_routine_kinds_are_exclusive() -> None:
    model = Model.model_validate(fixture())
    trajectory = routine(model)
    with pytest.raises(ValidationError):
        Routine.model_validate({**trajectory, "sweep": sweep()["sweep"]})
    with pytest.raises(ValidationError):
        Routine.model_validate({**sweep(), "joints": trajectory["joints"]})
    with pytest.raises(ValidationError):
        Routine.model_validate({**sweep(), "sweep": None})
    with pytest.raises(ValidationError):
        Routine.model_validate({**trajectory, "joints": [], "waypoints": []})
    assert Routine.model_validate(trajectory).routine == "joint_trajectory"


def test_sweep_targets_triangle_between_bounds_at_speed() -> None:
    spec = Sweep.model_validate(sweep()["sweep"])
    targets = sweep_targets(spec, 8.0, start=0.1)  # 2 rad of travel: 0.6 down, 1.0 up
    assert len(targets) == 480
    assert all(spec.lower <= value <= spec.upper for value in targets)
    step = spec.speed_rad_s / 60
    previous = 0.1
    for value in targets:
        assert abs(value - previous) <= step + 1e-9
        previous = value
    assert min(targets) == spec.lower and max(targets) == spec.upper, "both bounds reached"
    with pytest.raises(ValueError):
        sweep_targets(spec, 8.0, start=0.9)  # outside the sweep range
    noisy = sweep_targets(spec, 1.0, start=spec.upper + 1e-9)  # float noise clamps, never raises
    assert all(spec.lower <= value <= spec.upper for value in noisy)


def test_joint_trajectory_accepts_a_60_s_plan() -> None:
    model = Model.model_validate(fixture())
    data = routine(model)
    data["duration_s"] = 60.0
    plan = plan_routine(
        model, Routine.model_validate(data), {j.entity_id: 0.0 for j in model.joints}
    )
    assert len(plan) == 3600
