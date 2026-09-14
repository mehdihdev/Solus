"""An approved native CAD mutation produces a hint for the existing sync spine."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.httpcache import CacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import tracked_document_ids
from solus_api.connectors.onshape_ops import operation_by_name
from solus_api.models import AccountConnection, ConnectionStatus, Source, SourceStatus, SourceType
from solus_api.services.connections import account_ref_for
from solus_api.services.onshape_webhooks import (
    active_write_holds,
    add_write_hold,
    claim_schedule,
    dirty,
    hint_state,
    release_write_hold,
    save_state,
    state_for,
)

logger = logging.getLogger("solus.onshape_write_sync")
Enqueue = Callable[[AsyncSession, Source], Awaitable[uuid.UUID]]
SCHEDULING_TIMEOUT_SECONDS = 5


def _usable_source() -> Any:
    return or_(
        Source.status.in_((SourceStatus.CONNECTED, SourceStatus.SYNCING)),
        and_(
            Source.status == SourceStatus.ERROR,
            Source.last_error["code"].as_string() == "revision_changed",
        ),
    )


async def hold_onshape_write_sync(
    maker: async_sessionmaker[AsyncSession],
    *,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    tool_name: str,
    args: dict[str, Any],
    store: CacheStore | None,
    turn_id: uuid.UUID,
    turn_deadline: datetime,
) -> uuid.UUID | None:
    """Durable bookkeeping for an already-admitted write; never grants authority."""
    operation = operation_by_name(tool_name)
    if operation is None or not operation.requires_confirmation or "write" not in operation.tags:
        return None
    try:
        async with asyncio.timeout(SCHEDULING_TIMEOUT_SECONDS), maker() as db:
            sources = await db.scalars(
                select(Source)
                .where(
                    Source.project_id == project_id,
                    Source.team_id == team_id,
                    Source.type == SourceType.ONSHAPE,
                    _usable_source(),
                    Source.revision_base_source_id.is_(None),
                )
                .with_for_update()
            )
            selected = [
                row
                for row in sources
                if args.get("document_id") in tracked_document_ids(row.config)
            ]
            if len(selected) != 1 or not selected[0].secret_ref:
                raise ConnectorError("unavailable", "CAD source is unavailable for reconciliation")
            source = selected[0]
            refs = await _cache_refs(db, source)
            if refs is None:
                raise ConnectorError("unavailable", "CAD grant is unavailable for reconciliation")
            held = add_write_hold(state_for(source), turn_id, turn_deadline)
            if store is not None:
                for ref in refs:
                    await store.delete(
                        IntegrationCache.signal_key("onshape", ref, args["document_id"])
                    )
            save_state(source, hint_state(held))
            await db.commit()
            return source.id
    except ConnectorError:
        raise
    except Exception:
        raise ConnectorError(
            "unavailable", "CAD reconciliation bookkeeping failed; write was not started"
        ) from None


async def release_onshape_write_sync(
    maker: async_sessionmaker[AsyncSession],
    *,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    source_id: uuid.UUID,
    turn_id: uuid.UUID,
    enqueue: Enqueue,
) -> dict[str, str]:
    """Release only this turn's scoped owner; dirty state survives enqueue failure."""
    try:
        async with asyncio.timeout(SCHEDULING_TIMEOUT_SECONDS), maker() as db:
            source = await db.scalar(
                select(Source)
                .where(
                    Source.id == source_id,
                    Source.project_id == project_id,
                    Source.team_id == team_id,
                    Source.type == SourceType.ONSHAPE,
                    Source.revision_base_source_id.is_(None),
                )
                .with_for_update()
            )
            if source is None:
                return {"status": "unavailable"}
            before = state_for(source)
            owned = str(turn_id) in before.get("write_turn_holds", {})
            state = release_write_hold(before, turn_id)
            save_state(source, state)
            if not owned or active_write_holds(state) or not dirty(state):
                await db.commit()
                return {"status": "deferred"}
            allowed = source.status in (SourceStatus.CONNECTED, SourceStatus.SYNCING) or (
                source.status == SourceStatus.ERROR
                and (source.last_error or {}).get("code") == "revision_changed"
            )
            if not allowed or not source.secret_ref or await _cache_refs(db, source) is None:
                await db.commit()
                return {"status": "unavailable"}
            state, should_enqueue = claim_schedule(state)
            save_state(source, state)
            await db.commit()
            if not should_enqueue:
                return {"status": "queued"}
            job_id = await enqueue(db, source)
            return {"status": "queued", "job_id": str(job_id)}
    except Exception:
        logger.warning("CAD turn reconciliation release failed project=%s", project_id)
        return {"status": "failed"}


async def schedule_onshape_write_sync(
    maker: async_sessionmaker[AsyncSession],
    *,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    tool_name: str,
    args: dict[str, Any],
    store: CacheStore | None,
    enqueue: Enqueue,
) -> dict[str, str] | None:
    """Called only after successful approval. Never converts a write into a failure.

    A separate session prevents a failed scheduling transaction from poisoning
    confirmation history. The enqueue callback reuses the normal job/activity
    path with the deciding user and background execution.
    """
    operation = operation_by_name(tool_name)
    if operation is None or not operation.requires_confirmation or "write" not in operation.tags:
        return None
    unavailable = {
        "status": "unavailable",
        "message": "CAD change applied; its source is no longer available for graph sync.",
    }
    document_id = args.get("document_id")
    if not isinstance(document_id, str):
        return unavailable
    try:
        async with asyncio.timeout(SCHEDULING_TIMEOUT_SECONDS), maker() as db:
            sources = await db.scalars(
                select(Source).where(
                    Source.project_id == project_id,
                    Source.team_id == team_id,
                    Source.type == SourceType.ONSHAPE,
                    _usable_source(),
                    Source.revision_base_source_id.is_(None),
                )
            )
            selected = [row for row in sources if document_id in tracked_document_ids(row.config)]
            if len(selected) != 1:
                return unavailable
            source = selected[0]
            if not source.secret_ref:
                return unavailable
            refs = await _cache_refs(db, source)
            if refs is None:
                return unavailable
            if store is not None:
                # Delete through the store: cache.invalidate intentionally swallows
                # failures, which could enqueue a sync that trusts the old signal.
                # Include both existing source and account fallback identities.
                for ref in refs:
                    await store.delete(IntegrationCache.signal_key("onshape", ref, document_id))
            await db.refresh(source, with_for_update=True)
            state, should_enqueue = claim_schedule(hint_state(state_for(source)))
            save_state(source, state)
            await db.commit()
            if not should_enqueue:
                return {"status": "queued"}
            job_id = await enqueue(db, source)
            return {"status": "queued", "job_id": str(job_id)}
    except Exception:  # noqa: BLE001 — the CAD mutation has already succeeded
        logger.warning("graph sync scheduling failed after CAD write project=%s", project_id)
        return {
            "status": "failed",
            "message": "CAD change applied; graph sync could not be scheduled. "
            "Retry source sync, not the CAD change.",
        }


async def _cache_refs(db: AsyncSession, source: Source) -> set[str] | None:
    refs = {account_ref_for(source)}
    if source.connection_id is not None:
        account = await db.get(AccountConnection, source.connection_id)
        if (
            account is None
            or account.status != ConnectionStatus.CONNECTED
            or account.provider != SourceType.ONSHAPE
            or account.secret_ref != source.secret_ref
        ):
            return None
        refs.add(account_ref_for(account))
    return refs
