"""Constraint and transaction locking proof on dedicated migration databases."""

import asyncio
import re
import uuid

import asyncpg
import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from test_hardware_data_migration import HEAD, PREVIOUS, MigrationDatabase
from test_hardware_data_migration import _schema as _schema
from test_hardware_data_migration import migration_db as migration_db


@pytest.mark.parametrize("fault", ["duplicate", "negative", "nonconfig"])
def test_constraints_reject_invalid_rows(migration_db: MigrationDatabase, fault: str) -> None:
    migration_db.seed()
    migration_db.upgrade()
    with pytest.raises(IntegrityError):
        if fault == "duplicate":
            migration_db.execute(
                "INSERT INTO solus_entries(id,project_id,section,kind,entity_id,"
                "configured_entity_id,config_version,payload,author,created_at,updated_at) "
                "SELECT :id,project_id,section,kind,entity_id,configured_entity_id,"
                "config_version,payload,author,created_at,updated_at FROM solus_entries LIMIT 1",
                {"id": uuid.uuid4()},
            )
        elif fault == "negative":
            migration_db.execute("UPDATE solus_entries SET config_version=-1")
        else:
            migration_db.execute("UPDATE solus_entries SET kind='text'")
    assert migration_db.rows("SELECT count(*) AS n FROM solus_entries")[0]["n"] == 3
    script = ScriptDirectory.from_config(migration_db.config)
    assert len(script.get_heads()) == 1
    assert HEAD in {revision.revision for revision in script.walk_revisions()}


def test_backfill_waits_for_existing_writer_and_fails_atomically(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.seed()

    async def blocked_upgrade() -> None:
        connection = await asyncpg.connect(migration_db.url.replace("+asyncpg", ""))
        try:
            await connection.execute("BEGIN")
            await connection.execute("UPDATE projects SET name=name")
            with pytest.raises(DBAPIError):
                await asyncio.to_thread(migration_db.upgrade)
        finally:
            await connection.execute("ROLLBACK")
            await connection.close()

    asyncio.run(blocked_upgrade())
    assert (
        migration_db.rows("SELECT version_num FROM alembic_version")[0]["version_num"] == PREVIOUS
    )
    assert (
        migration_db.rows("SELECT configured_entity_id FROM solus_entries")[0][
            "configured_entity_id"
        ]
        is None
    )


def test_concurrent_first_config_has_one_winner(migration_db: MigrationDatabase) -> None:
    ids = migration_db.seed()
    migration_db.upgrade()
    subject = uuid.uuid4()
    migration_db.execute(
        "INSERT INTO graph_entity(id,project_id,kind,domain,name,origin,version,attrs,"
        "modality_hints,created_at,updated_at) VALUES (:id,:project,'part','project',"
        "'Race fixture','manual',1,'{}','{}',now(),now())",
        {"id": subject, "project": ids["project"]},
    )

    async def race() -> None:
        engine = create_async_engine(migration_db.url)
        insert = text(
            "INSERT INTO solus_entries(id,project_id,section,kind,entity_id,"
            "configured_entity_id,config_version,payload,author,created_at,updated_at) "
            "VALUES (:id,:project,'hardware','config',:node,:subject,1,'{}','user',now(),now())"
        )
        params = {"project": ids["project"], "node": ids["node"], "subject": subject}
        try:
            async with engine.connect() as first, engine.connect() as second:
                await first.execute(insert, {**params, "id": uuid.uuid4()})
                started = asyncio.Event()

                async def competitor() -> None:
                    started.set()
                    await second.execute(insert, {**params, "id": uuid.uuid4()})

                pending = asyncio.create_task(competitor())
                await started.wait()
                await asyncio.sleep(0.1)
                assert not pending.done()
                await first.commit()
                with pytest.raises(IntegrityError):
                    await pending
                await second.rollback()
        finally:
            await engine.dispose()

    asyncio.run(race())
    assert migration_db.rows("SELECT count(*) AS n FROM solus_entries")[0]["n"] == 4


@pytest.mark.parametrize("name", ["solus", "postgres", "solus_test_bad-name", "solus_test_"])
def test_migration_database_rejects_unsafe_base(name: str) -> None:
    from test_hardware_data_migration import _migration_url

    with pytest.raises(ValueError, match="test database"):
        _migration_url(f"postgresql+asyncpg://localhost/{name}", "gw0")


def test_migration_database_scope_separates_runs_and_workers() -> None:
    from test_hardware_data_migration import _migration_url

    base = "postgresql+asyncpg://localhost/solus_test_fixture_run_a"
    first = _migration_url(base, "gw0")
    assert first == _migration_url(base, "gw0")
    assert first != _migration_url(base, "gw1")
    assert first != _migration_url(base.replace("run_a", "run_b"), "gw0")
    assert first.database != "solus_test_fixture_run_a"
    assert first.database is not None and len(first.database) <= 63


@pytest.mark.parametrize("name", ["solus_test", "solus_test_fixture_run_a"])
@pytest.mark.parametrize("worker", ["master", "gw0"])
def test_migration_database_accepts_ci_and_scoped_test_bases(name: str, worker: str) -> None:
    from test_hardware_data_migration import _migration_url

    base = f"postgresql+asyncpg://localhost/{name}"
    target = _migration_url(base, worker)
    assert target.database != name
    assert re.fullmatch(r"solus_test_migration_[0-9a-f]{32}", target.database or "")
    assert target == _migration_url(base, worker)
    assert target != _migration_url(base, "gw1")
    assert target.drivername == "postgresql+asyncpg"
    assert target.host == "localhost"


@pytest.mark.parametrize("worker", ["", "main", "gw", "gw-1", "gw0/other"])
def test_migration_database_rejects_unsafe_workers(worker: str) -> None:
    from test_hardware_data_migration import _migration_url

    with pytest.raises(ValueError, match="test database"):
        _migration_url("postgresql+asyncpg://localhost/solus_test_fixture", worker)


@pytest.mark.parametrize("driver", ["postgresql", "postgresql+psycopg", "sqlite"])
def test_migration_database_rejects_other_drivers(driver: str) -> None:
    from test_hardware_data_migration import _migration_url

    with pytest.raises(ValueError, match="test database"):
        _migration_url(f"{driver}://localhost/solus_test_fixture", "gw0")


def test_migration_schema_reset_removes_previous_case_state(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.seed()
    migration_db.upgrade()
    migration_db.execute("CREATE TABLE previous_case_sentinel(id integer)")
    migration_db.reset()
    assert (
        migration_db.rows("SELECT to_regclass('previous_case_sentinel') AS value")[0]["value"]
        is None
    )
    assert migration_db.rows("SELECT to_regclass('alembic_version') AS value")[0]["value"] is None
    migration_db.upgrade(PREVIOUS)
    assert migration_db.rows("SELECT count(*) AS n FROM solus_entries")[0]["n"] == 0


@pytest.mark.parametrize(
    "name", ["solus", "solus_test", "solus_test_fixture_run_a", "solus_test_migration_fake"]
)
def test_schema_reset_refuses_non_migration_targets(name: str) -> None:
    from alembic.config import Config

    database = MigrationDatabase(f"postgresql+asyncpg://localhost/{name}", Config())
    with pytest.raises(ValueError, match="Refusing schema reset"):
        database.reset()


@pytest.mark.parametrize("key", ["database", "dbname"])
def test_migration_database_rejects_query_overrides(key: str) -> None:
    from alembic.config import Config
    from test_hardware_data_migration import _migration_url

    with pytest.raises(ValueError, match="test database"):
        _migration_url(f"postgresql+asyncpg://localhost/solus_test_fixture?{key}=solus", "gw0")
    target = "solus_test_migration_" + "a" * 32
    database = MigrationDatabase(f"postgresql+asyncpg://localhost/{target}?{key}=solus", Config())
    with pytest.raises(ValueError, match="Refusing schema reset"):
        database.reset()
