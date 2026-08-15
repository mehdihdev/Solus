"""RBT-04: active identification — gated motion, honest correlation, NO RESULT over guesses."""

import pytest
from livebench.recognition.active import (
    MAX_MAGNITUDE,
    MotionPlan,
    correlate,
    propose_motion,
    run_active_identification,
)
from solus_api.contracts.action_gate import ToolConfirmationEvent
from solus_api.fingerprint.contract import MatchState, Modality


def plan(magnitude: float = 0.05) -> MotionPlan:
    return MotionPlan(actuator="servo:9", magnitude=magnitude, duration_seconds=0.5)


class Capture:
    """Scripted telemetry capture: baseline first, then the during-motion samples."""

    def __init__(self, baseline: dict[str, list[float]], during: dict[str, list[float]]) -> None:
        self._phases = [baseline, during]

    async def __call__(self, seconds: float) -> dict[str, list[float]]:
        return self._phases.pop(0)


BASELINE = {
    "ch0": [0.0, 0.01, -0.01, 0.0],
    "ch1": [1.0, 1.01, 0.99, 1.0],
    "ch2": [5.0, 5.01, 4.99, 5.0],
}


class TestMotionPlanBounds:
    def test_magnitude_is_conservative_and_bounded(self) -> None:
        with pytest.raises(ValueError, match="magnitude"):
            MotionPlan(actuator="a", magnitude=MAX_MAGNITUDE * 2, duration_seconds=0.5)
        with pytest.raises(ValueError, match="duration"):
            MotionPlan(actuator="a", magnitude=0.05, duration_seconds=30.0)

    def test_proposal_shows_the_exact_commanded_value_and_actuator(self) -> None:
        event = propose_motion(plan(0.05))

        assert isinstance(event, ToolConfirmationEvent)
        assert "servo:9" in event.summary
        assert "0.05" in event.summary
        preview_text = " ".join(f"{row.label} {row.after}" for row in event.preview)
        assert "servo:9" in preview_text
        assert "0.05" in preview_text


class TestGate:
    async def test_refusal_leaves_hardware_untouched(self) -> None:
        commanded: list[MotionPlan] = []

        async def command(motion: MotionPlan) -> None:
            commanded.append(motion)

        async def refuse(event: ToolConfirmationEvent) -> bool:
            return False

        result = await run_active_identification(
            plan(), command=command, capture=Capture(BASELINE, BASELINE), approval=refuse
        )

        assert commanded == []
        assert result.verdict == "refused"
        assert result.channel is None

    async def test_approval_commands_exactly_the_proposed_motion(self) -> None:
        commanded: list[MotionPlan] = []

        async def command(motion: MotionPlan) -> None:
            commanded.append(motion)

        async def approve(event: ToolConfirmationEvent) -> bool:
            return True

        during = {**BASELINE, "ch1": [3.0, 3.2, 2.9, 3.1]}
        await run_active_identification(
            plan(0.05), command=command, capture=Capture(BASELINE, during), approval=approve
        )

        assert len(commanded) == 1
        assert commanded[0].magnitude == 0.05


async def _approve(event: ToolConfirmationEvent) -> bool:
    return True


async def _noop_command(motion: MotionPlan) -> None:
    return None


class TestCorrelation:
    async def test_clear_deflection_identifies_the_channel_as_bus_grade(self) -> None:
        during = {**BASELINE, "ch1": [3.0, 3.2, 2.9, 3.1]}

        result = await run_active_identification(
            plan(), command=_noop_command, capture=Capture(BASELINE, during), approval=_approve
        )

        assert result.verdict == "identified"
        assert result.channel == "ch1"
        assert result.evidence is not None
        assert result.evidence.modality is Modality.TELEMETRY_CHANNEL
        assert result.evidence.state is MatchState.MATCHED
        assert result.evidence.confidence == 0.9
        assert "commanded" in result.evidence.evidence["note"]

    async def test_ambiguous_response_declares_no_result(self) -> None:
        # Two channels deflect the same — the correct answer is "cannot tell".
        during = {**BASELINE, "ch0": [2.0, 2.1, 1.9, 2.0], "ch1": [3.0, 3.1, 2.9, 3.0]}

        result = await run_active_identification(
            plan(), command=_noop_command, capture=Capture(BASELINE, during), approval=_approve
        )

        assert result.verdict == "no_result"
        assert result.channel is None
        assert result.evidence is None

    async def test_no_response_declares_no_result(self) -> None:
        result = await run_active_identification(
            plan(), command=_noop_command, capture=Capture(BASELINE, BASELINE), approval=_approve
        )

        assert result.verdict == "no_result"
        assert result.channel is None

    def test_correlate_scores_are_deterministic(self) -> None:
        during = {**BASELINE, "ch2": [8.0, 8.1, 7.9, 8.0]}
        scores = correlate(BASELINE, during)
        assert max(scores, key=lambda name: scores[name]) == "ch2"
        assert scores["ch0"] < 1.0
