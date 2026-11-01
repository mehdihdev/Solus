"""A SOL setpoint: one bounded move of one joint (SOLUSDEV-319, ADR-014 amendment 2026-10-31).

docs/api/bench-view.md §6.2, docs/architecture/bench-view.md §6. Runs in the process that owns
the robot's bus, over the driver `Actuator` seam. The goal is the actuator's own clamp of the
target into the calibrated span (`to_goal`); each 30 Hz tick moves at most
`DEFAULT_MAX_STEP_TICKS` toward it; the move ends within `REACHED_TICKS` of the goal or after
`TIMEOUT_SECONDS`. It never touches torque: the joint holds its last goal however the move ends.
It is never a loop over targets and never a stream — one goal, then it is over.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, TypeVar

from livebench.hardware.actuation import (
    ActuatedJoint,
    Actuator,
    ActuatorUnavailableError,
    ActuatorWriteError,
    torque_state,
)
from livebench.teleop import DEFAULT_MAX_STEP_TICKS, DEFAULT_RATE_HZ, MAX_RATE_HZ, step_goals

__all__ = [
    "DEFAULT_MAX_STEP_TICKS",
    "DEFAULT_RATE_HZ",
    "REACHED_TICKS",
    "TIMEOUT_SECONDS",
    "JointNotFoundError",
    "SetpointMove",
    "SetpointPreview",
    "SetpointRefusalError",
    "preview",
]

logger = logging.getLogger(__name__)

REACHED_TICKS: Final = 2
TIMEOUT_SECONDS: Final = 5.0

MoveState = Literal["moving", "reached", "timed_out", "stopped", "failed"]
T = TypeVar("T")
_FAILURES = (ActuatorUnavailableError, ActuatorWriteError, OSError, ValueError)


class SetpointRefusalError(Exception):
    """A §6.2 refusal decided from the bus (`not_connected`, `uncalibrated`, `torque_off`)."""

    def __init__(self, code: str, message: str, unit: str | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.unit = code, message, unit


class JointNotFoundError(LookupError):
    """No actuated joint of this robot carries that signal name."""


@dataclass(frozen=True)
class SetpointPreview:
    address: int
    signal: str
    unit: str
    span: tuple[int, int]
    present_ticks: int
    current_value: float
    goal_ticks: int
    target_value: float
    requested: float
    clamped: bool
    max_step_value: float


def _joint(actuator: Actuator, signal: str) -> ActuatedJoint:
    try:
        joints = actuator.joints()
    except (ActuatorUnavailableError, OSError) as exc:
        raise SetpointRefusalError("not_connected", "the robot's link is reconnecting") from exc
    joint = next((j for j in joints if j.signal == signal), None)
    if joint is None:
        raise JointNotFoundError(signal)
    return joint


def _present(actuator: Actuator, joint: ActuatedJoint) -> int:
    try:
        ticks = actuator.read().get(joint.address)
    except (ActuatorUnavailableError, OSError) as exc:
        raise SetpointRefusalError("not_connected", "the robot's link is reconnecting") from exc
    if ticks is None:
        raise SetpointRefusalError(
            "not_connected", "the joint did not report a position", joint.unit
        )
    return ticks


def _check_torque(actuator: Actuator, joint: ActuatedJoint) -> None:
    try:
        torque = torque_state(actuator)
    except (ActuatorUnavailableError, ActuatorWriteError, OSError) as exc:
        raise SetpointRefusalError("not_connected", "the robot's link is reconnecting") from exc
    if torque is None:
        raise SetpointRefusalError("uncalibrated", "this driver cannot report torque", joint.unit)
    if not torque.get(joint.address, False):
        raise SetpointRefusalError("torque_off", "the joint's torque is off", joint.unit)


def preview(actuator: Actuator, signal: str, target: float) -> SetpointPreview:
    """Where the joint is and what `target` becomes once clamped. BLOCKING (reads the bus).
    Raises `SetpointRefusalError`, `JointNotFoundError` or `ValueError` (non-finite target)."""
    if not math.isfinite(target):
        raise ValueError("target must be a finite number")
    joint = _joint(actuator, signal)
    if joint.span is None:
        raise SetpointRefusalError("uncalibrated", "the joint has no calibrated range", joint.unit)
    _check_torque(actuator, joint)
    present = _present(actuator, joint)
    low, high = joint.span
    goal = min(high, max(low, actuator.to_goal(joint.address, target)))
    bounds = sorted((actuator.to_value(joint.address, low), actuator.to_value(joint.address, high)))
    step = actuator.to_value(joint.address, present + DEFAULT_MAX_STEP_TICKS)
    return SetpointPreview(
        address=joint.address,
        signal=joint.signal,
        unit=joint.unit,
        span=joint.span,
        present_ticks=present,
        current_value=actuator.to_value(joint.address, present),
        goal_ticks=goal,
        target_value=actuator.to_value(joint.address, goal),
        requested=target,
        clamped=not bounds[0] <= target <= bounds[1],
        max_step_value=round(abs(step - actuator.to_value(joint.address, present)), 6),
    )


class SetpointMove:
    """One move toward `goal`. `guard` is polled before every write: a non-None return is a stop
    reason (a teleop starting, a release) and ends the move as `stopped` before it writes."""

    def __init__(
        self,
        actuator: Actuator,
        address: int,
        goal: int,
        span: tuple[int, int],
        *,
        rate_hz: float = DEFAULT_RATE_HZ,
        max_step: int = DEFAULT_MAX_STEP_TICKS,
        timeout_s: float = TIMEOUT_SECONDS,
        guard: Callable[[], str | None] | None = None,
        on_ended: Callable[[MoveState], object] | None = None,
    ) -> None:
        if not 0 < rate_hz <= MAX_RATE_HZ or max_step < 1 or timeout_s <= 0:
            raise ValueError("rate_hz must be in (0, 1000], max_step ≥ 1 and timeout_s > 0")
        if not span[0] <= goal <= span[1]:
            raise ValueError("the goal is outside the joint's calibrated span")
        self._actuator, self.address, self.goal, self._span = actuator, address, goal, span
        self._period, self._max_step, self._timeout = 1.0 / rate_hz, max_step, timeout_s
        self._guard, self._on_ended = guard, on_ended
        self.state: MoveState = "moving"
        self.reason: str | None = None
        self._last: int | None = None
        self._task: asyncio.Task[None] | None = None
        self._done = asyncio.Event()
        #: The bus call on a worker thread now; `stop` waits for it so nothing reaches the bus
        #: after `stop` returns (cancelling the task does not stop a thread).
        self._inflight: asyncio.Future[Any] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def wait(self) -> None:
        await self._done.wait()

    async def stop(self, reason: str = "user") -> None:
        self._finish("stopped", reason)
        task = self._task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self._inflight is not None and not self._inflight.done():
            await asyncio.wait([self._inflight])

    def _finish(self, state: MoveState, reason: str | None = None) -> None:
        if self.state != "moving":
            return
        self.state, self.reason = state, reason
        self._done.set()
        logger.info(
            "setpoint move ended: address=%s state=%s reason=%s", self.address, state, reason
        )
        if self._on_ended is not None:
            self._on_ended(state)

    async def _io(self, call: Callable[..., T], *args: Any) -> T:
        self._inflight = asyncio.ensure_future(asyncio.to_thread(call, *args))
        return await asyncio.shield(self._inflight)

    async def _run(self) -> None:
        deadline = time.monotonic() + self._timeout
        try:
            while self.state == "moving":
                started = time.monotonic()
                await self._tick(deadline)
                await asyncio.sleep(max(0.0, self._period - (time.monotonic() - started)))
        except _FAILURES:
            self._finish("failed", "actuator_lost")
        except Exception:
            # Never leave a "moving" record that no longer moves anything.
            logger.exception("setpoint move failed: address=%s", self.address)
            self._finish("failed", "actuator_lost")

    async def _tick(self, deadline: float) -> None:
        present = (await self._io(self._actuator.read)).get(self.address)
        if present is None:
            raise ActuatorUnavailableError("the joint stopped reporting its position")
        if abs(present - self.goal) <= REACHED_TICKS:
            self._finish("reached")
            return
        if time.monotonic() >= deadline:
            self._finish("timed_out")
            return
        last = present if self._last is None else self._last
        stepped = step_goals(
            {self.address: self.goal}, {self.address: last}, max_step=self._max_step
        )
        goal = min(self._span[1], max(self._span[0], stepped[self.address]))
        if goal == self._last:
            return
        preempt = self._guard() if self._guard is not None else None
        if preempt is not None:
            self._finish("stopped", preempt)
            return
        await self._io(self._actuator.write_goals, {self.address: goal})
        self._last = goal
