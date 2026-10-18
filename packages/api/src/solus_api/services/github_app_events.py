"""Effects of GitHub App webhook events (SOLUSDEV-216, ADR-039 section 5).

Everything in `payload` is untrusted data (CLAUDE.md section 7). Routing is ONLY
`payload["installation"]["id"]` (a validated positive int) -> `find_by_external_id`; a payload
can never name a team, project or source. Only these fields are ever read, each type-checked:
`installation.id`, `action`, `ref`, `deleted`, `repository.full_name`, `repository(ies)_removed
[].full_name`, `changes.repository.name.from`, `changes.owner.from.{user,organization}.login`,
`membership.user.id|login` and `member.id|login`. Strings are compared, never persisted; the
single exception is a member login that matches GitHub's own login grammar.

Nothing here commits: the router owns the transaction (the delivery claim and these effects
commit together). Syncs are NOT started here: matching source ids are left in
`session.info[PENDING_SYNCS_KEY]` for the router to enqueue after the commit.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Coroutine
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.github_app import GitHubAppClient
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
    Membership,
    NotificationType,
    Role,
    Source,
    SourceStatus,
    SourceType,
    TeamInstallation,
    utcnow,
)
from solus_api.services.activity import record_activity
from solus_api.services.notifications import notify_user
from solus_api.services.team_installations import (
    CODE_REPO_REMOVED,
    disable_sources_for_repos,
    find_by_external_id,
    invalidate_installation_caches,
    mark_suspended,
    mark_unsuspended,
    refresh_installation_fields,
    revoke_installation,
)

logger = logging.getLogger("solus.services.github_app_events")

PENDING_SYNCS_KEY: Final = "github_app_pending_syncs"
_BRANCH_PREFIX: Final = "refs/heads/"
_MAX_REMOVED_REPOS: Final = 1000
_MAX_NAME: Final = 200
_LOGIN: Final = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", re.ASCII)
_ADMIN_ROLES: Final = (Role.OWNER, Role.ADMIN)

_Handler = Callable[
    [AsyncSession, TeamInstallation, dict[str, Any], Any], Coroutine[Any, Any, None]
]


# --------------------------------------------------------------------- field readers


def _obj(value: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _text(value: Any) -> str | None:
    if isinstance(value, str) and 0 < len(value) <= _MAX_NAME:
        return value
    return None


def _full_name(value: Any) -> str | None:
    name = _text(value)
    return name if name is not None and name.count("/") == 1 else None


def _installation_id(payload: dict[str, Any]) -> int | None:
    return _positive_int(_obj(payload, "installation", "id"))


def _cache(app_state: Any) -> IntegrationCache | None:
    cache: IntegrationCache | None = getattr(app_state, "integration_cache", None)
    return cache


def _drop(event: str, reason: str, installation_id: int | None = None) -> None:
    logger.info(
        "github_org.webhook_dropped event=%.64s reason=%s installation=%s",
        event,
        reason,
        installation_id,
    )


# ------------------------------------------------------------------------- dispatch


async def dispatch(
    session: AsyncSession, event: str, payload: dict[str, Any], *, app_state: Any
) -> None:
    """Apply one delivery. Unknown installations, unknown events and malformed fields are
    logged or ignored, never raised. Does not commit."""
    handler = _HANDLERS.get((event, _text(payload.get("action")) or ""))
    if handler is None and event in _ANY_ACTION:
        handler = _ANY_ACTION[event]
    if handler is None:
        return
    external_id = _installation_id(payload)
    if external_id is None:
        _drop(event, "invalid_installation_id")
        return
    inst = await find_by_external_id(session, external_id)
    if inst is None:
        _drop(event, "unknown_installation", external_id)
        return
    await handler(session, inst, payload, app_state)


# --------------------------------------------------------------------------- handlers


async def _push(
    session: AsyncSession, inst: TeamInstallation, payload: dict[str, Any], _state: Any
) -> None:
    ref = _text(payload.get("ref"))
    repo = _full_name(_obj(payload, "repository", "full_name"))
    if payload.get("deleted") is True or ref is None or repo is None:
        return
    if not ref.startswith(_BRANCH_PREFIX) or len(ref) == len(_BRANCH_PREFIX):
        return
    branch = ref[len(_BRANCH_PREFIX) :]
    sources = await session.scalars(
        select(Source).where(
            Source.installation_id == inst.id,
            Source.team_id == inst.team_id,
            Source.status == SourceStatus.CONNECTED,
        )
    )
    ids = [
        s.id
        for s in sources
        if isinstance(s.config.get("repo"), str)
        and s.config["repo"].lower() == repo.lower()
        and s.config.get("branch") == branch
    ]
    pending: list[uuid.UUID] = session.info.setdefault(PENDING_SYNCS_KEY, [])
    pending.extend(ids)


async def _installation_deleted(
    session: AsyncSession, inst: TeamInstallation, _payload: dict[str, Any], state: Any
) -> None:
    await revoke_installation(
        session, inst, actor=None, reason_code="installation_deleted", cache=_cache(state)
    )


async def _installation_suspend(
    session: AsyncSession, inst: TeamInstallation, _payload: dict[str, Any], _state: Any
) -> None:
    await mark_suspended(session, inst, utcnow())


async def _installation_unsuspend(
    session: AsyncSession, inst: TeamInstallation, _payload: dict[str, Any], _state: Any
) -> None:
    await mark_unsuspended(session, inst)


async def _new_permissions(
    session: AsyncSession, inst: TeamInstallation, _payload: dict[str, Any], _state: Any
) -> None:
    client = GitHubAppClient(inst.api_base_url, inst.web_base_url)
    try:
        info = await client.get_installation(inst.external_installation_id)
    except ConnectorError as exc:
        logger.warning(
            "github_org installation refresh failed installation=%s code=%s", inst.id, exc.code
        )
        return
    await refresh_installation_fields(session, inst, info)


def _removed_repo_names(payload: dict[str, Any]) -> set[str]:
    removed = payload.get("repositories_removed")
    if not isinstance(removed, list):
        return set()
    names = (_full_name(_obj(item, "full_name")) for item in removed[:_MAX_REMOVED_REPOS])
    return {name for name in names if name is not None}


async def _repos_removed(
    session: AsyncSession, inst: TeamInstallation, payload: dict[str, Any], state: Any
) -> None:
    await disable_sources_for_repos(session, inst, _removed_repo_names(payload), CODE_REPO_REMOVED)
    await invalidate_installation_caches(
        inst.external_installation_id, _cache(state), repos=True, roster=False
    )


async def _repos_added(
    _session: AsyncSession, inst: TeamInstallation, _payload: dict[str, Any], state: Any
) -> None:
    await invalidate_installation_caches(
        inst.external_installation_id, _cache(state), repos=True, roster=False
    )


async def _roster_changed(
    _session: AsyncSession, inst: TeamInstallation, _payload: dict[str, Any], state: Any
) -> None:
    await invalidate_installation_caches(
        inst.external_installation_id, _cache(state), repos=False, roster=True
    )


async def _github_member_user_id(
    session: AsyncSession, inst: TeamInstallation, github_id: int
) -> uuid.UUID | None:
    """A live member of the owning team whose live GitHub connection has this numeric id."""
    user_id: uuid.UUID | None = await session.scalar(
        select(AccountConnection.user_id)
        .join(Membership, Membership.user_id == AccountConnection.user_id)
        .where(
            AccountConnection.provider == SourceType.GITHUB,
            AccountConnection.status == ConnectionStatus.CONNECTED,
            AccountConnection.account_external_id == str(github_id),
            Membership.team_id == inst.team_id,
            Membership.deleted_at.is_(None),
        )
        .limit(1)
    )
    return user_id


async def _member_removed(
    session: AsyncSession, inst: TeamInstallation, payload: dict[str, Any], _state: Any
) -> None:
    user = _obj(payload, "membership", "user")
    if not isinstance(user, dict):
        user = payload.get("member")
    github_id = _positive_int(_obj(user, "id"))
    if github_id is None:
        return
    member_id = await _github_member_user_id(session, inst, github_id)
    if member_id is None:
        return
    login = _obj(user, "login")
    safe_login = login if isinstance(login, str) and _LOGIN.fullmatch(login) else None
    admins = await session.scalars(
        select(Membership.user_id).where(
            Membership.team_id == inst.team_id,
            Membership.deleted_at.is_(None),
            Membership.role.in_(_ADMIN_ROLES),
        )
    )
    attrs: dict[str, Any] = {
        "installation_id": str(inst.id),
        "user_id": str(member_id),
        "github_id": github_id,
    }
    body = f"GitHub user id {github_id}" + (f" ({safe_login})" if safe_login else "")
    body += " left the linked GitHub organization. Their Solus access is unchanged."
    for admin_id in admins.all():
        notify_user(
            session,
            user_id=admin_id,
            notification_type=NotificationType.GITHUB_ORG_MEMBER_REMOVED,
            title="A teammate left your GitHub organization",
            body=body,
            attrs=attrs,
        )
    record_activity(
        session,
        team_id=inst.team_id,
        activity_type="github_org.member_removed_notice",
        actor_id=None,
        payload=attrs,
    )
    logger.info(
        "github_org member_removed_notice installation=%s team=%s user=%s",
        inst.id,
        inst.team_id,
        member_id,
    )


def _old_repo_names(payload: dict[str, Any], repo: str, action: str) -> set[str]:
    """The repo's names as sources may still hold them: GitHub's payload carries the NEW
    full_name, with the previous name or owner under `changes`."""
    owner, _, name = repo.partition("/")
    names = {repo}
    if action == "renamed":
        old = _text(_obj(payload, "changes", "repository", "name", "from"))
        if old is not None:
            names.add(f"{owner}/{old}")
    if action == "transferred":
        previous = _obj(payload, "changes", "owner", "from")
        for kind in ("user", "organization"):
            old_owner = _text(_obj(previous, kind, "login"))
            if old_owner is not None:
                names.add(f"{old_owner}/{name}")
    return names


def _repository_handler(action: str, code: str) -> _Handler:
    async def handle(
        session: AsyncSession, inst: TeamInstallation, payload: dict[str, Any], _state: Any
    ) -> None:
        repo = _full_name(_obj(payload, "repository", "full_name"))
        if repo is None:
            return
        await disable_sources_for_repos(session, inst, _old_repo_names(payload, repo, action), code)

    return handle


_HANDLERS: Final[dict[tuple[str, str], _Handler]] = {
    ("installation", "deleted"): _installation_deleted,
    ("installation", "suspend"): _installation_suspend,
    ("installation", "unsuspend"): _installation_unsuspend,
    ("installation", "new_permissions_accepted"): _new_permissions,
    ("installation_repositories", "removed"): _repos_removed,
    ("installation_repositories", "added"): _repos_added,
    ("organization", "member_removed"): _member_removed,
    ("organization", "member_added"): _roster_changed,
    ("repository", "renamed"): _repository_handler("renamed", "repo_renamed"),
    ("repository", "transferred"): _repository_handler("transferred", "repo_transferred"),
    ("repository", "deleted"): _repository_handler("deleted", "repo_deleted"),
}
#: Events handled whatever their action: push has none, `member.*` all change the roster.
_ANY_ACTION: Final[dict[str, _Handler]] = {"push": _push, "member": _roster_changed}
