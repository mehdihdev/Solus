"""Leader → follower teleoperation (SOLUSDEV-319, ADR-014 amendment 2026-10-30).

Pure loop logic over the `Actuator` seam: pairing by bus address, the start-tolerance gate,
bounded steps, and the stop conditions. The follower always holds its pose on stop — release is
never the loop's decision.
"""

import asyncio
from collections.abc import Callable, Mapping

import pytest
from livebench.hardware.actuation import (
    ActuatedJoint,
    ActuatorUnavailableError,
    ActuatorWriteError,
)
from livebench.teleop import (
    MAX_MISSED_READS,
    TeleopLoop,
    TeleopNotReadyError,
    pair_joints,
    preview,
    start_teleop,
    step_goals,
)


class FakeActuator:
    """1 tick = 0.1 unit; goals clamp into the span like the real actuator."""

    def __init__(self, joints: list[ActuatedJoint], ticks: dict[int, int]) -> None:
        self._joints = tuple(joints)
        self.ticks = dict(ticks)
        self.writes: list[dict[int, int]] = []
        self.held = False
        self.released = False
        self.read_fails = 0  # next N reads raise
        self.silent: set[int] = set()
        self.write_fails = False

    def joints(self) -> tuple[ActuatedJoint, ...]:
        return self._joints

    def read(self) -> dict[int, int]:
        if self.read_fails:
            self.read_fails -= 1
            raise ActuatorUnavailableError("gap")
        return {a: t for a, t in self.ticks.items() if a not in self.silent}

    def to_value(self, address: int, ticks: int) -> float:
        return ticks / 10

    def to_goal(self, address: int, value: float) -> int:
        span = next(j.span for j in self._joints if j.address == address)
        assert span is not None
        return min(span[1], max(span[0], round(value * 10)))

    def write_goals(self, goals: Mapping[int, int]) -> None:
        if self.write_fails:
            raise ActuatorWriteError("no ack")
        for address, ticks in goals.items():  # the real actuator refuses goals past the span
            span = next(j.span for j in self._joints if j.address == address)
            if span is None or not span[0] <= ticks <= span[1]:
                raise ValueError(f"goal {ticks} outside {span}")
        self.writes.append(dict(goals))
        self.ticks.update(goals)

    def hold(self) -> dict[int, int]:
        self.held = True
        return {j.address: self.ticks[j.address] for j in self._joints if j.span}

    def release(self) -> None:
        self.released = True


def _joint(
    address: int, name: str, unit: str = "deg", span: tuple[int, int] | None = (0, 4000)
) -> ActuatedJoint:
    return ActuatedJoint(address=address, signal=f"{name}.position", unit=unit, span=span)


def _pair(
    leader_ticks: dict[int, int], follower_ticks: dict[int, int]
) -> tuple[FakeActuator, FakeActuator]:
    leader = FakeActuator([_joint(1, "l-pan"), _joint(6, "l-grip", "%")], leader_ticks)
    follower = FakeActuator([_joint(1, "f-pan"), _joint(6, "f-grip", "%")], follower_ticks)
    return leader, follower


def test_joints_pair_by_address_and_name_both_signals() -> None:
    leader, follower = _pair({1: 0, 6: 0}, {1: 0, 6: 0})
    pairs, blockers = pair_joints(leader.joints(), follower.joints())
    assert blockers == []
    assert [(p.address, p.leader_signal, p.follower_signal, p.unit) for p in pairs] == [
        (1, "l-pan.position", "f-pan.position", "deg"),
        (6, "l-grip.position", "f-grip.position", "%"),
    ]


def test_pairing_blocks_unpaired_uncalibrated_and_mismatched_joints() -> None:
    leader = [_joint(1, "a"), _joint(2, "b"), _joint(3, "c", "%"), _joint(4, "d", span=None)]
    follower = [_joint(1, "a"), _joint(3, "c", "deg"), _joint(4, "d"), _joint(5, "e")]
    pairs, blockers = pair_joints(leader, follower)
    assert [p.address for p in pairs] == [1]
    assert sorted((b.code, b.address) for b in blockers) == [
        ("mode_mismatch", 3),
        ("uncalibrated_joint", 4),
        ("unpaired_joint", 2),
        ("unpaired_joint", 5),
    ]


def test_preview_reports_each_joint_against_the_start_tolerance() -> None:
    # pan: leader 10.0 deg vs follower 30.0 deg (outside 15); grip: 50 % vs 40 % (inside 20).
    leader, follower = _pair({1: 100, 6: 500}, {1: 300, 6: 400})
    result = preview(leader, follower)
    rows = {r.pair.address: r for r in result.pairs}
    assert (rows[1].leader_value, rows[1].follower_value, rows[1].delta) == (10.0, 30.0, -20.0)
    assert rows[1].within_tolerance is False and rows[6].within_tolerance is True
    assert result.ready is False
    leader.ticks[1] = 250
    assert preview(leader, follower).ready is True


def test_preview_is_not_ready_when_a_joint_is_silent_or_pairing_blocks() -> None:
    leader, follower = _pair({1: 100, 6: 500}, {1: 100, 6: 500})
    leader.silent.add(6)
    silent = preview(leader, follower)
    assert silent.ready is False
    assert next(r for r in silent.pairs if r.pair.address == 6).leader_value is None
    lone = FakeActuator([_joint(1, "x")], {1: 0})
    assert preview(lone, follower).ready is False


def test_preview_refuses_one_robot_as_both_ends() -> None:
    leader, _ = _pair({1: 0, 6: 0}, {1: 0, 6: 0})
    result = preview(leader, leader)
    assert [b.code for b in result.blockers] == ["same_session"]


def test_step_goals_moves_at_most_the_step_toward_each_target() -> None:
    assert step_goals({1: 1000, 6: 205}, {1: 900, 6: 200}, max_step=68) == {1: 968, 6: 205}
    assert step_goals({1: 800}, {1: 900}, max_step=68) == {1: 832}


async def _run_until(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "condition never met"
        await asyncio.sleep(0.005)


async def test_start_holds_the_follower_then_tracks_the_leader_in_bounded_steps() -> None:
    leader, follower = _pair({1: 2100, 6: 500}, {1: 2000, 6: 500})
    loop = await start_teleop(leader, follower, rate_hz=500, max_step=40)
    assert follower.held
    await _run_until(lambda: follower.ticks[1] == 2100)
    steps = [w[1] for w in follower.writes]
    assert all(b - a <= 40 for a, b in zip([2000, *steps], steps, strict=False))
    await loop.stop()
    assert loop.stop_reason == "user" and follower.released is False


async def test_start_refuses_when_preview_is_not_ready() -> None:
    leader, follower = _pair({1: 0, 6: 500}, {1: 3000, 6: 500})
    with pytest.raises(TeleopNotReadyError) as refused:
        await start_teleop(leader, follower, rate_hz=500)
    assert refused.value.preview.ready is False
    assert follower.held is False and follower.writes == []


async def test_leader_lost_after_consecutive_failed_reads_stops_and_holds() -> None:
    leader, follower = _pair({1: 2000, 6: 500}, {1: 2000, 6: 500})
    stopped: list[str] = []
    loop = await start_teleop(leader, follower, rate_hz=500, on_stopped=stopped.append)
    leader.read_fails = MAX_MISSED_READS - 1  # a short gap is survived
    await asyncio.sleep(0.05)
    assert loop.running
    leader.silent.add(6)  # now a joint goes quiet for good
    await _run_until(lambda: not loop.running)
    assert loop.stop_reason == "leader_lost" and stopped == ["leader_lost"]
    assert follower.released is False


async def test_follower_write_failure_stops_the_loop() -> None:
    leader, follower = _pair({1: 2000, 6: 500}, {1: 2000, 6: 500})
    loop = await start_teleop(leader, follower, rate_hz=500)
    follower.write_fails = True
    await _run_until(lambda: not loop.running)
    assert loop.stop_reason == "follower_lost"


async def test_stop_is_idempotent_and_reports_the_first_reason_once() -> None:
    leader, follower = _pair({1: 2000, 6: 500}, {1: 2000, 6: 500})
    stopped: list[str] = []
    loop = await start_teleop(leader, follower, rate_hz=500, on_stopped=stopped.append)
    await loop.stop("session_ended")
    await loop.stop("user")
    assert loop.stop_reason == "session_ended" and stopped == ["session_ended"]


def test_loop_rejects_a_rate_outside_the_bound() -> None:
    leader, follower = _pair({1: 0, 6: 0}, {1: 0, 6: 0})
    pairs, _ = pair_joints(leader.joints(), follower.joints())
    with pytest.raises(ValueError):
        TeleopLoop(leader, follower, pairs, held={1: 0, 6: 0}, rate_hz=0)


async def test_a_follower_resting_past_its_range_is_brought_inside_not_crashed() -> None:
    # Calibration ranges are the extremes seen while calibrating; a resting arm can sit a tick
    # or two beyond them. The first goal must land inside the span, and the loop keep running.
    leader = FakeActuator([_joint(1, "l", span=(1000, 3000))], {1: 2950})
    follower = FakeActuator([_joint(1, "f", span=(1000, 3000))], {1: 3060})  # > one step past
    loop = await start_teleop(leader, follower, rate_hz=500, max_step=40)
    await _run_until(lambda: len(follower.writes) >= 3)
    assert loop.running
    assert all(1000 <= w[1] <= 3000 for w in follower.writes)
    await loop.stop()


async def test_an_unexpected_error_stops_the_loop_instead_of_leaving_it_running() -> None:
    leader, follower = _pair({1: 2000, 6: 500}, {1: 2000, 6: 500})
    loop = await start_teleop(leader, follower, rate_hz=500)

    def broken(address: int, ticks: int) -> float:
        raise ZeroDivisionError

    leader.to_value = broken  # type: ignore[method-assign]
    await _run_until(lambda: not loop.running)
    assert loop.stop_reason == "follower_lost"
