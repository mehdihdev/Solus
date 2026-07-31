"""BRG-03 no-dupe gate: reconnect + resync never duplicates graph entities.

The invariant chain: the companion never buffers results across reconnects
(bridge contract §5 — a reconnect is a new session, its old calls already
failed cloud-side), and every ingestion routes through `apply_sync_result`,
which upserts by (source_id, external_ref) among LIVE rows, soft-deletes stale
ones, and sits on the `uq_graph_entity_source_ref` partial-unique index. So a
tool coming back and re-syncing the same content is idempotent by
construction — these tests are the ticket's acceptance gate on that claim.
(The status-cache clear/repopulate on reconnect is asserted in
test_bridge_status.py::test_status_snapshot_cached_and_served.)
"""

import uuid
from collections.abc import Sequence

from solus_api.connectors.contracts import Domain, EntityOut, RelationOut, SyncResult
from solus_api.connectors.runtime import apply_sync_result
from solus_api.models import (
    GraphEntity,
    Membership,
    Project,
    Role,
    Source,
    SourceStatus,
    SourceType,
    Team,
    User,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_source(db: AsyncSession) -> Source:
    user = User(supabase_user_id=f"sub-{uuid.uuid4().hex[:8]}", email="resync@example.com")
    team = Team(name="Resync")
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name="Rover", created_by=user.id)
    db.add(project)
    await db.flush()
    source = Source(
        project_id=project.id,
        team_id=team.id,
        type=SourceType.KICAD,
        name="rover-main",
        status=SourceStatus.CONNECTED,
    )
    db.add(source)
    await db.flush()
    return source


def _sync(keys: Sequence[str]) -> SyncResult:
    entities = [
        EntityOut(
            source_key=key,
            type="component",
            domain=Domain.ELECTRICAL,
            name=key.upper(),
            properties={"mpn": f"MPN-{key}"},
        )
        for key in keys
    ]
    relations = [RelationOut(from_key=keys[0], to_key=key, type="connected_to") for key in keys[1:]]
    return SyncResult(entities=entities, relations=relations)


async def _live_rows(db: AsyncSession, source: Source) -> dict[str, GraphEntity]:
    rows = (
        (
            await db.execute(
                select(GraphEntity).where(
                    GraphEntity.source_id == source.id, GraphEntity.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.external_ref: row for row in rows if row.external_ref}


async def test_same_sync_applied_twice_across_reconnect_is_idempotent(db: AsyncSession) -> None:
    source = await _seed_source(db)
    first, errors = await apply_sync_result(db, source, _sync(["u1", "r5", "c9"]))
    assert errors == []
    await db.commit()
    before = await _live_rows(db, source)
    assert set(before) == {"u1", "r5", "c9"}
    ids_before = {ref: row.id for ref, row in before.items()}
    versions_before = {ref: row.version for ref, row in before.items()}

    # "Reconnect": a fresh session re-runs the identical sync (the companion
    # never replays old results — this is a NEW acquisition of the same state).
    second, errors = await apply_sync_result(db, source, _sync(["u1", "r5", "c9"]))
    assert errors == []
    await db.commit()
    after = await _live_rows(db, source)
    assert {ref: row.id for ref, row in after.items()} == ids_before  # same rows
    assert {ref: row.version for ref, row in after.items()} == versions_before  # untouched
    assert second.entities_created == 0
    assert second.entities_updated == 0


async def test_modified_resync_updates_in_place_and_tombstones(db: AsyncSession) -> None:
    source = await _seed_source(db)
    await apply_sync_result(db, source, _sync(["u1", "r5", "c9"]))
    await db.commit()
    before = await _live_rows(db, source)
    # Snapshot plain values — the identity map means `before` rows mutate in
    # place on the next apply.
    r5_id, r5_version = before["r5"].id, before["r5"].version

    changed = _sync(["u1", "r5"])  # c9 removed …
    changed.entities[1].properties["mpn"] = "MPN-r5-rev2"  # … r5 modified
    await apply_sync_result(db, source, changed)
    await db.commit()

    after = await _live_rows(db, source)
    assert set(after) == {"u1", "r5"}
    assert after["r5"].id == r5_id  # updated in place, not recreated
    assert after["r5"].version == r5_version + 1
    assert after["r5"].attrs["mpn"] == "MPN-r5-rev2"
    # c9 is tombstoned, not gone: living documentation (ADR-027)
    tombstone = await db.scalar(
        select(GraphEntity).where(
            GraphEntity.source_id == source.id,
            GraphEntity.external_ref == "c9",
            GraphEntity.deleted_at.is_not(None),
        )
    )
    assert tombstone is not None


async def test_reappearing_entity_keeps_exactly_one_live_row(db: AsyncSession) -> None:
    source = await _seed_source(db)
    await apply_sync_result(db, source, _sync(["u1", "c9"]))
    await db.commit()
    await apply_sync_result(db, source, _sync(["u1"]))  # tool offline sync lost c9
    await db.commit()
    await apply_sync_result(db, source, _sync(["u1", "c9"]))  # tool returns, c9 back
    await db.commit()

    live = (
        (
            await db.execute(
                select(GraphEntity).where(
                    GraphEntity.source_id == source.id,
                    GraphEntity.external_ref == "c9",
                    GraphEntity.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(live) == 1  # the partial-unique invariant, end to end
