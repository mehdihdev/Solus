"""§2.3 Projects — list/create under team (with dashboard summary counts),
detail with real graph stats, archive/unarchive (soft delete), delete by id."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SecretStoreDep, SessionDep, TeamCtx, require_role
from solus_api.models import (
    GraphEdge,
    GraphEntity,
    Membership,
    Project,
    ProjectMembership,
    Role,
    Source,
    utcnow,
)
from solus_api.routers.users import delete_projects_cascade
from solus_api.schemas import (
    TEAM_SETTINGS_DEFAULTS,
    ProjectCreate,
    ProjectUpdate,
    serialize_project,
    serialize_source,
)
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event
from solus_api.services.limits import check_can_create_project
from solus_api.services.notifications import notify_team

team_router = APIRouter(prefix="/api/v1/teams/{team_id}/projects")
project_router = APIRouter(prefix="/api/v1/projects")


async def _count_by_project(
    session: SessionDep, model: type[GraphEntity] | type[Source], project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not project_ids:
        return {}
    stmt = select(model.project_id, func.count()).where(model.project_id.in_(project_ids))
    deleted_at = getattr(model, "deleted_at", None)  # Source is not soft-deletable
    if deleted_at is not None:
        stmt = stmt.where(deleted_at.is_(None))
    rows = await session.execute(stmt.group_by(model.project_id))
    return {pid: int(count) for pid, count in rows.all()}


@team_router.get("")
async def list_projects(
    ctx: TeamCtx,
    session: SessionDep,
    include_archived: Annotated[bool, Query()] = False,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict[str, Any]:
    stmt = select(Project).where(Project.team_id == ctx.team.id)
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))
    if cursor:
        stmt = stmt.where(cursor_filter(Project.created_at, Project.id, cursor))
    stmt = stmt.order_by(Project.created_at.desc(), Project.id.desc()).limit(limit + 1)
    visible, meta = page_meta(list((await session.scalars(stmt)).all()), limit)
    # Dashboard summary counts in two grouped queries, not N+1 (FND-04).
    ids = [p.id for p in visible]
    entity_counts = await _count_by_project(session, GraphEntity, ids)
    source_counts = await _count_by_project(session, Source, ids)
    return envelope(
        [
            serialize_project(
                p,
                stats={
                    "entities": entity_counts.get(p.id, 0),
                    "sources": source_counts.get(p.id, 0),
                },
            )
            for p in visible
        ],
        meta=meta,
    )


@team_router.post("", status_code=201)
async def create_project(body: ProjectCreate, ctx: TeamCtx, session: SessionDep) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    await check_can_create_project(session, ctx.user)
    project = Project(
        team_id=ctx.team.id,
        name=body.name,
        description=body.description,
        created_by=ctx.user.id,
    )
    session.add(project)
    await session.flush()
    # ADR-025 dual-source access: auto-grant every current team member a ProjectMembership
    # (the creator included). Later joiners are seeded on accept_invite.
    member_ids = (
        await session.scalars(
            select(Membership.user_id).where(
                Membership.team_id == ctx.team.id, Membership.deleted_at.is_(None)
            )
        )
    ).all()
    session.add_all(ProjectMembership(project_id=project.id, user_id=uid) for uid in member_ids)
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
    # FND-05 seam: the rest of the team learns a project appeared — unless the
    # team turned that off (FND-07 team setting).
    team_settings = {**TEAM_SETTINGS_DEFAULTS, **ctx.team.settings}
    if team_settings["notify_project_created"]:
        await notify_team(
            session,
            team_id=ctx.team.id,
            notification_type="project.created",
            title=f'New project "{project.name}"',
            exclude_user_id=ctx.user.id,
            attrs={"project_id": str(project.id), "team_id": str(ctx.team.id)},
        )
    await session.commit()
    await session.refresh(project)
    return envelope(serialize_project(project))


async def _project_detail(ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    """Detail payload with real graph stats + connected-source summary (§2.3)."""
    entity_count = await session.scalar(
        select(func.count())
        .select_from(GraphEntity)
        .where(GraphEntity.project_id == ctx.project.id, GraphEntity.deleted_at.is_(None))
    )
    relation_count = await session.scalar(
        select(func.count())
        .select_from(GraphEdge)
        .where(GraphEdge.project_id == ctx.project.id, GraphEdge.deleted_at.is_(None))
    )
    sources = (
        await session.scalars(
            select(Source)
            .where(Source.project_id == ctx.project.id)
            .order_by(Source.created_at.desc())
        )
    ).all()
    return serialize_project(
        ctx.project,
        stats={"entities": int(entity_count or 0), "relations": int(relation_count or 0)},
        sources=[serialize_source(s) for s in sources],
    )


@project_router.get("/{project_id}")
async def get_project(ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    return envelope(await _project_detail(ctx, session))


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
    return envelope(await _project_detail(ctx, session))


@project_router.post("/{project_id}/archive")
async def archive_project(ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    """Soft delete (FND-04): the project leaves the default listing but keeps
    its graph and stays reachable by id. Idempotent."""
    require_role(ctx, Role.MEMBER)
    if ctx.project.archived_at is None:
        ctx.project.archived_at = utcnow()
        record_activity(
            session,
            team_id=ctx.team.id,
            activity_type="project.archived",
            actor_id=ctx.user.id,
            project_id=ctx.project.id,
            payload={"name": ctx.project.name},
        )
        emit_event(
            session,
            user=ctx.user,
            event_type="project.archived",
            team_id=ctx.team.id,
            project_id=ctx.project.id,
        )
        await session.commit()
        await session.refresh(ctx.project)
    return envelope(serialize_project(ctx.project))


@project_router.post("/{project_id}/unarchive")
async def unarchive_project(ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    if ctx.project.archived_at is not None:
        ctx.project.archived_at = None
        record_activity(
            session,
            team_id=ctx.team.id,
            activity_type="project.unarchived",
            actor_id=ctx.user.id,
            project_id=ctx.project.id,
            payload={"name": ctx.project.name},
        )
        await session.commit()
        await session.refresh(ctx.project)
    return envelope(serialize_project(ctx.project))


@project_router.delete("/{project_id}", status_code=204)
async def delete_project(
    ctx: ProjectCtx,
    session: SessionDep,
    secret_store: SecretStoreDep,
    confirm: Annotated[bool, Query()] = False,
) -> Response:
    require_role(ctx, Role.OWNER)  # ADR-025: only an OWNER can delete a project
    if not confirm:
        raise APIError(400, "confirmation_required", "Pass ?confirm=true to delete this project")
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
    # Full graph cleanup (incl. stored credentials) — the project row goes too.
    await delete_projects_cascade(session, [ctx.project.id], secret_store)
    await session.commit()
    return Response(status_code=204)
