"""Static holding torque, derived by Solus code (SOLUSDEV-246 ST5).

`torque = Σ m_i · g · r_i` about the pivot, times a safety factor. Inputs come
from a typed spec ("holds 2 kg at 30 cm") or from an assembly: CAD placements
give the lever arm (horizontal distance from the pivot, mm → m), and masses
come from the graph when a connector stored them or from the caller (an
Onshape mass-properties read) — a missing mass is REPORTED, never guessed.
Every result lists its assumptions so SOL states them rather than inventing.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

G = 9.80665
DEFAULT_SAFETY_FACTOR = 1.5
MIN_SAFETY_FACTOR = 1.0
MAX_SAFETY_FACTOR = 10.0
MAX_LOADS = 2000


@dataclass(frozen=True)
class Load:
    name: str
    mass_kg: float
    lever_arm_m: float


@dataclass(frozen=True)
class AssemblyPart:
    """A part under the assembly as the engine reads it from the graph."""

    id: uuid.UUID
    name: str
    mass_kg: float | None
    #: Placement translation (mm, STEP convention) relative to the assembly, or None.
    position_mm: tuple[float, float, float] | None


@dataclass(frozen=True)
class TorqueResult:
    static_torque_nm: float
    required_torque_nm: float
    safety_factor: float
    loads: tuple[Load, ...]
    #: Parts that could not contribute (no mass, no placement) — named, never guessed.
    unknown: tuple[str, ...]
    assumptions: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "static_torque_nm": round(self.static_torque_nm, 4),
            "required_torque_nm": round(self.required_torque_nm, 4),
            "safety_factor": self.safety_factor,
            "loads": [
                {"name": load.name, "mass_kg": load.mass_kg, "lever_arm_m": load.lever_arm_m}
                for load in self.loads
            ],
            "unknown": list(self.unknown),
            "assumptions": list(self.assumptions),
        }


def _finite_non_negative(value: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number")
    if value < 0:
        raise ValueError(f"{what} must be zero or more")
    return float(value)


def _safety(factor: float) -> float:
    factor = _finite_non_negative(factor, "safety factor")
    if not MIN_SAFETY_FACTOR <= factor <= MAX_SAFETY_FACTOR:
        raise ValueError(
            f"safety factor must be between {MIN_SAFETY_FACTOR} and {MAX_SAFETY_FACTOR}"
        )
    return factor


def derive_torque(
    loads: list[Load],
    *,
    unknown: tuple[str, ...] = (),
    safety_factor: float = DEFAULT_SAFETY_FACTOR,
) -> TorqueResult:
    """Pure: the static holding torque for `loads` about the pivot."""
    if len(loads) > MAX_LOADS:
        raise ValueError(f"at most {MAX_LOADS} loads")
    factor = _safety(safety_factor)
    total = 0.0
    for load in loads:
        total += (
            _finite_non_negative(load.mass_kg, "mass")
            * G
            * _finite_non_negative(load.lever_arm_m, "lever arm")
        )
    assumptions = [
        f"Static holding torque about the pivot: sum of mass x g ({G} m/s^2) x lever arm, "
        f"times a safety factor of {factor} for acceleration and friction.",
        "Lever arm is the horizontal distance from the pivot to each part's placement origin "
        "(gravity along -z); the part's centre of mass is assumed at its placement origin.",
    ]
    if unknown:
        assumptions.append(
            "Not included (no mass or no placement in the graph): " + ", ".join(unknown)
        )
    return TorqueResult(
        static_torque_nm=total,
        required_torque_nm=total * factor,
        safety_factor=factor,
        loads=tuple(loads),
        unknown=tuple(unknown),
        assumptions=tuple(assumptions),
    )


def torque_from_spec(
    *, load_kg: float, arm_m: float, safety_factor: float = DEFAULT_SAFETY_FACTOR
) -> TorqueResult:
    """ "Holds 2 kg at 30 cm" → one load at one arm."""
    return derive_torque(
        [
            Load(
                name="load",
                mass_kg=_finite_non_negative(load_kg, "load"),
                lever_arm_m=_finite_non_negative(arm_m, "arm"),
            )
        ],
        safety_factor=safety_factor,
    )


def loads_from_assembly(
    parts: list[AssemblyPart], *, pivot_mm: tuple[float, float, float]
) -> tuple[list[Load], tuple[str, ...]]:
    """Geometry → loads: every part with a mass AND a placement contributes at
    its horizontal distance from `pivot_mm` (in metres); the rest are named."""
    loads: list[Load] = []
    unknown: list[str] = []
    for part in parts:
        if part.mass_kg is None or part.position_mm is None:
            unknown.append(part.name)
            continue
        dx = part.position_mm[0] - pivot_mm[0]
        dy = part.position_mm[1] - pivot_mm[1]
        arm_m = math.hypot(dx, dy) / 1000.0
        loads.append(Load(name=part.name, mass_kg=part.mass_kg, lever_arm_m=arm_m))
    return loads, tuple(unknown)
