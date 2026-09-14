"""Approved enum expansion and lossless rollback on isolated PostgreSQL."""

import uuid

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError
from test_hardware_data_migration import MigrationDatabase
from test_hardware_data_migration import _schema as _schema
from test_hardware_data_migration import migration_db as migration_db

PREVIOUS = "a26000000005"
REVISION = "a26100000001"


def _insert(db: MigrationDatabase, *, tool: str, surface: str, effect: str) -> None:
    db.execute(
        "INSERT INTO tool_knowledge (id,tool,version_range,surface,control_id,label,effect,"
        "description,provenance,status,acquired_via,confidence,confirm_count,reject_count,"
        "version_min_key,created_at,updated_at) VALUES (:id,:tool,'>=1.0.0',:surface,"
        "'fixture.command','Fixture',:effect,'Vendor fixture','vendor_docs','published',"
        "'docs',1,0,0,'00001.00000.00000',now(),now())",
        {"id": uuid.uuid4(), "tool": tool, "surface": surface, "effect": effect},
    )


def test_upgrade_preserves_rows_and_accepts_approved_values(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(PREVIOUS)
    _insert(migration_db, tool="kicad", surface="menu", effect="settings")
    before = migration_db.rows("SELECT * FROM tool_knowledge")
    migration_db.upgrade(REVISION)
    assert migration_db.rows("SELECT * FROM tool_knowledge") == before
    _insert(migration_db, tool="code", surface="terminal", effect="execute")
    _insert(migration_db, tool="isaac", surface="toolbar", effect="create_feature")
    assert migration_db.rows("SELECT count(*) AS n FROM tool_knowledge")[0]["n"] == 3


@pytest.mark.parametrize("field", ["tool", "surface", "effect"])
def test_unknown_values_remain_rejected(migration_db: MigrationDatabase, field: str) -> None:
    migration_db.upgrade(REVISION)
    values = {"tool": "code", "surface": "terminal", "effect": "execute", field: "arbitrary"}
    with pytest.raises(IntegrityError):
        _insert(migration_db, **values)
    assert migration_db.rows("SELECT count(*) AS n FROM tool_knowledge")[0]["n"] == 0


@pytest.mark.parametrize(
    "values",
    [
        {"tool": "code", "surface": "menu", "effect": "settings"},
        {"tool": "isaac", "surface": "menu", "effect": "settings"},
        {"tool": "kicad", "surface": "terminal", "effect": "settings"},
        {"tool": "kicad", "surface": "menu", "effect": "execute"},
    ],
)
def test_downgrade_refuses_used_values_without_deleting_rows(
    migration_db: MigrationDatabase, values: dict[str, str]
) -> None:
    migration_db.upgrade(REVISION)
    _insert(migration_db, **values)
    # Tombstones still contain knowledge; a rollback must not silently discard them.
    migration_db.execute("UPDATE tool_knowledge SET deleted_at=now()")
    before = migration_db.rows("SELECT * FROM tool_knowledge")
    with pytest.raises(RuntimeError, match="new tool knowledge enum values"):
        command.downgrade(migration_db.config, PREVIOUS)
    assert migration_db.rows("SELECT * FROM tool_knowledge") == before
    assert (
        migration_db.rows("SELECT version_num FROM alembic_version")[0]["version_num"] == REVISION
    )
    _insert(migration_db, tool="code", surface="terminal", effect="execute")


def test_downgrade_restores_old_checks_without_changing_rows(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(REVISION)
    _insert(migration_db, tool="kicad", surface="menu", effect="settings")
    before = migration_db.rows("SELECT * FROM tool_knowledge")
    command.downgrade(migration_db.config, PREVIOUS)
    assert migration_db.rows("SELECT * FROM tool_knowledge") == before
    for values in (
        {"tool": "code", "surface": "menu", "effect": "settings"},
        {"tool": "isaac", "surface": "menu", "effect": "settings"},
        {"tool": "kicad", "surface": "terminal", "effect": "settings"},
        {"tool": "kicad", "surface": "menu", "effect": "execute"},
    ):
        with pytest.raises(IntegrityError):
            _insert(migration_db, **values)
