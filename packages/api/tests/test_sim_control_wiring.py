"""SOLUSDEV-321 P4-T5 — compare reads a real run against its routine's twin (P2-T5's classifier).

A run whose snapshots carry a `sim_result` is the twin's run of its routine: the simulation as
the control. When exactly one of the two runs compared is the twin's, compare stores, under
`evidence`, what `classify_sim_control` says of the real run beside `simulation_gap` (the two read
together, M80) and each shared part's residual against the twin. What each input reads:

- a run failed when it shows a stall or raised a warning or critical finding, passed when the
  stall check judged a part of it and it did neither, and says nothing otherwise;
- the task passed when every commanded part ends at its command;
- the twin models a fault when the same stall check judged, in the twin's run, a part that
  stalled in the real one. A raised finding is never counted as modelled.

Pure: manifests in, evidence out, and no provider is asked anything (R98).
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from solus_api.graph import kinds
from solus_api.graph.packet import TelemetryPacket
from solus_api.livebench.runs.analysis import compare, twin_run
from solus_api.livebench.runs.models import PartEvidence, RevisionSnapshot, RunFinding, RunManifest
from solus_api.livebench.scene.part_bindings import JointRange
from solus_api.simulation.sim_ladder import LOCAL_PROVIDERS

ROBOT: Final = uuid.uuid4()
SIM: Final = uuid.uuid4()
T0: Final = datetime(2026, 10, 29, tzinfo=UTC)
SAMPLES: Final = 10


def _routine_joint(name: str, device: str) -> PartEvidence:
    """One joint of the routine, commanded from 0 to 90 deg, with a 2 A stall rating."""
    return PartEvidence(
        entity_id=uuid.uuid4(),
        name=name,
        device_id=device,
        current_signal="current",
        position_signal="position",
        command_signal="command",
        stall_current_a=2.0,
        position_unit="deg",
    )


SHOULDER: Final = _routine_joint("shoulder", "dev/1")
ELBOW: Final = _routine_joint("elbow", "dev/2")


def _routine_packets(
    part: PartEvidence, *, stalls: bool = False, reaches: bool = True, current: bool = True
) -> list[TelemetryPacket]:
    """A joint's packets in one run of the routine. A stall holds it at 0 deg at 2.5 A while 90 is
    commanded; otherwise it climbs to 90 deg, or stops at 45 when it does not reach."""
    packets = []
    for n in range(SAMPLES):
        position = 0.0 if stalls else (90.0 if reaches else 45.0) * n / (SAMPLES - 1)
        values = {"position": position, "command": 90.0}
        values |= {"current": 2.5 if stalls else 0.8} if current else {}
        packets.append(
            TelemetryPacket(
                device_id=part.device_id,
                timestamp=T0 + timedelta(seconds=n / 2),
                values=values,
                units={signal: "A" if signal == "current" else "deg" for signal in values},
            )
        )
    return packets


def _routine_run(
    shoulder: dict[str, Any] | None = None,
    elbow: dict[str, Any] | None = None,
    *,
    twin: bool = False,
    findings: tuple[RunFinding, ...] = (),
) -> RunManifest:
    """One run of the two-joint routine; a twin's run carries its `sim_result`'s snapshot."""
    snapshot = RevisionSnapshot(entity_id=SIM, kind=kinds.SIM_RESULT, name="the routine's twin")
    return RunManifest(
        robot_id=ROBOT,
        started_at=T0,
        packets=[
            *_routine_packets(SHOULDER, **(shoulder or {})),
            *_routine_packets(ELBOW, **(elbow or {})),
        ],
        parts=[SHOULDER, ELBOW],
        snapshots=[snapshot] if twin else [],
        findings=list(findings),
    )


def _routine_finding(severity: str) -> RunFinding:
    return RunFinding.model_validate(
        {
            "finding_id": uuid.uuid4(),
            "rule_id": "temp_trend_to_limit",
            "subjects": [SHOULDER.entity_id],
            "severity": severity,
            "count": 1,
            "first_seen": T0,
            "last_seen": T0,
        }
    )


@pytest.mark.parametrize(
    ("real", "twin", "findings", "control", "gap", "passed"),
    [
        pytest.param(
            {"stalls": True},
            {},
            (),
            "electrical_or_mechanical",
            True,
            (False, True, False),
            id="the-shoulder-stalls-and-the-twin-that-models-it-passed-a-simulation-gap",
        ),
        pytest.param(
            {"stalls": True},
            {"current": False},
            (),
            "electrical_or_mechanical",
            False,
            (False, True, False),
            id="the-shoulder-stalls-where-the-twin-states-no-current-so-models-no-stall",
        ),
        pytest.param(
            {"stalls": True},
            {"stalls": True},
            (),
            "software",
            False,
            (False, False, False),
            id="both-stall-the-same-code-fails-in-both-worlds",
        ),
        pytest.param(
            {},
            {},
            (_routine_finding("warning"),),
            "electrical_or_mechanical",
            False,
            (False, True, True),
            id="a-warning-finding-fails-the-run-and-is-never-counted-as-modelled",
        ),
        pytest.param(
            {},
            {},
            (_routine_finding("info"),),
            "consistent",
            False,
            (True, True, True),
            id="an-info-finding-fails-nothing",
        ),
        pytest.param(
            {"reaches": False},
            {},
            (),
            "policy_or_perception",
            False,
            (True, True, False),
            id="no-fault-and-the-shoulder-misses-its-target",
        ),
        pytest.param(
            {},
            {"stalls": True},
            (),
            "consistent",
            False,
            (True, False, True),
            id="the-twin-failed-where-the-robot-passed-the-twins-gap-not-a-fault",
        ),
    ],
)
def test_compare_classifies_with_sim_control(
    real: dict[str, Any],
    twin: dict[str, Any],
    findings: tuple[RunFinding, ...],
    control: str,
    gap: bool,
    passed: tuple[bool, bool, bool],
) -> None:
    result = compare(_routine_run(twin, twin=True), _routine_run(real, findings=findings))

    evidence = result["evidence"]
    assert result["expected_source"] == "sim"
    assert (evidence["sim_control"], evidence["simulation_gap"], evidence["reason"]) == (
        control,
        gap,
        None,
    )
    assert (evidence["real_passed"], evidence["sim_passed"], evidence["task_passed"]) == passed
    assert evidence["sim_result_id"] == str(SIM)
    assert set(evidence["residuals"]) == {str(SHOULDER.entity_id), str(ELBOW.entity_id)}


def test_what_the_runs_do_not_state_is_never_classified() -> None:
    """Empty beats invented: a run in which the stall check could judge no part, and which raised
    nothing, has not passed or failed, so nothing is classified, and the evidence says which run
    said nothing."""
    silent = {"current": False}

    real_silent = compare(_routine_run(twin=True), _routine_run(silent, silent))["evidence"]
    twin_silent = compare(_routine_run(silent, silent, twin=True), _routine_run({"stalls": True}))

    assert (real_silent["real_passed"], real_silent["sim_control"]) == (None, None)
    assert real_silent["reason"] == "the real run states nothing that says whether it passed"
    evidence = twin_silent["evidence"]
    assert (evidence["real_passed"], evidence["sim_passed"], evidence["sim_control"]) == (
        False,
        None,
        None,
    )
    assert evidence["reason"] == "the twin's run states nothing that says whether it passed"
    assert real_silent["simulation_gap"] is False and evidence["simulation_gap"] is False


def test_the_twin_is_the_expectation_only_as_the_baseline_and_needs_a_real_run() -> None:
    """The comparison reads against a simulation only when the baseline is the twin's run, yet a
    real baseline against a twin candidate is still the control. Two real runs, or two twins,
    have no real run to read against a twin, and keep compare's shape as it was."""
    stalled = _routine_run({"stalls": True})

    flipped = compare(stalled, _routine_run(twin=True))
    real_runs = compare(_routine_run(), stalled)
    twins = compare(_routine_run(twin=True), _routine_run({"stalls": True}, twin=True))

    assert flipped["expected_source"] == "baseline_run"
    assert flipped["evidence"]["sim_control"] == "electrical_or_mechanical"
    assert real_runs["expected_source"] == "baseline_run" and "evidence" not in real_runs
    assert twins["expected_source"] == "sim" and "evidence" not in twins


def test_each_shared_part_is_judged_against_the_twin() -> None:
    """The residual (P4-T4's grid) of what the real run measured against the twin's run, part by
    part: a joint that follows its twin is consistent, and one stopped halfway is not."""
    residuals = compare(_routine_run(twin=True), _routine_run({"reaches": False}))["evidence"][
        "residuals"
    ]

    assert residuals[str(ELBOW.entity_id)]["status"] == "consistent"
    short = residuals[str(SHOULDER.entity_id)]
    assert short["status"] in {"attributed", "unattributed"} and short["residual_rms"] > 0


def test_compare_asks_no_provider_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    """R98: compare classifies what the manifests hold, and no simulation runs or is asked."""

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("compare reached a simulation provider")

    for provider in LOCAL_PROVIDERS:
        monkeypatch.setattr(type(provider), "run", forbidden)
        monkeypatch.setattr(type(provider), "can_answer", forbidden)

    result = compare(_routine_run(twin=True), _routine_run({"stalls": True}))

    assert result["evidence"]["sim_control"] == "electrical_or_mechanical"


def test_the_twins_marker_is_no_change_of_source_snapshots() -> None:
    """Minor 1: the marker names a simulation, not a source, so a twin against a real run with
    the same snapshots says the sources did not change; a changed source still says so."""
    moved = RevisionSnapshot(entity_id=uuid.uuid4(), kind="code", name="firmware", revision="r2")

    same = compare(_routine_run(twin=True), _routine_run())
    changed = compare(
        _routine_run(twin=True), _routine_run().model_copy(update={"snapshots": [moved]})
    )

    assert same["source_snapshots_changed"] is False and changed["source_snapshots_changed"] is True


# ------------------------------------------- the twin's run, from its simulation (P4-T5 fix 1)

SCENE: Final = uuid.uuid4()


def _joint_of(part: uuid.UUID) -> JointRange | None:
    """The scene binds the shoulder to the simulated `shoulder` joint, in radians; the elbow to
    nothing the simulation drove."""
    return (
        JointRange(SCENE, "shoulder", -math.pi, math.pi, "rad")
        if part == SHOULDER.entity_id
        else None
    )


def _trajectory_sim(**inputs: Any) -> dict[str, Any]:
    """A rung-3 trajectory simulation's attrs as `record_sim_result` stores them: the routine,
    commanding the shoulder to a quarter turn, and the recorded climb to it at 0.8 A."""
    times = [n / 2 for n in range(SAMPLES)]
    recorded = {
        "trajectory": {
            "joints": ["shoulder"],
            "points": [
                {"t": 0.0, "positions": [math.pi / 2]},
                {"t": times[-1], "positions": [math.pi / 2]},
            ],
        },
        "expected_trajectory": {
            "t": times,
            "positions": {"shoulder": [math.pi / 2 * n / (SAMPLES - 1) for n in range(SAMPLES)]},
        },
        "expected_current_a": {"shoulder": [0.8] * SAMPLES},
    } | inputs
    return {
        "subject_id": str(ROBOT),
        "rung": 3,
        "values": {"peak_joint_torque_nm": {"value": 1.2, "unit": "N m"}},
        "provenance": {
            "solver": "rigid_body_trajectory",
            "inputs": {
                name: {"value": value, "source": "derived"} for name, value in recorded.items()
            },
            "leaves_out": ["sensor noise and delay"],
        },
    }


def test_the_twins_run_lays_its_simulation_onto_the_real_runs_parts() -> None:
    """R117: `twin_run` lays a trajectory simulation's recording onto each part of the real run
    the scene binds to a simulated joint: the recorded position, the expected current and the
    routine's command at each sample, in the part's own units (the recording's radians as the
    part's degrees), from the real run's start. The elbow, bound to no simulated joint, is left
    out, and the twin carries the real run's snapshots and the simulation's marker."""
    real = _routine_run({"stalls": True})

    twin = twin_run(_trajectory_sim(), real, _joint_of, sim_result_id=SIM)

    assert [part.entity_id for part in twin.parts] == [SHOULDER.entity_id]
    assert (twin.robot_id, twin.started_at) == (real.robot_id, real.started_at)
    assert [(item.entity_id, item.kind) for item in twin.snapshots] == [(SIM, kinds.SIM_RESULT)]
    assert [packet.device_id for packet in twin.packets] == [SHOULDER.device_id] * SAMPLES
    first, last = twin.packets[0], twin.packets[-1]
    assert last.timestamp == T0 + timedelta(seconds=(SAMPLES - 1) / 2)
    assert first.values == pytest.approx({"position": 0.0, "current": 0.8, "command": 90.0})
    assert last.values == pytest.approx({"position": 90.0, "current": 0.8, "command": 90.0})
    assert last.units == {"position": "deg", "current": "A", "command": "deg"}


def test_compare_reads_a_real_run_against_the_twin_built_from_its_simulation() -> None:
    """The twin `twin_run` builds is the control: the shoulder stalls where its simulation, which
    models a stall, climbed, so the fault is electrical or mechanical, beside a simulation gap."""
    real = _routine_run({"stalls": True})

    result = compare(twin_run(_trajectory_sim(), real, _joint_of, sim_result_id=SIM), real)

    evidence = result["evidence"]
    assert (result["expected_source"], result["source_snapshots_changed"]) == ("sim", False)
    assert (evidence["sim_control"], evidence["simulation_gap"]) == (
        "electrical_or_mechanical",
        True,
    )
    assert (evidence["sim_result_id"], set(evidence["residuals"])) == (
        str(SIM),
        {str(SHOULDER.entity_id)},
    )


@pytest.mark.parametrize(
    ("sim", "joint_of"),
    [
        pytest.param(
            _trajectory_sim(),
            lambda part: JointRange(SCENE, "shoulder", 0.0, 0.1, "m"),
            id="a-slide-in-metres-is-no-joint-in-degrees",
        ),
        pytest.param(
            {"rung": 1, "provenance": {"inputs": {"load": {"value": 1.0, "source": "known"}}}},
            _joint_of,
            id="a-simulation-of-no-routine",
        ),
        pytest.param(
            _trajectory_sim(
                expected_trajectory={"t": [0.0, 0.5], "positions": {"shoulder": [0.0]}}
            ),
            _joint_of,
            id="a-series-shorter-than-its-times",
        ),
        pytest.param(
            _trajectory_sim(
                expected_trajectory={"t": [0.0, 1e300], "positions": {"shoulder": [0.0, 1.0]}}
            ),
            _joint_of,
            id="times-past-any-routine",
        ),
    ],
)
def test_a_part_its_simulation_states_nothing_of_is_left_out_of_the_twin(
    sim: dict[str, Any], joint_of: Callable[[uuid.UUID], JointRange | None]
) -> None:
    """Empty beats invented: a part whose joint the simulation did not record in a unit that
    converts, or whose recording is malformed, is not in the twin, and compare says the twin's
    run states nothing."""
    real = _routine_run({"stalls": True})

    twin = twin_run(sim, real, joint_of, sim_result_id=SIM)

    assert twin.parts == [] and twin.packets == []
    reason = compare(twin, real)["evidence"]["reason"]
    assert reason == "the twin's run states nothing that says whether it passed"
