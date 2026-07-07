"""§2.1 Users & settings — /users/me, /users/me/settings, account deletion."""

import uuid
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.secrets import SecretStore
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, SecretStoreDep, SessionDep, SettingsDep
from solus_api.models import (
    Activity,
    Entity,
    Invite,
    Job,
    Membership,
    Notification,
    OAuthState,
    Project,
    Relation,
    Role,
    SolMode,
    Source,
    Sync,
    Team,
    User,
)
from solus_api.schemas import (
    SettingsUpdate,
    UserUpdate,
    serialize_team_summary,
    serialize_user,
)
from solus_api.services.events import emit_event

router = APIRouter(prefix="/api/v1/users/me")


async def _team_memberships(session: AsyncSession, user: User) -> list[tuple[Team, Membership]]:
    rows = await session.execute(
        select(Team, Membership)
        .join(Membership, Membership.team_id == Team.id)
        .where(Membership.user_id == user.id)
        .order_by(Team.created_at)
    )
    return [(team, membership) for team, membership in rows.all()]


@router.get("")
async def get_me(user: CurrentUser, session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    teams = [
        serialize_team_summary(team, membership.role, settings)
        for team, membership in await _team_memberships(session, user)
    ]
    return envelope(serialize_user(user, teams))


@router.patch("")
async def update_me(
    body: UserUpdate, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await session.commit()
    await session.refresh(user)
    teams = [
        serialize_team_summary(team, membership.role, settings)
        for team, membership in await _team_memberships(session, user)
    ]
    return envelope(serialize_user(user, teams))


async def _sole_owner_blockers(session: AsyncSession, user: User) -> list[uuid.UUID]:
    """Teams the user solely owns that still have other members."""
    blockers: list[uuid.UUID] = []
    for team, membership in await _team_memberships(session, user):
        if membership.role is not Role.OWNER:
            continue
        members = (
            await session.scalars(select(Membership).where(Membership.team_id == team.id))
        ).all()
        owners = [m for m in members if m.role is Role.OWNER]
        if len(owners) == 1 and len(members) > 1:
            blockers.append(team.id)
    return blockers


async def delete_projects_cascade(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    secret_store: SecretStore | None = None,
) -> None:
    """Remove projects and everything hanging off them — jobs plus the graph
    tables (sources/entities/relations/syncs, SOLUSDEV-103) and their stored
    credentials. Explicit, not FK-cascade (portable across PG/SQLite)."""
    if not project_ids:
        return
    sources = (
        await session.execute(
            select(Source.id, Source.secret_ref).where(Source.project_id.in_(project_ids))
        )
    ).all()
    if secret_store is not None:
        for _sid, ref in sources:
            if ref:
                await secret_store.delete(ref)
    source_ids = [sid for sid, _ref in sources]
    if source_ids:
        await session.execute(delete(OAuthState).where(OAuthState.source_id.in_(source_ids)))
    await session.execute(delete(Sync).where(Sync.project_id.in_(project_ids)))
    await session.execute(delete(Relation).where(Relation.project_id.in_(project_ids)))
    await session.execute(delete(Entity).where(Entity.project_id.in_(project_ids)))
    await session.execute(delete(Source).where(Source.project_id.in_(project_ids)))
    await session.execute(delete(Job).where(Job.project_id.in_(project_ids)))
    await session.execute(delete(Project).where(Project.id.in_(project_ids)))


async def delete_team_cascade(
    session: AsyncSession, team_id: uuid.UUID, secret_store: SecretStore | None = None
) -> None:
    """Explicit cascade (portable across PG/SQLite FK enforcement)."""
    project_ids = list(
        (await session.scalars(select(Project.id).where(Project.team_id == team_id))).all()
    )
    await delete_projects_cascade(session, project_ids, secret_store)
    await session.execute(delete(Activity).where(Activity.team_id == team_id))
    await session.execute(delete(Invite).where(Invite.team_id == team_id))
    await session.execute(delete(Membership).where(Membership.team_id == team_id))
    await session.execute(delete(Team).where(Team.id == team_id))


@router.delete("", status_code=204)
async def delete_me(
    user: CurrentUser, session: SessionDep, secret_store: SecretStoreDep
) -> Response:
    blockers = await _sole_owner_blockers(session, user)
    if blockers:
        raise APIError(
            409,
            "ownership_transfer_required",
            "Transfer ownership of your teams before deleting your account",
            [{"team_id": str(team_id)} for team_id in blockers],
        )

    emit_event(session, user=user, event_type="user.deleted")
    for team, _membership in await _team_memberships(session, user):
        members = (
            await session.scalars(select(Membership).where(Membership.team_id == team.id))
        ).all()
        if len(members) == 1:
            await delete_team_cascade(session, team.id, secret_store)
        else:
            await session.execute(
                delete(Membership).where(
                    Membership.team_id == team.id, Membership.user_id == user.id
                )
            )
    await session.execute(delete(Notification).where(Notification.user_id == user.id))
    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()
    return Response(status_code=204)


def _settings_payload(user: User) -> dict[str, Any]:
    return {
        "sol_mode": user.sol_mode.value,
        "data_collection_consent": user.data_collection_consent,
        "onboarding_step": user.onboarding_step,
    }


@router.get("/settings")
async def get_settings_route(user: CurrentUser) -> dict[str, Any]:
    return envelope(_settings_payload(user))


@router.patch("/settings")
async def update_settings(
    body: SettingsUpdate, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    updates = body.model_dump(exclude_unset=True)
    if updates.get("sol_mode") is not None:
        user.sol_mode = SolMode(updates["sol_mode"])
    if updates.get("data_collection_consent") is not None:
        # ADR-011 opt-in/out. Flip before emitting so the event itself honors
        # the new consent state.
        user.data_collection_consent = updates["data_collection_consent"]
    if updates.get("onboarding_step") is not None:
        user.onboarding_step = updates["onboarding_step"]
    emit_event(session, user=user, event_type="settings.updated", payload=updates)
    await session.commit()
    await session.refresh(user)
    return envelope(_settings_payload(user))
