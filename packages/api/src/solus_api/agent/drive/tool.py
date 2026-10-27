"""`drive.step` — the one model-facing drive tool (ADR-041 §4; sol-drive.md §4).

SOL proposes `drive.step {app, intent}`; the ordinary confirmation gate parks it
and shows a card built from the arguments alone (App, What SOL will do, Budget,
Heads up) — the pill is frontmost while the card waits, so a live "is KiCad in
front" check there would always be stale. On approval the executor binds the
window, runs one bounded loop and returns. Progress streams through the
command-output channel (`STREAMING_TOOLS`), the way an approved command does.

An unfinished step (the user took over, budget used, a refusal) raises a
`ToolException` with a Solus-written sentence, so a running plan stops there.
"""

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_api.agent.command_output import current_output
from solus_api.agent.drive.executor import Budget, Progress, StepOutcome
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.agent.tools.untrusted import redact_text

logger = logging.getLogger("solus.drive")

#: ADR-041 §3: drivable apps by OS identity, mirroring the helper's own list
#: (solus-input `DrivableApps`) — the helper refuses anything else regardless.
DRIVABLE_APPS: Final[dict[str, frozenset[str]]] = {
    "kicad": frozenset({"org.kicad.kicad", "org.kicad.eeschema"}),
}
_APP_NAMES: Final = {"kicad": "KiCad"}
INTENT_MAX: Final = 300
_ONE_LINE: Final = re.compile(r"^[^\x00-\x1f\x7f  ]+$")

RunStep = Callable[[str, frozenset[str], Callable[[Progress], None]], Awaitable[StepOutcome]]
Record = Callable[[str, dict[str, Any]], Awaitable[None]]


class DriveStepArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    app: Literal["kicad"]
    intent: str = Field(min_length=1, max_length=INTENT_MAX, pattern=_ONE_LINE.pattern)


_PARAMS: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["app", "intent"],
    "properties": {
        "app": {"type": "string", "enum": sorted(DRIVABLE_APPS)},
        "intent": {
            "type": "string",
            "minLength": 1,
            "maxLength": INTENT_MAX,
            "description": "One plain sentence: what will change in the window.",
        },
    },
}

_DESCRIPTION: Final = (
    "Use the user's mouse and keyboard in their open KiCad window for ONE small, "
    "concrete step that no KiCad tool can do (for example: open the Add Symbol "
    "chooser and place a resistor). Prefer kicad.* tools whenever one fits. The "
    "user approves each step; it runs up to 15 actions in about 2 minutes, and "
    "stops if they touch the mouse or keyboard. `intent` is shown to them word for "
    "word: one plain sentence saying what will change in the window."
)
_CONSENT: Final = "SOL will move your mouse and type in your KiCad window for this one step"

#: What an unfinished step tells SOL and the person, by outcome.
_UNFINISHED: Final = {
    "paused": "paused — you took over",
    "budget": "stopped — this step's budget is used up; ask SOL to continue",
    "refused": "stopped — the input helper refused ({code})",
    "not_in_front": "nothing done — {app} was not in front; bring it forward and ask again",
    "declined": "stopped — SOL declined this step",
    "error": "stopped — something failed ({code})",
}


def _budget_label(budget: Budget) -> str:
    minutes = budget.max_seconds / 60
    span = f"{minutes:g} min" if minutes >= 1 else f"{budget.max_seconds:g} s"
    return f"up to {budget.max_actions} actions · {span}"


def _row(label: str, value: str) -> dict[str, Any]:
    return {"label": label, "before": None, "after": value}


class DriveStepTool:
    """One approved, bounded drive step. Built per turn by the runtime only when
    the requesting user's companion advertises the internal drive tools."""

    def __init__(self, *, run_step: RunStep, record: Record, budget: Budget) -> None:
        self._run_step = run_step
        self._record = record
        self._budget = budget
        self._descriptor = ToolDescriptor(
            name="drive.step",
            description=_DESCRIPTION,
            consent_summary=_CONSENT,
            params=_PARAMS,
            returns={"type": "object"},
            requires_confirmation=True,
            # The loop's own wall-clock budget bounds it; this is the backstop.
            timeout_seconds=budget.max_seconds + 60,
        )

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    @staticmethod
    def _parse(args: dict[str, Any]) -> DriveStepArgs:
        try:
            parsed = DriveStepArgs.model_validate(args)
        except ValidationError:
            raise ToolException(
                f"drive.step needs an allowlisted app and a one-line intent of at most "
                f"{INTENT_MAX} characters",
                code=ToolErrorCode.INVALID_ARGS,
            ) from None
        # The card redacts secret-shaped text; the loop would get the raw intent.
        # Displayed must be executed, so such an intent is refused outright.
        if redact_text(parsed.intent) != parsed.intent:
            raise ToolException(
                "drive.step's intent contains secret-shaped text that cannot be shown "
                "on the approval card; describe the step without it",
                code=ToolErrorCode.INVALID_ARGS,
            )
        return parsed

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        parsed = self._parse(args)
        return [
            _row("App", _APP_NAMES[parsed.app]),
            _row("What SOL will do", parsed.intent),
            _row("Budget", _budget_label(self._budget)),
            _row(
                "Heads up",
                "SOL will move your mouse and type in this window. "
                "Move the mouse or press Esc to stop it.",
            ),
        ]

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        parsed = self._parse(args)
        trail: list[Progress] = []
        sink = current_output.get()

        def on_progress(progress: Progress) -> None:
            trail.append(progress)
            if sink is not None:
                sink.append(
                    "stdout",
                    f"action {progress.action}/{progress.max_actions} · {progress.verb} · "
                    f"{progress.elapsed:.1f} s\n",
                )

        await self._safe_record(
            "drive.session_started", {"app": parsed.app, "budget": _budget_label(self._budget)}
        )
        result = await self._run_step(parsed.intent, DRIVABLE_APPS[parsed.app], on_progress)
        await self._record_outcome(parsed.app, result, trail)
        if result.outcome == "done":
            return {
                "outcome": "done",
                "actions": result.actions,
                "seconds": result.seconds,
                "summary": result.summary,
            }
        sentence = _UNFINISHED[result.outcome].format(
            code=result.code or "unknown", app=_APP_NAMES[parsed.app]
        )
        noun = "action" if result.actions == 1 else "actions"
        raise ToolException(
            f"Drive step {sentence} after {result.actions} {noun}.",
            code=ToolErrorCode.TOOL_ERROR,
        )

    async def _record_outcome(self, app: str, result: StepOutcome, trail: list[Progress]) -> None:
        failed = result.outcome != "done"
        for progress in trail:
            refused = progress.action == result.failed_action
            code = result.code if refused and result.code else "ok"
            await self._safe_record(
                "drive.action", {"index": progress.action, "verb": progress.verb, "result": code}
            )
        if failed:
            await self._safe_record(
                "drive.aborted", {"outcome": result.outcome, "code": result.code}
            )
        await self._safe_record(
            "drive.session_ended",
            {
                "app": app,
                "actions": result.actions,
                "seconds": result.seconds,
                "outcome": result.outcome,
                "code": result.code,
            },
        )

    async def _safe_record(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            await self._record(event_type, payload)
        except Exception:  # noqa: BLE001 — data collection never fails the step
            logger.warning("drive event %s not recorded", event_type, exc_info=True)
