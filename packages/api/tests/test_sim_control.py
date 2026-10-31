"""SOLUSDEV-321 P2-T5 — the simulation as the control (`livebench/findings/sim_control.py`).

The same routine run in the twin says where a real failure lives, so the truth table is the whole
contract: every (real, twin, task) row of `classify_sim_control`, and the four rows of
`simulation_gap` that show each of its three conditions decides the answer on its own.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

import pytest
from solus_api.livebench.findings.sim_control import classify_sim_control, simulation_gap


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        # classify_sim_control(real_passed, sim_passed, task_passed). The real robot failed, so
        # the twin is the control: it passed (the fault is in what it does not model) or it failed
        # too (the same code fails in both worlds); the task result does not change the answer.
        pytest.param(
            partial(classify_sim_control, False, True, False),
            "electrical_or_mechanical",
            id="classify-real-failed-twin-passed-task-failed",
        ),
        pytest.param(
            partial(classify_sim_control, False, True, True),
            "electrical_or_mechanical",
            id="classify-real-failed-twin-passed-task-passed",
        ),
        pytest.param(
            partial(classify_sim_control, False, False, False),
            "software",
            id="classify-real-failed-twin-failed-task-failed",
        ),
        pytest.param(
            partial(classify_sim_control, False, False, True),
            "software",
            id="classify-real-failed-twin-failed-task-passed",
        ),
        # The real robot passed, so the task decides whatever the twin did: no fault and the
        # objective is not met (policy_or_perception), or it is met (consistent); a twin that
        # failed anyway is its own model being off, not a fault (M80).
        pytest.param(
            partial(classify_sim_control, True, True, False),
            "policy_or_perception",
            id="classify-real-passed-twin-passed-task-failed",
        ),
        pytest.param(
            partial(classify_sim_control, True, False, False),
            "policy_or_perception",
            id="classify-real-passed-twin-failed-task-failed",
        ),
        pytest.param(
            partial(classify_sim_control, True, True, True),
            "consistent",
            id="classify-real-passed-twin-passed-task-passed",
        ),
        pytest.param(
            partial(classify_sim_control, True, False, True),
            "consistent",
            id="classify-real-passed-twin-failed-task-passed",
        ),
        # simulation_gap(real_passed, sim_passed, *, sim_covers_fault): True only for a real
        # failure the twin passed although it models that fault; flip any one condition and the
        # gap is gone.
        pytest.param(
            partial(simulation_gap, False, True, sim_covers_fault=True),
            True,
            id="gap-real-failed-twin-passed-fault-modelled",
        ),
        pytest.param(
            partial(simulation_gap, True, True, sim_covers_fault=True),
            False,
            id="no-gap-real-passed",
        ),
        pytest.param(
            partial(simulation_gap, False, False, sim_covers_fault=True),
            False,
            id="no-gap-twin-failed-too",
        ),
        pytest.param(
            partial(simulation_gap, False, True, sim_covers_fault=False),
            False,
            id="no-gap-fault-not-modelled",
        ),
    ],
)
def test_truth_table(call: Callable[[], object], expected: object) -> None:
    assert call() == expected
