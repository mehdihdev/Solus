"""Hard server-owned ceilings selected only from validated action mode."""

from dataclasses import dataclass

from solus_api.agent.modes import ActionMode


@dataclass(frozen=True, slots=True)
class TurnLimits:
    model_rounds: int
    tool_calls: int
    timeout_seconds: float


GUIDE_LIMITS = TurnLimits(5, 8, 120.0)
BUILD_LIMITS = TurnLimits(16, 24, 300.0)


def turn_limits(mode: ActionMode) -> TurnLimits:
    if not isinstance(mode, ActionMode):
        raise ValueError("A validated action mode is required")
    return BUILD_LIMITS if mode is ActionMode.DO else GUIDE_LIMITS
