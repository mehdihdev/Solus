"""Leader → follower teleoperation (SOLUSDEV-319, ADR-014 amendment 2026-10-30).

Runs beside the two robots' sessions, in the process that owns both buses, over the driver
`Actuator` seam. Each tick reads the leader, converts every paired joint through both robots'
calibrations (the leader's value becomes the follower's goal), and moves the follower at most a
bounded step. It never releases torque: on any stop the follower holds its last goal.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, TypeVar

from livebench.hardware.actuation import (
    ActuatedJoint,
    Actuator,
    ActuatorUnavailableError,
    ActuatorWriteError,
)

logger = logging.getLogger(__name__)

#: Start gate: every follower joint within this distance of where the leader would send it.
TOLERANCE: Final[Mapping[str, float]] = {"deg": 15.0, "%": 20.0}
DEFAULT_RATE_HZ: Final = 30.0
MAX_RATE_HZ: Final = 1000.0
#: ~6 deg per tick on a 4096-tick servo: 180 deg/s at 30 Hz.
DEFAULT_MAX_STEP_TICKS: Final = 68
MAX_MISSED_READS: Final = 3

T = TypeVar("T")
StopReason = Literal["user", "leader_lost", "follower_lost", "session_ended", "shutdown"]
_FAILURES = (ActuatorUnavailableError, ActuatorWriteError, OSError)


@dataclass(frozen=True)
class Blocker:
    code: str
    message: str
    address: int | None = None


@dataclass(frozen=True)
class JointPair:
    address: int
    leader_signal: str
    follower_signal: str
    unit: str
    follower_span: tuple[int, int]


@dataclass(frozen=True)
class PairReading:
    pair: JointPair
    leader_value: float | None
    follower_value: float | None

    @property
    def delta(self) -> float | None:
        if self.leader_value is None or self.follower_value is None:
            return None
        return round(self.leader_value - self.follower_value, 6)

    @property
    def within_tolerance(self) -> bool:
        return self.delta is not None and abs(self.delta) <= TOLERANCE[self.pair.unit]


@dataclass(frozen=True)
class TeleopPreview:
    pairs: tuple[PairReading, ...]
    blockers: tuple[Blocker, ...]

    @property
    def ready(self) -> bool:
        return (
            bool(self.pairs) and not self.blockers and all(r.within_tolerance for r in self.pairs)
        )


class _LeaderLostError(Exception):
    """An unexpected failure on the leader side of a tick."""


class TeleopNotReadyError(RuntimeError):
    def __init__(self, preview: TeleopPreview) -> None:
        super().__init__("teleoperation is not ready to start")
        self.preview = preview


def pair_joints(
    leader: Sequence[ActuatedJoint], follower: Sequence[ActuatedJoint]
) -> tuple[list[JointPair], list[Blocker]]:
    """Pair by bus address; refuse anything that cannot be driven safely."""
    by_address = {j.address: j for j in leader}
    driven = {j.address: j for j in follower}
    pairs: list[JointPair] = []
    blockers = [
        Blocker("unpaired_joint", f"{j.signal} has no joint at address {a} on the other robot", a)
        for a, j in {**by_address, **driven}.items()
        if (a in by_address) != (a in driven)
    ]
    for address in sorted(by_address.keys() & driven.keys()):
        lead, follow = by_address[address], driven[address]
        if lead.span is None or follow.span is None or follow.unit not in TOLERANCE:
            name = follow.signal if follow.span is None else lead.signal
            blockers.append(
                Blocker("uncalibrated_joint", f"{name} has no calibrated range", address)
            )
        elif lead.mode != follow.mode or lead.unit != follow.unit:
            blockers.append(
                Blocker(
                    "mode_mismatch",
                    f"{lead.signal} is {lead.mode}, {follow.signal} is {follow.mode}",
                    address,
                )
            )
        else:
            pairs.append(JointPair(address, lead.signal, follow.signal, follow.unit, follow.span))
    return pairs, blockers


def preview(
    leader: Actuator, follower: Actuator, *, max_step: int = DEFAULT_MAX_STEP_TICKS
) -> TeleopPreview:
    """Where each paired joint is on both robots now. Blocking (reads both buses). A follower
    resting more than one step outside its range would jump on the first tick: blocked."""
    if leader is follower:
        return TeleopPreview((), (Blocker("same_session", "pick two different robots"),))
    pairs, blockers = pair_joints(leader.joints(), follower.joints())
    lead, follow = leader.read(), follower.read()
    readings = tuple(
        PairReading(
            pair,
            leader.to_value(pair.address, lead[pair.address]) if pair.address in lead else None,
            follower.to_value(pair.address, follow[pair.address])
            if pair.address in follow
            else None,
        )
        for pair in pairs
    )
    for pair in pairs:
        low, high = pair.follower_span
        ticks = follow.get(pair.address)
        if ticks is not None and (ticks < low - max_step or ticks > high + max_step):
            blockers.append(
                Blocker(
                    "follower_out_of_range",
                    f"{pair.follower_signal} rests outside its calibrated range; move it back",
                    pair.address,
                )
            )
    return TeleopPreview(readings, tuple(blockers))


def step_goals(
    targets: Mapping[int, int], last: Mapping[int, int], *, max_step: int
) -> dict[int, int]:
    """Each goal moves from its last value toward its target by at most `max_step` ticks."""
    return {
        address: last[address] + max(-max_step, min(max_step, target - last[address]))
        for address, target in targets.items()
    }


class TeleopLoop:
    def __init__(
        self,
        leader: Actuator,
        follower: Actuator,
        pairs: Sequence[JointPair],
        *,
        held: Mapping[int, int],
        rate_hz: float = DEFAULT_RATE_HZ,
        max_step: int = DEFAULT_MAX_STEP_TICKS,
        on_stopped: Callable[[StopReason], object] | None = None,
    ) -> None:
        if not 0 < rate_hz <= MAX_RATE_HZ or max_step < 1:
            raise ValueError("rate_hz must be in (0, 1000] and max_step at least 1")
        self._leader, self._follower = leader, follower
        self.pairs = tuple(pairs)
        self.rate_hz = rate_hz
        self._max_step = max_step
        self._last = {p.address: held[p.address] for p in self.pairs}
        self._on_stopped = on_stopped
        self.stop_reason: StopReason | None = None
        self._task: asyncio.Task[None] | None = None
        #: The bus call running on a worker thread right now; cancelling the task does not stop
        #: it, so `stop` waits for it — nothing reaches the bus after `stop` returns.
        self._inflight: asyncio.Future[Any] | None = None

    @property
    def running(self) -> bool:
        return self.stop_reason is None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self, reason: StopReason = "user") -> None:
        self._finish(reason)
        task, current = self._task, asyncio.current_task()
        if task is not None and task is not current:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self._inflight is not None and not self._inflight.done():
            await asyncio.wait([self._inflight])

    async def _io(self, call: Callable[..., T], *args: Any) -> T:
        self._inflight = asyncio.ensure_future(asyncio.to_thread(call, *args))
        return await asyncio.shield(self._inflight)

    def _finish(self, reason: StopReason) -> None:
        if self.stop_reason is not None:
            return
        self.stop_reason = reason
        logger.info("teleop stopped: %s", reason)
        if self._on_stopped is not None:
            self._on_stopped(reason)

    async def _leader_values(self) -> dict[int, float] | None:
        """The leader's calibrated value per paired joint, or None for a missed read. Raises
        `_LeaderLostError` for anything unexpected (never misreported as a follower failure)."""
        try:
            ticks = await self._io(self._leader.read)
            if any(p.address not in ticks for p in self.pairs):
                return None
            return {
                p.address: self._leader.to_value(p.address, ticks[p.address]) for p in self.pairs
            }
        except _FAILURES:
            return None
        except Exception as exc:
            logger.exception("teleop leader read failed")
            raise _LeaderLostError from exc

    async def _run(self) -> None:
        period, missed = 1.0 / self.rate_hz, 0
        while self.running:
            started = time.monotonic()
            try:
                values = await self._leader_values()
            except _LeaderLostError:
                self._finish("leader_lost")
                return
            if values is None:
                missed += 1
                if missed >= MAX_MISSED_READS:
                    self._finish("leader_lost")
                    return
            else:
                missed = 0
                try:
                    await self._drive(values)
                except _FAILURES:
                    self._finish("follower_lost")
                    return
                except Exception:
                    # Never leave a "running" loop that no longer drives anything.
                    logger.exception("teleop follower step failed")
                    self._finish("follower_lost")
                    return
            await asyncio.sleep(max(0.0, period - (time.monotonic() - started)))

    async def _drive(self, values: Mapping[int, float]) -> None:
        targets = {
            p.address: self._follower.to_goal(p.address, values[p.address]) for p in self.pairs
        }
        stepped = step_goals(targets, self._last, max_step=self._max_step)
        # A follower resting within one step past its extremes is brought inside on this tick.
        goals = {
            p.address: min(p.follower_span[1], max(p.follower_span[0], stepped[p.address]))
            for p in self.pairs
        }
        await self._io(self._follower.write_goals, goals)
        self._last = goals


async def start_teleop(
    leader: Actuator,
    follower: Actuator,
    *,
    rate_hz: float = DEFAULT_RATE_HZ,
    max_step: int = DEFAULT_MAX_STEP_TICKS,
    on_stopped: Callable[[StopReason], object] | None = None,
) -> TeleopLoop:
    """Re-check the start gate on fresh readings, hold the follower's pose, then start tracking.
    Raises `TeleopNotReadyError` (nothing written) when the gate fails."""
    fresh = await asyncio.to_thread(preview, leader, follower, max_step=max_step)
    if not fresh.ready:
        raise TeleopNotReadyError(fresh)
    held = await asyncio.to_thread(follower.hold)
    loop = TeleopLoop(
        leader,
        follower,
        [r.pair for r in fresh.pairs],
        held=held,
        rate_hz=rate_hz,
        max_step=max_step,
        on_stopped=on_stopped,
    )
    loop.start()
    return loop
