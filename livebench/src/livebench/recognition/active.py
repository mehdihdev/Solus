"""Active identification (RBT-04): command a bounded motion, watch which channel moves.

The capability only Solus has — holding control AND telemetry at the same moment —
and the one that moves real hardware, so every run goes through the CTR-03 gate:

1. `propose_motion` builds the `ToolConfirmationEvent` showing the EXACT actuator
   and commanded magnitude (bounded at construction — `MAX_MAGNITUDE`, conservative
   by default).
2. The `approval` seam answers it. On this branch the real approval surface is
   unmerged (SOLUSDEV-60); callers plug the flow in here, tests plug fakes.
   **Refusal returns before the command callable is ever invoked** — refused means
   the hardware was not touched.
3. Baseline capture → the bounded motion → during-motion capture → correlation.

Correlation is honest: it reports the responding channel only when the deflection
is BOTH strong and unambiguous (top score over threshold AND clearly ahead of the
runner-up); anything else is an explicit NO RESULT — a weak guess about a
motor→channel mapping poisons everything downstream. An unambiguous hit feeds
RBT-03 as bus-grade evidence (0.9), because a commanded-and-observed response is
the strongest identity claim telemetry can make.
"""

import statistics
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Literal

from solus_api.contracts.action_gate import DiffRow, ToolConfirmationEvent
from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef

#: Normalized command units; deliberately small — identification needs a twitch, not a sweep.
MAX_MAGNITUDE: Final = 0.2
MAX_DURATION_SECONDS: Final = 5.0

#: A channel identifies only when its deflection clears this z-score…
SCORE_THRESHOLD: Final = 5.0
#: …and beats the runner-up by this factor (otherwise: cannot tell).
AMBIGUITY_MARGIN: Final = 3.0

Capture = Callable[[float], Awaitable[dict[str, list[float]]]]
Approval = Callable[[ToolConfirmationEvent], Awaitable[bool]]


@dataclass(frozen=True)
class MotionPlan:
    """One bounded, explicitly-described motion on one actuator."""

    actuator: str
    magnitude: float
    duration_seconds: float

    def __post_init__(self) -> None:
        if not 0 < abs(self.magnitude) <= MAX_MAGNITUDE:
            raise ValueError(f"magnitude out of the conservative bound: {self.magnitude}")
        if not 0 < self.duration_seconds <= MAX_DURATION_SECONDS:
            raise ValueError(f"duration out of range: {self.duration_seconds}")


CommandFn = Callable[[MotionPlan], Awaitable[None]]


@dataclass(frozen=True)
class ActiveIdResult:
    verdict: Literal["identified", "no_result", "refused"]
    channel: str | None
    confidence: float
    scores: dict[str, float]
    evidence: ModalityMatch | None


def propose_motion(plan: MotionPlan) -> ToolConfirmationEvent:
    """The gate payload: the exact motion, visible before anything moves."""
    return ToolConfirmationEvent(
        confirmation_id=uuid.uuid4().hex,
        tool="active_identification",
        args={
            "actuator": plan.actuator,
            "magnitude": plan.magnitude,
            "duration_seconds": plan.duration_seconds,
        },
        summary=(
            f"Command a bounded identification motion: {plan.actuator} to "
            f"{plan.magnitude} (normalized) for {plan.duration_seconds}s"
        ),
        preview=[
            DiffRow(
                label=f"commanded value on {plan.actuator}", before="0", after=str(plan.magnitude)
            ),
            DiffRow(label="duration", before=None, after=f"{plan.duration_seconds}s"),
        ],
    )


def correlate(baseline: dict[str, list[float]], during: dict[str, list[float]]) -> dict[str, float]:
    """Per-channel deflection score: |mean shift| in baseline-noise units. Pure."""
    scores: dict[str, float] = {}
    for name, base in baseline.items():
        samples = during.get(name)
        if not base or not samples:
            continue
        noise = statistics.pstdev(base) if len(base) > 1 else 0.0
        scores[name] = abs(statistics.fmean(samples) - statistics.fmean(base)) / max(noise, 1e-6)
    return scores


def _verdict(scores: dict[str, float]) -> str | None:
    """The responding channel, or None when the honest answer is "cannot tell"."""
    if not scores:
        return None
    ranked = sorted(scores, key=lambda name: scores[name], reverse=True)
    top = ranked[0]
    if scores[top] < SCORE_THRESHOLD:
        return None
    if len(ranked) > 1 and scores[top] < AMBIGUITY_MARGIN * scores[ranked[1]]:
        return None
    return top


async def run_active_identification(
    plan: MotionPlan,
    *,
    command: CommandFn,
    capture: Capture,
    approval: Approval,
) -> ActiveIdResult:
    """Propose → gate → (maybe) move → correlate. Never moves hardware unapproved."""
    event = propose_motion(plan)
    if not await approval(event):
        return ActiveIdResult("refused", None, 0.0, {}, None)

    baseline = await capture(plan.duration_seconds)
    await command(plan)
    during = await capture(plan.duration_seconds)

    scores = correlate(baseline, during)
    channel = _verdict(scores)
    if channel is None:
        return ActiveIdResult("no_result", None, 0.0, scores, None)

    evidence = ModalityMatch(
        modality=Modality.TELEMETRY_CHANNEL,
        source_ref=SourceRef(source_connector="active-id", external_ref=channel),
        confidence=0.9,
        state=MatchState.MATCHED,
        evidence={
            "matched_on": "active_correlation",
            "value": f"{scores[channel]:.1f}σ",
            "note": (
                f"commanded {plan.actuator} to {plan.magnitude} and channel {channel} "
                "deflected unambiguously — observed, not inferred; still names the "
                "channel, and the user confirms the mapping (RBT-03)"
            ),
        },
    )
    return ActiveIdResult("identified", channel, 0.9, scores, evidence)
