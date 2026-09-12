"""Personal immutable Git views; acquisition never mutates a shared source."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.connectors.contracts import ConnectorError, Credentials, SyncContext, SyncResult
from solus_api.connectors.github import GitHubConnector
from solus_api.connectors.gitlab import GitLabConnector
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.runtime import _resolve_credentials, apply_sync_result
from solus_api.connectors.secrets import SecretStore
from solus_api.graph.live import LiveHub, graph_changed_frame
from solus_api.models import (
    GraphEntity,
    Source,
    SourceRevision,
    SourceStatus,
    SourceViewSelection,
    utcnow,
)
from solus_api.services.git_revisions import GitConnector, resolve_branch
from solus_api.services.physical_robots import GraphChangeCounts


def view_payload(
    base_source_id: uuid.UUID,
    selection: SourceViewSelection | None,
    *,
    active_source_id: uuid.UUID | None = None,
    active_branch: str | None = None,
    active_commit: str | None = None,
) -> dict[str, Any]:
    return {
        "base_source_id": str(base_source_id),
        "status": selection.status if selection is not None else "default",
        "source_id": str(active_source_id or base_source_id),
        "branch": active_branch,
        "commit": active_commit,
        "error": selection.error if selection is not None else None,
    }


async def selection_for(
    session: AsyncSession, source: Source, user_id: uuid.UUID
) -> SourceViewSelection | None:
    return (
        await session.scalars(
            select(SourceViewSelection)
            .where(
                SourceViewSelection.base_source_id == source.id,
                SourceViewSelection.project_id == source.project_id,
                SourceViewSelection.user_id == user_id,
            )
            .execution_options(populate_existing=True)
        )
    ).one_or_none()


async def get_view(session: AsyncSession, source: Source, user_id: uuid.UUID) -> dict[str, Any]:
    selection = await selection_for(session, source, user_id)
    revision = None
    if selection is not None and selection.active_revision_id is not None:
        revision = await session.scalar(
            select(SourceRevision).where(
                SourceRevision.id == selection.active_revision_id,
                SourceRevision.base_source_id == source.id,
                SourceRevision.project_id == source.project_id,
            )
        )
    return view_payload(
        source.id,
        selection,
        active_source_id=revision.materialized_source_id if revision else None,
        active_branch=(selection.active_branch or revision.branch)
        if revision and selection
        else None,
        active_commit=revision.commit_id if revision else None,
    )


def git_connector(registry: ConnectorRegistry, source: Source) -> GitConnector:
    connector = registry.create(source.type.value)
    if not isinstance(connector, (GitHubConnector, GitLabConnector)):
        raise ConnectorError(
            "unsupported_revisions", "This source does not support Git branch views"
        )
    return connector


async def acquire_revision(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: ConnectorRegistry,
    secret_store: SecretStore,
    source_id: uuid.UUID,
    user_id: uuid.UUID,
    generation: uuid.UUID,
    hub: LiveHub | None = None,
) -> None:
    try:
        async with asyncio.timeout(180):
            await _acquire(sessionmaker, registry, secret_store, source_id, user_id, generation)
    except (Exception, asyncio.CancelledError) as exc:
        logging.getLogger("solus.source_revisions").warning(
            "revision acquisition failed source=%s kind=%s", source_id, type(exc).__name__
        )
        async with sessionmaker() as session:
            selection = await session.scalar(
                select(SourceViewSelection)
                .where(
                    SourceViewSelection.base_source_id == source_id,
                    SourceViewSelection.user_id == user_id,
                    SourceViewSelection.request_generation == generation,
                )
                .with_for_update()
            )
            if selection is not None:
                selection.status = "failed"
                selection.error = "Branch acquisition failed. Your previous view is unchanged."
                await session.commit()
        if isinstance(exc, asyncio.CancelledError):
            raise

    if hub is not None:
        async with sessionmaker() as session:
            selection = await session.scalar(
                select(SourceViewSelection).where(
                    SourceViewSelection.base_source_id == source_id,
                    SourceViewSelection.user_id == user_id,
                    SourceViewSelection.request_generation == generation,
                )
            )
            if selection is not None:
                await hub.publish(
                    selection.project_id,
                    graph_changed_frame(
                        project_id=selection.project_id,
                        source_id=None,
                        sync_id=None,
                        counts=GraphChangeCounts(),
                        at=utcnow().isoformat(),
                    ),
                )


async def _acquire(
    sessionmaker: async_sessionmaker[AsyncSession],
    registry: ConnectorRegistry,
    secret_store: SecretStore,
    source_id: uuid.UUID,
    user_id: uuid.UUID,
    generation: uuid.UUID,
) -> None:
    from solus_api.deps import visible_project_ids

    async with sessionmaker() as session:
        base = await session.get(Source, source_id)
        if (
            base is None
            or base.revision_base_source_id is not None
            or base.status == SourceStatus.DISCONNECTED
        ):
            return
        if base.project_id not in await visible_project_ids(session, user_id):
            return
        selection = await selection_for(session, base, user_id)
        if (
            selection is None
            or selection.request_generation != generation
            or selection.status != "pending"
        ):
            return
        branch = selection.requested_branch or ""
        repo = str(base.config["repo"])
        connection_id = base.connection_id
        connector = git_connector(registry, base)
        if base.secret_ref is None:
            raise ConnectorError("invalid_credentials", "Connect this source again")
        credentials = await _resolve_credentials(secret_store, base.secret_ref)
        commit = await resolve_branch(connector, credentials, repo, branch)
        existing = await session.scalar(
            select(SourceRevision).where(
                SourceRevision.base_source_id == base.id, SourceRevision.commit_id == commit
            )
        )
        result = await _fetch_result(connector, credentials, base, commit, existing)
        # Recheck source, permission and generation after all network work. Base
        # lock serializes snapshot creation and selection updates in one order.
        await session.rollback()
        base = await session.scalar(select(Source).where(Source.id == source_id).with_for_update())
        if (
            base is None
            or base.status == SourceStatus.DISCONNECTED
            or base.project_id not in await visible_project_ids(session, user_id)
        ):
            return
        selection = await selection_for(session, base, user_id)
        if (
            selection is None
            or selection.request_generation != generation
            or selection.status != "pending"
        ):
            return
        if base.config.get("repo") != repo or base.connection_id != connection_id:
            raise ConnectorError("source_changed", "Source connection changed during acquisition")
        revision = await session.scalar(
            select(SourceRevision).where(
                SourceRevision.base_source_id == base.id, SourceRevision.commit_id == commit
            )
        )
        if revision is None:
            if result is None:
                raise ConnectorError("revision_unavailable", "Revision is no longer available")
            revision = await _materialize(session, base, result, user_id, commit, branch)
        selection.active_revision_id = revision.id
        selection.active_branch = branch
        selection.status = "ready"
        selection.error = None
        await session.commit()


async def _materialize(
    session: AsyncSession,
    base: Source,
    result: SyncResult,
    user_id: uuid.UUID,
    commit: str,
    branch: str,
) -> SourceRevision:
    snapshot = Source(
        project_id=base.project_id,
        team_id=base.team_id,
        type=base.type,
        name=base.name,
        status=SourceStatus.CONNECTED,
        revision_base_source_id=base.id,
        config={**base.config, "branch": commit},
        cursor={**result.cursor, "sha": commit, "branch": branch},
        created_by=user_id,
        last_synced_at=utcnow(),
    )
    session.add(snapshot)
    await session.flush()
    _, errors = await apply_sync_result(session, snapshot, result)
    if errors:
        raise ConnectorError("incomplete_revision", "Revision graph was incomplete")
    entities = (
        await session.scalars(select(GraphEntity).where(GraphEntity.source_id == snapshot.id))
    ).all()
    for entity in entities:
        entity.attrs = {
            **entity.attrs,
            "base_source_id": str(base.id),
            "revision_commit": commit,
        }
    revision = SourceRevision(
        project_id=base.project_id,
        base_source_id=base.id,
        materialized_source_id=snapshot.id,
        commit_id=commit,
        branch=branch,
    )
    session.add(revision)
    await session.flush()
    return revision


async def _fetch_result(
    connector: GitConnector,
    credentials: Credentials,
    base: Source,
    commit: str,
    existing: SourceRevision | None,
) -> SyncResult | None:
    if existing is not None:
        return None
    result = await connector.sync(
        SyncContext(credentials=credentials, config={**base.config, "branch": commit}, cursor={})
    )
    if result.errors or str(result.cursor.get("sha", "")) != commit:
        raise ConnectorError("incomplete_revision", "Revision acquisition was incomplete")
    return result
