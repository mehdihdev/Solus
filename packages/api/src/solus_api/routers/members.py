"""§2.2 Team members — list, role changes, removal. Last-owner safeguards."""

import uuid
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import SessionDep, TeamCtx, require_role
from solus_api.models import Membership, Role, User
from solus_api.schemas import MemberRoleUpdate, serialize_member
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event

router = APIRouter(prefix="/api/v1/teams/{team_id}/members")


async def _get_target(session: SessionDep, team_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    membership = await session.get(Membership, (team_id, user_id))
    if membership is None:
        raise APIError(404, "not_found", "Member not found")
    return membership


async def _owner_count(session: SessionDep, team_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.team_id == team_id, Membership.role == Role.OWNER)
    )
    return count or 0


@router.get("")
async def list_members(ctx: TeamCtx, session: SessionDep) -> dict[str, Any]:
    rows = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.team_id == ctx.team.id)
        .order_by(Membership.created_at)
    )
    return envelope([serialize_member(m, u) for m, u in rows.all()])


@router.patch("/{user_id}")
async def change_role(
    user_id: uuid.UUID, body: MemberRoleUpdate, ctx: TeamCtx, session: SessionDep
) -> dict[str, Any]:
    require_role(ctx, Role.ADMIN)
    target = await _get_target(session, ctx.team.id, user_id)
    new_role = Role(body.role)

    touches_owner = new_role is Role.OWNER or target.role is Role.OWNER
    if touches_owner and ctx.membership.role is not Role.OWNER:
        raise APIError(403, "forbidden", "Only an owner can grant or revoke ownership")
    if (
        target.role is Role.OWNER
        and new_role is not Role.OWNER
        and await _owner_count(session, ctx.team.id) == 1
    ):
        raise APIError(409, "last_owner", "A team must retain at least one owner")

    target.role = new_role
    record_activity(
        session,
        team_id=ctx.team.id,
        activity_type="member.role_changed",
        actor_id=ctx.user.id,
        payload={"user_id": str(user_id), "role": new_role.value},
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="member.role_changed",
        team_id=ctx.team.id,
        payload={"role": new_role.value},
    )
    await session.commit()
    target_user = await session.get(User, user_id)
    assert target_user is not None
    return envelope(serialize_member(target, target_user))


@router.delete("/{user_id}", status_code=204)
async def remove_member(user_id: uuid.UUID, ctx: TeamCtx, session: SessionDep) -> Response:
    target = await _get_target(session, ctx.team.id, user_id)
    is_self = user_id == ctx.user.id
    if not is_self:
        require_role(ctx, Role.ADMIN)
        if target.role is Role.OWNER and ctx.membership.role is not Role.OWNER:
            raise APIError(403, "forbidden", "Only an owner can remove an owner")
    if target.role is Role.OWNER and await _owner_count(session, ctx.team.id) == 1:
        raise APIError(409, "last_owner", "A team must retain at least one owner")

    await session.delete(target)
    record_activity(
        session,
        team_id=ctx.team.id,
        activity_type="member.left" if is_self else "member.removed",
        actor_id=ctx.user.id,
        payload={"user_id": str(user_id)},
    )
    emit_event(session, user=ctx.user, event_type="member.removed", team_id=ctx.team.id)
    await session.commit()
    return Response(status_code=204)
