"""Sync executor tests — state persistence, entity/relation upsert, incremental
reconciliation, and failure recording (SOLUSDEV-103 acceptance criteria)."""

import uuid

import pytest
from solus_api.connectors.contracts import (
    AccountInfo,
    AuthKind,
    Connector,
    ConnectorError,
    Credentials,
    Domain,
    EntityOut,
    RelationOut,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.runtime import run_sync
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.fingerprint.contract import SourceRef
from solus_api.models import (
    GraphEdge,
    GraphEntity,
    JobStatus,
    Project,
    Source,
    SourceStatus,
    SourceType,
    Sync,
    SyncTrigger,
    Team,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


class ScriptedConnector(Connector):
    """Returns a queued list of SyncResults (or raises) across successive syncs."""

    provider = "fake"
    auth_kind = AuthKind.PAT

    def __init__(self, results: list[SyncResult | Exception]) -> None:
        self._results = results
        self._i = 0

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        return AccountInfo(external_id="1", login="octo")

    async def sync(self, ctx: SyncContext) -> SyncResult:
        item = self._results[self._i]
        self._i += 1
        if isinstance(item, Exception):
            raise item
        return item

    async def detect_changes(self, ctx: SyncContext) -> bool:
        return True


def _entity(key: str, name: str | None = None) -> EntityOut:
    return EntityOut(source_key=key, type="code_file", domain=Domain.CODE, name=name or key)


async def _seed_source(
    maker: async_sessionmaker[AsyncSession], store: InMemorySecretStore
) -> Source:
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
            type=SourceType.GITHUB,
            name="octo/r",
            status=SourceStatus.CONNECTED,
            config={"repo": "octo/r", "branch": "main"},
            secret_ref=f"source/{uuid.uuid4()}",
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
    await store.put(source.secret_ref or "", "tok")
    return source


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_sync_persists_entities_and_relations(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    result = SyncResult(
        entities=[_entity("pkg"), _entity("pkg/a.py")],
        relations=[RelationOut(from_key="pkg", to_key="pkg/a.py", type="contains")],
        cursor={"sha": "abc"},
    )
    connector = ScriptedConnector([result])

    sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )

    async with maker() as db:
        sync = await db.get(Sync, sync_id)
        assert sync is not None
        assert sync.status == JobStatus.SUCCEEDED
        assert sync.entities_created == 2
        assert sync.relations_created == 1
        assert sync.trigger == SyncTrigger.MANUAL
        entities = (
            await db.scalars(select(GraphEntity).where(GraphEntity.source_id == source.id))
        ).all()
        assert {e.external_ref for e in entities} == {"pkg", "pkg/a.py"}
        rel_count = await db.scalar(
            select(func.count()).select_from(GraphEdge).where(GraphEdge.source_id == source.id)
        )
        assert rel_count == 1
        refreshed = await db.get(Source, source.id)
        assert refreshed is not None
        assert refreshed.status == SourceStatus.CONNECTED
        assert refreshed.cursor == {"sha": "abc"}
        assert refreshed.last_synced_at is not None


async def test_resync_updates_and_reconciles(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    first = SyncResult(
        entities=[_entity("pkg"), _entity("pkg/a.py"), _entity("pkg/old.py")],
        relations=[RelationOut(from_key="pkg", to_key="pkg/a.py", type="contains")],
        cursor={"sha": "1"},
    )
    # second sync: a.py renamed, old.py removed, new.py added; relation changes.
    second = SyncResult(
        entities=[_entity("pkg"), _entity("pkg/a.py", name="renamed.py"), _entity("pkg/new.py")],
        relations=[RelationOut(from_key="pkg", to_key="pkg/new.py", type="contains")],
        cursor={"sha": "2"},
    )
    connector = ScriptedConnector([first, second])

    await run_sync(source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store)
    second_sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )

    async with maker() as db:
        active = (
            await db.scalars(
                select(GraphEntity).where(
                    GraphEntity.source_id == source.id, GraphEntity.deleted_at.is_(None)
                )
            )
        ).all()
        by_key = {e.external_ref: e for e in active}
        assert set(by_key) == {"pkg", "pkg/a.py", "pkg/new.py"}  # old.py soft-deleted away
        assert by_key["pkg/a.py"].name == "renamed.py"
        assert by_key["pkg/a.py"].version == 2  # bumped on update
        # A4: stale rows are soft-deleted (ADR-027 living-doc), not physically removed.
        old = await db.scalar(
            select(GraphEntity).where(
                GraphEntity.source_id == source.id, GraphEntity.external_ref == "pkg/old.py"
            )
        )
        assert old is not None and old.deleted_at is not None
        sync = await db.get(Sync, second_sync_id)
        assert sync is not None
        assert sync.entities_updated >= 1
        assert sync.relations_created == 1
        assert sync.relations_deleted == 1


async def test_sync_records_connector_failure(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    connector = ScriptedConnector([ConnectorError("repo_not_found", "no such repo")])

    sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )

    async with maker() as db:
        sync = await db.get(Sync, sync_id)
        assert sync is not None
        assert sync.status == JobStatus.FAILED
        assert sync.errors and sync.errors[0]["message"] == "no such repo"
        source_row = await db.get(Source, source.id)
        assert source_row is not None
        assert source_row.status == SourceStatus.ERROR
        assert source_row.last_error is not None
        assert source_row.last_error["code"] == "repo_not_found"


async def test_sync_failure_never_echoes_internal_exception_text(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Non-ConnectorError failures store a generic message — raw exception text
    can carry SQL, bound params, or ingested content (SOLUSDEV-114 security
    review MEDIUM-1); the detail belongs in server logs only."""
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    internal = "INSERT INTO graph_entity VALUES ('secret-ingested-content')"
    connector = ScriptedConnector([RuntimeError(internal)])

    sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )

    async with maker() as db:
        source_row = await db.get(Source, source.id)
        sync = await db.get(Sync, sync_id)
        assert source_row is not None and source_row.last_error is not None
        assert sync is not None
        assert source_row.last_error["code"] == "sync_error"
        assert internal not in source_row.last_error["message"]
        assert source_row.last_error["message"]  # still human-readable, not empty
        assert all(internal not in e["message"] for e in sync.errors)


async def test_sync_failure_bounds_connector_error_size(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Connector-authored errors pass through but bounded (§7 — bound message
    sizes; SOLUSDEV-114 security review MEDIUM-2)."""
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    connector = ScriptedConnector([ConnectorError("x" * 1_000, "m" * 100_000)])

    await run_sync(source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store)

    async with maker() as db:
        source_row = await db.get(Source, source.id)
        assert source_row is not None and source_row.last_error is not None
        assert len(source_row.last_error["code"]) <= 128
        assert len(source_row.last_error["message"]) <= 1024


async def test_sync_fails_without_credentials(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    store = InMemorySecretStore()  # secret never put
    source = await _seed_source(maker, store)
    await store.delete(source.secret_ref or "")
    connector = ScriptedConnector([SyncResult()])

    sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )
    async with maker() as db:
        sync = await db.get(Sync, sync_id)
        assert sync is not None
        assert sync.status == JobStatus.FAILED


async def test_sync_with_vanished_secret_reports_actionable_error(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """A source whose secret_ref points at a missing secret (e.g. stored in the
    in-memory dev store before a restart) must surface an actionable
    missing-credentials error, not the generic internal-sync-error message."""
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    await store.delete(source.secret_ref or "")
    connector = ScriptedConnector([SyncResult()])

    await run_sync(source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store)

    async with maker() as db:
        source_row = await db.get(Source, source.id)
        assert source_row is not None and source_row.last_error is not None
        assert source_row.last_error["code"] == "missing_credentials"
        assert "reconnect" in source_row.last_error["message"].lower()
        # The opaque ref must not leak into the client-visible message.
        assert (source.secret_ref or "") not in source_row.last_error["message"]


async def test_auth_none_connector_syncs_without_stored_credentials(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    # SOLUSDEV-100 (Phase 4 review): a committed-export source (auth_kind NONE)
    # has no secret_ref by design — run_sync must not demand one.
    from fixtures.kicad_sample import KICAD_XML
    from solus_api.connectors.kicad import KicadConnector

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
            type=SourceType.KICAD,
            name="power-board",
            status=SourceStatus.CONNECTED,
            config={"export": KICAD_XML},
            secret_ref=None,
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)

    sync_id = await run_sync(
        source_id=source.id,
        sessionmaker=maker,
        connector=KicadConnector(),
        secret_store=InMemorySecretStore(),
    )

    async with maker() as db:
        sync = await db.get(Sync, sync_id)
        assert sync is not None
        assert sync.status == JobStatus.SUCCEEDED
        assert sync.entities_created == 6  # 3 components + 3 nets
        assert sync.relations_created == 6


async def test_resync_updates_changed_edge_metadata(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """An edge whose (src, dst, type) key is unchanged but whose properties moved is
    updated in place, not frozen at first-write (regression guard for the relation
    reconcile update branch — domain_pair/attrs must not go stale)."""
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    first = SyncResult(
        entities=[_entity("pkg"), _entity("pkg/a.py")],
        relations=[
            RelationOut(from_key="pkg", to_key="pkg/a.py", type="contains", properties={"n": 1})
        ],
    )
    second = SyncResult(
        entities=[_entity("pkg"), _entity("pkg/a.py")],
        relations=[
            RelationOut(from_key="pkg", to_key="pkg/a.py", type="contains", properties={"n": 2})
        ],
    )
    connector = ScriptedConnector([first, second])
    await run_sync(source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store)
    await run_sync(source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store)

    async with maker() as db:
        edge = await db.scalar(
            select(GraphEdge).where(
                GraphEdge.source_id == source.id, GraphEdge.deleted_at.is_(None)
            )
        )
        assert edge is not None
        assert edge.attrs == {"n": 2}  # updated in place, not frozen at {"n": 1}


async def test_resync_readd_after_soft_delete_creates_fresh_row(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Re-emitting a previously soft-deleted external_ref lands a fresh LIVE row
    beside the tombstone. The partial-unique (source_id, external_ref) WHERE
    deleted_at IS NULL must not collide or resurrect — this is the isolation-safe
    re-sync property."""
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    connector = ScriptedConnector(
        [
            SyncResult(entities=[_entity("keep"), _entity("gone")], cursor={"sha": "1"}),
            SyncResult(entities=[_entity("keep")], cursor={"sha": "2"}),  # gone → soft-deleted
            SyncResult(
                entities=[_entity("keep"), _entity("gone")], cursor={"sha": "3"}
            ),  # re-added
        ]
    )
    for _ in range(3):
        await run_sync(
            source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
        )

    async with maker() as db:
        gone = (
            await db.scalars(
                select(GraphEntity).where(
                    GraphEntity.source_id == source.id, GraphEntity.external_ref == "gone"
                )
            )
        ).all()
        assert len(gone) == 2  # tombstone + fresh live row, no IntegrityError
        assert sum(1 for g in gone if g.deleted_at is None) == 1  # exactly one live


async def test_sync_persists_modality_hints_and_linchpin(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Decision B guarantees, end to end.

    Guarantee 1 (identity linchpin): a connector-written entity's `source_key` lands as
    `graph_entity.external_ref`, and the fingerprint's `SourceRef` keyed on that same
    `external_ref` is resolvable. Guarantee 2 (modality channel): `EntityOut.modality_hints`
    is persisted to its own `graph_entity.modality_hints` column for the matcher.
    """
    store = InMemorySecretStore()
    source = await _seed_source(maker, store)
    hints = {"part_number": "LM358", "schematic_symbol": "Amplifier_Operational:LM358"}
    result = SyncResult(
        entities=[
            EntityOut(
                source_key="U1",
                type="component",
                domain=Domain.ELECTRICAL,
                name="U1",
                modality_hints=hints,
            )
        ],
        cursor={"sha": "abc"},
    )
    await run_sync(
        source_id=source.id,
        sessionmaker=maker,
        connector=ScriptedConnector([result]),
        secret_store=store,
    )

    async with maker() as db:
        entity = await db.scalar(
            select(GraphEntity).where(
                GraphEntity.source_id == source.id, GraphEntity.deleted_at.is_(None)
            )
        )
        assert entity is not None
        assert entity.external_ref == "U1"  # linchpin: source_key ≡ external_ref
        assert entity.modality_hints == hints  # persisted to its own column
        # The linchpin's far end: a fingerprint SourceRef on the same external_ref is resolvable
        # (source_connector + external_ref identify exactly this graph row).
        ref = SourceRef(source_connector=entity.source_connector, external_ref=entity.external_ref)
        assert ref.external_ref == entity.external_ref
