"""SOLUSDEV-319 / ADR-042 schema: academic plan + grant CHECKs, academic_verifications."""

import uuid

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError
from test_hardware_data_migration import MigrationDatabase
from test_hardware_data_migration import _schema as _schema
from test_hardware_data_migration import migration_db as migration_db

PREVIOUS = "a31900000002"
REVISION = "a31900000003"


def _has_table(db: MigrationDatabase) -> bool:
    return bool(db.rows("SELECT to_regclass('public.academic_verifications') AS t")[0]["t"])


def _seed_user(db: MigrationDatabase) -> uuid.UUID:
    uid = uuid.uuid4()
    db.execute(
        "INSERT INTO users (id, supabase_user_id, email, sol_mode, data_collection_consent, "
        "onboarding_step, created_at, updated_at) "
        "VALUES (:id, :ext, :em, 'guide', false, 'about', now(), now())",
        {"id": uid, "ext": f"x-{uid}", "em": f"{uid}@example.com"},
    )
    return uid


def _academic_sub(db: MigrationDatabase, uid: uuid.UUID) -> None:
    db.execute(
        "INSERT INTO subscriptions (id, user_id, plan, status, limits, created_at, updated_at) "
        "VALUES (:id, :u, 'academic', 'active', '{}'::jsonb, now(), now())",
        {"id": uuid.uuid4(), "u": uid},
    )


def _grant(db: MigrationDatabase, uid: uuid.UUID) -> None:
    db.execute(
        "INSERT INTO credit_ledger (id, user_id, amount, type, balance_after, attrs, created_at) "
        "VALUES (:id, :u, 1000, 'academic_grant', 1000, '{}'::jsonb, now())",
        {"id": uuid.uuid4(), "u": uid},
    )


def test_previous_schema_rejects_academic(migration_db: MigrationDatabase) -> None:
    migration_db.upgrade(PREVIOUS)
    uid = _seed_user(migration_db)
    with pytest.raises(IntegrityError):
        _academic_sub(migration_db, uid)


def test_upgrade_admits_academic_rows_and_creates_the_table(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(REVISION)
    uid = _seed_user(migration_db)
    _academic_sub(migration_db, uid)
    _grant(migration_db, uid)
    assert _has_table(migration_db)


def test_verified_email_is_unique_but_pending_is_not(migration_db: MigrationDatabase) -> None:
    migration_db.upgrade(REVISION)
    insert = (
        "INSERT INTO academic_verifications (id, user_id, pending_email, verified_email, "
        "created_at, updated_at) VALUES (:id, :u, :p, :v, now(), now())"
    )
    a, b, c = (_seed_user(migration_db) for _ in range(3))
    migration_db.execute(insert, {"id": uuid.uuid4(), "u": a, "p": "x@mit.edu", "v": None})
    migration_db.execute(insert, {"id": uuid.uuid4(), "u": b, "p": "x@mit.edu", "v": "x@mit.edu"})
    with pytest.raises(IntegrityError):
        migration_db.execute(insert, {"id": uuid.uuid4(), "u": c, "p": None, "v": "x@mit.edu"})


def test_downgrade_keeps_rows_valid_and_upgrade_is_repeatable(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(REVISION)
    uid = _seed_user(migration_db)
    _academic_sub(migration_db, uid)
    _grant(migration_db, uid)
    command.downgrade(migration_db.config, PREVIOUS)
    assert not _has_table(migration_db)
    assert migration_db.rows("SELECT plan FROM subscriptions")[0]["plan"] == "basic"
    assert migration_db.rows("SELECT type FROM credit_ledger")[0]["type"] == "adjustment"
    migration_db.upgrade(REVISION)
    assert _has_table(migration_db)
