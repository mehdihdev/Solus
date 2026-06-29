"""§2.2 Invites — create/list/revoke (team-scoped) and accept (token-scoped).

Inviting onto a personal team flips it to a regular team: the seamless
individual→team upgrade entry point (ADR-015/017).
"""

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import select

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, SessionDep, SettingsDep, TeamCtx, require_role
from solus_api.models import (
    Invite,
    InviteStatus,
    Membership,
    Role,
    User,
    ensure_utc,
    utcnow,
)
from solus_api.schemas import InviteCreate, serialize_invite
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event

team_router = APIRouter(prefix="/api/v1/teams/{team_id}/invites")
accept_router = APIRouter(prefix="/api/v1/invites")


@team_router.get("")
async def list_invites(ctx: TeamCtx, session: SessionDep) -> dict[str, Any]:
    require_role(ctx, Role.ADMIN)
    rows = await session.scalars(
        select(Invite)
        .where(Invite.team_id == ctx.team.id, Invite.status == InviteStatus.PENDING)
        .order_by(Invite.created_at.desc())
    )
    return envelope([serialize_invite(i) for i in rows.all()])


@team_router.post("", status_code=201)
async def create_invite(
    body: InviteCreate, ctx: TeamCtx, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    require_role(ctx, Role.ADMIN)
    email = body.email.lower()

    existing_member = await session.scalar(
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(Membership.team_id == ctx.team.id, User.email == email)
    )
    if existing_member is not None:
        raise APIError(409, "already_member", "That user is already on the team")

    pending = await session.scalar(
        select(Invite).where(
            Invite.team_id == ctx.team.id,
            Invite.email == email,
            Invite.status == InviteStatus.PENDING,
        )
    )
    if pending is not None:
        raise APIError(409, "invite_pending", "An invite for that email is already pending")

    invite = Invite(
        team_id=ctx.team.id,
        email=email,
        role=Role(body.role),
        invited_by=ctx.user.id,
        expires_at=utcnow() + timedelta(days=settings.invite_ttl_days),
    )
    session.add(invite)

    if ctx.team.is_personal:
        # Individual→team upgrade: billing transition, not a data migration (§1.3).
        ctx.team.is_personal = False
        record_activity(
            session, team_id=ctx.team.id, activity_type="team.upgraded", actor_id=ctx.user.id
        )
        emit_event(session, user=ctx.user, event_type="team.upgraded", team_id=ctx.team.id)

    record_activity(
        session,
        team_id=ctx.team.id,
        activity_type="invite.created",
        actor_id=ctx.user.id,
        payload={"email": email, "role": body.role},
    )
    emit_event(session, user=ctx.user, event_type="invite.created", team_id=ctx.team.id)
    await session.commit()
    await session.refresh(invite)
    return envelope(serialize_invite(invite, include_token=True))


@team_router.delete("/{invite_id}", status_code=204)
async def revoke_invite(invite_id: uuid.UUID, ctx: TeamCtx, session: SessionDep) -> Response:
    require_role(ctx, Role.ADMIN)
    invite = await session.scalar(
        select(Invite).where(Invite.id == invite_id, Invite.team_id == ctx.team.id)
    )
    if invite is None:
        raise APIError(404, "not_found", "Invite not found")
    invite.status = InviteStatus.REVOKED
    record_activity(
        session,
        team_id=ctx.team.id,
        activity_type="invite.revoked",
        actor_id=ctx.user.id,
        payload={"email": invite.email},
    )
    await session.commit()
    return Response(status_code=204)


@accept_router.post("/{invite_token}/accept")
async def accept_invite(
    invite_token: str, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    invite = await session.scalar(select(Invite).where(Invite.token == invite_token))
    if invite is None:
        raise APIError(404, "not_found", "Invite not found")
    if invite.status is InviteStatus.REVOKED:
        raise APIError(409, "invite_revoked", "This invite has been revoked")
    if invite.status is InviteStatus.ACCEPTED:
        raise APIError(409, "invite_already_accepted", "This invite was already used")
    if ensure_utc(invite.expires_at) < utcnow():
        raise APIError(410, "invite_expired", "This invite has expired")
    if user.email.lower() != invite.email:
        raise APIError(403, "forbidden", "This invite was issued to a different email")
    if await session.get(Membership, (invite.team_id, user.id)) is not None:
        raise APIError(409, "already_member", "You are already on this team")

    session.add(Membership(team_id=invite.team_id, user_id=user.id, role=invite.role))
    invite.status = InviteStatus.ACCEPTED
    record_activity(
        session,
        team_id=invite.team_id,
        activity_type="invite.accepted",
        actor_id=user.id,
        payload={"email": invite.email},
    )
    emit_event(session, user=user, event_type="invite.accepted", team_id=invite.team_id)
    await session.commit()
    return envelope({"team_id": invite.team_id, "role": invite.role.value})
