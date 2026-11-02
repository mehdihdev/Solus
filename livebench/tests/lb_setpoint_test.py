"""SOL setpoint: one bounded move of one joint (SOLUSDEV-319, ADR-014 amendment 2026-10-31).

docs/api/bench-view.md §6.2 and docs/architecture/bench-view.md §6: the goal is clamped by the
actuator into the calibrated span, each 30 Hz tick moves at most 68 ticks, the move ends within
2 ticks of the goal or after 5 s, torque is never touched, and stop / a guard / a lost actuator
end it. Pure logic over a fake `Actuator`.
"""

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest
from livebench.hardware.actuation import (
    ActuatedJoint,
    ActuatorUnavailableError,
    ActuatorWriteError,
    torque_state,
)
from livebench.setpoint import (
    DEFAULT_MAX_STEP_TICKS,
    DEFAULT_RATE_HZ,
    REACHED_TICKS,
    TIMEOUT_SECONDS,
    JointNotFoundError,
    SetpointMove,
    SetpointRefusalError,
    preview,
)
from solus_api.livebench.setpoint import SetpointNotFoundError, SetpointRefusedError
from solus_api.livebench.teleop import NotActuatedError

from livebench import local

FAST_HZ = 1000.0


class FakeActuator:
    """1 tick = 0.1 unit; goals clamp into the span; writes move the servo when `follows`."""

    def __init__(
        self,
        ticks: dict[int, int],
        *,
        span: tuple[int, int] | None = (0, 4000),
        torque: dict[int, bool] | None = None,
    ) -> None:
        self._joints = (
            ActuatedJoint(1, "arm-shoulder_pan.position", "deg", span, "degrees"),
            ActuatedJoint(6, "arm-gripper.position", "%", (0, 1000), "range_0_100"),
        )
        self.ticks = dict(ticks)
        self.torque = {1: True, 6: True} if torque is None else torque
        self.writes: list[dict[int, int]] = []
        self.follows = True
        self.unavailable = False
        self.write_fails_after: int | None = None
        self.silent: set[int] = set()
        self.held = False
        self.released = False

    def joints(self) -> tuple[ActuatedJoint, ...]:
        if self.unavailable:
            raise ActuatorUnavailableError("gap")
        return self._joints

    def read(self) -> dict[int, int]:
        if self.unavailable:
            raise ActuatorUnavailableError("gap")
        return {a: t for a, t in self.ticks.items() if a not in self.silent}

    def to_value(self, address: int, ticks: int) -> float:
        return ticks / 10

    def to_goal(self, address: int, value: float) -> int:
        span = next(j.span for j in self._joints if j.address == address)
        assert span is not None
        return min(span[1], max(span[0], round(value * 10)))

    def write_goals(self, goals: Mapping[int, int]) -> None:
        if self.write_fails_after is not None and len(self.writes) >= self.write_fails_after:
            raise ActuatorWriteError("no ack")
        for address, ticks in goals.items():
            span = next(j.span for j in self._joints if j.address == address)
            if span is None or not span[0] <= ticks <= span[1]:
                raise ValueError(f"goal {ticks} outside {span}")
        self.writes.append(dict(goals))
        if self.follows:
            self.ticks.update(goals)

    def torque_enabled(self) -> dict[int, bool]:
        return dict(self.torque)

    def hold(self) -> dict[int, int]:
        self.held = True
        return {}

    def release(self) -> None:
        self.released = True


class NoTorqueActuator(FakeActuator):
    """A driver without the optional torque read."""

    torque_enabled = None  # type: ignore[assignment]


PAN = "arm-shoulder_pan.position"


def test_motion_bounds_are_the_documented_ones() -> None:
    assert (DEFAULT_RATE_HZ, DEFAULT_MAX_STEP_TICKS) == (30.0, 68)
    assert (REACHED_TICKS, TIMEOUT_SECONDS) == (2, 5.0)


# ── preview ─────────────────────────────────────────────────────────────────────


def test_preview_reads_the_present_value_and_converts_the_target() -> None:
    result = preview(FakeActuator({1: 124, 6: 500}), PAN, 40.0)
    assert (result.address, result.signal, result.unit) == (1, PAN, "deg")
    assert (result.present_ticks, result.current_value) == (124, 12.4)
    assert (result.goal_ticks, result.target_value, result.requested) == (400, 40.0, 40.0)
    assert result.clamped is False and result.span == (0, 4000)


def test_preview_clamps_a_target_outside_the_calibrated_span() -> None:
    high = preview(FakeActuator({1: 500}, span=(100, 950)), PAN, 120.0)
    assert (high.goal_ticks, high.target_value, high.clamped) == (950, 95.0, True)
    low = preview(FakeActuator({1: 500}, span=(100, 950)), PAN, -5.0)
    assert (low.goal_ticks, low.target_value, low.clamped) == (100, 10.0, True)


def test_preview_refuses_a_non_finite_target() -> None:
    with pytest.raises(ValueError):
        preview(FakeActuator({1: 0}), PAN, float("nan"))


def test_preview_unknown_joint_is_not_found() -> None:
    with pytest.raises(JointNotFoundError):
        preview(FakeActuator({1: 0}), "arm-elbow.position", 1.0)


@pytest.mark.parametrize(
    ("actuator", "code"),
    [
        (FakeActuator({1: 0}, span=None), "uncalibrated"),
        (NoTorqueActuator({1: 0}), "uncalibrated"),
        (FakeActuator({1: 0}, torque={1: False, 6: True}), "torque_off"),
        (FakeActuator({1: 0}, torque={6: True}), "torque_off"),
    ],
)
def test_preview_refusals(actuator: FakeActuator, code: str) -> None:
    with pytest.raises(SetpointRefusalError) as caught:
        preview(actuator, PAN, 10.0)
    assert caught.value.code == code
    assert caught.value.unit in ("deg", None)


def test_preview_refuses_a_link_in_its_reconnect_gap_and_a_silent_servo() -> None:
    gap = FakeActuator({1: 0})
    gap.unavailable = True
    with pytest.raises(SetpointRefusalError) as caught:
        preview(gap, PAN, 10.0)
    assert caught.value.code == "not_connected"
    silent = FakeActuator({1: 0})
    silent.silent.add(1)
    with pytest.raises(SetpointRefusalError) as caught:
        preview(silent, PAN, 10.0)
    assert caught.value.code == "not_connected"


def test_torque_state_is_optional_on_the_actuator() -> None:
    assert torque_state(FakeActuator({1: 0})) == {1: True, 6: True}
    assert torque_state(NoTorqueActuator({1: 0})) is None


# ── the move ────────────────────────────────────────────────────────────────────


async def _run(move: SetpointMove) -> str:
    move.start()
    await asyncio.wait_for(move.wait(), timeout=5)
    return move.state


async def test_move_steps_at_most_the_per_tick_limit_and_ends_reached() -> None:
    actuator = FakeActuator({1: 100})
    ended: list[str] = []
    move = SetpointMove(actuator, 1, 400, (0, 4000), rate_hz=FAST_HZ, on_ended=ended.append)
    assert await _run(move) == "reached"
    goals = [100] + [w[1] for w in actuator.writes]
    assert all(abs(b - a) <= DEFAULT_MAX_STEP_TICKS for a, b in zip(goals, goals[1:], strict=False))
    assert goals[-1] == 400 and len(actuator.writes) == 5  # 68*4 = 272 < 300 ≤ 340
    assert ended == ["reached"]
    assert actuator.held is False and actuator.released is False  # torque never touched


async def test_move_already_within_two_ticks_writes_nothing() -> None:
    actuator = FakeActuator({1: 399})
    move = SetpointMove(actuator, 1, 400, (0, 4000), rate_hz=FAST_HZ)
    assert await _run(move) == "reached"
    assert actuator.writes == []


async def test_move_ends_within_two_ticks_of_the_goal() -> None:
    actuator = FakeActuator({1: 100})

    def lagging(goals: Mapping[int, int]) -> None:  # the servo settles 2 ticks short
        actuator.writes.append(dict(goals))
        actuator.ticks[1] = goals[1] - 2 if goals[1] == 400 else goals[1]

    actuator.write_goals = lagging  # type: ignore[method-assign]
    move = SetpointMove(actuator, 1, 400, (0, 4000), rate_hz=FAST_HZ)
    assert await _run(move) == "reached"


async def test_a_stalled_joint_never_lets_the_goal_run_ahead_and_holds_where_it_is() -> None:
    actuator = FakeActuator({1: 100})
    actuator.follows = False  # a stalled joint never gets there
    move = SetpointMove(actuator, 1, 4000, (0, 4000), rate_hz=FAST_HZ, timeout_s=0.05)
    assert await _run(move) == "timed_out"
    assert actuator.released is False
    assert all(abs(w[1] - 100) <= DEFAULT_MAX_STEP_TICKS for w in actuator.writes)
    assert actuator.writes == [{1: 100 + DEFAULT_MAX_STEP_TICKS}, {1: 100}]  # holds the present


async def test_a_partly_blocked_joint_keeps_the_goal_one_step_from_its_measured_position() -> None:
    actuator = FakeActuator({1: 100})

    def blocked(goals: Mapping[int, int]) -> None:  # an obstacle at 230 ticks
        actuator.writes.append(dict(goals))
        actuator.ticks[1] = min(goals[1], 230)

    actuator.write_goals = blocked  # type: ignore[method-assign]
    move = SetpointMove(actuator, 1, 4000, (0, 4000), rate_hz=FAST_HZ, timeout_s=0.05)
    assert await _run(move) == "timed_out"
    assert all(w[1] <= 230 + DEFAULT_MAX_STEP_TICKS for w in actuator.writes)
    assert actuator.writes[-1] == {1: 230}


async def test_a_timeout_before_any_write_writes_nothing() -> None:
    actuator = FakeActuator({1: 100})
    move = SetpointMove(actuator, 1, 4000, (0, 4000), rate_hz=FAST_HZ, timeout_s=1e-9)
    assert await _run(move) == "timed_out"
    assert actuator.writes == []


async def test_a_guard_at_timeout_stops_without_the_hold_write() -> None:
    actuator = FakeActuator({1: 100})
    actuator.follows = False
    preempt: list[str] = []

    def guard() -> str | None:
        return preempt[0] if preempt else None

    move = SetpointMove(actuator, 1, 4000, (0, 4000), rate_hz=FAST_HZ, timeout_s=0.05, guard=guard)
    move.start()
    await asyncio.sleep(0.02)
    preempt.append("teleop")
    await asyncio.wait_for(move.wait(), timeout=1)
    assert (move.state, move.reason) == ("stopped", "teleop")
    assert actuator.writes == [{1: 100 + DEFAULT_MAX_STEP_TICKS}]


async def test_move_from_a_rest_outside_the_span_never_writes_outside_it() -> None:
    actuator = FakeActuator({1: 960}, span=(100, 950))
    move = SetpointMove(actuator, 1, 900, (100, 950), rate_hz=FAST_HZ)
    assert await _run(move) == "reached"
    assert all(100 <= w[1] <= 950 for w in actuator.writes)


@pytest.mark.parametrize(
    ("present", "refused"),
    [
        (4000 + DEFAULT_MAX_STEP_TICKS, False),  # just within one step of the span: movable
        (4000 + DEFAULT_MAX_STEP_TICKS + 1, True),
        (100 - DEFAULT_MAX_STEP_TICKS - 1, True),
    ],
)
def test_preview_refuses_a_rest_more_than_one_step_outside_the_span(
    present: int, refused: bool
) -> None:
    actuator = FakeActuator({1: present}, span=(100, 4000))
    if not refused:
        assert preview(actuator, "arm-shoulder_pan.position", 50.0).present_ticks == present
        return
    with pytest.raises(SetpointRefusalError) as caught:
        preview(actuator, "arm-shoulder_pan.position", 50.0)
    assert caught.value.code == "uncalibrated"


async def test_a_write_more_than_one_step_from_the_last_goal_fails_the_move() -> None:
    # The rest drifted far outside the span after preview: re-clamping the stepped goal into the
    # span would jump more than one step, so the move fails before it writes.
    actuator = FakeActuator({1: 1200}, span=(100, 950))
    ended: list[str] = []
    move = SetpointMove(actuator, 1, 900, (100, 950), rate_hz=FAST_HZ, on_ended=ended.append)
    assert await _run(move) == "failed"
    assert (move.reason, ended, actuator.writes) == ("step_limit", ["failed"], [])


async def test_actuator_lost_mid_move_fails_and_stops_writing() -> None:
    actuator = FakeActuator({1: 0})
    actuator.write_fails_after = 2
    ended: list[str] = []
    move = SetpointMove(actuator, 1, 4000, (0, 4000), rate_hz=FAST_HZ, on_ended=ended.append)
    assert await _run(move) == "failed"
    assert ended == ["failed"] and len(actuator.writes) == 2
    assert move.reason == "actuator_lost"


@pytest.mark.parametrize("failure", ["gap", "silent"])
async def test_a_lost_read_mid_move_fails(failure: str) -> None:
    actuator = FakeActuator({1: 0})
    move = SetpointMove(actuator, 1, 4000, (0, 4000), rate_hz=FAST_HZ)
    if failure == "gap":
        actuator.unavailable = True
    else:
        actuator.silent.add(1)
    assert await _run(move) == "failed"
    assert actuator.writes == []


async def test_stop_ends_the_move_and_nothing_is_written_after() -> None:
    actuator = FakeActuator({1: 0})
    actuator.follows = False
    ended: list[str] = []
    move = SetpointMove(actuator, 1, 4000, (0, 4000), rate_hz=FAST_HZ, on_ended=ended.append)
    move.start()
    await asyncio.sleep(0.01)
    await move.stop("user")
    count = len(actuator.writes)
    await asyncio.sleep(0.01)
    assert move.state == "stopped" and move.reason == "user"
    assert len(actuator.writes) == count and ended == ["stopped"]
    await move.stop("user")  # idempotent
    assert ended == ["stopped"]


async def test_a_guard_preempts_the_move_before_its_next_write() -> None:
    actuator = FakeActuator({1: 0})
    actuator.follows = False
    preempt: list[str] = []
    move = SetpointMove(
        actuator, 1, 4000, (0, 4000), rate_hz=FAST_HZ, guard=lambda: preempt[0] if preempt else None
    )
    move.start()
    await asyncio.sleep(0.01)
    preempt.append("teleop")
    await asyncio.wait_for(move.wait(), timeout=1)
    count = len(actuator.writes)
    await asyncio.sleep(0.01)
    assert (move.state, move.reason) == ("stopped", "teleop")
    assert len(actuator.writes) == count


def test_move_validates_its_bounds() -> None:
    with pytest.raises(ValueError):
        SetpointMove(FakeActuator({1: 0}), 1, 5000, (0, 4000))
    with pytest.raises(ValueError):
        SetpointMove(FakeActuator({1: 0}), 1, 10, (0, 4000), rate_hz=0)


# ── livebench.local wrappers (the API's door) ───────────────────────────────────


class Conn:
    def __init__(self, actuator: Any) -> None:
        self.actuator = actuator


def test_local_preview_is_wire_shaped() -> None:
    wire = local.setpoint_preview(Conn(FakeActuator({1: 124})), PAN, 120.0)
    assert wire == {
        "address": 1,
        "joint": PAN,
        "unit": "deg",
        "current": 12.4,
        "target": 120.0,
        "requested": 120.0,
        "clamped": False,
        "goal_ticks": 1200,
        "max_step_ticks": 68,
        "max_step": 6.8,
    }


def test_local_preview_translates_refusals_and_unknown_joints() -> None:
    with pytest.raises(NotActuatedError):
        local.setpoint_preview(Conn(None), PAN, 1.0)
    with pytest.raises(SetpointRefusedError) as caught:
        local.setpoint_preview(Conn(FakeActuator({1: 0}, torque={1: False})), PAN, 1.0)
    assert caught.value.code == "torque_off" and caught.value.unit == "deg"
    with pytest.raises(SetpointNotFoundError):
        local.setpoint_preview(Conn(FakeActuator({1: 0})), "nope.position", 1.0)


async def test_local_apply_status_and_stop() -> None:
    actuator = FakeActuator({1: 0})
    actuator.follows = False
    ended: list[str] = []
    handle = await local.setpoint_apply(
        Conn(actuator), PAN, 400.0, on_ended=ended.append, rate_hz=FAST_HZ
    )
    assert handle.goal_ticks == 4000 and handle.clamped is False
    assert local.setpoint_status(handle)["state"] == "moving"
    await local.setpoint_stop(handle, "session_ended")
    assert local.setpoint_status(handle) == {"state": "stopped", "reason": "session_ended"}
    assert ended == ["stopped"]


async def test_local_apply_rechecks_refusals_on_fresh_readings() -> None:
    actuator = FakeActuator({1: 0}, torque={1: False})
    with pytest.raises(SetpointRefusedError):
        await local.setpoint_apply(Conn(actuator), PAN, 10.0, on_ended=lambda _s: None)
    assert actuator.writes == []


async def test_local_apply_refuses_a_rest_far_outside_the_span() -> None:
    actuator = FakeActuator({1: 4000 + DEFAULT_MAX_STEP_TICKS + 1}, span=(100, 4000))
    with pytest.raises(SetpointRefusedError) as caught:
        await local.setpoint_apply(Conn(actuator), PAN, 10.0, on_ended=lambda _s: None)
    assert caught.value.code == "uncalibrated" and actuator.writes == []
