"""Team-owned provider installations: the single core behind SOLUSDEV-216 (ADR-039).

Every route, webhook handler and worker that touches a `TeamInstallation` goes through here,
so the rules live in one place:

* A live installation needs a live COLLABORATIVE team and `deleted_at IS NULL`.
* Revoking (unlink, uninstall, suspend, repo removal) disables sources with
  `SourceStatus.ERROR` or `DISCONNECTED` plus a `last_error {code, message}`; there is no
  DEGRADED status (docs/api/github-orgs.md section 6).
* Nothing here commits. The caller owns the transaction (same convention as
  `connections.revoke_connection`). Live frames are queued by the model row listeners.
* Caches are keyed by the GitHub installation id only, never by team or login, so a team
  that re-links gets nothing from the previous owner and no key can alias another account.
  They use the shared `IntegrationCache` (Redis-backed); a missing cache is a no-op.
* Plan accounting (`link_counts_for_user`): a link counts against its linker only while
  they are a live member of the team.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.github_app import InstallationInfo, invalidate_installation_token
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.core.errors import APIError
from solus_api.models import (
    InstallationStatus,
    Membership,
    Source,
    SourceStatus,
    Team,
    TeamInstallation,
    TeamKind,
    User,
    utcnow,
)
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event

logger = logging.getLogger("solus.services.team_installations")

PROVIDER: Final = "github"
CODE_UNLINKED: Final = "installation_unlinked"
CODE_SUSPENDED: Final = "installation_suspended"
CODE_REPO_REMOVED: Final = "repo_access_removed"

_REASON_MESSAGES: Final[dict[str, str]] = {
    CODE_UNLINKED: "The GitHub organization was unlinked from this team",
    CODE_SUSPENDED: "The GitHub App installation is suspended",
    CODE_REPO_REMOVED: "The repository is no longer accessible to the GitHub App",
    "installation_deleted": "The GitHub App was uninstalled",
    "repo_renamed": "The repository was renamed on GitHub",
    "repo_transferred": "The repository was transferred on GitHub",
    "repo_deleted": "The repository was deleted on GitHub",
}
_REFUSALS: Final[dict[InstallationStatus, tuple[str, str]]] = {
    InstallationStatus.SUSPENDED: (
        "installation_suspended",
        "The GitHub App installation is suspended. Unsuspend it on GitHub.",
    ),
    InstallationStatus.REVOKED: (
        "installation_revoked",
        "The GitHub App installation was revoked. Link the organization again.",
    ),
}
_LIVE_STATES: Final = (SourceStatus.CONNECTED, SourceStatus.ERROR)
_CACHE_ACCOUNT_PREFIX: Final = "installation:"


def normalise_repo(name: str) -> str:
    """The one comparison key for GitHub `owner/name`s (GitHub names are case-insensitive).

    Every place that matches a repo name (binding, de-duplication, webhook matching, repo
    disabling) goes through this, so none of them can drift apart."""
    return name.casefold()


def _error(code: str) -> dict[str, str]:
    return {"code": code, "message": _REASON_MESSAGES.get(code, code.replace("_", " "))}


# ------------------------------------------------------------------ lookups


def _live_query(provider: str = PROVIDER) -> Any:
    return (
        select(TeamInstallation)
        .join(Team, Team.id == TeamInstallation.team_id)
        .where(
            TeamInstallation.provider == provider,
            TeamInstallation.deleted_at.is_(None),
            Team.deleted_at.is_(None),
            Team.kind == TeamKind.COLLABORATIVE,
        )
    )


async def get_live_installation(
    session: AsyncSession, team_id: uuid.UUID, provider: str = PROVIDER
) -> TeamInstallation | None:
    """The team's installation, or None. Requires a live COLLABORATIVE team and a live row
    (any status: callers decide what REVOKED/SUSPENDED mean via `require_active_installation`)."""
    result: TeamInstallation | None = await session.scalar(
        _live_query(provider).where(TeamInstallation.team_id == team_id)
    )
    return result


async def require_active_installation(
    session: AsyncSession, team_id: uuid.UUID
) -> TeamInstallation:
    """The team's ACTIVE installation, or 409 `installation_missing`,
    `installation_suspended` or `installation_revoked`."""
    inst = await get_live_installation(session, team_id)
    if inst is None:
        raise APIError(409, "installation_missing", "This team has no linked GitHub organization.")
    refusal = _REFUSALS.get(inst.status)
    if refusal is not None:
        raise APIError(409, *refusal)
    return inst


async def find_by_external_id(
    session: AsyncSession, external_installation_id: int
) -> TeamInstallation | None:
    """Webhook routing entry point: the live, non-revoked installation with this GitHub id on
    a live COLLABORATIVE team. Unknown, revoked, soft-deleted or deleted-team rows are None."""
    result: TeamInstallation | None = await session.scalar(
        _live_query().where(
            TeamInstallation.external_installation_id == external_installation_id,
            TeamInstallation.status != InstallationStatus.REVOKED,
        )
    )
    return result


# ------------------------------------------------------------------ caches


def _account_ref(external_installation_id: int) -> str:
    return f"{_CACHE_ACCOUNT_PREFIX}{external_installation_id}"


def repos_cache_key(external_installation_id: int) -> str:
    """Integration-cache key of the installation's repo listing."""
    return IntegrationCache.signal_key(PROVIDER, _account_ref(external_installation_id), "repos")


def roster_cache_key(external_installation_id: int) -> str:
    """Integration-cache key of the installation's org roster."""
    return IntegrationCache.signal_key(PROVIDER, _account_ref(external_installation_id), "roster")


async def invalidate_installation_caches(
    external_installation_id: int,
    cache: IntegrationCache | None,
    *,
    repos: bool = True,
    roster: bool = True,
) -> None:
    """Drop the repo and/or roster cache of one installation. No cache is a no-op."""
    if cache is None:
        return
    if repos:
        await cache.invalidate(repos_cache_key(external_installation_id))
    if roster:
        await cache.invalidate(roster_cache_key(external_installation_id))


# ------------------------------------------------------------------ sources


async def _bound_sources(
    session: AsyncSession, inst: TeamInstallation, states: tuple[SourceStatus, ...]
) -> list[Source]:
    rows = await session.scalars(
        select(Source)
        .where(Source.installation_id == inst.id, Source.status.in_(states))
        .with_for_update()
    )
    return list(rows.all())


async def count_bound_sources(session: AsyncSession, inst: TeamInstallation) -> int:
    """Live (non-DISCONNECTED) sources bound to the installation, for the unlink confirm."""
    count = await session.scalar(
        select(func.count())
        .select_from(Source)
        .where(Source.installation_id == inst.id, Source.status != SourceStatus.DISCONNECTED)
    )
    return count or 0


async def revoke_installation(
    session: AsyncSession,
    inst: TeamInstallation,
    *,
    actor: User | None,
    reason_code: str = CODE_UNLINKED,
    cache: IntegrationCache | None = None,
) -> int:
    """Soft-delete the installation (status REVOKED) and disconnect every bound source.

    Sources become DISCONNECTED with `last_error {code: reason_code, message}` and no
    `secret_ref`; `installation_id` stays for the audit. The reserved ref is never a
    SecretStore key, so nothing is deleted from the store. Drops the cached token and the
    repo and roster caches, records activity `github_org.unlinked` (actor_id None for a
    system actor) and emits a data event only for a User actor. Does NOT commit.
    Returns how many sources were disabled."""
    bound = await _bound_sources(session, inst, _LIVE_STATES)
    for source in bound:
        source.status = SourceStatus.DISCONNECTED
        source.secret_ref = None
        source.last_error = _error(reason_code)
    now = utcnow()
    inst.status = InstallationStatus.REVOKED
    inst.revoked_at = now
    inst.deleted_at = now
    await session.flush()
    invalidate_installation_token(inst.external_installation_id)
    await invalidate_installation_caches(inst.external_installation_id, cache)
    payload = {
        "installation_id": str(inst.id),
        "account_login": inst.account_login,
        "reason": reason_code,
        "disabled_sources": len(bound),
    }
    record_activity(
        session,
        team_id=inst.team_id,
        activity_type="github_org.unlinked",
        actor_id=actor.id if actor is not None else None,
        payload=payload,
    )
    if actor is not None:
        emit_event(
            session,
            user=actor,
            event_type="github_org.unlinked",
            team_id=inst.team_id,
            payload={"disabled_sources": len(bound), "reason": reason_code},
        )
    logger.info(
        "github_org unlinked installation=%s team=%s reason=%s disabled_sources=%d actor=%s",
        inst.id,
        inst.team_id,
        reason_code,
        len(bound),
        actor.id if actor is not None else None,
    )
    return len(bound)


async def disable_sources_for_repos(
    session: AsyncSession, inst: TeamInstallation, repo_full_names: set[str], code: str
) -> int:
    """Move this installation's sources tracking any of `repo_full_names` (`normalise_repo`
    match on `config["repo"]`) to ERROR with `last_error {code, message}`. Returns the count."""
    wanted = {normalise_repo(name) for name in repo_full_names}
    if not wanted:
        return 0
    disabled = 0
    for source in await _bound_sources(session, inst, _LIVE_STATES):
        repo = source.config.get("repo")
        if isinstance(repo, str) and normalise_repo(repo) in wanted:
            source.status = SourceStatus.ERROR
            source.last_error = _error(code)
            disabled += 1
    await session.flush()
    return disabled


async def mark_suspended(
    session: AsyncSession, inst: TeamInstallation, suspended_at: datetime
) -> None:
    """Record the suspension and move CONNECTED sources to ERROR `installation_suspended`."""
    inst.status = InstallationStatus.SUSPENDED
    inst.suspended_at = suspended_at
    for source in await _bound_sources(session, inst, (SourceStatus.CONNECTED,)):
        source.status = SourceStatus.ERROR
        source.last_error = _error(CODE_SUSPENDED)
    await session.flush()
    invalidate_installation_token(inst.external_installation_id)


async def mark_unsuspended(session: AsyncSession, inst: TeamInstallation) -> None:
    """Reactivate, restoring ONLY sources whose error code is `installation_suspended`.
    A source that failed for another reason stays in ERROR."""
    inst.status = InstallationStatus.ACTIVE
    inst.suspended_at = None
    for source in await _bound_sources(session, inst, (SourceStatus.ERROR,)):
        error = source.last_error
        if isinstance(error, dict) and error.get("code") == CODE_SUSPENDED:
            source.status = SourceStatus.CONNECTED
            source.last_error = None
    await session.flush()


async def refresh_installation_fields(
    session: AsyncSession, inst: TeamInstallation, info: InstallationInfo
) -> None:
    """Copy GitHub's record onto the row (login, avatar, type, selection, suspension).
    Never touches `team_id`; a REVOKED row stays REVOKED. Suspension state follows GitHub:
    a suspended record suspends, an unsuspended one reactivates only a SUSPENDED row."""
    inst.account_login = info.account_login
    inst.account_external_id = info.account_id
    inst.account_type = info.account_type
    inst.account_avatar_url = info.account_avatar_url
    inst.repository_selection = info.repository_selection
    if inst.status is InstallationStatus.REVOKED:
        await session.flush()
        return
    if info.suspended_at is not None and inst.status is InstallationStatus.ACTIVE:
        await mark_suspended(session, inst, info.suspended_at)
    elif info.suspended_at is None and inst.status is InstallationStatus.SUSPENDED:
        await mark_unsuspended(session, inst)
    else:
        inst.suspended_at = info.suspended_at
    await session.flush()


# ------------------------------------------------------------------ accounting


async def link_counts_for_user(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Live installations this user linked while still a live member of the team
    (ADR-039 section 8; a departed linker no longer pays for the team's link)."""
    count = await session.scalar(
        select(func.count())
        .select_from(TeamInstallation)
        .join(
            Membership,
            (Membership.team_id == TeamInstallation.team_id)
            & (Membership.user_id == TeamInstallation.linked_by)
            & Membership.deleted_at.is_(None),
        )
        .where(TeamInstallation.linked_by == user_id, TeamInstallation.deleted_at.is_(None))
    )
    return count or 0
