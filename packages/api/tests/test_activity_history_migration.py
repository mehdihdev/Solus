"""a32000000005 (SOLUSDEV-320 P5-T7): `activities` gains `entity_ids` (JSONB, `'[]'`
default, GIN jsonb_path_ops), `why_ref` and the `(project_id, created_at)` index; the
downgrade removes all of it. Own scratch database, pattern `test_search_index_migration`."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from test_hardware_data_migration import MigrationDatabase, _migration_url

API_DIR = Path(__file__).resolve().parents[1]
PREVIOUS = "a32000000004"
REVISION = "a32000000005"


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """Never let the shared suite schema fixture migrate this module's database."""


@pytest.fixture
def history_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[MigrationDatabase]:
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


_COLUMNS_SQL = (
    "SELECT column_name, is_nullable FROM information_schema.columns "
    "WHERE table_name = 'activities' AND column_name IN ('entity_ids', 'why_ref') "
    "ORDER BY column_name"
)
_INDEXES_SQL = "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'activities'"


def _insert_activity(
    db: MigrationDatabase, row_id: uuid.UUID, with_entities: str | None = None
) -> None:
    columns = "id, team_id, type, payload, created_at"
    values = ":id, :team, 'sync.completed', '{}'::jsonb, now()"
    if with_entities is not None:
        columns += ", entity_ids"
        values += f", '{with_entities}'::jsonb"
    db.execute(
        f"INSERT INTO activities ({columns}) VALUES ({values})",  # noqa: S608 — test literal
        {"id": row_id, "team": uuid.uuid4()},
    )


def test_upgrade_defaults_existing_rows_indexes_and_downgrade_drops_everything(
    history_db: MigrationDatabase,
) -> None:
    before = uuid.uuid4()
    _insert_activity(history_db, before)
    assert history_db.rows(_COLUMNS_SQL) == []

    history_db.upgrade(REVISION)

    columns = {row["column_name"]: row for row in history_db.rows(_COLUMNS_SQL)}
    assert set(columns) == {"entity_ids", "why_ref"}
    assert columns["entity_ids"]["is_nullable"] == "NO"
    assert columns["why_ref"]["is_nullable"] == "YES"
    nulls = history_db.rows("SELECT count(*) AS n FROM activities WHERE entity_ids IS NULL")
    assert nulls[0]["n"] == 0
    rows = {
        row["id"]: row for row in history_db.rows("SELECT id, entity_ids, why_ref FROM activities")
    }
    assert rows[before]["entity_ids"] == [] and rows[before]["why_ref"] is None
    # A writer that predates the column (an older API during a rollout) still inserts.
    after = uuid.uuid4()
    _insert_activity(history_db, after)
    tagged = uuid.uuid4()
    tag = str(uuid.uuid4())
    _insert_activity(history_db, tagged, with_entities=f'["{tag}"]')
    rows = {row["id"]: row for row in history_db.rows("SELECT id, entity_ids FROM activities")}
    assert rows[after]["entity_ids"] == [] and rows[tagged]["entity_ids"] == [tag]
    # The containment filter the history route uses hits the GIN index's operator class.
    hit = history_db.rows(
        f"SELECT id FROM activities WHERE entity_ids @> '[\"{tag}\"]'::jsonb"  # noqa: S608
    )
    assert [row["id"] for row in hit] == [tagged]
    indexes = {row["indexname"]: row["indexdef"] for row in history_db.rows(_INDEXES_SQL)}
    assert "USING gin (entity_ids jsonb_path_ops)" in indexes["ix_activities_entity_ids"]
    assert "(project_id, created_at)" in indexes["ix_activities_project_created"]

    command.downgrade(history_db.config, PREVIOUS)
    assert history_db.rows(_COLUMNS_SQL) == []
    names = {row["indexname"] for row in history_db.rows(_INDEXES_SQL)}
    assert not {"ix_activities_entity_ids", "ix_activities_project_created"} & names
    assert history_db.rows("SELECT count(*) AS n FROM activities")[0]["n"] == 3

    # Repeatable: the upgrade applies again over the rows the downgrade kept.
    command.upgrade(history_db.config, REVISION)
    columns = {row["column_name"]: row for row in history_db.rows(_COLUMNS_SQL)}
    assert set(columns) == {"entity_ids", "why_ref"}
    rows = history_db.rows("SELECT count(*) AS n FROM activities WHERE entity_ids = '[]'::jsonb")
    assert rows[0]["n"] == 3
