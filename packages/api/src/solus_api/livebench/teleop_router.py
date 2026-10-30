"""Teleoperation routes (SOLUSDEV-319) — API-implementation.md §15 "Teleoperation amendment".

Every route rides `ProjectCtx` (auth + team scope) and resolves sessions through the caller's
project only, so another project's session id is simply not found. Driving routes need the
member role; viewers may only read the current teleop. No SOL tool reaches any of this
(ADR-014 amendment 2026-10-30).
"""

import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from solus_api.bridge.service import ConnectRateLimiter
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, require_role
from solus_api.livebench.sessions import SessionNotFoundError, SessionStillStartingError
from solus_api.livebench.teleop import (
    NotActuatedError,
    PreviewExpiredError,
    TeleopManager,
    TeleopNotReadyError,
    TeleopRunningError,
)
from solus_api.models import Role, User
from solus_api.services.events import emit_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/projects/{project_id}/bench")
#: Per user. The dialog previews ~2x a second; starts and releases are deliberate clicks.
#: Stop is the safety control and is never limited.
PREVIEWS_PER_MINUTE = 240
DRIVES_PER_MINUTE = 60


class TeleopPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    leader_session_id: uuid.UUID
    follower_session_id: uuid.UUID


class TeleopStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: uuid.UUID
    confirm: Literal[True]


class ReleaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal[True]


def _manager(request: Request) -> TeleopManager:
    if request.app.state.bench_local is None:
        raise APIError(503, "source_unavailable", "Local hardware is not available on this server")
    manager: TeleopManager = request.app.state.bench_teleop
    return manager


def _limit(request: Request, ctx: ProjectCtx, kind: str) -> None:
    limits = getattr(request.app.state, "bench_teleop_limits", None)
    if limits is None:
        limits = request.app.state.bench_teleop_limits = {
            "preview": ConnectRateLimiter(PREVIEWS_PER_MINUTE),
            "drive": ConnectRateLimiter(DRIVES_PER_MINUTE),
        }
    if not limits[kind].allow(str(ctx.user.id)):
        raise APIError(429, "rate_limited", "Too many teleoperation requests; slow down")


def _session_errors(exc: Exception) -> APIError:
    if isinstance(exc, SessionStillStartingError):
        return APIError(409, "session_starting", "Session is still starting")
    return APIError(404, "not_found", "Session not found")


@router.post("/teleop/preview")
async def preview_teleop(
    ctx: ProjectCtx, request: Request, body: TeleopPreviewIn
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    _limit(request, ctx, "preview")
    try:
        data = await _manager(request).preview(
            ctx.project.id, body.leader_session_id, body.follower_session_id
        )
    except (SessionNotFoundError, SessionStillStartingError) as exc:
        raise _session_errors(exc) from exc
    return envelope(data)


@router.post("/teleop", status_code=201)
async def start_teleop(
    ctx: ProjectCtx, session: SessionDep, request: Request, body: TeleopStartIn
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    _limit(request, ctx, "drive")
    sessionmaker = request.app.state.sessionmaker
    user_id, team_id, project_id = ctx.user.id, ctx.team.id, ctx.project.id

    async def record_stop(teleop: dict[str, Any]) -> None:
        # The loop can stop on its own (leader unplugged) long after this request returned.
        try:
            async with sessionmaker() as db:
                user = await db.get(User, user_id)
                if user is None:
                    return
                emit_event(
                    db,
                    user=user,
                    event_type="bench.teleop_stopped",
                    team_id=team_id,
                    project_id=project_id,
                    payload={"teleop_id": teleop["id"], "stop_reason": teleop["stop_reason"]},
                )
                await db.commit()
        except Exception:
            logger.exception("teleop stop event failed: project=%s", project_id)

    try:
        teleop = await _manager(request).start(
            ctx.project.id, body.preview_id, record_stop=record_stop
        )
    except PreviewExpiredError as exc:
        raise APIError(410, "preview_expired", "Preview again before starting") from exc
    except TeleopRunningError as exc:
        raise APIError(409, "teleop_running", str(exc)) from exc
    except TeleopNotReadyError as exc:
        raise APIError(
            409, "teleop_not_ready", "Teleoperation is not ready", details=[exc.preview]
        ) from exc
    except (SessionNotFoundError, SessionStillStartingError) as exc:
        raise _session_errors(exc) from exc
    except RuntimeError as exc:
        # The follower could not be held (a servo did not acknowledge): nothing is tracking.
        logger.warning("teleop start failed: project=%s error=%s", ctx.project.id, exc)
        raise APIError(503, "teleop_failed", str(exc)) from exc
    emit_event(
        session,
        user=ctx.user,
        event_type="bench.teleop_started",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={
            "teleop_id": teleop["id"],
            "leader_session_id": teleop["leader"]["session_id"],
            "follower_session_id": teleop["follower"]["session_id"],
            "joints": len(teleop["pairs"]),
        },
    )
    await session.commit()
    return envelope(teleop)


@router.get("/teleop")
async def current_teleop(ctx: ProjectCtx, request: Request) -> dict[str, Any]:
    return envelope(_manager(request).current(ctx.project.id))


@router.post("/teleop/stop")
async def stop_teleop(ctx: ProjectCtx, request: Request) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    return envelope(await _manager(request).stop(ctx.project.id))


@router.post("/sessions/{session_id}/release")
async def release_robot(
    ctx: ProjectCtx, session: SessionDep, request: Request, session_id: uuid.UUID, body: ReleaseIn
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    _limit(request, ctx, "drive")
    try:
        await _manager(request).release(ctx.project.id, session_id)
    except (SessionNotFoundError, SessionStillStartingError) as exc:
        raise _session_errors(exc) from exc
    except TeleopRunningError as exc:
        raise APIError(409, "teleop_running", str(exc)) from exc
    except NotActuatedError as exc:
        raise APIError(409, "not_actuated", str(exc)) from exc
    except RuntimeError as exc:
        # A servo that did not acknowledge torque off: say so, never claim it went limp.
        logger.warning("robot release failed: project=%s session=%s", ctx.project.id, session_id)
        raise APIError(503, "release_failed", str(exc)) from exc
    emit_event(
        session,
        user=ctx.user,
        event_type="bench.robot_released",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"session_id": str(session_id)},
    )
    await session.commit()
    return envelope({"session_id": str(session_id), "released": True})
