"""SOLUSDEV-321 P4-T4 (R93) — a real run's residual against a simulation's trajectory, attributed.

`livebench/runs/analysis.py` judges, joint by joint, the residual between what a run measured and
what a `sim_result` expected (`provenance.inputs.expected_trajectory`). It attributes the residual
to ONE of `mass`, `limit`, `sensor_offset` and `contact` by a deterministic grid of named sizes:
each parameter's forward model is tried at `GRID_STEPS` values, and the parameter that alone
explains most of the residual is named when it explains enough and leads the next by a margin.
Otherwise the residual is `unattributed`; one within a hundredth of the motion is `consistent`.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from solus_api.graph.packet import TelemetryPacket
from solus_api.livebench.runs.analysis import (
    ATTRIBUTION_MARGIN,
    ATTRIBUTION_MIN,
    RESIDUAL_PARAMETERS,
    RESIDUAL_SAMPLES,
    residual_attribution,
    run_positions,
)
from solus_api.livebench.runs.models import PartEvidence, RunManifest

DURATION_S: Final = 2.0
TIMES: Final = [k * DURATION_S / 255 for k in range(256)]
#: The joint swings out to 0.8 rad and back over the routine: up, then down.
EXPECTED: Final = [0.8 * math.sin(math.pi * t / DURATION_S) for t in TIMES]


def _lagged(times: list[float], values: list[float], tau_s: float) -> list[float]:
    """What a joint tracks when a heavier link adds a first-order lag of `tau_s`."""
    out = [values[0]]
    for k in range(1, len(values)):
        step = 1.0 - math.exp(-(times[k] - times[k - 1]) / tau_s)
        out.append(out[-1] + step * (values[k] - out[-1]))
    return out


def _stopped_at(times: list[float], values: list[float], at_s: float) -> list[float]:
    """What a joint does when it meets an obstacle at `at_s` and stays there."""
    stop = next(k for k, t in enumerate(times) if t >= at_s)
    return values[:stop] + [values[stop]] * (len(values) - stop)


#: The expected sweep with exactly one parameter perturbed.
PERTURBED: Final = {
    "sensor_offset": [v + 0.05 for v in EXPECTED],
    "limit": [min(v, 0.6) for v in EXPECTED],
    "mass": _lagged(TIMES, EXPECTED, 0.15),
    "contact": _stopped_at(TIMES, EXPECTED, 0.5),
}


@pytest.mark.parametrize("parameter", RESIDUAL_PARAMETERS)
def test_single_parameter_attribution(parameter: str) -> None:
    found = residual_attribution(TIMES, EXPECTED, TIMES, PERTURBED[parameter])
    assert (found["status"], found["parameter"]) == ("attributed", parameter)
    explained = found["explained"]
    assert explained[parameter] >= ATTRIBUTION_MIN
    for other in RESIDUAL_PARAMETERS:
        if other != parameter:
            assert explained[parameter] - explained[other] >= ATTRIBUTION_MARGIN


def test_the_grid_estimates_the_perturbation_it_names() -> None:
    def estimate(parameter: str) -> dict[str, float | str]:
        found = residual_attribution(TIMES, EXPECTED, TIMES, PERTURBED[parameter])
        return dict(found["estimate"][parameter])

    assert estimate("sensor_offset")["offset"] == pytest.approx(0.05, abs=0.005)
    limit = estimate("limit")
    assert limit["side"] == "upper" and limit["at"] == pytest.approx(0.6, abs=0.03)
    assert float(estimate("mass")["tau_s"]) == pytest.approx(0.15, rel=0.3)
    assert estimate("contact")["at_s"] == pytest.approx(0.5, abs=0.07)


def test_the_attribution_is_deterministic_and_bounded() -> None:
    # A run recorded at 10 kHz is judged on the same bounded grid as one at 128 Hz.
    fine_t = [k * DURATION_S / 19_999 for k in range(20_000)]
    fine = [min(0.8 * math.sin(math.pi * t / DURATION_S), 0.6) for t in fine_t]
    first = residual_attribution(TIMES, EXPECTED, fine_t, fine)
    assert first == residual_attribution(TIMES, EXPECTED, fine_t, fine)
    assert (first["status"], first["parameter"]) == ("attributed", "limit")
    assert first["samples"] == RESIDUAL_SAMPLES


def test_a_run_that_matches_is_consistent_and_two_perturbations_are_not_forced_onto_one() -> None:
    matching = residual_attribution(TIMES, EXPECTED, TIMES, [v + 1e-5 for v in EXPECTED])
    assert (matching["status"], matching["parameter"]) == ("consistent", None)
    both = [min(v, 0.6) + 0.05 for v in EXPECTED]
    mixed = residual_attribution(TIMES, EXPECTED, TIMES, both)
    assert (mixed["status"], mixed["parameter"]) == ("unattributed", None)


@pytest.mark.parametrize(
    ("observed_t", "observed", "why"),
    [
        pytest.param(
            [3.0 + 0.1 * k for k in range(10)], [0.0] * 10, "share no time", id="no-overlap"
        ),
        pytest.param([0.0, 1.0], [0.0, 0.1], "at least", id="too-few-samples"),
        pytest.param(TIMES, [*EXPECTED[:-1], math.nan], "finite", id="a-nan"),
        pytest.param([*TIMES[:-2], TIMES[-1], TIMES[-2]], EXPECTED, "increasing", id="unordered"),
        pytest.param(TIMES, EXPECTED[:-1], "as many", id="ragged"),
    ],
)
def test_series_that_cannot_be_compared_are_insufficient(
    observed_t: list[float], observed: list[float], why: str
) -> None:
    found = residual_attribution(TIMES, EXPECTED, observed_t, observed)
    assert (found["status"], found["parameter"]) == ("insufficient", None)
    assert why in found["reason"]


def test_run_positions_reads_a_parts_measured_positions_in_its_unit() -> None:
    start = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    part = PartEvidence(
        entity_id=uuid.uuid4(),
        name="shoulder",
        device_id="servo-1",
        position_signal="servo1.position",
        position_unit="rad",
    )
    packets = [
        TelemetryPacket(
            device_id="servo-1",
            timestamp=start + timedelta(seconds=0.5),
            values={"servo1.position": 90.0},
            units={"servo1.position": "deg"},
        ),
        TelemetryPacket(
            device_id="other",
            timestamp=start + timedelta(seconds=0.6),
            values={"servo1.position": 1.0},
        ),
        TelemetryPacket(
            device_id="servo-1",
            timestamp=start + timedelta(seconds=1.0),
            values={"servo1.voltage": 12.0},
        ),
    ]
    run = RunManifest(robot_id=uuid.uuid4(), started_at=start, packets=packets, parts=[part])
    times, positions = run_positions(run, part)
    assert times == [0.5]
    assert positions == pytest.approx([math.pi / 2])
