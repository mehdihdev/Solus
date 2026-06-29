"""§2.3 Projects — list/create under team, detail/update/delete by id."""

from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import delete, select

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, TeamCtx, require_role
from solus_api.models import Job, Project, Role
from solus_api.schemas import ProjectCreate, ProjectUpdate, serialize_project
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event

team_router = APIRouter(prefix="/api/v1/teams/{team_id}/projects")
project_router = APIRouter(prefix="/api/v1/projects")


@team_router.get("")
async def list_projects(ctx: TeamCtx, session: SessionDep) -> dict[str, Any]:
    rows = await session.scalars(
        select(Project).where(Project.team_id == ctx.team.id).order_by(Project.created_at.desc())
    )
    return envelope([serialize_project(p) for p in rows.all()])


@team_router.post("", status_code=201)
async def create_project(body: ProjectCreate, ctx: TeamCtx, session: SessionDep) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    project = Project(team_id=ctx.team.id, name=body.name, description=body.description)
    session.add(project)
    await session.flush()
    record_activity(
        session,
        team_id=ctx.team.id,
        activity_type="project.created",
        actor_id=ctx.user.id,
        project_id=project.id,
        payload={"name": project.name},
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="project.created",
        team_id=ctx.team.id,
        project_id=project.id,
    )
    await session.commit()
    await session.refresh(project)
    return envelope(serialize_project(project))


@project_router.get("/{project_id}")
async def get_project(ctx: ProjectCtx) -> dict[str, Any]:
    return envelope(serialize_project(ctx.project, detail=True))


@project_router.patch("/{project_id}")
async def update_project(
    body: ProjectUpdate, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(ctx.project, field, value)
    if updates:
        record_activity(
            session,
            team_id=ctx.team.id,
            activity_type="project.updated",
            actor_id=ctx.user.id,
            project_id=ctx.project.id,
            payload={"fields": sorted(updates)},
        )
    await session.commit()
    await session.refresh(ctx.project)
    return envelope(serialize_project(ctx.project, detail=True))


@project_router.delete("/{project_id}", status_code=204)
async def delete_project(
    ctx: ProjectCtx,
    session: SessionDep,
    confirm: Annotated[bool, Query()] = False,
) -> Response:
    require_role(ctx, Role.ADMIN)
    if not confirm:
        raise APIError(400, "confirmation_required", "Pass ?confirm=true to delete this project")
    await session.execute(delete(Job).where(Job.project_id == ctx.project.id))
    record_activity(
        session,
        team_id=ctx.team.id,
        activity_type="project.deleted",
        actor_id=ctx.user.id,
        payload={"name": ctx.project.name},
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="project.deleted",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
    )
    await session.delete(ctx.project)
    await session.commit()
    return Response(status_code=204)
