"""SOL `bench.setpoint` operations (SOLUSDEV-319): docs/api/bench-view.md §6.1 card rows, §6.2
refusals, §8 events. Executions count against the setpoint and teleop drive limiters; card
previews (park and decision-time re-render) against the teleop preview limiter."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.tools.bench_tools_common import (
    SETPOINT,
    BenchScope,
    Caller,
    as_uuid,
    cell,
    number,
    rate_limited,
    row,
)
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.service import ConnectRateLimiter
from solus_api.livebench.sessions import SessionNotFoundError
from solus_api.livebench.setpoint import (
    SetpointEventKind,
    SetpointNotFoundError,
    SetpointRefusedError,
    emit_setpoint_event,
)
from solus_api.livebench.teleop import PreviewExpiredError
from solus_api.livebench.teleop_router import DRIVES_PER_MINUTE, PREVIEWS_PER_MINUTE
from solus_api.models import ConfirmationStatus, ToolConfirmation, User, utcnow

logger = logging.getLogger("solus.agent.bench_view")

#: route doc §6: 30 setpoint executions a minute per user, in the teleop limiter registry
#: (`app.state.bench_teleop_limits`); each execution also counts as a teleop drive.
SETPOINTS_PER_MINUTE: Final = 30
_MOTION = "One move, at most {step} per tick; ends at the target or after 5 s"


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


def setpoint_error(exc: SetpointRefusedError) -> ToolException:
    code = ToolErrorCode.INVALID_ARGS if exc.code == "uncalibrated" else ToolErrorCode.UNAVAILABLE
    return ToolException(str(exc), code=code)


class SetpointOperations:
    def __init__(self, session: AsyncSession, scope: BenchScope, state: Any) -> None:
        self.session, self.scope, self.state = session, scope, state
        self.caller = Caller(session, scope)

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
                sessions.get(self.scope.project_id, as_uuid(args["session_id"]))
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
                    as_uuid(args["session_id"]),
                    str(args["joint"]),
                    float(args["target"]),
                )
            )
        except SetpointRefusedError as exc:
            await self._event("refused", exc.unit, exc.clamped, exc.code)
            raise setpoint_error(exc) from None
        except SetpointNotFoundError:
            raise _joint_not_found() from None
        except ValueError:
            raise ToolException(
                "target must be a finite number", code=ToolErrorCode.INVALID_ARGS
            ) from None

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        await self.caller.require_member()
        if self.state is not None:
            key = str(self.scope.user_id)
            rate_limited(setpoint_limiters(self.state)["preview"], key, "too many previews")
        facts = await self._facts(args)
        if not await self._already_parked(args):
            await self._event("requested", facts["unit"], facts["clamped"], None)
        unit = str(facts["unit"])
        target = number(facts["target"], unit)
        if facts["clamped"]:
            requested = number(facts["requested"], unit)
            target = f"{target} (requested {requested}, clamped to calibrated range)"
        return [
            row("Robot", cell(facts["robot"])),
            row("Joint", cell(facts["joint"])),
            row("Current value", number(facts["current"], unit)),
            row("Target", target),
            row("Motion", _MOTION.format(step=number(facts["max_step"], unit))),
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
            raise setpoint_error(exc) from None
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
        return any(json.dumps(stored, sort_keys=True) == key for stored in rows)

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
