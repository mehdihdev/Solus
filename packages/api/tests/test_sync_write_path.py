"""SOLUSDEV-167 P5: the graph write path under concurrency and deletion.

Three defects the audit found, each of which silently produces a wrong answer
rather than an error:

  * `apply_sync_result` is SELECT-then-branch-in-Python with no lock, so two
    concurrent syncs of one source both INSERT and collide on
    `uq_graph_entity_source_ref`.
  * a soft delete does not bump `version`, so a tombstone is invisible to any
    version-watching consumer.
  * `_Counts` has no delete counter, so a delete-only sync reports "nothing
    happened" — which would gate the live-propagation publish to False and a
    teammate would never learn entities were removed.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, cast

import pytest
from solus_api.connectors.contracts import (
    Connector,
    Credentials,
    Domain,
    EntityOut,
    SyncResult,
)
from solus_api.connectors.runtime import apply_sync_result
from solus_api.models import GraphEntity, Project, Source, SourceStatus, SourceType, Team
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(maker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        source = Source(
            project_id=project.id,
            team_id=team.id,
            type=SourceType.ONSHAPE,
            name="onshape",
            status=SourceStatus.CONNECTED,
            config={},
        )
        db.add(source)
        await db.commit()
        return source.id


def _result(*keys: str) -> SyncResult:
    return SyncResult(
        entities=[
            EntityOut(source_key=k, type="part", domain=Domain.MECHANICAL, name=k) for k in keys
        ],
        relations=[],
        cursor={"v": "1"},
    )


async def _apply(
    maker: async_sessionmaker[AsyncSession], source_id: uuid.UUID, result: SyncResult
) -> Any:
    async with maker() as db:
        source = await db.get(Source, source_id)
        assert source is not None
        counts, _ = await apply_sync_result(db, source, result)
        await db.commit()
        return counts


async def test_a_tombstone_bumps_version_so_a_watcher_can_see_it(maker: Any) -> None:
    """A soft delete is a CHANGE. Without the bump a version-watching consumer
    sees the row's last live version forever and never learns it was removed."""
    source_id = await _seed(maker)
    await _apply(maker, source_id, _result("a", "b"))

    async with maker() as db:
        before = await db.scalar(
            select(GraphEntity.version).where(
                GraphEntity.source_id == source_id, GraphEntity.external_ref == "b"
            )
        )

    await _apply(maker, source_id, _result("a"))  # "b" disappears upstream

    async with maker() as db:
        row = (
            await db.scalars(
                select(GraphEntity).where(
                    GraphEntity.source_id == source_id, GraphEntity.external_ref == "b"
                )
            )
        ).one()
    assert row.deleted_at is not None, "the stale entity should be soft-deleted"
    assert row.version == before + 1, "a tombstone must bump version"


async def test_a_delete_only_sync_reports_the_deletion(maker: Any) -> None:
    """`_Counts` had no delete field, so this sync reported all-zero — which
    reads as "nothing changed" and would suppress the live-propagation frame."""
    source_id = await _seed(maker)
    await _apply(maker, source_id, _result("a", "b"))

    counts = await _apply(maker, source_id, _result("a"))

    assert counts.entities_deleted == 1
    assert counts.changed is True, "a delete-only sync is a change"


async def test_an_unchanged_sync_reports_no_change(maker: Any) -> None:
    """The other side of `changed`: re-applying an identical snapshot must not
    look like a change, or every no-op sync would wake every open session."""
    source_id = await _seed(maker)
    await _apply(maker, source_id, _result("a", "b"))

    counts = await _apply(maker, source_id, _result("a", "b"))

    assert counts.changed is False


async def test_concurrent_applies_serialize_instead_of_colliding(maker: Any) -> None:
    """The per-source advisory lock. Without it both coroutines SELECT before
    either commits, both INSERT, and the loser raises UniqueViolationError on
    uq_graph_entity_source_ref."""
    source_id = await _seed(maker)

    results = await asyncio.gather(
        _apply(maker, source_id, _result("a", "b", "c")),
        _apply(maker, source_id, _result("a", "b", "c")),
        return_exceptions=True,
    )

    failures = [r for r in results if isinstance(r, BaseException)]
    assert not failures, f"concurrent apply collided instead of serializing: {failures}"
    async with maker() as db:
        live = await db.scalar(
            select(func.count())
            .select_from(GraphEntity)
            .where(GraphEntity.source_id == source_id, GraphEntity.deleted_at.is_(None))
        )
    assert live == 3, f"expected 3 entities, saw {live}"


# ------------------------------------------ SOLUSDEV-167: the amplifier, again


async def test_a_no_signal_probe_does_not_buy_a_full_sync(maker: Any) -> None:
    """`_unchanged` must not swallow "we could not ask" into "go spend".

    NO_SIGNAL_CODES exists so a rate limit or an exhausted quota never becomes
    "it changed". The sweep honoured that, but `run_sync` caught the re-raise and
    proceeded to a FULL export — so on the webhook and bridge producer paths a
    402 still bought a translation job, a poll loop and a download. That is
    exactly the amplifier this ticket removes.
    """
    from solus_api.connectors.contracts import AuthKind, ConnectorError, SyncContext
    from solus_api.connectors.runtime import _unchanged

    class _OutOfQuota:
        auth_kind = AuthKind.OAUTH

        async def detect_changes(self, ctx: SyncContext) -> bool:
            raise ConnectorError("quota_exhausted", "allowance spent")

    with pytest.raises(ConnectorError) as caught:
        await _unchanged(
            connector=cast(Connector, _OutOfQuota()),
            credentials=Credentials(token="t"),
            config={},
            cursor={"v": "1"},
        )

    assert caught.value.code == "quota_exhausted"


async def test_an_ordinary_probe_failure_still_falls_through_to_a_sync(maker: Any) -> None:
    """The fail-safe survives for genuinely ambiguous errors — a 500 could mean
    anything, so it must not silently skip a sync and risk missing a change."""
    from solus_api.connectors.contracts import AuthKind, ConnectorError, SyncContext
    from solus_api.connectors.runtime import _unchanged

    class _Broken:
        auth_kind = AuthKind.OAUTH

        async def detect_changes(self, ctx: SyncContext) -> bool:
            raise ConnectorError("api_error", "upstream 500")

    assert (
        await _unchanged(
            connector=cast(Connector, _Broken()),
            credentials=Credentials(token="t"),
            config={},
            cursor={"v": "1"},
        )
        is False
    )
