"""§2.2 Invites — create/list/revoke (team-scoped) and accept (token-scoped).

Inviting from a personal team spins up a new COLLABORATIVE team and issues the invite there:
personal teams stay solo-only and billing-exempt (ADR-032, SOLUSDEV-72 Decisions C-E).
"""

import uuid
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import (
    CurrentUser,
    RequireVerified,
    SessionDep,
    SettingsDep,
    TeamCtx,
    live_membership,
    require_role,
)
from solus_api.models import (
    Invite,
    InviteStatus,
    Membership,
    Project,
    ProjectMembership,
    Role,
    Team,
    TeamKind,
    User,
    ensure_utc,
    utcnow,
)
from solus_api.schemas import InviteCreate, serialize_invite
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event
from solus_api.services.limits import check_can_accept_team_invite, check_can_create_team
from solus_api.services.notifications import notify_user

team_router = APIRouter(prefix="/api/v1/teams/{team_id}/invites")
accept_router = APIRouter(prefix="/api/v1/invites")


@team_router.get("")
async def list_invites(
    ctx: TeamCtx,
    session: SessionDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    require_role(ctx, Role.ADMIN)
    stmt = (
        select(Invite)
        .where(Invite.team_id == ctx.team.id, Invite.status == InviteStatus.PENDING)
        .order_by(Invite.created_at.desc(), Invite.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        stmt = stmt.where(cursor_filter(Invite.created_at, Invite.id, cursor))
    visible, meta = page_meta(list((await session.scalars(stmt)).all()), limit)
    return envelope([serialize_invite(i) for i in visible], meta=meta)


@team_router.post("", status_code=201)
async def create_invite(
    body: InviteCreate,
    ctx: TeamCtx,
    session: SessionDep,
    settings: SettingsDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    require_role(ctx, Role.ADMIN)
    email = body.email.lower()

    # Personal teams stay solo-only (ADR-032). To collaborate, spin up a COLLABORATIVE team
    # (counts toward the acting user's team limit) and issue the invite there — the personal
    # team and its solo projects are left intact.
    target_team = ctx.team
    if ctx.team.kind == TeamKind.PERSONAL:
        await check_can_create_team(session, ctx.user)
        display = ctx.user.email.split("@")[0] or "New"
        target_team = Team(name=f"{display}'s Team", kind=TeamKind.COLLABORATIVE)
        session.add(target_team)
        await session.flush()
        session.add(Membership(team_id=target_team.id, user_id=ctx.user.id, role=Role.OWNER))
        record_activity(
            session, team_id=target_team.id, activity_type="team.created", actor_id=ctx.user.id
        )
        emit_event(session, user=ctx.user, event_type="team.created", team_id=target_team.id)

    existing_member = await session.scalar(
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(Membership.team_id == target_team.id, User.email == email)
    )
    if existing_member is not None:
        raise APIError(409, "already_member", "That user is already on the team")

    pending = await session.scalar(
        select(Invite).where(
            Invite.team_id == target_team.id,
            Invite.email == email,
            Invite.status == InviteStatus.PENDING,
        )
    )
    if pending is not None:
        raise APIError(409, "invite_pending", "An invite for that email is already pending")

    invite = Invite(
        team_id=target_team.id,
        email=email,
        role=Role(body.role),
        invited_by=ctx.user.id,
        expires_at=utcnow() + timedelta(days=settings.invite_ttl_days),
    )
    session.add(invite)
    record_activity(
        session,
        team_id=target_team.id,
        activity_type="invite.created",
        actor_id=ctx.user.id,
        payload={"email": email, "role": body.role},
    )
    emit_event(session, user=ctx.user, event_type="invite.created", team_id=target_team.id)
    await session.flush()  # assign the invite id/token before notifying

    # FND-01: the invitation rides the existing notification path. An invitee
    # with an account gets it in-app; the token is theirs to receive (it is
    # exactly what the invite email would deliver). Email delivery, when built,
    # hangs off this same notification row.
    invitee = await session.scalar(select(User).where(User.email == email))
    if invitee is not None:
        notify_user(
            session,
            user_id=invitee.id,
            notification_type="team.invite",
            title=f'You\'ve been invited to join "{target_team.name}"',
            attrs={
                "team_id": str(target_team.id),
                "invite_id": str(invite.id),
                "role": body.role,
                "token": invite.token,
            },
        )
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
    if await live_membership(session, invite.team_id, user.id) is not None:
        raise APIError(409, "already_member", "You are already on this team")
    # Cross-plan block (ADR-032): the INVITEE's own collaborative-team count vs their limit.
    await check_can_accept_team_invite(session, user)

    session.add(Membership(team_id=invite.team_id, user_id=user.id, role=invite.role))
    invite.status = InviteStatus.ACCEPTED
    # Dual-source access (ADR-025): grant the joiner every existing team project they don't
    # already have a live share for. A re-invite after removal (tombstoned rows) or a prior
    # direct share keeps its row — seeding a duplicate would violate the (project_id, user_id)
    # live-unique index.
    team_project_ids = set(
        (
            await session.scalars(
                select(Project.id).where(
                    Project.team_id == invite.team_id, Project.deleted_at.is_(None)
                )
            )
        ).all()
    )
    already_shared = set(
        (
            await session.scalars(
                select(ProjectMembership.project_id).where(
                    ProjectMembership.user_id == user.id,
                    ProjectMembership.deleted_at.is_(None),
                )
            )
        ).all()
    )
    session.add_all(
        ProjectMembership(project_id=pid, user_id=user.id)
        for pid in team_project_ids - already_shared
    )
    record_activity(
        session,
        team_id=invite.team_id,
        activity_type="invite.accepted",
        actor_id=user.id,
        payload={"email": invite.email},
    )
    emit_event(session, user=user, event_type="invite.accepted", team_id=invite.team_id)
    if invite.invited_by is not None and invite.invited_by != user.id:
        notify_user(
            session,
            user_id=invite.invited_by,
            notification_type="invite.accepted",
            title=f"{invite.email} accepted your invite",
            attrs={"team_id": str(invite.team_id), "email": invite.email},
        )
    await session.commit()
    return envelope({"team_id": invite.team_id, "role": invite.role.value})
