"""Finite joint routines for `run_routine`: the plan (what target set goes out when) and the
result (per-joint tracking against the last target). Pure functions; the server owns the clock,
the adapter calls and the wall-time bound (``duration_s + 10``)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from .adapters.adapter_base import JointSample, decimate, finite
from .tool_args import RunRoutineArgs

SWEEP_STEP_S: Final = 0.25
MAX_ROUTINE_SAMPLES: Final = 50

Plan = list[tuple[float, dict[str, float]]]


def routine_plan(args: RunRoutineArgs) -> Plan:
    """``[(t_s, {joint: target})]`` sorted by time, every t ≤ duration_s."""
    if args.routine == "sweep":
        if args.sweep is None:
            raise ValueError("sweep needs a sweep spec")
        spec = args.sweep
        return sweep_plan(spec.joint, spec.lower, spec.upper, spec.speed_rad_s, args.duration_s)
    if not args.waypoints:
        raise ValueError("joint_trajectory needs waypoints")
    plan = sorted(
        ((w.t_s, dict(w.positions)) for w in args.waypoints if w.t_s <= args.duration_s),
        key=lambda item: item[0],
    )
    if not plan:
        raise ValueError("every waypoint lies past duration_s")
    return plan


def sweep_plan(joint: str, lower: float, upper: float, speed: float, duration_s: float) -> Plan:
    """Triangle wave between the bounds at ``speed``, one target every ``SWEEP_STEP_S``."""
    if upper <= lower:
        raise ValueError("sweep upper must exceed lower")
    span = upper - lower
    plan: Plan = []
    for index in range(int(duration_s / SWEEP_STEP_S) + 1):
        t = index * SWEEP_STEP_S
        phase = (speed * t) % (2 * span)
        position = lower + (phase if phase <= span else 2 * span - phase)
        plan.append((t, {joint: round(position, 6)}))
    return plan


def joint_targets_of(plan: Sequence[tuple[float, dict[str, float]]]) -> dict[str, float]:
    """The LAST target of every joint the plan touches."""
    last: dict[str, float] = {}
    for _, targets in plan:
        last.update(targets)
    return last


def sample_row(sample: JointSample) -> dict[str, Any]:
    return {
        "joint": sample.joint,
        "position": finite(sample.position),
        "velocity": finite(sample.velocity),
        "sim_time_s": sample.sim_time_s,
    }


def routine_result(
    args: RunRoutineArgs,
    session_id: str,
    world: str,
    plan: Sequence[tuple[float, dict[str, float]]],
    sent: int,
    samples: Sequence[JointSample],
    wall_s: float,
    family: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """``family`` is ``(name, version)`` of the family the world runs under, so the run the API
    files from this result names its solver honestly (SOLUSDEV-322 P5-T4)."""
    targets = joint_targets_of(plan)
    final = {s.joint: p for s in samples if (p := finite(s.position)) is not None}
    per_joint = {
        joint: {
            "target": target,
            "final": final.get(joint),
            "error": abs(final[joint] - target) if joint in final else None,
        }
        for joint, target in targets.items()
    }
    errors = [r["error"] for r in per_joint.values() if r["error"] is not None]
    return {
        "ok": True,
        "session_id": session_id,
        "world": world,
        "model": args.model,
        "routine": args.routine,
        "family": family[0] if family else None,
        "version": family[1] if family else None,
        "duration_s": args.duration_s,
        "wall_s": round(wall_s, 3),
        "targets_sent": sent,
        "targets_planned": len(plan),
        "per_joint": per_joint,
        "max_abs_error_rad": max(errors) if errors else None,
        "paused": any(s.paused for s in samples),
        "samples": [sample_row(s) for s in decimate(list(samples), MAX_ROUTINE_SAMPLES)],
    }
