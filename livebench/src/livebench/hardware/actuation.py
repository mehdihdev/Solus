"""The optional actuation seam (SOLUSDEV-319, ADR-014 amendment 2026-10-30).

A protocol driver MAY expose an `Actuator` for a configured robot: the same bus its polling
source owns, addressed by bus address, converting between calibrated values and goal ticks the
way the source converts readings. Teleoperation is its only caller. Every method blocks on the
bus — callers run them off-loop. Drivers without one simply have no `actuator` method.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class ActuatorUnavailableError(RuntimeError):
    """The robot's link is not open right now (between reconnects, or closed)."""


class ActuatorWriteError(RuntimeError):
    """A servo did not acknowledge a write, or did not answer a read the write depends on."""


@dataclass(frozen=True)
class ActuatedJoint:
    address: int
    signal: str  # the reading's signal name, e.g. "arm-shoulder_pan.position"
    unit: str  # the calibrated unit ("deg", "%"), or "tick" when uncalibrated
    span: tuple[int, int] | None  # calibrated tick range; None = never actuated


class Actuator(Protocol):
    def joints(self) -> tuple[ActuatedJoint, ...]: ...

    def read(self) -> dict[int, int]:
        """Present ticks per address; a silent servo is absent."""
        ...

    def to_value(self, address: int, ticks: int) -> float: ...

    def to_goal(self, address: int, value: float) -> int:
        """Goal ticks for a calibrated value, clamped into the joint's span."""
        ...

    def write_goals(self, goals: Mapping[int, int]) -> None: ...

    def hold(self) -> dict[int, int]:
        """Goal := present pose, then torque on, for every calibrated joint. Returns the goals."""
        ...

    def release(self) -> None:
        """Torque off on every joint."""
        ...
