"""§2.2 Teams — list, create, detail, rename, delete (with safeguards)."""

from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, SecretStoreDep, SessionDep, TeamCtx, require_role
from solus_api.models import Membership, Role, Team, TeamKind
from solus_api.routers.users import delete_team_cascade
from solus_api.schemas import TeamCreate, TeamUpdate, serialize_team_detail
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event
from solus_api.services.limits import check_can_create_team

router = APIRouter(prefix="/api/v1/teams")


async def _member_count(session: SessionDep, team_id: Any) -> int:
    count = await session.scalar(
        select(func.count()).select_from(Membership).where(Membership.team_id == team_id)
    )
    return count or 0


@router.get("")
async def list_teams(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    rows = await session.execute(
        select(Team, Membership.role)
        .join(Membership, Membership.team_id == Team.id)
        .where(Membership.user_id == user.id)
        .order_by(Team.created_at)
    )
    data = [
        {
            "id": team.id,
            "name": team.name,
            "is_personal": team.kind == TeamKind.PERSONAL,
            "plan_status": team.plan_status,
            "role": role.value,
            "created_at": team.created_at,
        }
        for team, role in rows.all()
    ]
    return envelope(data)


@router.post("", status_code=201)
async def create_team(body: TeamCreate, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    await check_can_create_team(session, user)
    team = Team(name=body.name)  # kind defaults to COLLABORATIVE
    session.add(team)
    await session.flush()
    session.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    record_activity(session, team_id=team.id, activity_type="team.created", actor_id=user.id)
    emit_event(session, user=user, event_type="team.created", team_id=team.id)
    await session.commit()
    await session.refresh(team)
    return envelope(serialize_team_detail(team, Role.OWNER, 1))


@router.get("/{team_id}")
async def get_team(ctx: TeamCtx, session: SessionDep) -> dict[str, Any]:
    count = await _member_count(session, ctx.team.id)
    return envelope(serialize_team_detail(ctx.team, ctx.membership.role, count))


@router.patch("/{team_id}")
async def update_team(body: TeamUpdate, ctx: TeamCtx, session: SessionDep) -> dict[str, Any]:
    require_role(ctx, Role.ADMIN)
    updates = body.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"]:
        ctx.team.name = updates["name"]
        record_activity(
            session,
            team_id=ctx.team.id,
            activity_type="team.renamed",
            actor_id=ctx.user.id,
            payload={"name": updates["name"]},
        )
    if body.settings is not None:
        # Full validated snapshot (TeamSettings has defaults for every key),
        # so stored settings are always complete and schema-shaped (FND-07).
        ctx.team.settings = body.settings.model_dump()
        record_activity(
            session,
            team_id=ctx.team.id,
            activity_type="team.settings_updated",
            actor_id=ctx.user.id,
            payload={"settings": ctx.team.settings},
        )
        emit_event(session, user=ctx.user, event_type="team.settings_updated", team_id=ctx.team.id)
    await session.commit()
    await session.refresh(ctx.team)
    count = await _member_count(session, ctx.team.id)
    return envelope(serialize_team_detail(ctx.team, ctx.membership.role, count))


@router.delete("/{team_id}", status_code=204)
async def delete_team(
    ctx: TeamCtx,
    session: SessionDep,
    secret_store: SecretStoreDep,
    confirm: Annotated[bool, Query()] = False,
) -> Response:
    require_role(ctx, Role.OWNER)
    if not confirm:
        raise APIError(400, "confirmation_required", "Pass ?confirm=true to delete this team")
    if ctx.team.kind == TeamKind.PERSONAL:
        raise APIError(409, "personal_team_undeletable", "Personal teams cannot be deleted")
    emit_event(session, user=ctx.user, event_type="team.deleted", team_id=ctx.team.id)
    await delete_team_cascade(session, ctx.team.id, secret_store)
    await session.commit()
    return Response(status_code=204)
