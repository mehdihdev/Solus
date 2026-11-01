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

import json
import logging
import math
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.bridge.service import ConnectRateLimiter
from solus_api.core.errors import APIError
from solus_api.deps import live_membership
from solus_api.livebench.sessions import SessionNotFoundError, SessionStillStartingError
from solus_api.livebench.sessions_shared import (
    RUNNER_ABSENT,
    BenchSessionIn,
    emit_session_event,
    resolve_session,
    start_resolved_session,
)
from solus_api.livebench.setpoint import (
    SetpointEventKind,
    SetpointNotFoundError,
    SetpointRefusedError,
    emit_setpoint_event,
)
from solus_api.livebench.teleop import PreviewExpiredError
from solus_api.livebench.teleop_router import DRIVES_PER_MINUTE, PREVIEWS_PER_MINUTE
from solus_api.livebench.view.expression import SignalRef, evaluate, parse_expression
from solus_api.livebench.view.schemas import (
    MAX_OPS,
    DerivedName,
    SetDisplay,
    Unit,
    parse_ops,
)
from solus_api.livebench.view.service import BenchViewService, OpModel
from solus_api.models import (
    ROLE_RANK,
    ConfirmationStatus,
    Project,
    Role,
    ToolConfirmation,
    User,
    utcnow,
)

logger = logging.getLogger("solus.agent.bench_view")

READ, DISPLAY, UPSERT, DELETE = (
    "bench_view.read",
    "bench_view.update_display",
    "bench_view.upsert_derived",
    "bench_view.delete_derived",
)
SESSION_START, SESSION_STOP, SETPOINT = (
    "bench.session_start",
    "bench.session_stop",
    "bench.setpoint",
)

#: route doc §6: 30 setpoint executions a minute per user, in the teleop limiter registry
#: (`app.state.bench_teleop_limits`); each execution also counts as a teleop drive.
SETPOINTS_PER_MINUTE: Final = 30
#: The newest samples read per device for `bench_view.read` values (the evaluator's window cap).
_VALUE_SAMPLES: Final = 2000
_CELL_CAP: Final = 200
_READ_RESULT_CAP: Final = 16_000
_MOTION = "One move, at most {step} per tick; ends at the target or after 5 s"


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


# ── helpers ─────────────────────────────────────────────────────────────────────


def _cell(value: object, cap: int = _CELL_CAP) -> str:
    """One printable line, capped: a card row value from team- or device-authored text."""
    text = "".join(c if c.isprintable() else " " for c in str(value))
    text = " ".join(text.split())
    return text if len(text) <= cap else text[: cap - 1] + "…"


def _uuid(value: object) -> uuid.UUID:
    """A model-supplied id (JSON Schema `format` is not enforced by the registry)."""
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise ToolException("id must be a UUID", code=ToolErrorCode.INVALID_ARGS) from None


def _row(label: str, after: str | None, before: str | None = None) -> dict[str, Any]:
    return {"label": label, "before": before, "after": after}


def _invalid(exc: ValidationError) -> ToolException:
    """Field paths and pydantic's fixed messages only — never the rejected input."""
    parts = [
        f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}"
        for error in exc.errors(include_input=False, include_url=False)[:3]
    ]
    return ToolException("; ".join(parts) or "invalid arguments", code=ToolErrorCode.INVALID_ARGS)


def _api_tool_error(exc: APIError) -> ToolException:
    """The view service's APIError as a tool error (route doc §6). Details are Solus-composed
    (codes, positions, fixed sentences) and never echo the expression."""
    if exc.status_code == 403:
        return ToolException("Requires member role on this team.", code=ToolErrorCode.UNAUTHORIZED)
    if exc.status_code == 404:
        return ToolException(exc.message, code=ToolErrorCode.NOT_FOUND)
    if exc.status_code == 409:
        return ToolException(exc.message, code=ToolErrorCode.TOOL_ERROR, retryable=True)
    if exc.code == "expression_error":
        spans = [
            f"{d['code']} at {d['position']} (length {d['length']}): {d['message']}"
            for d in (exc.details or [])
        ]
        return ToolException(
            "expression_error: " + "; ".join(spans), code=ToolErrorCode.INVALID_ARGS
        )
    if exc.status_code == 422:
        return ToolException(f"{exc.code}: {exc.message}", code=ToolErrorCode.INVALID_ARGS)
    return ToolException(f"{exc.code}: {exc.message}", code=ToolErrorCode.UNAVAILABLE)


def _refusal(exc: ToolException) -> PreviewRefusal:
    return PreviewRefusal(exc.message, code=exc.code)


def _summary_display(ops: Sequence[SetDisplay]) -> str:
    verbs = {
        "pinned": ("Pinned", "Unpinned"),
        "hidden": ("Hid", "Showed"),
        "order": ("Reordered", "Reordered"),
        "unit": ("Changed the unit of", "Reset the unit of"),
        "limits": ("Set limits on", "Reset limits on"),
        "plot_group": ("Grouped", "Ungrouped"),
    }
    counts: dict[str, int] = {}
    for op in ops:
        for name in op.patch.model_fields_set:
            value = getattr(op.patch, name)
            verb = verbs[name][0 if value not in (None, False) else 1]
            counts[verb] = counts.get(verb, 0) + 1
    return "; ".join(f"{verb} {n} signal{'s' if n != 1 else ''}" for verb, n in counts.items())


def _number(value: float | None, unit: str) -> str:
    if value is None or not math.isfinite(value):
        return "unknown"
    return f"{value:.1f} {unit}".strip()


@dataclass(frozen=True)
class BenchScope:
    project_id: uuid.UUID
    team_id: uuid.UUID
    user_id: uuid.UUID


class _Caller:
    """The requesting user inside one tool call: their user row and current team role."""

    def __init__(self, session: AsyncSession, scope: BenchScope) -> None:
        self.session, self.scope = session, scope

    async def user(self) -> User:
        user = await self.session.get(User, self.scope.user_id)
        if user is None:
            raise ToolException("User not found.", code=ToolErrorCode.UNAUTHORIZED)
        return user

    async def role(self) -> Role | None:
        project = await self.session.scalar(
            select(Project.id).where(
                Project.id == self.scope.project_id,
                Project.team_id == self.scope.team_id,
                Project.deleted_at.is_(None),
            )
        )
        if project is None:
            raise ToolException("Project not found.", code=ToolErrorCode.NOT_FOUND)
        membership = await live_membership(self.session, self.scope.team_id, self.scope.user_id)
        return membership.role if membership is not None else None

    async def require_member(self) -> Role:
        role = await self.role()
        if role is None or ROLE_RANK[role] < ROLE_RANK[Role.MEMBER]:
            raise ToolException(
                "Requires member role on this team; viewers can read the bench only.",
                code=ToolErrorCode.UNAUTHORIZED,
            )
        return role


# ── bench view ──────────────────────────────────────────────────────────────────


class BenchViewOperations:
    def __init__(self, session: AsyncSession, scope: BenchScope, state: Any) -> None:
        self.session, self.scope, self.state = session, scope, state
        self.caller = _Caller(session, scope)
        self.service = BenchViewService(session)

    async def read(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.caller.role()  # project scope check; any role reads
        view = (await self.service.get(self.scope.project_id)).model_dump(mode="json")
        if args.get("include_values", True):
            await self._add_latest(view["derived"])
        return view

    async def _add_latest(self, derived: list[dict[str, Any]]) -> None:
        plumbing = getattr(self.state, "telemetry_plumbing", None)
        cache: dict[str, dict[str, list[tuple[float, float]]]] = {}
        for entry in derived:
            entry["latest"] = {"value": None, "at": None}
            if plumbing is None:
                continue
            parsed = parse_expression(entry["expression"])
            series = {ref: await self._series(plumbing, cache, ref) for ref in parsed.refs}
            samples = evaluate(parsed, series)
            if samples:
                at, value = samples[-1]
                entry["latest"] = {
                    "value": value if math.isfinite(value) else None,
                    "at": utc_iso(at),
                }

    async def _series(
        self, plumbing: Any, cache: dict[str, dict[str, list[tuple[float, float]]]], ref: SignalRef
    ) -> list[tuple[float, float]]:
        if ref.device_id not in cache:
            view = await plumbing.get_device_recent(
                self.scope.project_id, ref.device_id, limit=_VALUE_SAMPLES
            )
            cache[ref.device_id] = {
                s.signal: [(p.timestamp.timestamp(), p.value) for p in s.points]
                for s in view.signals
            }
        return cache[ref.device_id].get(ref.signal, [])

    async def _apply(self, ops: Sequence[OpModel]) -> Any:
        role = await self.caller.require_member()
        try:
            result = await self.service.apply(
                project_id=self.scope.project_id,
                team_id=self.scope.team_id,
                user=await self.caller.user(),
                role=role,
                ops=ops,
                expected_version=None,
                actor="sol",
            )
        except APIError as exc:
            raise _api_tool_error(exc) from None
        await self.session.commit()
        return result

    @staticmethod
    def _ops(raw: list[dict[str, Any]]) -> list[OpModel]:
        try:
            return parse_ops(raw)
        except ValidationError as exc:
            raise _invalid(exc) from None
        except APIError as exc:
            raise _api_tool_error(exc) from None

    async def update_display(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.caller.require_member()
        ops = self._ops(list(args["ops"]))
        result = await self._apply(ops)
        return {
            "version": result.version,
            "inverse_ops": [op.model_dump(mode="json") for op in result.inverse_ops],
            "summary": _summary_display([op for op in ops if isinstance(op, SetDisplay)]),
        }

    async def upsert_derived(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.caller.require_member()
        (op,) = self._ops([{**args, "kind": "upsert_derived"}])
        result = await self._apply([op])
        derived_id = result.inverse_ops[0].id
        entry = next(d for d in result.view.derived if d.id == derived_id)
        verb = "Created" if result.inverse_ops[0].kind == "delete_derived" else "Updated"
        return {
            "version": result.version,
            "id": str(derived_id),
            "node_count": entry.node_count,
            "inverse_ops": [op.model_dump(mode="json") for op in result.inverse_ops],
            "summary": f"{verb} derived signal ‹{_cell(entry.name, 64)}›",
        }

    async def delete_preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        await self.caller.require_member()
        view = await self.service.get(self.scope.project_id)
        derived_id = _uuid(args["id"])
        entry = next((d for d in view.derived if d.id == derived_id), None)
        if entry is None:
            raise ToolException("Derived signal not found.", code=ToolErrorCode.NOT_FOUND)
        shown = sum(1 for e in view.display if getattr(e.target, "id", None) == derived_id)
        return [
            _row("Derived signal", None, _cell(entry.name, 64)),
            _row("Expression", None, _cell(entry.expression)),
            _row("Shown in", "removed", f"{shown} display settings"),
        ]

    async def delete_derived(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.caller.require_member()
        ops = self._ops([{"kind": "delete_derived", "id": args["id"]}])
        result = await self._apply(ops)
        return {
            "version": result.version,
            "inverse_ops": [op.model_dump(mode="json") for op in result.inverse_ops],
        }


def utc_iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat()


# ── bench control: sessions ─────────────────────────────────────────────────────


class BenchSessionOperations:
    def __init__(self, session: AsyncSession, scope: BenchScope, state: Any) -> None:
        self.session, self.scope, self.state = session, scope, state
        self.caller = _Caller(session, scope)

    def _local(self) -> Any:
        local = getattr(self.state, "bench_local", None)
        if local is None:
            raise ToolException(
                f"source_unavailable: {RUNNER_ABSENT}", code=ToolErrorCode.UNAVAILABLE
            )
        return local

    async def _resolved(self, args: dict[str, Any]) -> tuple[BenchSessionIn, Any]:
        await self.caller.require_member()
        local = self._local()
        try:
            body = BenchSessionIn.model_validate(args)
        except ValidationError as exc:
            raise _invalid(exc) from None
        try:
            resolved = await resolve_session(
                local,
                self.state.settings,
                self.session,
                self.scope.project_id,
                body,
                self.scope.user_id,
            )
        except APIError as exc:
            raise _api_tool_error(exc) from None
        return body, resolved

    async def start_preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        body, resolved = await self._resolved(args)
        manager = self.state.bench_sessions
        cap = getattr(manager, "_cap", None)
        if cap is not None and len(manager.list(self.scope.project_id, status="active")) >= cap:
            raise ToolException(
                f"too_many_sessions: {cap} sessions already active in this project",
                code=ToolErrorCode.UNAVAILABLE,
            )
        provider = body.config.provider
        target = (
            "Simulator"
            if body.mode == "sim"
            else "Robot"
            if provider in ("robot", "replay")
            else "Device"
        )
        return [
            _row("Action", "Start session"),
            _row("Source", provider),
            _row("Mode", body.mode),
            _row(target, _cell(resolved.label)),
            _row("Window", f"{body.config.window_seconds:g} s"),
        ]

    async def start(self, args: dict[str, Any]) -> dict[str, Any]:
        body, resolved = await self._resolved(args)
        try:
            record = await start_resolved_session(
                self.state.bench_sessions, self.scope.project_id, body, resolved, self.scope.user_id
            )
        except APIError as exc:
            raise _api_tool_error(exc) from None
        await self._emit(record, started=True)
        await self.session.commit()
        return dict(record.model_dump(mode="json"))

    def _record(self, args: dict[str, Any]) -> Any:
        manager = getattr(self.state, "bench_sessions", None)
        if manager is None:
            raise ToolException(
                f"source_unavailable: {RUNNER_ABSENT}", code=ToolErrorCode.UNAVAILABLE
            )
        try:
            record = manager.get(self.scope.project_id, _uuid(args["session_id"]))
        except SessionNotFoundError:
            raise ToolException("Session not found.", code=ToolErrorCode.NOT_FOUND) from None
        if record.status == "starting":
            raise ToolException(
                "session_starting: Session is still starting", code=ToolErrorCode.UNAVAILABLE
            )
        return record

    def check_stop(self, args: dict[str, Any]) -> dict[str, Any]:
        """`stored_args`: an unknown or starting session is refused before parking."""
        self._record(args)
        return args

    async def stop_preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        await self.caller.require_member()
        record = self._record(args)
        return [
            _row("Action", "Stop session"),
            _row("Session", "stopped", _cell(record.label)),
            _row("Provider", None, record.provider),
        ]

    async def stop(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.caller.require_member()
        self._record(args)
        try:
            record = await self.state.bench_sessions.stop(
                self.scope.project_id, _uuid(args["session_id"])
            )
        except SessionNotFoundError:
            raise ToolException("Session not found.", code=ToolErrorCode.NOT_FOUND) from None
        except SessionStillStartingError:
            raise ToolException(
                "session_starting: Session is still starting", code=ToolErrorCode.UNAVAILABLE
            ) from None
        await self._emit(record, started=False)
        await self.session.commit()
        return dict(record.model_dump(mode="json"))

    async def _emit(self, record: Any, *, started: bool) -> None:
        emit_session_event(
            self.session,
            user=await self.caller.user(),
            team_id=self.scope.team_id,
            project_id=self.scope.project_id,
            started=started,
            record=record,
            actor="sol",
        )


# ── bench control: setpoint ─────────────────────────────────────────────────────


def setpoint_limiters(state: Any) -> dict[str, ConnectRateLimiter]:
    """The teleop limiter registry on app.state, gaining a `setpoint` limiter."""
    limits: dict[str, ConnectRateLimiter] | None = getattr(state, "bench_teleop_limits", None)
    if limits is None:
        limits = state.bench_teleop_limits = {
            "preview": ConnectRateLimiter(PREVIEWS_PER_MINUTE),
            "drive": ConnectRateLimiter(DRIVES_PER_MINUTE),
        }
    limits.setdefault("setpoint", ConnectRateLimiter(SETPOINTS_PER_MINUTE))
    return limits


def _joint_not_found() -> ToolException:
    return ToolException("Session or joint not found.", code=ToolErrorCode.NOT_FOUND)


def _setpoint_error(exc: SetpointRefusedError) -> ToolException:
    code = ToolErrorCode.INVALID_ARGS if exc.code == "uncalibrated" else ToolErrorCode.UNAVAILABLE
    return ToolException(str(exc), code=code)


class SetpointOperations:
    def __init__(self, session: AsyncSession, scope: BenchScope, state: Any) -> None:
        self.session, self.scope, self.state = session, scope, state
        self.caller = _Caller(session, scope)

    def _manager(self) -> Any:
        manager = getattr(self.state, "bench_setpoint", None)
        if manager is None or getattr(self.state, "bench_local", None) is None:
            raise SetpointRefusedError("unavailable")
        return manager

    def check(self, args: dict[str, Any]) -> dict[str, Any]:
        """`stored_args`: an unknown session (any other team's included) is `not_found` before
        parking. Without a local bench the preview refuses `unavailable` instead."""
        sessions = getattr(self.state, "bench_sessions", None)
        if sessions is not None and getattr(self.state, "bench_local", None) is not None:
            try:
                sessions.get(self.scope.project_id, _uuid(args["session_id"]))
            except SessionNotFoundError:
                raise ToolException("Session not found.", code=ToolErrorCode.NOT_FOUND) from None
        return args

    async def _facts(self, args: dict[str, Any]) -> dict[str, Any]:
        """A fresh manager preview; refusals are evented and raised as tool errors."""
        await self.caller.require_member()
        try:
            return dict(
                await self._manager().preview(
                    self.scope.project_id,
                    _uuid(args["session_id"]),
                    str(args["joint"]),
                    float(args["target"]),
                )
            )
        except SetpointRefusedError as exc:
            await self._event("refused", exc.unit, exc.clamped, exc.code)
            raise _setpoint_error(exc) from None
        except SetpointNotFoundError:
            raise _joint_not_found() from None
        except ValueError:
            raise ToolException(
                "target must be a finite number", code=ToolErrorCode.INVALID_ARGS
            ) from None

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        facts = await self._facts(args)
        if not await self._already_parked(args):
            await self._event("requested", facts["unit"], facts["clamped"], None)
        unit = str(facts["unit"])
        target = _number(facts["target"], unit)
        if facts["clamped"]:
            requested = _number(facts["requested"], unit)
            target = f"{target} (requested {requested}, clamped to calibrated range)"
        return [
            _row("Robot", _cell(facts["robot"])),
            _row("Joint", _cell(facts["joint"])),
            _row("Current value", _number(facts["current"], unit)),
            _row("Target", target),
            _row("Motion", _MOTION.format(step=_number(facts["max_step"], unit))),
        ]

    async def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.caller.require_member()
        limits = setpoint_limiters(self.state) if self.state is not None else None
        key = str(self.scope.user_id)
        if limits is not None and not (
            limits["setpoint"].allow(key) and limits["drive"].allow(key)
        ):
            logger.info("bench.setpoint rate limited: user=%s", key)
            raise ToolException(
                "rate_limited: too many setpoints; wait a minute",
                code=ToolErrorCode.UNAVAILABLE,
                retryable=True,
            )
        facts = await self._facts(args)
        try:
            move = await self._manager().start(
                self.scope.project_id, uuid.UUID(str(facts["preview_id"]))
            )
        except SetpointRefusedError as exc:
            await self._event("refused", exc.unit or facts["unit"], facts["clamped"], exc.code)
            raise _setpoint_error(exc) from None
        except SetpointNotFoundError:
            raise _joint_not_found() from None
        except PreviewExpiredError:
            raise ToolException(
                "The setpoint preview expired; ask again.",
                code=ToolErrorCode.UNAVAILABLE,
                retryable=True,
            ) from None
        await self._event("applied", move["unit"], move["clamped"], None)
        return {
            "id": move["id"],
            "state": move["state"],
            "target": move["target"],
            "clamped": move["clamped"],
        }

    async def _already_parked(self, args: dict[str, Any]) -> bool:
        """True at decision time (this card's row exists and is pending), so a re-preview
        never counts as a second request."""
        rows = await self.session.scalars(
            select(ToolConfirmation.args).where(
                ToolConfirmation.project_id == self.scope.project_id,
                ToolConfirmation.user_id == self.scope.user_id,
                ToolConfirmation.tool == SETPOINT,
                ToolConfirmation.status == ConfirmationStatus.PENDING,
                ToolConfirmation.expires_at > utcnow(),
            )
        )
        key = json.dumps(args, sort_keys=True)
        return any(json.dumps(row, sort_keys=True) == key for row in rows)

    async def _event(
        self, kind: SetpointEventKind, unit: str | None, clamped: bool | None, code: str | None
    ) -> None:
        user = await self.session.get(User, self.scope.user_id)
        if user is None:
            return
        emit_setpoint_event(
            self.session,
            user=user,
            team_id=self.scope.team_id,
            project_id=self.scope.project_id,
            kind=kind,
            unit=unit,
            clamped=clamped,
            code=code,
        )
        await self.session.commit()


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
                    raise _setpoint_error(exc) from None
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
                    raise _refusal(_setpoint_error(exc)) from None
                except PreviewRefusal:
                    raise
                except ToolException as exc:
                    raise _refusal(exc) from None
                return rows

        def check(args: dict[str, Any]) -> dict[str, Any]:
            assert check_name is not None
            result: dict[str, Any] = getattr(kind(None, scope, state), check_name)(args)  # type: ignore[arg-type]
            return result

        return _GatedBenchTool(descriptor, invoke, preview, check if check_name else None)

    return [bind(descriptor) for descriptor in bench_descriptors()]
