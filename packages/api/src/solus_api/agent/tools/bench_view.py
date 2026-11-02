"""SOL bench tools: the team-shared bench view and bench control (SOLUSDEV-319).

docs/api/bench-view.md §6 (frozen names, args, confirmation, card rows, refusal codes) and §8
(events); docs/architecture/bench-view.md §5–§6; ADR-014 amendment 2026-10-31.

Every tool is built per turn for ONE requesting user in ONE team-scoped project; the role is
read fresh from the team membership on every call (viewer: `unauthorized` before anything is
touched). The view tools call `BenchViewService`, the only writer. Display edits and derived
upserts apply directly and return `inverse_ops` for the turn's Undo chip; deleting a derived
signal, starting or stopping a session, and a setpoint go through the confirmation gate. There
is no teleop tool, no loop tool and no tool that streams commands.

Names, expressions and labels are team- or device-authored data: they reach the model only as
JSON values inside fenced tool results (prompt.tool_result_block), and on cards only as escaped
row values capped to one printable line.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Final

from pydantic import BaseModel, ConfigDict, Field, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.tools.bench_session_tools import BenchSessionOperations
from solus_api.agent.tools.bench_setpoint_tool import (
    SETPOINTS_PER_MINUTE,
    SetpointOperations,
    setpoint_error,
    setpoint_limiters,
)
from solus_api.agent.tools.bench_tools_common import (
    DELETE,
    DISPLAY,
    READ,
    SESSION_START,
    SESSION_STOP,
    SETPOINT,
    UPSERT,
    BenchScope,
    refusal,
)
from solus_api.agent.tools.bench_view_tools import VALUE_SAMPLES, BenchViewOperations
from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.livebench.sessions_shared import BenchSessionIn
from solus_api.livebench.setpoint import SetpointRefusedError
from solus_api.livebench.view.schemas import MAX_OPS, DerivedName, SetDisplay, Unit

__all__ = [
    "SETPOINTS_PER_MINUTE",
    "VALUE_SAMPLES",
    "BenchScope",
    "BenchSessionOperations",
    "BenchViewOperations",
    "SetpointOperations",
    "bench_descriptors",
    "build_bench_view_tools",
    "setpoint_limiters",
]

_READ_RESULT_CAP: Final = 16_000

# ── model-facing argument shapes (strict; the registry validates against their schema) ──


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ReadArgs(_Args):
    include_values: bool = True


class _DisplayArgs(_Args):
    ops: Annotated[list[SetDisplay], Field(min_length=1, max_length=MAX_OPS)]


class _UpsertArgs(_Args):
    id: uuid.UUID | None = None
    name: DerivedName
    expression: Annotated[StrictStr, Field(min_length=1, max_length=512)]
    unit: Unit | None = None


class _DeleteArgs(_Args):
    id: uuid.UUID


class _SessionStopArgs(_Args):
    session_id: uuid.UUID


class _SetpointArgs(_Args):
    session_id: uuid.UUID
    joint: Annotated[StrictStr, Field(min_length=1, max_length=128, pattern=r"^[\x20-\x7E]+$")]
    target: Annotated[float, Field(allow_inf_nan=False)]


def bench_descriptors() -> list[ToolDescriptor]:
    def gated(name: str, description: str, model: type[BaseModel], consent: str) -> ToolDescriptor:
        return ToolDescriptor(
            name=name,
            description=description,
            params=model.model_json_schema(),
            returns={"type": "object"},
            requires_confirmation=True,
            consent_summary=consent,
        )

    def direct(name: str, description: str, model: type[BaseModel]) -> ToolDescriptor:
        return ToolDescriptor(
            name=name,
            description=description,
            params=model.model_json_schema(),
            returns={"type": "object"},
        )

    return [
        ToolDescriptor(
            name=READ,
            description=(
                "List the project's Live Bench derived signals (computed measurements/channels) "
                "and display settings (pinned, hidden, order, units, limits, plot groups), with "
                "each derived signal's latest value when include_values is true."
            ),
            params=_ReadArgs.model_json_schema(),
            returns={"type": "object"},
            result_cap=_READ_RESULT_CAP,
        ),
        direct(
            DISPLAY,
            "Change how signals show on the shared Live Bench (pin, hide, order, unit, fixed "
            "y-axis limits, plot group). Applies at once; the person can Undo it.",
            _DisplayArgs,
        ),
        direct(
            UPSERT,
            "Create or edit a derived signal (a computed measurement/channel shown in Live "
            "Bench), e.g. a constant like 10, or an expression over existing signals such as "
            'sig("<device_id>", "<signal>") - sig("<device_id>", "<other>"), using + - * / and '
            "abs/min/max/clamp/scale/ma/lowpass/deriv/integ. Pass id to edit an existing one. "
            "Applies at once; the person can Undo it.",
            _UpsertArgs,
        ),
        gated(
            DELETE,
            "Delete a derived signal and its display settings (needs the person's approval).",
            _DeleteArgs,
            "Delete a derived signal from the shared Live Bench view.",
        ),
        gated(
            SESSION_START,
            "Start a Live Bench session (simulator or real robot); needs the person's approval.",
            BenchSessionIn,
            "Start a Live Bench session.",
        ),
        gated(
            SESSION_STOP,
            "Stop a running Live Bench session; needs the person's approval.",
            _SessionStopArgs,
            "Stop a Live Bench session.",
        ),
        gated(
            SETPOINT,
            "Move ONE joint of a connected robot to a target (in the joint's calibrated unit), "
            "as one bounded move; needs the person's approval for every move.",
            _SetpointArgs,
            "Move one robot joint once to the target shown.",
        ),
    ]


# ── assembly ────────────────────────────────────────────────────────────────────


class _GatedBenchTool(InProcessTool):
    """A gated bench tool: never parked without its complete rows."""

    requires_complete_preview = True

    def __init__(
        self,
        descriptor: ToolDescriptor,
        handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        preview: Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]],
        check: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(descriptor, handler, preview)
        if check is not None:
            self.stored_args = check


_Ops = BenchViewOperations | BenchSessionOperations | SetpointOperations
_HANDLERS: Final[dict[str, tuple[type[_Ops], str, str | None, str | None]]] = {
    # name: (operations class, invoke method, preview method, stored_args check)
    READ: (BenchViewOperations, "read", None, None),
    DISPLAY: (BenchViewOperations, "update_display", None, None),
    UPSERT: (BenchViewOperations, "upsert_derived", None, None),
    DELETE: (BenchViewOperations, "delete_derived", "delete_preview", None),
    SESSION_START: (BenchSessionOperations, "start", "start_preview", None),
    SESSION_STOP: (BenchSessionOperations, "stop", "stop_preview", "check_stop"),
    SETPOINT: (SetpointOperations, "execute", "preview", "check"),
}


def build_bench_view_tools(
    session_factory: async_sessionmaker[AsyncSession],
    scope: BenchScope,
    state: Any | None,
) -> list[InProcessTool]:
    """Metadata is pure; every invoke/preview opens its own short-lived session. `state` is
    the app state (`bench_local`, `bench_sessions`, `bench_setpoint`, `telemetry_plumbing`,
    `settings`); None (no app state wired) refuses the control tools as unavailable."""

    def bind(descriptor: ToolDescriptor) -> InProcessTool:
        kind, invoke_name, preview_name, check_name = _HANDLERS[descriptor.name]

        async def invoke(args: dict[str, Any]) -> dict[str, Any]:
            async with session_factory() as session:
                try:
                    result: dict[str, Any] = await getattr(
                        kind(session, scope, state), invoke_name
                    )(args)
                except SetpointRefusedError as exc:
                    raise setpoint_error(exc) from None
                return result

        if preview_name is None:
            return InProcessTool(descriptor, invoke)

        async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
            async with session_factory() as session:
                try:
                    rows: list[dict[str, Any]] = await getattr(
                        kind(session, scope, state), preview_name
                    )(args)
                except SetpointRefusedError as exc:
                    raise refusal(setpoint_error(exc)) from None
                except PreviewRefusal:
                    raise
                except ToolException as exc:
                    raise refusal(exc) from None
                return rows

        def check(args: dict[str, Any]) -> dict[str, Any]:
            assert check_name is not None
            result: dict[str, Any] = getattr(kind(None, scope, state), check_name)(args)  # type: ignore[arg-type]
            return result

        return _GatedBenchTool(descriptor, invoke, preview, check if check_name else None)

    return [bind(descriptor) for descriptor in bench_descriptors()]
