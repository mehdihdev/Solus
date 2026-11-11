"""Routine planning is pure: a sweep is a triangle wave between the bounds at the given speed,
a trajectory is its waypoints in time order and inside `duration_s`; the result reports per-joint
tracking against the LAST target of every joint."""

from __future__ import annotations

import json

import pytest

from integrations.mcp.gazebo.solus.adapters.adapter_base import JointSample
from integrations.mcp.gazebo.solus.gazebo_routines import (
    SWEEP_STEP_S,
    joint_targets_of,
    routine_plan,
    routine_result,
    sample_row,
    sweep_plan,
)
from integrations.mcp.gazebo.solus.tool_args import RunRoutineArgs


def _args(**overrides: object) -> RunRoutineArgs:
    base: dict[str, object] = {"session_id": "s", "model": "twolink", "duration_s": 2.0}
    return RunRoutineArgs.model_validate({**base, **overrides})


def test_sweep_plan_is_a_bounded_triangle_wave() -> None:
    plan = sweep_plan("elbow", -1.0, 1.0, 1.0, 8.0)
    times = [t for t, _ in plan]
    assert times[0] == 0.0 and times[-1] <= 8.0 and len(plan) == int(8.0 / SWEEP_STEP_S) + 1
    positions = [targets["elbow"] for _, targets in plan]
    assert min(positions) >= -1.0 and max(positions) <= 1.0
    assert (
        positions[0] == -1.0 and positions[8] == 1.0 and positions[16] == -1.0
    )  # 2 s up, 2 s down
    with pytest.raises(ValueError):
        sweep_plan("elbow", 1.0, 1.0, 1.0, 2.0)


def test_routine_plan_sorts_and_clips_waypoints_and_requires_its_spec() -> None:
    args = _args(
        routine="joint_trajectory",
        waypoints=[
            {"t_s": 1.5, "positions": {"shoulder": 0.5}},
            {"t_s": 0.0, "positions": {"shoulder": 0.0, "elbow": 0.1}},
            {"t_s": 9.0, "positions": {"shoulder": 9.0}},  # past duration_s: dropped
        ],
    )
    plan = routine_plan(args)
    assert [t for t, _ in plan] == [0.0, 1.5]
    assert joint_targets_of(plan) == {"shoulder": 0.5, "elbow": 0.1}
    with pytest.raises(ValueError, match="waypoints"):
        routine_plan(_args(routine="joint_trajectory"))
    with pytest.raises(ValueError, match="past duration"):
        routine_plan(
            _args(routine="joint_trajectory", waypoints=[{"t_s": 5.0, "positions": {"a": 0.0}}])
        )
    with pytest.raises(ValueError, match="sweep spec"):
        routine_plan(_args(routine="sweep"))
    swept = routine_plan(
        _args(routine="sweep", sweep={"joint": "j", "lower": 0.0, "upper": 1.0, "speed_rad_s": 2.0})
    )
    assert swept[0] == (0.0, {"j": 0.0}) and len(swept) == int(2.0 / SWEEP_STEP_S) + 1


def test_routine_result_reports_tracking_against_the_last_targets() -> None:
    args = _args(routine="joint_trajectory", waypoints=[{"t_s": 0.0, "positions": {"a": 1.0}}])
    plan = [(0.0, {"a": 0.5, "b": 0.0}), (1.0, {"a": 1.0})]
    samples = [
        JointSample("a", 0.9, 0.1, 10.0, False),
        JointSample("a", 0.95, 0.0, 10.5, False),
        JointSample("b", 0.2, None, 10.5, False),
    ]
    result = routine_result(args, "sid", "empty", plan, 2, samples, 2.345)
    assert result["ok"] and result["targets_sent"] == 2 and result["targets_planned"] == 2
    assert result["per_joint"]["a"] == {"target": 1.0, "final": 0.95, "error": pytest.approx(0.05)}
    assert result["per_joint"]["b"]["error"] == pytest.approx(0.2)
    assert result["max_abs_error_rad"] == pytest.approx(0.2)
    assert result["wall_s"] == 2.345 and result["paused"] is False
    assert [s["joint"] for s in result["samples"]] == ["a", "a", "b"]
    empty = routine_result(args, "sid", "empty", plan, 0, [], 0.0)
    assert empty["per_joint"]["a"] == {"target": 1.0, "final": None, "error": None}
    assert empty["max_abs_error_rad"] is None


def test_non_finite_samples_are_none_in_rows_and_ignored_in_tracking() -> None:
    nan, inf = float("nan"), float("inf")
    assert sample_row(JointSample("a", nan, inf, None, False)) == {
        "joint": "a",
        "position": None,
        "velocity": None,
        "sim_time_s": None,
    }
    args = _args(routine="joint_trajectory", waypoints=[{"t_s": 0.0, "positions": {"a": 1.0}}])
    diverged = [JointSample("a", nan, None, None, False)]
    result = routine_result(args, "sid", "empty", [(0.0, {"a": 1.0})], 1, diverged, 1.0)
    assert result["per_joint"]["a"] == {"target": 1.0, "final": None, "error": None}
    assert result["max_abs_error_rad"] is None
    json.dumps(result, allow_nan=False)
