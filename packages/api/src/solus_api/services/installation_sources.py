"""Installation-backed sources (SOLUSDEV-216, ADR-039 s4, docs/api/github-orgs.md s2).

A member binds one repository that the TEAM's GitHub App installation can see to one of
the team's projects. The trust rules live here so the sources route and the repo-listing
route cannot drift apart:

* The team comes from the project (or the source), never from request input, so a project
  of team A cannot resolve team B's installation however the request is shaped.
* A repo is bindable only if it is in the installation's repo listing (cached per
  installation in the shared `IntegrationCache`; the same list backs `GET /github/repos`).
* The Source carries the reserved `secret_ref` and no stored token; the credential is
  minted on demand (`resolve_installation_credentials`).
* Binding is free: it never calls `check_can_add_integration`. The link itself was
  counted against the linking admin (ADR-039 s8).

Nothing here commits; the caller owns the transaction.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.github_app import (
    installation_secret_ref,
    resolve_installation_credentials,
)
from solus_api.connectors.integration_cache import Fetched
from solus_api.connectors.registry import UnknownConnectorError
from solus_api.core.errors import APIError
from solus_api.models import Project, Source, SourceStatus, SourceType, TeamInstallation, User
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event
from solus_api.services.team_installations import (
    repos_cache_key,
    require_active_installation,
)

logger = logging.getLogger("solus.services.installation_sources")

#: The repo list is also refreshed by the App webhook (`installation_repositories.*`
#: invalidates it), so this TTL is only the backstop for a missed delivery.
REPOS_CACHE_TTL_SECONDS: Final = 15 * 60
MAX_REPO_NAME_LENGTH: Final = 200
#: The only config keys a bound source may carry (`GitHubConnector.config_fields`).
BOUND_CONFIG_KEYS: Final = ("repo", "branch")
#: Source columns and linkage keys that are never writable through `config`.
RESERVED_CONFIG_KEYS: Final = frozenset({"secret_ref", "installation_id", "connection_id"})


def _validation_error(message: str) -> APIError:
    return APIError(400, "validation_error", message)


def repo_of(config: dict[str, Any]) -> str:
    """The `owner/name` the config names, or 400. Untrusted input, bounded and typed."""
    repo = config.get("repo")
    if not isinstance(repo, str) or not repo.strip() or len(repo) > MAX_REPO_NAME_LENGTH:
        raise _validation_error("config.repo must be a non-empty 'owner/name' string")
    return repo


def bound_config(config: dict[str, Any]) -> dict[str, Any]:
    """`repo` (validated) and an optional string `branch`; every other key is dropped."""
    repo = repo_of(config)
    branch = config.get("branch")
    if branch is None:
        return {"repo": repo}
    if not isinstance(branch, str) or not branch.strip() or len(branch) > MAX_REPO_NAME_LENGTH:
        raise _validation_error("config.branch must be a non-empty string")
    return {"repo": repo, "branch": branch}


async def list_installation_repos(
    app_state: Any, inst: TeamInstallation, *, refresh: bool = False
) -> Fetched[list[dict[str, Any]]]:
    """Every repo the installation can see, served from the per-installation cache.

    The cache key carries the GitHub installation id only, and callers have already
    resolved `inst` from the requesting team, so a hit can never cross teams. A failed
    walk is never cached."""
    cache = app_state.integration_cache
    try:
        connector = app_state.connector_registry.create(SourceType.GITHUB.value)
    except UnknownConnectorError as exc:
        raise APIError(400, "connector_unavailable", "No connector for 'github'") from exc

    async def fetch() -> list[dict[str, Any]]:
        credentials = await resolve_installation_credentials(installation_secret_ref(inst.id))
        repos: list[dict[str, Any]] = await connector.list_repositories(credentials)
        return repos

    try:
        fetched: Fetched[list[dict[str, Any]]] = await cache.fetch(
            repos_cache_key(inst.external_installation_id),
            ttl_seconds=REPOS_CACHE_TTL_SECONDS,
            fetch=fetch,
            refresh=refresh,
        )
    except ConnectorError as exc:
        logger.warning(
            "installation repo listing failed installation=%s code=%s", inst.id, exc.code
        )
        if exc.code == "installation_unavailable":
            raise APIError(
                409,
                "installation_revoked",
                "The GitHub App installation is no longer available. Link the organization again.",
            ) from exc
        raise APIError(502, exc.code, exc.message) from exc
    return fetched


async def require_repo_in_installation(
    app_state: Any, inst: TeamInstallation, repo: str
) -> dict[str, Any]:
    """The listed repo record, or 400 `repo_not_in_installation`. GitHub names are
    case-insensitive, so the comparison is too."""
    wanted = repo.casefold()
    for record in (await list_installation_repos(app_state, inst)).value:
        name = record.get("full_name")
        if isinstance(name, str) and name.casefold() == wanted:
            return record
    raise APIError(
        400,
        "repo_not_in_installation",
        "That repository is not shared with the team's GitHub App installation.",
    )


async def _existing_binding(
    session: AsyncSession, project_id: uuid.UUID, inst: TeamInstallation, repo: str
) -> Source | None:
    rows = await session.scalars(
        select(Source).where(
            Source.project_id == project_id,
            Source.installation_id == inst.id,
            Source.type == SourceType.GITHUB,
            Source.revision_base_source_id.is_(None),
        )
    )
    wanted = repo.casefold()
    for source in rows.all():
        bound = source.config.get("repo")
        if isinstance(bound, str) and bound.casefold() == wanted:
            return source
    return None


async def bind_installation_source(
    session: AsyncSession,
    *,
    project: Project,
    user: User,
    config: dict[str, Any],
    app_state: Any,
    name: str | None = None,
) -> Source:
    """Bind `config.repo` of the project's TEAM installation to `project`.

    409 `installation_missing` / `installation_suspended` / `installation_revoked` from
    the status gate, 400 `repo_not_in_installation`. Rebinding the same repo returns the
    existing source."""
    inst = await require_active_installation(session, project.team_id)
    clean = bound_config(config)
    await require_repo_in_installation(app_state, inst, clean["repo"])
    existing = await _existing_binding(session, project.id, inst, clean["repo"])
    if existing is not None:
        return existing

    source = Source(
        project_id=project.id,
        team_id=project.team_id,
        type=SourceType.GITHUB,
        name=name or clean["repo"],
        config=clean,
        status=SourceStatus.CONNECTED,
        installation_id=inst.id,
        secret_ref=installation_secret_ref(inst.id),
        connection_id=None,
        account_login=inst.account_login,
        account_external_id=f"installation:{inst.external_installation_id}",
        created_by=user.id,
    )
    session.add(source)
    await session.flush()
    record_activity(
        session,
        team_id=project.team_id,
        activity_type="source.connected",
        actor_id=user.id,
        project_id=project.id,
        domain="integrations",
        payload={"type": SourceType.GITHUB.value, "name": source.name},
    )
    emit_event(
        session,
        user=user,
        event_type="github_org.repo_bound",
        team_id=project.team_id,
        project_id=project.id,
        payload={"source_id": str(source.id), "installation_id": str(inst.id)},
    )
    return source


async def recheck_bound_repo(
    session: AsyncSession, *, source: Source, repo: Any, app_state: Any
) -> None:
    """A repo change on an installation-bound source re-runs the visibility check.

    The team comes from the source. If the installation it was bound through is no longer
    the team's live one (unlinked and re-linked), the source is stale: 409 revoked."""
    inst = await require_active_installation(session, source.team_id)
    if inst.id != source.installation_id:
        raise APIError(
            409,
            "installation_revoked",
            "This source was bound through an installation that is no longer linked.",
        )
    await require_repo_in_installation(app_state, inst, repo_of({"repo": repo}))
