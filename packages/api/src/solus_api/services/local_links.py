"""Derived `clone_of` edges — a local clone to the code-host repo it was cloned from
(SOLUSDEV-249 / INTEGRATIONS I2; `docs/api/local-folder.md` §5).

The link is DETERMINISTIC, not a fingerprint: the local source's sync cursor
carries `remote` (`owner/name`, from `.git/config`) and `host`; a sibling
GitHub/GitLab source in the same project whose `config["repo"]` matches
(case-folded) owns the repo node (`code_host.REPO_ROOT_KEY`). Internal revision
snapshots never participate. An exact branch match wins; otherwise the repository
must have one unambiguous attached source. One edge per
`(clone node, repo node)`, `origin="derived"`, filed under the LOCAL source's id
so it dies with the source, and reconciled whenever either side syncs
(`runtime._commit_success`). `apply_sync_result` reconciles only
`origin="connector"` edges, so a derived edge is never churned by the sync
that owns its endpoints. Nothing here reads outside the project.
"""

from __future__ import annotations

import logging
import uuid
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.connectors.code_host import REPO_ROOT_KEY
from solus_api.connectors.local_folder import CLONE_KEY
from solus_api.models import GraphEdge, GraphEntity, Source, SourceStatus, SourceType, utcnow

logger = logging.getLogger("solus.services.local_links")

CLONE_OF: Final = "clone_of"
DERIVED_ORIGIN: Final = "derived"
_HOST_TYPES: Final = {"github": SourceType.GITHUB, "gitlab": SourceType.GITLAB}


async def _live_entity(session: AsyncSession, source_id: uuid.UUID, key: str) -> GraphEntity | None:
    row: GraphEntity | None = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.source_id == source_id,
            GraphEntity.external_ref == key,
            GraphEntity.deleted_at.is_(None),
        )
    )
    return row


async def _repo_node_for(
    session: AsyncSession, project_id: uuid.UUID, remote: str, host: str, branch: str | None
) -> GraphEntity | None:
    host_type = _HOST_TYPES.get(host)
    if host_type is None:
        return None
    siblings = await session.scalars(
        select(Source).where(
            Source.project_id == project_id,
            Source.type == host_type,
            Source.revision_base_source_id.is_(None),
            Source.status != SourceStatus.DISCONNECTED,
        )
    )
    wanted = remote.casefold()
    candidates = [
        sibling
        for sibling in siblings.all()
        if isinstance(sibling.config.get("repo"), str)
        and sibling.config["repo"].casefold() == wanted
    ]
    matching_branch = [
        candidate
        for candidate in candidates
        if branch is not None and candidate.config.get("branch") == branch
    ]
    choices = matching_branch or candidates
    if len(choices) != 1:
        return None
    return await _live_entity(session, choices[0].id, REPO_ROOT_KEY)


async def _desired_edge(session: AsyncSession, local: Source) -> tuple[uuid.UUID, uuid.UUID] | None:
    remote = local.cursor.get("remote")
    host = local.cursor.get("host")
    if not isinstance(remote, str) or not isinstance(host, str):
        return None
    clone = await _live_entity(session, local.id, CLONE_KEY)
    if clone is None:
        return None
    branch = local.cursor.get("branch")
    repo = await _repo_node_for(
        session, local.project_id, remote, host, branch if isinstance(branch, str) else None
    )
    if repo is None:
        return None
    return (clone.id, repo.id)


async def reconcile_local_links(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Make the project's derived `clone_of` edges match what its local sources'
    cursors and its code-host repo nodes say. Idempotent; flushes, never commits."""
    locals_ = (
        await session.scalars(
            select(Source).where(
                Source.project_id == project_id,
                Source.type == SourceType.LOCAL,
                Source.status != SourceStatus.DISCONNECTED,
            )
        )
    ).all()
    existing = (
        await session.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type == CLONE_OF,
                GraphEdge.origin == DERIVED_ORIGIN,
                GraphEdge.deleted_at.is_(None),
            )
        )
    ).all()
    by_key = {(row.source_id, row.src_id, row.dst_id): row for row in existing}
    desired: set[tuple[uuid.UUID | None, uuid.UUID, uuid.UUID]] = set()
    for local in locals_:
        edge = await _desired_edge(session, local)
        if edge is not None:
            desired.add((local.id, *edge))
    for key in desired - set(by_key):
        source_id, src_id, dst_id = key
        session.add(
            GraphEdge(
                project_id=project_id,
                source_id=source_id,
                origin=DERIVED_ORIGIN,
                src_id=src_id,
                dst_id=dst_id,
                relation_type=CLONE_OF,
                domain_pair="code<->code",
                confidence=1.0,
                attrs={},
            )
        )
        logger.info("local clone linked project=%s source=%s", project_id, source_id)
    for key, row in by_key.items():
        if key not in desired:
            row.deleted_at = utcnow()
    await session.flush()
