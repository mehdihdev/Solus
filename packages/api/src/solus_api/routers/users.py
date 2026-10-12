"""§2.1 Users & settings — /users/me, /users/me/settings, account deletion."""

import uuid
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.billing import credits, usage
from solus_api.billing.development import is_development_unlimited
from solus_api.bridge.service import ConnectRateLimiter
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import (
    CurrentUser,
    IntegrationCacheDep,
    RequireVerified,
    SecretStoreDep,
    SessionDep,
    SettingsDep,
    StripeGatewayDep,
    SupabaseAdminDep,
)
from solus_api.models import (
    PanelBinding,
    PanelPairing,
    SolMode,
    Subscription,
    SubscriptionStatus,
    User,
    default_limits,
    ensure_utc,
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
from solus_api.services.account_deletion import (
    AccountDeletionService,
    OwnershipTransferRequired,
    team_memberships,
)
from solus_api.services.events import emit_event

router = APIRouter(prefix="/api/v1/users/me")


@router.get("")
async def get_me(user: CurrentUser, session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    teams = [
        serialize_team_summary(team, membership.role, settings)
        for team, membership in await team_memberships(session, user)
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
        for team, membership in await team_memberships(session, user)
    ]
    return envelope(serialize_user(user, teams))


@router.delete("", status_code=204)
async def delete_me(
    user: CurrentUser,
    session: SessionDep,
    secret_store: SecretStoreDep,
    supabase_admin: SupabaseAdminDep,
    cache: IntegrationCacheDep,
    gateway: StripeGatewayDep,
    _verified: RequireVerified,
) -> Response:
    """Self-service deletion. Never accepts `ownership_transfers` (staff-only, SOLUSDEV-314)."""
    service = AccountDeletionService(
        session,
        secret_store=secret_store,
        supabase_admin=supabase_admin,
        cache=cache,
        gateway=gateway,
    )
    try:
        await service.delete_account(user)
    except OwnershipTransferRequired as exc:
        raise APIError(
            409,
            exc.code,
            "Transfer ownership of your teams before deleting your account",
            [{"team_id": str(team_id)} for team_id in exc.team_ids],
        ) from exc
    return Response(status_code=204)


def _settings_payload(user: User) -> dict[str, Any]:
    return {
        "sol_mode": user.sol_mode.value,
        "sol_custom_instruction": user.sol_custom_instruction,
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
    if "sol_custom_instruction" in updates:
        # Tri-state on purpose: absent = unchanged, null = clear (SOLUSDEV-233).
        raw = updates["sol_custom_instruction"]
        user.sol_custom_instruction = raw.strip() or None if raw is not None else None
    if updates.get("data_collection_consent") is not None:
        # ADR-011 opt-in/out. Flip before emitting so the event itself honors
        # the new consent state.
        user.data_collection_consent = updates["data_collection_consent"]
    if updates.get("onboarding_step") is not None:
        user.onboarding_step = updates["onboarding_step"]
    # The instruction is user-authored prompt input: the event records THAT it
    # changed (set/cleared), never the text itself (§7).
    event_payload = dict(updates)
    if "sol_custom_instruction" in event_payload:
        event_payload["sol_custom_instruction"] = (
            "set" if user.sol_custom_instruction else "cleared"
        )
    emit_event(session, user=user, event_type="settings.updated", payload=event_payload)
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
    """Pick/change the trial plan during onboarding (ADR-032): sets the plan and that plan's
    default limits while the subscription stays TRIALING. Allowed ONLY for an unpaid local
    trial (status TRIALING and no Stripe subscription); otherwise 409, because paid plan
    changes go through Billing/Stripe. `expires_at` is never touched, so repeated calls
    cannot restart the trial."""
    sub = await _live_subscription(session, user)
    if sub.status != SubscriptionStatus.TRIALING or sub.stripe_subscription_id is not None:
        raise APIError(
            409,
            "subscription_change_not_allowed",
            "Your plan can only be changed here during the free trial. "
            "Use Billing to change or manage your subscription.",
        )
    sub.plan = body.plan
    sub.limits = default_limits(body.plan)
    emit_event(
        session, user=user, event_type="subscription.updated", payload={"plan": body.plan.value}
    )
    await session.commit()
    await session.refresh(sub)
    return envelope(SubscriptionRead.model_validate(sub).model_dump(mode="json"))


@router.get("/credits")
async def get_credits(
    user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    """Current credit balance (ADR-024). Always answerable — 0 before any ledger row
    exists. The desktop Billing screen reads this to reflect credit-pack purchases."""
    balance = await credits.get_balance(session, user.id)
    return envelope(
        CreditBalanceView(
            user_id=user.id,
            balance=balance,
            unlimited=is_development_unlimited(user.id, settings),
        ).model_dump(mode="json")
    )


@router.get("/usage")
async def get_usage(
    user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    """The always-visible meter (ADR-018, SOLUSDEV-233): credit-denominated usage
    for the current cycle. Windowed by the subscription's monthly anniversary;
    UTC calendar month before a subscription exists. `allowance` is the plan's
    starting-credit grant (ADR-023/024, provisional) — null means no plan-derived
    denominator, and clients fall back to showing the balance alone."""
    now = utcnow()
    sub = await session.scalar(
        select(Subscription).where(
            Subscription.user_id == user.id, Subscription.deleted_at.is_(None)
        )
    )
    if sub is not None:
        since, until = usage.cycle_window(ensure_utc(sub.created_at), now)
        allowance = settings.plan_credit_grants.get(sub.plan.value)
    else:
        since, until = usage.calendar_month_window(now)
        allowance = None
    used = await usage.cycle_spend(session, user.id, since=since, until=until)
    balance = await credits.get_balance(session, user.id)
    return envelope(
        {
            "unlimited": is_development_unlimited(user.id, settings),
            "used": used,
            "allowance": allowance,
            "balance": balance,
            "cycle_start": since.isoformat(),
            "cycle_end": until.isoformat(),
        }
    )


# ------------------------------------------------------------ panel links
#
# The approve / list / revoke half of the Onshape panel pairing (SOLUS-A7-01).
#
# Deliberately HERE rather than in `routers/panel.py`: these are the only three
# operations in the flow that need a real Solus session, and keeping them out of
# that module is what makes "no route under /api/v1/panel can reach
# provisioning" a statement `test_panel.py` checks mechanically rather than a
# convention someone has to remember.
#
# Holding a live, verified Solus session IS the proof of who is approving. The
# `user_code` proves only that the person typing it is looking at the panel.

#: Codes are 8 chars from a 31-symbol alphabet (~40 bits) and live 10 minutes,
#: so guessing is already hopeless; this bounds the noise a compromised account
#: could make and keys on the authenticated user, unlike the IP-blind global
#: limiter (`core/ratelimit.py` cannot see past the ALB).
PANEL_APPROVALS_PER_MINUTE = 10


class PanelLinkApprove(BaseModel):
    """Reject unknown fields: this endpoint hands out a 90-day credential."""

    model_config = ConfigDict(extra="forbid")

    user_code: str = Field(min_length=1, max_length=32)


@router.post("/panel-links")
async def approve_panel_link(
    body: PanelLinkApprove,
    user: CurrentUser,
    _verified: RequireVerified,
    session: SessionDep,
    request: Request,
) -> dict[str, Any]:
    """Approve a pairing by its user code. Mints nothing.

    The token is minted at redemption inside `panel/pair/poll`, so the plaintext
    never exists on this side and cannot be logged with the request body.
    """
    limiter: ConnectRateLimiter | None = getattr(request.app.state, "panel_approve_limiter", None)
    if limiter is not None and not limiter.allow(str(user.id)):
        raise APIError(429, "rate_limited", "Too many pairing attempts. Wait a minute.")

    code = body.user_code.strip().upper()
    pairing = await session.scalar(select(PanelPairing).where(PanelPairing.user_code == code))
    if pairing is None or ensure_utc(pairing.expires_at) <= utcnow():
        raise APIError(
            404, "invalid_pairing", "That code is not valid. Ask the panel for a new one."
        )
    if pairing.approved_user_id is not None:
        raise APIError(409, "already_approved", "That code was already approved.")

    pairing.approved_user_id = user.id
    emit_event(session, user=user, event_type="panel.link.approved", payload={})
    await session.commit()
    return envelope({"status": "approved"})


@router.get("/panel-links")
async def list_panel_links(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """Live panel links, so revoking one is possible without guessing its id."""
    bindings = await session.scalars(
        select(PanelBinding)
        .where(PanelBinding.user_id == user.id, PanelBinding.revoked_at.is_(None))
        .order_by(PanelBinding.created_at.desc())
    )
    return envelope(
        [
            {
                "id": str(binding.id),
                # Untrusted label from Onshape, charset-validated at pair/start.
                # Shown so a user can tell two links apart; never a lookup key.
                "onshape_user_id": binding.onshape_user_id,
                "created_at": binding.created_at.isoformat(),
                "last_used_at": binding.last_used_at.isoformat() if binding.last_used_at else None,
                "expires_at": binding.expires_at.isoformat(),
            }
            for binding in bindings.all()
        ]
    )


@router.delete("/panel-links/{binding_id}", status_code=204)
async def revoke_panel_link(
    binding_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    """Revoke immediately — `get_panel_binding` re-reads the row per request, so
    there is no cache for a revocation to lag behind."""
    binding = await session.get(PanelBinding, binding_id)
    if binding is None or binding.user_id != user.id or binding.revoked_at is not None:
        raise APIError(404, "not_found", "No such panel link")
    binding.revoked_at = utcnow()
    emit_event(session, user=user, event_type="panel.link.revoked", payload={})
    await session.commit()
    return Response(status_code=204)
