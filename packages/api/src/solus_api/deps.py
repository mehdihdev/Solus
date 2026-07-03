"""Centralized authN/authZ dependencies (CLAUDE.md §7, API.md §1.2/§1.3).

Every protected route authenticates and team-scopes through these — never
ad-hoc per-endpoint auth. Non-members receive 404 (no existence leak);
insufficient role within a team receives 403.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.secrets import SecretStore
from solus_api.core.config import Settings
from solus_api.core.db import get_session
from solus_api.core.errors import APIError
from solus_api.core.security import TokenClaims, decode_token
from solus_api.models import ROLE_RANK, Membership, Project, Role, Team, User

PERSONAL_TEAM_NAME = "Personal"

_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_connector_registry(request: Request) -> "ConnectorRegistry":
    registry: ConnectorRegistry = request.app.state.connector_registry
    return registry


def get_secret_store(request: Request) -> "SecretStore":
    store: SecretStore = request.app.state.secret_store
    return store


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
RegistryDep = Annotated["ConnectorRegistry", Depends(get_connector_registry)]
SecretStoreDep = Annotated["SecretStore", Depends(get_secret_store)]


async def _provision_user(session: AsyncSession, claims: TokenClaims) -> User:
    """First authenticated request: create the user and their personal team
    (§1.3 — this is what makes individual→team an upgrade, not a migration)."""
    user = User(auth_id=claims.sub, email=claims.email or "")
    team = Team(name=PERSONAL_TEAM_NAME, is_personal=True)
    session.add_all([user, team])
    await session.flush()
    session.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    await session.commit()
    await session.refresh(user)
    return user


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: SessionDep,
    settings: SettingsDep,
) -> User:
    if credentials is None:
        raise APIError(401, "unauthorized", "Missing bearer token")
    claims = decode_token(credentials.credentials, settings)
    user = await session.scalar(select(User).where(User.auth_id == claims.sub))
    if user is None:
        user = await _provision_user(session, claims)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass(frozen=True)
class TeamContext:
    team: Team
    membership: Membership
    user: User


@dataclass(frozen=True)
class ProjectContext:
    project: Project
    team: Team
    membership: Membership
    user: User


def require_role(context: "TeamContext | ProjectContext", minimum: Role) -> None:
    if ROLE_RANK[context.membership.role] < ROLE_RANK[minimum]:
        raise APIError(403, "forbidden", f"Requires {minimum.value} role on this team")


async def get_team_context(
    team_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> TeamContext:
    team = await session.get(Team, team_id)
    membership = await session.get(Membership, (team_id, user.id)) if team else None
    if team is None or membership is None:
        raise APIError(404, "not_found", "Team not found")
    return TeamContext(team=team, membership=membership, user=user)


TeamCtx = Annotated[TeamContext, Depends(get_team_context)]


async def get_project_context(
    project_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> ProjectContext:
    project = await session.get(Project, project_id)
    membership = await session.get(Membership, (project.team_id, user.id)) if project else None
    if project is None or membership is None:
        raise APIError(404, "not_found", "Project not found")
    team = await session.get(Team, project.team_id)
    if team is None:
        raise APIError(404, "not_found", "Project not found")
    return ProjectContext(project=project, team=team, membership=membership, user=user)


ProjectCtx = Annotated[ProjectContext, Depends(get_project_context)]
