"""`drive.step` — the one model-facing drive tool (ADR-041 §4; sol-drive.md §4).

SOL proposes `drive.step {app, intent}`; the ordinary confirmation gate parks it
and shows a card built from the arguments alone (App, What SOL will do, Budget,
Heads up) — the pill is frontmost while the card waits, so a live "is KiCad in
front" check there would always be stale.

`app: "front"` (sol-drive.md §2.2) is offered only when the turn's `front_app`
is drivable and window-bound. The model's arguments never carry a binding:
`stored_args` — Solus code, before parking — copies the turn's window into the
stored arguments, and the card and the run read only that stored window.

On approval the executor binds the window, runs one bounded loop and returns.
Progress streams through the command-output channel (`STREAMING_TOOLS`), the
way an approved command does.

An unfinished step (the user took over, budget used, a refusal) raises a
`ToolException` with a Solus-written sentence, so a running plan stops there.
"""

import asyncio
import logging
import re
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from solus_api.agent.command_output import current_output
from solus_api.agent.drive.binding import FrontAppBinding, WindowBinding
from solus_api.agent.drive.executor import Budget, Progress, StepOutcome, Target, refused_intent
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
#: One line, and no angle brackets: the intent is fenced as `<goal>…</goal>` in
#: the loop's prompt (executor._intro), so it must not be able to close the fence.
_ONE_LINE: Final = re.compile("^[^\\x00-\\x1f\\x7f\\u2028\\u2029<>]+$")

RunStep = Callable[[str, Target, Callable[[Progress], None]], Awaitable[StepOutcome]]
Record = Callable[[str, dict[str, Any]], Awaitable[None]]
FRONT: Final = "front"
INTENT_REFUSED: Final = (
    "drive.step can't upload, flash or deploy; use the integration's own tools for that"
)


class DriveStepArgs(BaseModel):
    """The model's arguments: no binding field, ever."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    app: Literal["kicad", "front"]
    intent: str = Field(min_length=1, max_length=INTENT_MAX, pattern=_ONE_LINE.pattern)


class DriveStepStoredArgs(DriveStepArgs):
    """A parked call's stored arguments: `window` is Solus-stamped, `front` only."""

    window: WindowBinding | None = None

    @model_validator(mode="after")
    def _window_iff_front(self) -> "DriveStepStoredArgs":
        if (self.app == FRONT) != (self.window is not None):
            raise ValueError("a stored window belongs to a front step, and only there")
        return self


def _params(apps: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["app", "intent"],
        "properties": {
            "app": {
                "type": "string",
                "enum": apps,
                "description": (
                    "kicad: the user's KiCad window. front: the window the user "
                    "summoned SOL over (offered only when SOL can drive it)."
                ),
            },
            "intent": {
                "type": "string",
                "minLength": 1,
                "maxLength": INTENT_MAX,
                "description": "One plain sentence: what will change in the window.",
            },
        },
    }


def _description(budget: Budget) -> str:
    return (
        "Use the user's mouse and keyboard in their open KiCad window, or the window "
        "they summoned SOL over, for ONE small, concrete step that no integration tool "
        "or workspace file tool can do (for example: open the Add Symbol chooser and "
        "place a resistor). Prefer kicad.* and other integration tools, then file "
        "tools such as machine.write_file, whenever one fits. Never upload, flash or "
        "deploy with it. The "
        f"user approves each step; it runs {_budget_label(budget)}, and stops if they "
        "touch the mouse or keyboard. `intent` is shown to them word for word: one "
        "plain sentence saying what will change in the window."
    )


_CONSENT: Final = "SOL will move your mouse and type in your KiCad window for this one step"

#: What an unfinished step tells SOL and the person, by outcome.
_UNFINISHED: Final = {
    "paused": "paused — you took over",
    "budget": "stopped — this step's budget is used up; ask SOL to continue",
    "refused": "stopped — the input helper refused ({code})",
    "not_in_front": "nothing done — {app} was not in front; bring it forward and ask again",
    "declined": "stopped — SOL declined this step",
    "saved": "stopped — SOL saved the design to disk",
    "error": "stopped — something failed ({code})",
}
#: Codes with a sentence of their own (the person can act on these).
_BY_CODE: Final = {
    "rate_limited": "stopped — too many SOL requests right now; wait a minute and ask again",
    "no_credits": "stopped — you are out of credits",
    "tokens": "stopped — this step used its model budget; ask SOL to continue",
    "outside_workspace": (
        "stopped — the KiCad in front has a project outside this Solus project open"
    ),
    "no_workspace": "stopped — link a folder to this project to let SOL use KiCad",
    "agent_unavailable": "stopped — the input helper is not running; check Settings › SOL",
    "relaunched": "stopped — {app} was restarted; summon SOL over the window again",
    "window_mismatch": "stopped — a different {app} window is in front",
    "app_denied": "stopped — SOL can't use the mouse and keyboard in that app",
    "intent_refused": INTENT_REFUSED,
}
#: A window-bound step's save watch cannot tell SOL's save from autosave.
_WINDOW_SAVED: Final = "stopped — a file in this project changed"


def progress_line(progress: Progress) -> str:
    """One progress line on the command-output channel. A STABLE format the pill
    parses (sol-drive.md §4): `^action (\\d+)/(\\d+) · ([a-z]+) · (\\d+\\.\\d) s$`."""
    return (
        f"action {progress.action}/{progress.max_actions} · {progress.verb} · "
        f"{progress.elapsed:.1f} s\n"
    )


def _budget_label(budget: Budget) -> str:
    minutes = budget.max_seconds / 60
    span = f"{minutes:g} min" if minutes >= 1 else f"{budget.max_seconds:g} s"
    return f"up to {budget.max_actions} actions · {span}"


#: Letters that render as nothing (Hangul fillers, Khmer vowel inherents…).
_INVISIBLE_LETTERS: Final = frozenset("\u115f\u1160\u3164\uffa0\u17b4\u17b5\u180e\u2800")
#: Format, private-use, unassigned, surrogate, separators and combining marks:
#: none can be shown verbatim on a card a person reads.
_HIDDEN_CATEGORIES: Final = frozenset({"Cc", "Cf", "Co", "Cn", "Cs", "Zl", "Zp", "Mn", "Me"})


def _visible_text(text: str) -> bool:
    """Every character renders as itself: NFC, plain spaces only, nothing hidden."""
    if unicodedata.normalize("NFC", text) != text:
        return False
    return all(
        (ch == " " or unicodedata.category(ch) != "Zs")
        and unicodedata.category(ch) not in _HIDDEN_CATEGORIES
        and ch not in _INVISIBLE_LETTERS
        for ch in text
    )


@asynccontextmanager
async def _no_lease() -> AsyncIterator[None]:
    yield


def _row(label: str, value: str) -> dict[str, Any]:
    return {"label": label, "before": None, "after": value}


class DriveStepTool:
    """One approved, bounded drive step. Built per turn by the runtime only when
    the requesting user's companion advertises the internal drive tools."""

    def __init__(
        self,
        *,
        run_step: RunStep,
        record: Record,
        budget: Budget,
        lease: "Callable[[], AbstractAsyncContextManager[None]] | None" = None,
        front: FrontAppBinding | None = None,
    ) -> None:
        self._run_step = run_step
        self._record = record
        self._budget = budget
        self._lease = lease or _no_lease
        #: The turn's window, when `front` is offered; only `stored_args` reads it.
        self._window = front.window() if front is not None else None
        apps = sorted([*DRIVABLE_APPS, *([FRONT] if self._window is not None else [])])
        self._descriptor = ToolDescriptor(
            name="drive.step",
            description=_description(budget),
            consent_summary=_CONSENT,
            params=_params(apps),
            returns={"type": "object"},
            requires_confirmation=True,
            # The loop's own wall-clock budget bounds it; this is the backstop.
            timeout_seconds=budget.max_seconds + 60,
        )

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    def stored_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """What the gate parks: the model's arguments, checked like `_parse`, plus
        — for `front` — the turn's window, copied by Solus code. A model-supplied
        `window` is invalid_args (the model schema has no such field)."""
        parsed = self._check(DriveStepArgs, args)
        if parsed.app != FRONT:
            return parsed.model_dump()
        if self._window is None:
            raise ToolException(
                "drive.step can use the front app only when SOL was summoned over a "
                "window it can drive",
                code=ToolErrorCode.INVALID_ARGS,
            )
        return {**parsed.model_dump(), "window": self._window.model_dump()}

    @classmethod
    def _parse(cls, args: dict[str, Any]) -> DriveStepStoredArgs:
        """Stored arguments, as the card and the run read them."""
        return cls._check(DriveStepStoredArgs, args)

    @staticmethod
    def _check[T: DriveStepArgs](model: type[T], args: dict[str, Any]) -> T:
        try:
            parsed = model.model_validate(args)
        except ValidationError:
            raise ToolException(
                f"drive.step needs an allowlisted app and a one-line intent of at most "
                f"{INTENT_MAX} characters, without < or >",
                code=ToolErrorCode.INVALID_ARGS,
            ) from None
        # Displayed must be executed: the card strips non-printable characters
        # (zero-width, bidi overrides, tag characters), collapses runs of spaces
        # and redacts secret-shaped text, while the loop would get the raw intent.
        # Anything the card would alter is refused outright.
        intent = parsed.intent
        if not _visible_text(intent) or "  " in intent or intent != intent.strip():
            raise ToolException(
                "drive.step's intent must be plain visible text, single-spaced",
                code=ToolErrorCode.INVALID_ARGS,
            )
        if redact_text(intent) != intent:
            raise ToolException(
                "drive.step's intent contains secret-shaped text that cannot be shown "
                "on the approval card; describe the step without it",
                code=ToolErrorCode.INVALID_ARGS,
            )
        if refused_intent(intent):
            raise ToolException(INTENT_REFUSED, code=ToolErrorCode.INVALID_ARGS)
        return parsed

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        parsed = self._parse(args)
        heads_up = _row(
            "Heads up",
            "SOL will move your mouse and type in this window. "
            "Move the mouse or press Esc to stop it.",
        )
        budget = _row("Budget", _budget_label(self._budget))
        if parsed.window is None:
            return [_row("App", _APP_NAMES[parsed.app]), _row("What SOL will do", parsed.intent),
                    budget, heads_up]  # fmt: skip
        # The title is untrusted: a card value the gate cleans and React renders as text.
        return [
            _row("App", parsed.window.name),
            _row("Window", parsed.window.title or "Untitled window"),
            _row("What SOL will do", parsed.intent),
            _row("Screen", "SOL will see this window"),
            budget,
            heads_up,
        ]

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        parsed = self._parse(args)
        window = parsed.window
        target: Target = window if window is not None else DRIVABLE_APPS[parsed.app]
        binding = "project" if window is None else "window"
        app_name = _APP_NAMES[parsed.app] if window is None else window.name
        trail: list[Progress] = []
        sink = current_output.get()

        def on_progress(progress: Progress) -> None:
            trail.append(progress)
            if sink is not None:
                sink.append("stdout", progress_line(progress))

        async with self._lease():
            await self._safe_record(
                "drive.session_started",
                {"app": parsed.app, "binding": binding, "budget": _budget_label(self._budget)},
            )
            try:
                result = await self._run_step(parsed.intent, target, on_progress)
            except asyncio.CancelledError:
                # The registry backstop (or a dropped request) cancelled the
                # step: the audit trail still ends, then cancellation proceeds.
                for progress in trail:
                    # The last one may have been in flight when the step stopped.
                    landed = "cancelled" if progress is trail[-1] else "ok"
                    await self._safe_record(
                        "drive.action",
                        {
                            "index": progress.action,
                            "verb": progress.verb,
                            "result": landed,
                            "binding": binding,
                        },
                    )
                await self._safe_record(
                    "drive.aborted", {"outcome": "cancelled", "code": None, "binding": binding}
                )
                await self._safe_record(
                    "drive.session_ended",
                    {
                        "app": parsed.app,
                        "binding": binding,
                        "actions": len(trail),
                        "outcome": "cancelled",
                        "code": None,
                    },
                )
                raise
        await self._record_outcome(parsed.app, binding, result, trail)
        if result.outcome == "done":
            return {
                "outcome": "done",
                "actions": result.actions,
                "seconds": result.seconds,
                # Model output derived from the screen: redacted like every
                # other persisted or streamed value.
                "summary": redact_text(result.summary),
            }
        sentence = (
            _WINDOW_SAVED
            if result.outcome == "saved" and window is not None
            else (_BY_CODE.get(result.code or "") or _UNFINISHED[result.outcome])
        ).format(code=result.code or "unknown", app=app_name)
        noun = "action" if result.actions == 1 else "actions"
        raise ToolException(
            f"Drive step {sentence} after {result.actions} {noun}.",
            code=ToolErrorCode.TOOL_ERROR,
        )

    async def _record_outcome(
        self, app: str, binding: str, result: StepOutcome, trail: list[Progress]
    ) -> None:
        """ADR-011 events: `app` is kicad|front and `binding` project|window —
        never a bundle id, app name or title (sol-drive.md §2.2)."""
        failed = result.outcome != "done"
        for progress in trail:
            refused = progress.action == result.failed_action
            code = result.code if refused and result.code else "ok"
            await self._safe_record(
                "drive.action",
                {
                    "index": progress.action,
                    "verb": progress.verb,
                    "result": code,
                    "binding": binding,
                },
            )
        if failed:
            await self._safe_record(
                "drive.aborted",
                {"outcome": result.outcome, "code": result.code, "binding": binding},
            )
        await self._safe_record(
            "drive.session_ended",
            {
                "app": app,
                "binding": binding,
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
