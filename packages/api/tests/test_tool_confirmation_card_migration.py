"""a32600000002 (SOLUSDEV-326): `tool_confirmations.card`, the card a parked call shows.

A nullable JSONB column (docs/contracts/action-gate.md §Cards 1): an existing row keeps no card,
a new one may carry the Solus-authored card, and the downgrade drops the column again.
"""

from __future__ import annotations

import json
import uuid

from alembic import command
from alembic.script import ScriptDirectory
from test_hardware_data_migration import API_DIR, MigrationDatabase
from test_hardware_data_migration import _schema as _schema
from test_hardware_data_migration import migration_db as migration_db

PREVIOUS = "a32600000001"
REVISION = "a32600000002"
CARD = {"kind": "offer", "title": "A board is plugged in", "primary": "Look", "resumes": True}


def _card_column_shape(db: MigrationDatabase) -> dict[str, str] | None:
    rows = db.rows(
        "SELECT data_type, is_nullable FROM information_schema.columns "
        "WHERE table_name='tool_confirmations' AND column_name='card'"
    )
    return rows[0] if rows else None


def _seed_parked_row(db: MigrationDatabase, card: dict[str, object] | None) -> uuid.UUID:
    """A pending confirmation under a fresh user, team and project, inserted by SQL."""
    user, team, project, row = (uuid.uuid4() for _ in range(4))
    db.execute(
        "INSERT INTO users (id, supabase_user_id, email, sol_mode, data_collection_consent, "
        "onboarding_step, created_at, updated_at) "
        "VALUES (:id, :ext, :em, 'guide', false, 'about', now(), now())",
        {"id": user, "ext": f"x-{user}", "em": f"{user}@example.com"},
    )
    db.execute(
        "INSERT INTO teams (id, name, kind, plan_status, settings, created_at, updated_at) "
        "VALUES (:id, 'T', 'collaborative', 'trial', '{}', now(), now())",
        {"id": team},
    )
    db.execute(
        "INSERT INTO projects (id, team_id, name, created_at, updated_at) "
        "VALUES (:id, :team, 'P', now(), now())",
        {"id": project, "team": team},
    )
    columns = "id, project_id, team_id, user_id, tool, args, summary, preview, status, expires_at"
    values = ":id, :project, :team, :user, 'ask_user', '{}', 'Q', '[]', 'pending', now()"
    params: dict[str, object] = {"id": row, "project": project, "team": team, "user": user}
    if card is not None:
        columns, values = f"{columns}, card", f"{values}, CAST(:card AS jsonb)"
        params["card"] = json.dumps(card)
    db.execute(
        f"INSERT INTO tool_confirmations ({columns}, created_at, updated_at) "
        f"VALUES ({values}, now(), now())",
        params,
    )
    return row


def test_the_revision_descends_from_the_previous_head_and_is_the_only_head() -> None:
    script = ScriptDirectory(str(API_DIR / "migrations"))
    assert script.get_heads() == [REVISION]
    revision = script.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == PREVIOUS


def test_upgrade_adds_a_nullable_jsonb_card_and_keeps_existing_rows_cardless(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(PREVIOUS)
    assert _card_column_shape(migration_db) is None
    old = _seed_parked_row(migration_db, None)

    migration_db.upgrade(REVISION)

    assert _card_column_shape(migration_db) == {"data_type": "jsonb", "is_nullable": "YES"}
    new = _seed_parked_row(migration_db, CARD)
    cards = {
        row["id"]: row["card"]
        for row in migration_db.rows("SELECT id, card FROM tool_confirmations")
    }
    assert cards == {old: None, new: CARD}


def test_downgrade_drops_the_column_and_upgrade_is_repeatable(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(REVISION)
    _seed_parked_row(migration_db, CARD)

    command.downgrade(migration_db.config, PREVIOUS)
    assert _card_column_shape(migration_db) is None
    assert migration_db.rows("SELECT count(*) AS n FROM tool_confirmations")[0]["n"] == 1

    migration_db.upgrade(REVISION)
    assert _card_column_shape(migration_db) == {"data_type": "jsonb", "is_nullable": "YES"}
