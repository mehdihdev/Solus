"""Project-shared workspace layout: docs/api/workspace.md (SOLUSDEV-242)."""

from fastapi import APIRouter
from pydantic import BaseModel

from solus_api.deps import ProjectCtx, SessionDep, require_role
from solus_api.models import Role
from solus_api.services.events import emit_event
from solus_api.services.workspace_layout import (
    WorkspaceLayoutData,
    WorkspaceLayoutInput,
    load_workspace_layout,
    save_workspace_layout,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/workspace-layout")


class WorkspaceLayoutResponse(BaseModel):
    data: WorkspaceLayoutData


@router.get("", response_model=WorkspaceLayoutResponse)
async def get_layout(ctx: ProjectCtx, session: SessionDep) -> WorkspaceLayoutResponse:
    return WorkspaceLayoutResponse(data=await load_workspace_layout(session, ctx.project.id))


@router.put("", response_model=WorkspaceLayoutResponse)
async def put_layout(
    body: WorkspaceLayoutInput, ctx: ProjectCtx, session: SessionDep
) -> WorkspaceLayoutResponse:
    require_role(ctx, Role.MEMBER)
    layout = await save_workspace_layout(session, ctx.project.id, body)
    emit_event(
        session,
        user=ctx.user,
        event_type="workspace.layout_updated",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"position_count": len(layout.positions), "version": layout.version},
    )
    await session.commit()
    return WorkspaceLayoutResponse(data=layout)
