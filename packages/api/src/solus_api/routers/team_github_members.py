"""GET /api/v1/teams/{team_id}/github/members (docs/api/github-orgs.md, ADR-039 section 6).

The linked organization's roster with each person's Solus status. The status never grants
access: it only tells an admin whom to invite. Matching is by numeric GitHub id alone."""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import IntegrationCacheDep, SessionDep, TeamCtx, require_role
from solus_api.extensions.ratelimit import get_or_create_limiter
from solus_api.models import Invite, InviteStatus, Role, TeamKind
from solus_api.services.github_identity import github_ids_for_team_members
from solus_api.services.github_roster import ORGANIZATION, get_roster, page_of
from solus_api.services.team_installations import require_active_installation

router = APIRouter(prefix="/api/v1/teams/{team_id}/github", tags=["github-org-members"])

MEMBERS_PER_MINUTE_PER_USER = 30
_LIMITER = "github_members_limiter"
_WINDOW_SECONDS = 60

SolusStatus = Literal["member", "invited", "not_on_solus"]


def _check_rate(request: Request, user_id: uuid.UUID) -> None:
    limiter = get_or_create_limiter(request.app.state, _LIMITER, _WINDOW_SECONDS)
    if limiter.bump(str(user_id)) > MEMBERS_PER_MINUTE_PER_USER:
        raise APIError(
            429,
            "rate_limited",
            "Too many roster requests; slow down",
            headers={"Retry-After": str(_WINDOW_SECONDS)},
        )


@router.get("/members")
async def list_org_members(
    request: Request,
    ctx: TeamCtx,
    session: SessionDep,
    cache: IntegrationCacheDep,
    cursor: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    require_role(ctx, Role.ADMIN)
    if ctx.team.kind == TeamKind.PERSONAL:
        raise APIError(
            409, "personal_team_unsupported", "Personal teams cannot link an organization"
        )
    inst = await require_active_installation(session, ctx.team.id)
    if inst.account_type != ORGANIZATION:
        raise APIError(
            400, "not_an_organization", "The linked GitHub account is not an organization"
        )
    _check_rate(request, ctx.user.id)

    roster, _ = await get_roster(cache, inst)
    visible, meta = page_of(roster, cursor, limit)
    page_ids = [m.github_id for m in visible]
    member_ids = await github_ids_for_team_members(session, ctx.team.id)
    invited_ids = set(
        (
            await session.scalars(
                select(Invite.github_user_id).where(
                    Invite.team_id == ctx.team.id,
                    Invite.status == InviteStatus.PENDING,
                    Invite.github_user_id.in_(page_ids),
                )
            )
        ).all()
    )

    def status_of(github_id: int) -> SolusStatus:
        if github_id in member_ids:
            return "member"
        return "invited" if github_id in invited_ids else "not_on_solus"

    items = [
        {
            "github_id": m.github_id,
            "github_login": m.github_login,
            "avatar_url": m.avatar_url,
            "solus_status": status_of(m.github_id),
        }
        for m in visible
    ]
    return envelope(items, meta=meta)
