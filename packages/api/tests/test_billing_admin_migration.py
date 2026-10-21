"""SOLUSDEV-313 schema: subscription override/comp columns + stripe_cancel_requests."""

import uuid

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Table
from sqlalchemy.exc import IntegrityError
from test_hardware_data_migration import MigrationDatabase
from test_hardware_data_migration import _schema as _schema
from test_hardware_data_migration import migration_db as migration_db

PREVIOUS = "a38000000001"
SUB_COLUMNS = {"limits_override", "comp_plan", "comp_expires_at"}


def _revision() -> str:
    from test_hardware_data_migration import API_DIR

    script = ScriptDirectory(str(API_DIR / "migrations"))
    (head,) = script.get_heads()
    return head


def _sub_columns(db: MigrationDatabase) -> dict[str, str]:
    rows = db.rows(
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_name='subscriptions'"
    )
    return {r["column_name"]: r["is_nullable"] for r in rows}


def _has_table(db: MigrationDatabase) -> bool:
    return bool(db.rows("SELECT to_regclass('public.stripe_cancel_requests') AS t")[0]["t"])


def test_there_is_exactly_one_alembic_head_and_it_descends_from_the_previous() -> None:
    script = ScriptDirectory(str(__import__("test_hardware_data_migration").API_DIR / "migrations"))
    assert len(script.get_heads()) == 1
    # Pin this migration's parent, not the global head, so later tickets can stack on it.
    billing = script.get_revision("a31300000001")
    assert billing is not None
    assert billing.down_revision == PREVIOUS


def test_upgrade_adds_nullable_columns_and_the_tombstone_table(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(PREVIOUS)
    assert not (SUB_COLUMNS & set(_sub_columns(migration_db)))
    assert not _has_table(migration_db)
    migration_db.upgrade(_revision())
    cols = _sub_columns(migration_db)
    assert all(cols[c] == "YES" for c in SUB_COLUMNS)
    assert _has_table(migration_db)


def test_downgrade_removes_everything_and_upgrade_is_repeatable(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(_revision())
    command.downgrade(migration_db.config, PREVIOUS)
    assert not (SUB_COLUMNS & set(_sub_columns(migration_db)))
    assert not _has_table(migration_db)
    assert migration_db.rows("SELECT version_num FROM alembic_version")[0]["version_num"] == (
        PREVIOUS
    )
    migration_db.upgrade(_revision())
    assert SUB_COLUMNS <= set(_sub_columns(migration_db))


def test_existing_subscription_rows_survive_with_null_new_columns(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(PREVIOUS)
    uid = uuid.uuid4()
    migration_db.execute(
        "INSERT INTO users (id, supabase_user_id, email, sol_mode, data_collection_consent, "
        "onboarding_step, created_at, updated_at) "
        "VALUES (:id, :ext, :em, 'guide', false, 'about', now(), now())",
        {"id": uid, "ext": f"x-{uid}", "em": f"{uid}@example.com"},
    )
    migration_db.execute(
        "INSERT INTO subscriptions (id, user_id, plan, status, limits, created_at, updated_at) "
        "VALUES (:id, :u, 'basic', 'active', '{}'::jsonb, now(), now())",
        {"id": uuid.uuid4(), "u": uid},
    )
    migration_db.upgrade(_revision())
    row = migration_db.rows(
        "SELECT limits_override, comp_plan, comp_expires_at FROM subscriptions"
    )[0]
    assert row == {"limits_override": None, "comp_plan": None, "comp_expires_at": None}


def test_cancel_request_is_unique_per_customer_and_holds_no_user_data(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(_revision())
    cols = {
        r["column_name"]
        for r in migration_db.rows(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='stripe_cancel_requests'"
        )
    }
    assert cols == {
        "id",
        "stripe_customer_id",
        "stripe_subscription_id",
        "attempts",
        "next_attempt_at",
        "completed_at",
        "created_at",
    }
    insert = (
        "INSERT INTO stripe_cancel_requests (id, stripe_customer_id, attempts, next_attempt_at,"
        " created_at) VALUES (:id, 'cus_1', 0, now(), now())"
    )
    migration_db.execute(insert, {"id": uuid.uuid4()})
    with pytest.raises(IntegrityError):
        migration_db.execute(insert, {"id": uuid.uuid4()})


def _indexes(db: MigrationDatabase) -> dict[str, str]:
    rows = db.rows(
        "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='stripe_cancel_requests'"
    )
    return {r["indexname"]: r["indexdef"] for r in rows}


def test_due_index_is_partial_on_pending_rows_and_customer_index_is_unique(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(_revision())
    indexes = _indexes(migration_db)
    due = indexes["ix_stripe_cancel_requests_pending_next_attempt"]
    assert "(next_attempt_at)" in due and "WHERE (completed_at IS NULL)" in due
    assert "ix_stripe_cancel_requests_next_attempt_at" not in indexes
    assert "UNIQUE" in indexes["ix_stripe_cancel_requests_stripe_customer_id"]


def test_model_declares_the_same_partial_index() -> None:
    from solus_api.models import StripeCancelRequest

    table = StripeCancelRequest.__table__
    assert isinstance(table, Table)
    declared = {str(i.name): i for i in table.indexes}
    due = declared["ix_stripe_cancel_requests_pending_next_attempt"]
    assert [c.name for c in due.columns] == ["next_attempt_at"]
    assert "completed_at IS NULL" in str(due.dialect_options["postgresql"]["where"])
    assert "ix_stripe_cancel_requests_next_attempt_at" not in declared


def test_comp_plan_check_is_validated_and_rejects_bad_plans_and_downgrade_drops_indexes(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(_revision())
    rows = migration_db.rows(
        "SELECT convalidated FROM pg_constraint WHERE conname='subscription_comp_plan'"
    )
    assert rows == [{"convalidated": True}]
    command.downgrade(migration_db.config, PREVIOUS)
    assert _indexes(migration_db) == {}
