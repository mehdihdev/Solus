"""§2.1 Users & settings — /users/me, /users/me/settings, account deletion."""

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing import credits
from solus_api.connectors.secrets import SecretStore
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import (
    TRIAL_DAYS,
    CurrentUser,
    RequireVerified,
    SecretStoreDep,
    SessionDep,
    SettingsDep,
    SupabaseAdminDep,
)
from solus_api.models import (
    Activity,
    CreditBalance,
    CreditLedger,
    CreditTxnType,
    DeletedAccount,
    GraphEdge,
    GraphEntity,
    Invite,
    Job,
    Membership,
    Notification,
    NotificationType,
    OAuthState,
    Project,
    Role,
    SolMode,
    Source,
    Subscription,
    SubscriptionStatus,
    Sync,
    Team,
    User,
    default_limits,
    utcnow,
)
from solus_api.schemas import (
    CreditBalanceView,
    SettingsUpdate,
    SubscriptionRead,
    SubscriptionUpdate,
    UserUpdate,
    serialize_team_summary,
    serialize_user,
)
from solus_api.services.events import emit_event
from solus_api.services.notifications import notify_team

router = APIRouter(prefix="/api/v1/users/me")


async def _team_memberships(session: AsyncSession, user: User) -> list[tuple[Team, Membership]]:
    rows = await session.execute(
        select(Team, Membership)
        .join(Membership, Membership.team_id == Team.id)
        .where(Membership.user_id == user.id, Membership.deleted_at.is_(None))
        .order_by(Team.created_at)
    )
    return [(team, membership) for team, membership in rows.all()]


async def _live_members(session: AsyncSession, team_id: uuid.UUID) -> list[Membership]:
    """Live (non-soft-deleted) members of a team — the set that counts for the
    sole-owner guard and the leave-vs-cascade decision (SOLUSDEV-82 sec review M1)."""
    rows = await session.scalars(
        select(Membership).where(Membership.team_id == team_id, Membership.deleted_at.is_(None))
    )
    return list(rows.all())


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
    updates = body.model_dump(exclude_unset=True)
    if "name" in updates:
        user.display_name = updates["name"]
    if "avatar_url" in updates:
        user.avatar_url = updates["avatar_url"]
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
        members = await _live_members(session, team.id)
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
    await session.execute(delete(GraphEdge).where(GraphEdge.project_id.in_(project_ids)))
    await session.execute(delete(GraphEntity).where(GraphEntity.project_id.in_(project_ids)))
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


async def _forfeit_credits(session: AsyncSession, user: User) -> None:
    """Forfeit the user's credits on deletion (ADR-024). The append-only ledger is
    preserved (its user_id is nulled by the FK on delete); a forfeiture ADJUSTMENT
    entry records the zeroing, retaining the user id in `attrs`. The cached balance
    row is removed."""
    balance = await session.scalar(select(CreditBalance).where(CreditBalance.user_id == user.id))
    current = balance.balance if balance is not None else 0
    if current:
        session.add(
            CreditLedger(
                user_id=user.id,
                amount=-current,
                type=CreditTxnType.ADJUSTMENT,
                balance_after=0,
                attrs={"reason": "account_deleted", "user_id": str(user.id)},
            )
        )
    if balance is not None:
        await session.delete(balance)


@router.delete("", status_code=204)
async def delete_me(
    user: CurrentUser,
    session: SessionDep,
    secret_store: SecretStoreDep,
    supabase_admin: SupabaseAdminDep,
    _verified: RequireVerified,
) -> Response:
    blockers = await _sole_owner_blockers(session, user)
    if blockers:
        raise APIError(
            409,
            "ownership_transfer_required",
            "Transfer ownership of your teams before deleting your account",
            [{"team_id": str(team_id)} for team_id in blockers],
        )

    display = user.display_name or user.email.split("@")[0] or "A teammate"
    emit_event(session, user=user, event_type="user.deleted")
    for team, _membership in await _team_memberships(session, user):
        members = await _live_members(session, team.id)
        if len(members) == 1:
            await delete_team_cascade(session, team.id, secret_store)
        else:
            # Let the remaining members know a teammate left before we drop the row.
            await notify_team(
                session,
                team_id=team.id,
                notification_type=NotificationType.MEMBER_LEFT,
                title=f"{display} left {team.name}",
                exclude_user_id=user.id,
                attrs={"team_id": str(team.id)},
            )
            await session.execute(
                delete(Membership).where(
                    Membership.team_id == team.id, Membership.user_id == user.id
                )
            )
    await _forfeit_credits(session, user)
    # Tombstone the identity so a still-valid token cannot re-provision (durable delete).
    session.add(DeletedAccount(supabase_user_id=user.supabase_user_id))
    await session.execute(delete(Notification).where(Notification.user_id == user.id))
    supabase_user_id = user.supabase_user_id
    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()
    # Best-effort remote revoke AFTER the local commit: kills the Supabase session /
    # auth user. A failure here is logged, not fatal — the tombstone already blocks
    # re-provision and local data is gone.
    await supabase_admin.delete_user(supabase_user_id)
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


async def _live_subscription(session: AsyncSession, user: User) -> Subscription:
    sub = await session.scalar(
        select(Subscription).where(
            Subscription.user_id == user.id, Subscription.deleted_at.is_(None)
        )
    )
    if sub is None:
        raise APIError(404, "not_found", "No subscription")
    return sub


@router.get("/subscription")
async def get_subscription(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    sub = await _live_subscription(session, user)
    return envelope(SubscriptionRead.model_validate(sub).model_dump(mode="json"))


@router.patch("/subscription")
async def update_subscription(
    body: SubscriptionUpdate, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    """Pick/change the plan during onboarding: (re)starts a 14-day trial of the chosen plan
    with that plan's limits (ADR-032). Enforcement reads `limits`; real billing is deferred."""
    sub = await _live_subscription(session, user)
    sub.plan = body.plan
    sub.limits = default_limits(body.plan)
    sub.status = SubscriptionStatus.TRIALING
    sub.expires_at = utcnow() + timedelta(days=TRIAL_DAYS)
    emit_event(
        session, user=user, event_type="subscription.updated", payload={"plan": body.plan.value}
    )
    await session.commit()
    await session.refresh(sub)
    return envelope(SubscriptionRead.model_validate(sub).model_dump(mode="json"))


@router.get("/credits")
async def get_credits(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """Current credit balance (ADR-024). Always answerable — 0 before any ledger row
    exists. The desktop Billing screen reads this to reflect credit-pack purchases."""
    balance = await credits.get_balance(session, user.id)
    return envelope(CreditBalanceView(user_id=user.id, balance=balance).model_dump(mode="json"))
