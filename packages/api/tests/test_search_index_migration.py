"""a32000000004 (SOLUSDEV-320 T7): the search index migration replays the same way every time.

The revision carries FROZEN copies of the search SQL and the origin vocabulary; this module
proves the frozen copies still equal the live ones (a later change needs a NEW migration, not
an edit to history), and exercises the data step on a real Alembic upgrade.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import Iterator
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import asyncpg
import pytest
from alembic.config import Config
from solus_api.graph import search_text as live
from solus_api.models import Project, Team
from solus_contracts.relations import EdgeOrigin
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_hardware_data_migration import MigrationDatabase, _migration_url

API_DIR = Path(__file__).resolve().parents[1]
PREVIOUS = "a32000000003"
REVISION = "a32000000004"
MIGRATION = API_DIR / "migrations" / "versions" / f"{REVISION}_solusdev_320_search_index.py"


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """Never let the shared suite schema fixture migrate this module's database."""


def _load_migration() -> ModuleType:
    spec = spec_from_file_location("solus_search_index_320", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def search_index_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[MigrationDatabase]:
    url = _migration_url(
        os.environ["SOLUS_TEST_DATABASE_URL"], os.environ.get("PYTEST_XDIST_WORKER", "master")
    )
    name = url.database
    assert name is not None
    admin = url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )

    async def ensure_database() -> None:
        connection = await asyncpg.connect(admin)
        try:
            if not await connection.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", name):
                await connection.execute(f'CREATE DATABASE "{name}"')
        finally:
            await connection.close()

    asyncio.run(ensure_database())
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.set_main_option("prepend_sys_path", str(API_DIR))
    monkeypatch.setenv("SOLUS_DATABASE_URL", url.render_as_string(hide_password=False))
    db = MigrationDatabase(url.render_as_string(hide_password=False), cfg)
    try:
        db.reset()
        db.upgrade(PREVIOUS)
        yield db
    finally:
        db.reset()


def _seed_recognition_edge(db: MigrationDatabase, origin: str) -> uuid.UUID:
    """A pre-index project with one `origin=<origin>` edge, inserted by SQL: the ORM model
    now carries the generated search columns, which this revision's schema lacks."""

    async def seed() -> uuid.UUID:
        engine = create_async_engine(db.url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                team = Team(name="search index")
                session.add(team)
                await session.flush()
                project = Project(team_id=team.id, name="search index")
                session.add(project)
                await session.commit()
                return project.id
        finally:
            await engine.dispose()

    project_id = asyncio.run(seed())
    src, dst, edge = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for entity_id, name in ((src, "U1"), (dst, "net:+3V3")):
        db.execute(
            "INSERT INTO graph_entity (id, project_id, kind, domain, name, origin, version, "
            "attrs, modality_hints, created_at, updated_at) VALUES (:id, :pid, 'component', "
            "'electrical', :name, 'connector', 1, '{}', '{}', now(), now())",
            {"id": entity_id, "pid": project_id, "name": name},
        )
    db.execute(
        "INSERT INTO graph_edge (id, project_id, src_id, dst_id, relation_type, domain_pair, "
        "confidence, origin, attrs, created_at, updated_at) VALUES (:id, :pid, :src, :dst, "
        "'connected_to', 'electrical<->electrical', 1.0, :origin, '{}', now(), now())",
        {"id": edge, "pid": project_id, "src": src, "dst": dst, "origin": origin},
    )
    return edge


def test_frozen_sql_and_origins_still_equal_the_live_definitions() -> None:
    """Fails when the live search SQL or EdgeOrigin changes: write a NEW migration."""
    module = _load_migration()
    assert module.FROZEN_PAYLOAD_TEXT_STATEMENTS == live.SOLUS_PAYLOAD_TEXT_STATEMENTS
    assert module.FROZEN_COLUMNS == (
        ("graph_entity", live.ENTITY_SEARCH_SQL, live.ENTITY_SEARCH_TSV_SQL),
        ("solus_entries", live.ENTRY_SEARCH_SQL, live.ENTRY_SEARCH_TSV_SQL),
    )
    assert module.FROZEN_ORIGINS == tuple(origin.value for origin in EdgeOrigin)
    assert "search_path" in module.FROZEN_PAYLOAD_TEXT_STATEMENTS[0]


def test_upgrade_builds_the_index_and_rewrites_recognition_origins(
    search_index_db: MigrationDatabase,
) -> None:
    edge = _seed_recognition_edge(search_index_db, "recognition")
    search_index_db.upgrade(REVISION)
    [row] = search_index_db.rows(f"SELECT origin FROM graph_edge WHERE id = '{edge}'")  # noqa: S608 — a uuid this test minted
    assert row["origin"] == "system"
    indexes = {
        r["indexname"]: r["indexdef"]
        for r in search_index_db.rows(
            "SELECT indexname, indexdef FROM pg_indexes WHERE indexname LIKE 'ix_%search%' "
            "OR indexname LIKE 'ix_%trgm'"
        )
    }
    assert indexes == {
        "ix_graph_entity_search_tsv": (
            "CREATE INDEX ix_graph_entity_search_tsv ON public.graph_entity USING gin (search_tsv)"
        ),
        "ix_graph_entity_name_trgm": (
            "CREATE INDEX ix_graph_entity_name_trgm ON public.graph_entity "
            "USING gin (name gin_trgm_ops)"
        ),
        "ix_solus_entries_search_tsv": (
            "CREATE INDEX ix_solus_entries_search_tsv ON public.solus_entries "
            "USING gin (search_tsv)"
        ),
        "ix_solus_entries_search_text_trgm": (
            "CREATE INDEX ix_solus_entries_search_text_trgm ON public.solus_entries "
            "USING gin (search_text gin_trgm_ops)"
        ),
    }
    texts = search_index_db.rows("SELECT search_text FROM graph_entity")
    assert {r["search_text"] for r in texts} == {"U1", "net:+3V3"}


def test_upgrade_refuses_an_origin_outside_the_vocabulary(
    search_index_db: MigrationDatabase,
) -> None:
    _seed_recognition_edge(search_index_db, "linking")
    with pytest.raises(RuntimeError, match="outside EdgeOrigin"):
        search_index_db.upgrade(REVISION)
