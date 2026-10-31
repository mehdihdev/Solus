"""SOLUSDEV-321 P2-T5 — the simulation as the control: where a real failure lives.

The same routine run in the twin is the control experiment for a real run. Pure: booleans in, a
label out, no graph write and no model call. The run comparison (P4-T5) calls it and stores the
answers as `evidence.sim_control` and `evidence.simulation_gap`. Shared code: no vendor, connector
or simulator name (the hygiene ratchets sweep this package).
"""

from __future__ import annotations

from typing import Literal

SimControl = Literal["electrical_or_mechanical", "software", "policy_or_perception", "consistent"]


def classify_sim_control(real_passed: bool, sim_passed: bool, task_passed: bool) -> SimControl:
    # the real robot failed: the twin is the control
    #   twin passed  → electrical_or_mechanical: the fault is in what the twin does not model,
    #                  unless `simulation_gap` says it models that fault, when its model missed it
    #                  (M80: the label is always read with the gap)
    #   twin failed  → software: the same code fails in both worlds
    # the real robot passed, so the task decides, whatever the twin did:
    #   task failed  → policy_or_perception: no fault, and the objective is not met
    #   task passed  → consistent. A twin that failed where the robot passed is its own model
    #                  being off, never a fault: no predicate says so, and the comparison shows it
    #                  as `sim_passed: false` beside this label
    if not real_passed:
        return "electrical_or_mechanical" if sim_passed else "software"
    return "consistent" if task_passed else "policy_or_perception"


def simulation_gap(real_passed: bool, sim_passed: bool, *, sim_covers_fault: bool) -> bool:
    """True when a fault the simulation models (a stage-3 fault it should have caught)
    passed the twin."""
    return (not real_passed) and sim_passed and sim_covers_fault
