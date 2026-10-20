"""SOLUSDEV-236 schema: subscriptions.billing_interval + current_period_end."""

import uuid

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError
from test_hardware_data_migration import MigrationDatabase
from test_hardware_data_migration import _schema as _schema
from test_hardware_data_migration import migration_db as migration_db

REVISION = "a23600000001"
PREVIOUS = "a21600000001"
NEW_COLUMNS = {"billing_interval", "current_period_end"}


def _sub_columns(db: MigrationDatabase) -> dict[str, str]:
    rows = db.rows(
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_name='subscriptions'"
    )
    return {r["column_name"]: r["is_nullable"] for r in rows}


def _insert_user(db: MigrationDatabase) -> uuid.UUID:
    uid = uuid.uuid4()
    db.execute(
        "INSERT INTO users (id, supabase_user_id, email, sol_mode, data_collection_consent, "
        "onboarding_step, created_at, updated_at) "
        "VALUES (:id, :ext, :em, 'guide', false, 'about', now(), now())",
        {"id": uid, "ext": f"x-{uid}", "em": f"{uid}@example.com"},
    )
    return uid


def _insert_sub(db: MigrationDatabase, user: uuid.UUID, interval: str | None) -> None:
    db.execute(
        "INSERT INTO subscriptions (id, user_id, plan, status, limits, billing_interval, "
        "created_at, updated_at) "
        "VALUES (:id, :u, 'basic', 'active', '{}'::jsonb, :i, now(), now())",
        {"id": uuid.uuid4(), "u": user, "i": interval},
    )


def test_migration_descends_from_previous_head() -> None:
    from test_hardware_data_migration import API_DIR

    script = ScriptDirectory(str(API_DIR / "migrations"))
    assert len(script.get_heads()) == 1
    rev = script.get_revision(REVISION)
    assert rev is not None
    assert rev.down_revision == PREVIOUS


def test_upgrade_adds_nullable_columns(migration_db: MigrationDatabase) -> None:
    migration_db.upgrade(PREVIOUS)
    assert not (NEW_COLUMNS & set(_sub_columns(migration_db)))
    migration_db.upgrade(REVISION)
    cols = _sub_columns(migration_db)
    assert all(cols[c] == "YES" for c in NEW_COLUMNS)


def test_downgrade_drops_columns_and_check_and_is_repeatable(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(REVISION)
    command.downgrade(migration_db.config, PREVIOUS)
    assert not (NEW_COLUMNS & set(_sub_columns(migration_db)))
    assert not migration_db.rows(
        "SELECT 1 FROM pg_constraint WHERE conname='ck_subscriptions_billing_interval'"
    )
    migration_db.upgrade(REVISION)
    assert NEW_COLUMNS <= set(_sub_columns(migration_db))


def test_existing_rows_survive_with_null_columns(migration_db: MigrationDatabase) -> None:
    migration_db.upgrade(PREVIOUS)
    uid = _insert_user(migration_db)
    migration_db.execute(
        "INSERT INTO subscriptions (id, user_id, plan, status, limits, created_at, updated_at) "
        "VALUES (:id, :u, 'basic', 'active', '{}'::jsonb, now(), now())",
        {"id": uuid.uuid4(), "u": uid},
    )
    migration_db.upgrade(REVISION)
    row = migration_db.rows("SELECT billing_interval, current_period_end FROM subscriptions")[0]
    assert row == {"billing_interval": None, "current_period_end": None}


@pytest.mark.parametrize("value", ["month", "year", None])
def test_check_accepts_month_year_and_null(
    migration_db: MigrationDatabase, value: str | None
) -> None:
    migration_db.upgrade(REVISION)
    _insert_sub(migration_db, _insert_user(migration_db), value)


@pytest.mark.parametrize("value", ["week", "", "Month"])
def test_check_rejects_other_intervals(migration_db: MigrationDatabase, value: str) -> None:
    migration_db.upgrade(REVISION)
    with pytest.raises(IntegrityError):
        _insert_sub(migration_db, _insert_user(migration_db), value)
