"""Application status monitoring; never starts or modifies a simulation."""

from typing import Any

from fastapi import APIRouter, Request

from solus_api.agent.runtime import _owned_isaac_tools
from solus_api.core.responses import envelope
from solus_api.deps import BridgeSessionsDep, ProjectCtx, SessionMakerDep, SettingsDep
from solus_api.extensions.ratelimit import get_or_create_limiter, rate_limited_response
from solus_api.services.isaac_connection import (
    IsaacConnectionEnvelope,
    IsaacConnectionStatus,
    observe_connection,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/isaac")


@router.get("/connection-status", response_model=IsaacConnectionEnvelope)
async def connection_status(
    request: Request,
    ctx: ProjectCtx,
    bridge: BridgeSessionsDep,
    sessionmaker: SessionMakerDep,
    settings: SettingsDep,
) -> Any:
    limiter = get_or_create_limiter(request.app.state, "isaac_connection_limiter", 60)
    if limiter.bump(f"{ctx.user.id}:{ctx.project.id}") > 20:
        return rate_limited_response("Too many application status checks; wait a minute", 60)
    scope = (ctx.user.id, ctx.team.id, ctx.project.id)
    captured = bridge.get(*scope)
    if captured is None:
        return envelope(IsaacConnectionStatus().model_dump())
    tools = _owned_isaac_tools(
        sessionmaker,
        ctx.project.id,
        bridge,
        ctx.user.id,
        ctx.team.id,
        settings.bridge_tool_call_max_bytes,
    )
    result = await observe_connection(bridge, scope, captured, tools)
    return envelope(result.model_dump())
