"""Per-user plan-limit enforcement (ADR-023/032, SOLUSDEV-72 Decisions C-E).

Every check is against the ACTING USER'S OWN subscription and reads `limits` as DATA
(null / absent key = unlimited) — NEVER branches on plan name. The count and the caller's
insert run in the SAME transaction, and the acting user's subscription row is locked
`FOR UPDATE`, so a double-click can't slip past the limit (a limit that races is a limit that
leaks). The personal team is always exempt from the team count.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.models import (
    Membership,
    Project,
    Source,
    SourceStatus,
    Subscription,
    Team,
    TeamKind,
    User,
)

_UPGRADE_URL = "/settings/billing"
_TEAMS_URL = "/settings/teams"


async def _locked_limits(session: AsyncSession, user_id: uuid.UUID) -> dict[str, object]:
    """The user's subscription limits, with the row locked `FOR UPDATE` so the check and the
    caller's insert serialize within this transaction. No subscription → not-yet-allowed
    (defensive: onboarding provisions one, so this is a safety net, not the normal path)."""
    sub = await session.scalar(
        select(Subscription)
        .where(Subscription.user_id == user_id, Subscription.deleted_at.is_(None))
        .with_for_update()
    )
    if sub is None:
        raise APIError(
            402, "subscription_required", "Choose a plan to finish onboarding before creating this."
        )
    return sub.limits


def _limit(limits: dict[str, object], key: str) -> int | None:
    """The numeric cap for a key, or None (unlimited) when the key is absent or explicitly null."""
    value = limits.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _limit_error(limit: str, current: int, cap: int, message: str) -> APIError:
    return APIError(
        409,
        "plan_limit_reached",
        message,
        [
            {
                "limit": limit,
                "current": current,
                "max": cap,
                "upgrade": _UPGRADE_URL,
                "manage_teams": _TEAMS_URL,
            }
        ],
    )


async def _count_collaborative_teams(session: AsyncSession, user_id: uuid.UUID) -> int:
    # COLLABORATIVE memberships only — the auto-provisioned PERSONAL team is always exempt.
    count = await session.scalar(
        select(func.count())
        .select_from(Membership)
        .join(Team, Team.id == Membership.team_id)
        .where(
            Membership.user_id == user_id,
            Membership.deleted_at.is_(None),
            Team.kind == TeamKind.COLLABORATIVE,
            Team.deleted_at.is_(None),
        )
    )
    return count or 0


async def check_can_create_team(session: AsyncSession, user: User) -> None:
    cap = _limit(await _locked_limits(session, user.id), "max_teams")
    if cap is None:
        return
    current = await _count_collaborative_teams(session, user.id)
    if current >= cap:
        raise _limit_error(
            "max_teams",
            current,
            cap,
            "You're at your collaborative-team limit. Leave a team or upgrade your plan.",
        )


async def check_can_accept_team_invite(session: AsyncSession, invitee: User) -> None:
    """Cross-plan block: the INVITEE's own collaborative-team count vs their limit, at accept."""
    await check_can_create_team(session, invitee)


async def check_can_create_project(session: AsyncSession, user: User) -> None:
    cap = _limit(await _locked_limits(session, user.id), "max_projects")
    if cap is None:
        return
    current = await session.scalar(
        select(func.count())
        .select_from(Project)
        .where(Project.created_by == user.id, Project.deleted_at.is_(None))
    )
    if (current or 0) >= cap:
        raise _limit_error(
            "max_projects",
            current or 0,
            cap,
            "You're at your project limit. Delete a project or upgrade your plan.",
        )


async def check_can_add_integration(session: AsyncSession, user: User) -> None:
    cap = _limit(await _locked_limits(session, user.id), "max_integrations")
    if cap is None:
        return
    current = await session.scalar(
        select(func.count())
        .select_from(Source)
        .where(Source.created_by == user.id, Source.status != SourceStatus.DISCONNECTED)
    )
    if (current or 0) >= cap:
        raise _limit_error(
            "max_integrations",
            current or 0,
            cap,
            "You're at your integration limit. Disconnect a source or upgrade your plan.",
        )
