"""Link a GitHub App installation to a team (SOLUSDEV-216, ADR-039 section 2).

The install flow proves three things before any row is written: the caller started it
(single-use server state bound to user, team and purpose), the caller can reach the
installation on GitHub (their user-to-server token lists it), and the installation is not
already owned by another team. The user token lives in memory for the proof only and is
revoked at GitHub afterwards; it is never logged, stored or returned.

Commit boundaries: `consume_state` commits immediately so a state can never be replayed
(even after a later failure). Everything from the plan-limit re-check to the insert shares
one transaction, so the subscription lock held by the check covers the insert.
"""

from __future__ import annotations

import logging
import secrets as pysecrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.github_app import (
    DEFAULT_API_BASE,
    DEFAULT_WEB_BASE,
    GitHubAppClient,
    InstallationInfo,
)
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.models import (
    InstallationStatus,
    OAuthState,
    Team,
    TeamInstallation,
    TeamKind,
    User,
    ensure_utc,
    utcnow,
)
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event
from solus_api.services.limits import check_can_add_integration
from solus_api.services.team_installations import (
    find_by_external_id,
    get_live_installation,
    refresh_installation_fields,
)

logger = logging.getLogger("solus.services.team_github_link")

STATE_PURPOSE: Final = "github_app_install"
STATE_TTL: Final = timedelta(minutes=10)
_UPSTREAM_REFUSALS: Final = frozenset({"oauth_exchange_failed"})


@dataclass(frozen=True, slots=True)
class LinkOutcome:
    """Result of `complete_install`: the row, and whether it was newly created."""

    installation: TeamInstallation
    created: bool


def require_collaborative(team: Team) -> None:
    if team.kind is not TeamKind.COLLABORATIVE:
        raise APIError(
            409, "personal_team_unsupported", "Personal teams cannot link a GitHub organization."
        )


def require_app_configured(settings: Settings) -> None:
    if not settings.github_app_configured:
        raise APIError(503, "github_app_unconfigured", "The GitHub App is not configured.")


def _upstream_error(exc: ConnectorError) -> APIError:
    """A GitHub failure as an API error: refusals are 400, anything else is a 502."""
    status = 400 if exc.code in _UPSTREAM_REFUSALS else 502
    return APIError(status, exc.code, exc.message)


async def start_install(
    session: AsyncSession,
    *,
    user: User,
    team: Team,
    settings: Settings,
    redirect_uri: str,
) -> dict[str, str]:
    """Create the single-use install state and return the GitHub install URL."""
    require_collaborative(team)
    require_app_configured(settings)
    if await get_live_installation(session, team.id) is not None:
        raise APIError(409, "already_linked", "This team already has a GitHub organization linked.")
    await check_can_add_integration(session, user)
    state = pysecrets.token_urlsafe(32)
    session.add(
        OAuthState(
            state=state,
            provider=STATE_PURPOSE,
            user_id=user.id,
            team_id=team.id,
            redirect_uri=redirect_uri,
            expires_at=utcnow() + STATE_TTL,
        )
    )
    await session.commit()
    install_url = (
        f"{DEFAULT_WEB_BASE}/apps/{settings.github_app_slug}/installations/new?state={state}"
    )
    return {"install_url": install_url, "state": state, "redirect_uri": redirect_uri}


async def consume_state(session: AsyncSession, *, state: str, user: User, team: Team) -> OAuthState:
    """Load and delete the state in its own committed step (replay-proof).

    A state belonging to another user or team, or of another purpose, is refused WITHOUT
    being consumed, so a stranger cannot burn somebody else's handshake."""
    record = await session.get(OAuthState, state)
    if (
        record is None
        or record.provider != STATE_PURPOSE
        or record.user_id != user.id
        or record.team_id != team.id
    ):
        raise _invalid_state()
    expired = ensure_utc(record.expires_at) < utcnow()
    await session.delete(record)
    await session.commit()
    if expired:
        raise _invalid_state()
    return record


def _invalid_state() -> APIError:
    return APIError(404, "install_state_invalid", "Unknown or expired install state.")


async def _prove_access(
    client: GitHubAppClient, code: str, installation_id: int
) -> InstallationInfo:
    """Exchange the code, then prove the installer can reach `installation_id` AND is an
    admin of its account (installation membership alone is granted to any org member who
    can see one covered repo). The token is revoked at GitHub on every path once obtained,
    and never leaves this function. Returns the installation's record."""
    try:
        token = await client.exchange_user_code(code)
    except ConnectorError as exc:
        raise _upstream_error(exc) from exc
    try:
        accessible = await client.user_installation_ids(token)
        if installation_id not in accessible:
            raise APIError(
                403, "installation_not_accessible", "You cannot access that GitHub installation."
            )
        info = await client.get_installation(installation_id)
        if not await _is_account_admin(client, token, info):
            raise APIError(
                403,
                "installation_admin_required",
                "Only an admin of the GitHub account can link its installation.",
            )
        return info
    except ConnectorError as exc:
        raise _upstream_error(exc) from exc
    finally:
        await client.revoke_user_token(token)


async def _is_account_admin(client: GitHubAppClient, token: str, info: InstallationInfo) -> bool:
    if info.account_type == "Organization":
        membership = await client.org_membership_role(token, info.account_login)
        return membership is not None and membership == ("admin", "active")
    if info.account_type == "User":
        return await client.user_id(token) == info.account_id
    return False


def _linked_elsewhere() -> APIError:
    return APIError(
        409,
        "installation_linked_elsewhere",
        "That GitHub installation is linked to another team. Unlink it there first.",
    )


async def complete_install(
    session: AsyncSession,
    *,
    user: User,
    team: Team,
    state: str,
    code: str,
    installation_id: int,
    client: GitHubAppClient | None = None,
) -> LinkOutcome:
    """Run steps 1-7 of docs/api/github-orgs.md. Any failure leaves nothing bound."""
    await consume_state(session, state=state, user=user, team=team)
    client = client or GitHubAppClient()
    info = await _prove_access(client, code, installation_id)

    existing = await find_by_external_id(session, installation_id)
    if existing is not None and existing.team_id != team.id:
        raise _linked_elsewhere()
    mine = existing or await get_live_installation(session, team.id)
    if mine is not None and mine.external_installation_id != installation_id:
        raise APIError(409, "already_linked", "This team already has a GitHub organization linked.")
    if mine is not None:
        await refresh_installation_fields(session, mine, info)
        await session.commit()
        return LinkOutcome(mine, created=False)

    await check_can_add_integration(session, user)
    return LinkOutcome(await _insert(session, user, team, info), created=True)


async def _insert(
    session: AsyncSession, user: User, team: Team, info: InstallationInfo
) -> TeamInstallation:
    suspended = info.suspended_at is not None
    row = TeamInstallation(
        id=uuid.uuid4(),
        team_id=team.id,
        external_installation_id=info.installation_id,
        account_login=info.account_login,
        account_external_id=info.account_id,
        account_type=info.account_type,
        account_avatar_url=info.account_avatar_url,
        repository_selection=info.repository_selection,
        status=InstallationStatus.SUSPENDED if suspended else InstallationStatus.ACTIVE,
        suspended_at=info.suspended_at,
        api_base_url=DEFAULT_API_BASE,
        web_base_url=DEFAULT_WEB_BASE,
        linked_by=user.id,
    )
    team_id = team.id  # read before a rollback expires the ORM objects
    try:
        async with session.begin_nested():
            session.add(row)
    except IntegrityError as exc:
        await session.rollback()
        logger.info("github_org link race lost team=%s", team_id)
        raise _linked_elsewhere() from exc
    record_activity(
        session,
        team_id=team.id,
        activity_type="github_org.linked",
        actor_id=user.id,
        payload={
            "installation_id": str(row.id),
            "account_login": row.account_login,
            "account_type": row.account_type,
        },
    )
    emit_event(
        session,
        user=user,
        event_type="github_org.linked",
        team_id=team.id,
        payload={
            "account_type": row.account_type,
            "repository_selection": row.repository_selection,
        },
    )
    await session.commit()
    logger.info("github_org linked installation=%s team=%s user=%s", row.id, team.id, user.id)
    return row


async def linked_by_user(session: AsyncSession, row: TeamInstallation) -> User | None:
    """The user who linked the installation, or None once their account is gone."""
    if row.linked_by is None:
        return None
    return await session.get(User, row.linked_by)
