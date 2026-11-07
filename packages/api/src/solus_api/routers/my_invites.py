"""Invitations to me (SOLUSDEV-319, multi-team Home): list, accept by id, decline.

docs/api/API-implementation.md §4 "Invitations to me". Only EMAIL invites addressed to the
caller's VERIFIED email — the token's, never the stored `users.email` — are reachable
(ADR-009, `VerifiedEmail`): matching on an address the
caller has not proven would let anyone who signs up with someone else's email see, and join,
their teams. Anyone else's invite — and a GitHub-identity invite (ADR-039), which keeps its
token flow — is `404 not_found`, never a hint that it exists.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, SessionDep, VerifiedEmail
from solus_api.models import Invite, InviteStatus, Membership, Team, User, utcnow
from solus_api.routers.invites import ensure_open, join_via_invite
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event
from solus_api.services.notifications import notify_user

router = APIRouter(prefix="/api/v1/users/me/invites")

#: A person has few pending invites; past this the list is cut, newest first.
MAX_LISTED = 50


def _inviter_name(inviter: User | None) -> dict[str, str] | None:
    if inviter is None:
        return None
    return {"name": inviter.display_name or inviter.email.split("@")[0]}


async def _mine(session: AsyncSession, email: str, invite_id: uuid.UUID) -> Invite:
    """The caller's own email invite, else 404 (no existence leak). Row-locked for the update."""
    invite = await session.scalar(
        select(Invite)
        .where(Invite.id == invite_id, Invite.email == email)
        .with_for_update()
    )
    if invite is None:
        raise APIError(404, "not_found", "Invite not found")
    return invite


@router.get("")
async def list_my_invites(
    user: CurrentUser, session: SessionDep, email: VerifiedEmail
) -> dict[str, Any]:
    joined = select(Membership.team_id).where(
        Membership.user_id == user.id, Membership.deleted_at.is_(None)
    )
    rows = (
        await session.execute(
            select(Invite, Team, User)
            .join(Team, Team.id == Invite.team_id)
            .outerjoin(User, User.id == Invite.invited_by)
            .where(
                Invite.email == email,
                Invite.status == InviteStatus.PENDING,
                Invite.expires_at > utcnow(),
                Team.deleted_at.is_(None),
                Invite.team_id.not_in(joined),
            )
            .order_by(Invite.created_at.desc(), Invite.id.desc())
            .limit(MAX_LISTED)
        )
    ).all()
    return envelope(
        [
            {
                "id": invite.id,
                "team": {"id": team.id, "name": team.name},
                "role": invite.role.value,
                "invited_by": _inviter_name(inviter),
                "created_at": invite.created_at,
                "expires_at": invite.expires_at,
            }
            for invite, team, inviter in rows
        ]
    )


@router.post("/{invite_id}/accept")
async def accept_my_invite(
    invite_id: uuid.UUID, user: CurrentUser, session: SessionDep, email: VerifiedEmail
) -> dict[str, Any]:
    invite = await _mine(session, email, invite_id)
    return envelope(await join_via_invite(session, user, invite))


@router.post("/{invite_id}/decline", status_code=204)
async def decline_my_invite(
    invite_id: uuid.UUID, user: CurrentUser, session: SessionDep, email: VerifiedEmail
) -> Response:
    invite = await _mine(session, email, invite_id)
    ensure_open(invite)
    invite.status = InviteStatus.DECLINED
    record_activity(
        session,
        team_id=invite.team_id,
        activity_type="invite.declined",
        actor_id=user.id,
        payload={"email": invite.email},
    )
    emit_event(session, user=user, event_type="invite.declined", team_id=invite.team_id)
    if invite.invited_by is not None and invite.invited_by != user.id:
        notify_user(
            session,
            user_id=invite.invited_by,
            notification_type="invite.declined",
            title=f"{invite.email} declined your invite",
            attrs={"team_id": str(invite.team_id), "email": invite.email},
        )
    await session.commit()
    return Response(status_code=204)
