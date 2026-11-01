"""Feetech actuation over the polling source's own bus (SOLUSDEV-319, ADR-014 amendment).

One handle per robot that outlives reconnects: each source incarnation attaches its bus and
joints, and detaches on close, so a teleop loop holding the handle keeps working across a link
heal and fails cleanly (`ActuatorUnavailableError`) in the gap. The bus lock in `FeetechBus`
serializes these exchanges with the polling sweep.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from livebench.hardware.actuation import (
    ActuatedJoint,
    ActuatorUnavailableError,
    ActuatorWriteError,
)

if TYPE_CHECKING:
    from livebench.plugins.feetech.feetech_codec import FeetechBus
    from livebench.plugins.feetech.feetech_driver import _FeetechJoint


class FeetechActuator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bus: FeetechBus | None = None
        self._joints: dict[int, _FeetechJoint] = {}

    def attach(self, bus: FeetechBus, joints: Sequence[_FeetechJoint]) -> None:
        with self._lock:
            self._bus, self._joints = bus, {j.servo_id: j for j in joints}

    def detach(self, bus: FeetechBus) -> None:
        with self._lock:
            if self._bus is bus:
                self._bus, self._joints = None, {}

    def _link(self) -> tuple[FeetechBus, dict[int, _FeetechJoint]]:
        with self._lock:
            if self._bus is None:
                raise ActuatorUnavailableError("the robot's link is not open")
            return self._bus, dict(self._joints)

    def _calibrated(self) -> tuple[FeetechBus, dict[int, _FeetechJoint]]:
        bus, joints = self._link()
        return bus, {address: j for address, j in joints.items() if j.goal_span is not None}

    def joints(self) -> tuple[ActuatedJoint, ...]:
        _, joints = self._link()
        return tuple(
            ActuatedJoint(
                address=j.servo_id,
                signal=f"{j.prefix}.position",
                unit=j.position(j.center)[1],
                span=j.goal_span,
                mode=j.mode.value if j.mode is not None else None,
            )
            for j in joints.values()
        )

    def read(self) -> dict[int, int]:
        bus, joints = self._link()
        return {
            address: ticks
            for address in joints
            if (ticks := bus.read_register(address, "Present_Position")) is not None
        }

    def torque_enabled(self) -> dict[int, bool]:
        """Torque-enable per joint (`TorqueReader`); a servo that does not answer is absent."""
        bus, joints = self._link()
        return {
            address: bool(value)
            for address in joints
            if (value := bus.read_register(address, "Torque_Enable")) is not None
        }

    def to_value(self, address: int, ticks: int) -> float:
        return self._link()[1][address].position(ticks)[0]

    def to_goal(self, address: int, value: float) -> int:
        return self._link()[1][address].goal_ticks(value)

    def write_goals(self, goals: Mapping[int, int]) -> None:
        bus, joints = self._calibrated()
        for address, ticks in goals.items():
            span = joints[address].goal_span if address in joints else None
            if span is None or not span[0] <= ticks <= span[1]:
                raise ValueError(f"goal {ticks} for servo {address} is outside its range")
        for address, ticks in goals.items():
            if not bus.write_register(address, "Goal_Position", ticks):
                raise ActuatorWriteError(f"servo {address} did not acknowledge its goal")

    def hold(self) -> dict[int, int]:
        bus, joints = self._calibrated()
        present = {address: bus.read_register(address, "Present_Position") for address in joints}
        held = {a: t for a, t in present.items() if t is not None and t >= 0}
        if len(held) != len(joints):
            raise ActuatorWriteError("not every joint reported a position it can hold")
        for address, ticks in held.items():
            if not bus.write_register(address, "Goal_Position", ticks):
                raise ActuatorWriteError(f"servo {address} did not acknowledge its hold goal")
        for address in held:
            if not bus.write_register(address, "Torque_Enable", 1):
                raise ActuatorWriteError(f"servo {address} did not acknowledge torque on")
        return held

    def release(self) -> None:
        """Torque off on every joint that answers; only a calibrated joint (one `hold` could
        have turned on) that stays torqued is a failure."""
        bus, joints = self._link()
        acked = {a: bus.write_register(a, "Torque_Enable", 0) for a in joints}
        failed = [a for a, ok in acked.items() if not ok and joints[a].goal_span is not None]
        if failed:
            raise ActuatorWriteError(f"servos {failed} did not acknowledge torque off")
