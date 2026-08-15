"""Centralized authN/authZ dependencies (CLAUDE.md §7, API.md §1.2/§1.3).

Every protected route authenticates and team-scopes through these — never
ad-hoc per-endpoint auth. Non-members receive 404 (no existence leak);
insufficient role within a team receives 403.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.interfaces import SolSystems
from solus_api.agent.runtime import AgentRunner
from solus_api.billing.credits import grant_trial_credits
from solus_api.billing.stripe_gateway import StripeGateway
from solus_api.bridge.registry import BridgeSessionRegistry
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.secrets import SecretStore
from solus_api.core.config import Settings
from solus_api.core.db import get_session
from solus_api.core.errors import APIError
from solus_api.core.security import TokenClaims, decode_token
from solus_api.models import (
    ROLE_RANK,
    DeletedAccount,
    Membership,
    PanelBinding,
    PlanType,
    Project,
    ProjectMembership,
    Role,
    Subscription,
    SubscriptionStatus,
    Team,
    TeamKind,
    User,
    default_limits,
    ensure_utc,
    utcnow,
)
from solus_api.services.supabase_admin import SupabaseAdmin

PERSONAL_TEAM_NAME = "Personal"
# Every user starts on a 14-day trial of their chosen plan (ADR-032); onboarding picks it.
TRIAL_DAYS = 14

_bearer = HTTPBearer(auto_error=False)


def get_bridge_sessions(request: Request) -> "BridgeSessionRegistry":
    """The live companion-session registry (SOLUSDEV-154), one per app."""
    registry: BridgeSessionRegistry = request.app.state.bridge_sessions
    return registry


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_connector_registry(request: Request) -> "ConnectorRegistry":
    registry: ConnectorRegistry = request.app.state.connector_registry
    return registry


def get_secret_store(request: Request) -> "SecretStore":
    store: SecretStore = request.app.state.secret_store
    return store


def get_supabase_admin(request: Request) -> "SupabaseAdmin":
    admin: SupabaseAdmin = request.app.state.supabase_admin
    return admin


def get_jwks_client(request: Request) -> "PyJWKClient | None":
    """The JWKS client for verifying Supabase ES256 tokens (SOLUSDEV-152), or None
    when supabase_url is unconfigured (only legacy HS256 tokens validate then)."""
    client: PyJWKClient | None = request.app.state.jwks_client
    return client


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    """The app's session factory — for code that must open its OWN session outside a
    request scope (the SOL SSE generator streams after the request session closes)."""
    maker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    return maker


def get_sol_systems(request: Request) -> SolSystems:
    """The W0-07 systems impl (mock-and-swap): `FakeSolSystems` now, the real impl later
    — swapped on app.state with no endpoint change."""
    systems: SolSystems = request.app.state.sol_systems
    return systems


def get_agent_runner(request: Request) -> AgentRunner:
    """The reasoning-loop runner behind the seam: the scaffold now, SOL-01/02 later."""
    runner: AgentRunner = request.app.state.agent_runner
    return runner


def get_stripe_gateway(request: Request) -> "StripeGateway":
    """The outbound Stripe wrapper, keyed from the SecretStore. Overridable in
    tests via app.dependency_overrides to avoid real Stripe calls."""
    return StripeGateway(get_secret_store(request))


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SessionMakerDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
BridgeSessionsDep = Annotated["BridgeSessionRegistry", Depends(get_bridge_sessions)]
RegistryDep = Annotated["ConnectorRegistry", Depends(get_connector_registry)]
SecretStoreDep = Annotated["SecretStore", Depends(get_secret_store)]
SupabaseAdminDep = Annotated["SupabaseAdmin", Depends(get_supabase_admin)]
JwksClientDep = Annotated[PyJWKClient | None, Depends(get_jwks_client)]
SolSystemsDep = Annotated[SolSystems, Depends(get_sol_systems)]
AgentRunnerDep = Annotated[AgentRunner, Depends(get_agent_runner)]
StripeGatewayDep = Annotated[StripeGateway, Depends(get_stripe_gateway)]


async def _provision_user(
    session: AsyncSession, claims: TokenClaims, *, trial_credit_grant: int = 0
) -> User:
    """First authenticated request: create the user and their personal team
    (§1.3 — this is what makes individual→team an upgrade, not a migration)."""
    user = User(supabase_user_id=claims.sub, email=claims.email or "")
    team = Team(name=PERSONAL_TEAM_NAME, kind=TeamKind.PERSONAL)
    session.add_all([user, team])
    await session.flush()
    session.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    # Start every user on a 14-day BASIC trial (ADR-032). Enforcement reads `limits` as
    # data; the plan is chosen/changed via PATCH /users/me/subscription during onboarding.
    session.add(
        Subscription(
            user_id=user.id,
            plan=PlanType.BASIC,
            status=SubscriptionStatus.TRIALING,
            limits=default_limits(PlanType.BASIC),
            expires_at=utcnow() + timedelta(days=TRIAL_DAYS),
        )
    )
    await session.commit()
    await session.refresh(user)
    # Bounded free-trial credit allowance — the trial's hard cost cap (ADR-024,
    # SOLUSDEV-83). Idempotent, so a retried provision never double-grants.
    if trial_credit_grant:
        await grant_trial_credits(session, user.id, trial_credit_grant)
    return user


def get_current_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: SettingsDep,
    jwks_client: JwksClientDep,
) -> TokenClaims:
    """Decode the bearer token to identity claims. Cached per-request by FastAPI,
    so `get_current_user` and `require_verified` share a single decode."""
    if credentials is None:
        raise APIError(401, "unauthorized", "Missing bearer token")
    return decode_token(credentials.credentials, settings, jwks_client)


ClaimsDep = Annotated[TokenClaims, Depends(get_current_claims)]


async def get_current_user(claims: ClaimsDep, session: SessionDep, settings: SettingsDep) -> User:
    user = await session.scalar(select(User).where(User.supabase_user_id == claims.sub))
    if user is None:
        # A deleted identity must not silently re-provision on a still-valid token
        # (SOLUSDEV-82). The tombstone makes account deletion durable.
        tombstoned = await session.scalar(
            select(DeletedAccount).where(DeletedAccount.supabase_user_id == claims.sub)
        )
        if tombstoned is not None:
            raise APIError(401, "account_deleted", "This account has been deleted")
        user = await _provision_user(
            session, claims, trial_credit_grant=settings.trial_credit_grant
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_verified(claims: ClaimsDep) -> None:
    """Gate for sensitive write actions (SOLUSDEV-82, ADR-009): the caller's email
    must be verified. Applied as a route dependency alongside team/project scoping."""
    if not claims.email_verified:
        raise APIError(
            403,
            "email_not_verified",
            "Verify your email address before performing this action",
        )


RequireVerified = Annotated[None, Depends(require_verified)]


@dataclass(frozen=True)
class TeamContext:
    team: Team
    membership: Membership
    user: User


@dataclass(frozen=True)
class ProjectContext:
    project: Project
    team: Team
    # None for a share-only user (direct ProjectMembership, no team role) — read-only.
    membership: Membership | None
    user: User


def require_role(context: "TeamContext | ProjectContext", minimum: Role) -> None:
    membership = context.membership
    if membership is None or ROLE_RANK[membership.role] < ROLE_RANK[minimum]:
        raise APIError(403, "forbidden", f"Requires {minimum.value} role on this team")


async def live_membership(
    session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID
) -> Membership | None:
    """The user's non-deleted membership in a team, or None."""
    membership: Membership | None = await session.scalar(
        select(Membership).where(
            Membership.team_id == team_id,
            Membership.user_id == user_id,
            Membership.deleted_at.is_(None),
        )
    )
    return membership


# ------------------------------------------------------- panel credentials
#
# A SECOND, DISJOINT CREDENTIAL CLASS (SOLUS-A7-01). Supabase JWTs may
# provision an account; panel tokens are provisioning-free by construction. The
# two namespaces never touch: a panel route hashes its bearer and looks the
# digest up in `panel_bindings`, so a JWT simply misses. No format sniffing, no
# shared decode path, and nothing here calls `get_current_user`.
#
# These live in `deps.py` with the other dependencies deliberately, so
# CLAUDE.md §7's "per-endpoint ad-hoc auth logic is forbidden" holds literally
# rather than by exception.

PANEL_TOKEN_TTL_DAYS = 90
#: How stale `last_used_at` may get before it is rewritten.
PANEL_LAST_USED_RESOLUTION = timedelta(hours=1)


def panel_token_hash(token: str) -> str:
    """Digest used for lookup. sha256 rather than a KDF: the token carries 256
    bits of entropy, so there is nothing to slow down, and a KDF would force a
    full-table scan instead of an indexed equality."""
    return hashlib.sha256(token.encode()).hexdigest()


async def get_panel_binding(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> PanelBinding:
    """The live binding behind a panel bearer token, or 401.

    Never provisions and never creates: an unknown token is simply
    unauthenticated. Revocation and expiry are effective on the very next
    request because the row is re-read every time — there is no cache anywhere
    in this path.
    """
    if credentials is None:
        raise APIError(401, "unauthenticated", "Panel token required")
    binding: PanelBinding | None = await session.scalar(
        select(PanelBinding).where(
            PanelBinding.token_hash == panel_token_hash(credentials.credentials)
        )
    )
    now = utcnow()
    if binding is None or binding.revoked_at is not None or ensure_utc(binding.expires_at) <= now:
        raise APIError(401, "unauthenticated", "Panel token required")
    # Coarse: the revoke UI needs "last used" to be recognisable, not exact, and
    # the panel polls often enough that a write per request would be pure noise.
    last = binding.last_used_at
    if last is None or (now - ensure_utc(last)) > PANEL_LAST_USED_RESOLUTION:
        binding.last_used_at = now
        await session.commit()
    return binding


async def get_panel_user(
    session: SessionDep, binding: Annotated[PanelBinding, Depends(get_panel_binding)]
) -> User:
    """The Solus user a panel acts for.

    Resolved by FK from a binding the user themselves approved — the
    `routers/bridge.py` precedent of looking a user up by hand rather than
    letting FastAPI inject `CurrentUser`, which is what would provision.
    """
    user = await session.get(User, binding.user_id)
    if user is None or user.deleted_at is not None:
        raise APIError(401, "unauthenticated", "Panel token required")
    return user


async def visible_project_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Every project this user may read — team membership OR a direct project
    share (ADR-025), which is the same set `get_project_context` admits."""
    by_team = await session.scalars(
        select(Project.id)
        .join(Membership, Membership.team_id == Project.team_id)
        .where(
            Membership.user_id == user_id,
            Membership.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
    )
    shared = await session.scalars(
        select(ProjectMembership.project_id).where(
            ProjectMembership.user_id == user_id,
            ProjectMembership.deleted_at.is_(None),
        )
    )
    return set(by_team.all()) | set(shared.all())


PanelBindingDep = Annotated[PanelBinding, Depends(get_panel_binding)]
PanelUser = Annotated[User, Depends(get_panel_user)]


async def get_team_context(
    team_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> TeamContext:
    team = await session.get(Team, team_id)
    membership = await live_membership(session, team_id, user.id) if team else None
    if team is None or membership is None:
        raise APIError(404, "not_found", "Team not found")
    return TeamContext(team=team, membership=membership, user=user)


TeamCtx = Annotated[TeamContext, Depends(get_team_context)]


async def get_project_context(
    project_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> ProjectContext:
    project = await session.get(Project, project_id)
    if project is None:
        raise APIError(404, "not_found", "Project not found")
    membership = await live_membership(session, project.team_id, user.id)
    if membership is None:
        # Dual-source access (ADR-025): a direct project share grants access even without team
        # membership. Share-only users have no team role → read-only (require_role fails on None).
        share = await session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == user.id,
                ProjectMembership.deleted_at.is_(None),
            )
        )
        if share is None:
            raise APIError(404, "not_found", "Project not found")
    team = await session.get(Team, project.team_id)
    if team is None:
        raise APIError(404, "not_found", "Project not found")
    return ProjectContext(project=project, team=team, membership=membership, user=user)


ProjectCtx = Annotated[ProjectContext, Depends(get_project_context)]
