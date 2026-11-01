"""Team-shared bench view routes: docs/api/bench-view.md §2–§3 (SOLUSDEV-319)."""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from solus_api.bridge.service import ConnectRateLimiter
from solus_api.core.errors import APIError
from solus_api.deps import ProjectContext, ProjectCtx, SessionDep, require_role
from solus_api.livebench.view.schemas import BenchViewData, BenchViewPatch, BenchViewResult
from solus_api.livebench.view.service import BenchViewService
from solus_api.models import Role

PATCHES_PER_MINUTE: Final = 120

router = APIRouter(prefix="/api/v1/projects/{project_id}/bench")


class BenchViewResponse(BaseModel):
    data: BenchViewData


class BenchViewWriteResponse(BaseModel):
    data: BenchViewResult


def _writer(request: Request, ctx: ProjectCtx) -> ProjectContext:
    """Role, then rate limit — as a dependency, so both are decided before the body is
    validated (route doc §3.3 check order: 401, 404, 403, 429, 422)."""
    require_role(ctx, Role.MEMBER)
    limiter = getattr(request.app.state, "bench_view_limiter", None)
    if limiter is None:
        limiter = request.app.state.bench_view_limiter = ConnectRateLimiter(PATCHES_PER_MINUTE)
    if not limiter.allow(str(ctx.user.id)):
        raise APIError(429, "rate_limited", "Too many bench view edits; slow down")
    return ctx


WriterCtx = Annotated[ProjectContext, Depends(_writer)]


@router.get("/view", response_model=BenchViewResponse)
async def get_view(ctx: ProjectCtx, session: SessionDep) -> BenchViewResponse:
    return BenchViewResponse(data=await BenchViewService(session).get(ctx.project.id))


@router.patch("/view", response_model=BenchViewWriteResponse)
async def patch_view(
    body: BenchViewPatch, ctx: WriterCtx, session: SessionDep
) -> BenchViewWriteResponse:
    result = await BenchViewService(session).apply(
        project_id=ctx.project.id,
        team_id=ctx.team.id,
        user=ctx.user,
        role=ctx.membership.role if ctx.membership is not None else None,
        ops=body.ops,
        expected_version=body.version,
        undo=body.undo,
        actor="user",
    )
    await session.commit()
    return BenchViewWriteResponse(data=result)
