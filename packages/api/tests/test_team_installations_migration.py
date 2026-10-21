"""SOLUSDEV-216 schema: team_installations, sources/invites/oauth_states extensions."""

import uuid

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError
from test_hardware_data_migration import API_DIR, MigrationDatabase
from test_hardware_data_migration import _schema as _schema
from test_hardware_data_migration import migration_db as migration_db

PREVIOUS = "a31300000001"
REVISION = "a21600000001"


def _cols(db: MigrationDatabase, table: str) -> dict[str, str]:
    rows = db.rows(
        f"SELECT column_name, is_nullable FROM information_schema.columns "  # noqa: S608
        f"WHERE table_name='{table}'"
    )
    return {r["column_name"]: r["is_nullable"] for r in rows}


def _has_table(db: MigrationDatabase, table: str) -> bool:
    return bool(db.rows(f"SELECT to_regclass('public.{table}') AS t")[0]["t"])


def _seed_team_user(db: MigrationDatabase) -> tuple[uuid.UUID, uuid.UUID]:
    team, user = uuid.uuid4(), uuid.uuid4()
    db.execute(
        "INSERT INTO teams (id, name, kind, plan_status, settings, created_at, updated_at) "
        "VALUES (:id, 'T', 'collaborative', 'trial', '{}', now(), now())",
        {"id": team},
    )
    db.execute(
        "INSERT INTO users (id, supabase_user_id, email, sol_mode, data_collection_consent, "
        "onboarding_step, created_at, updated_at) "
        "VALUES (:id, :ext, :em, 'guide', false, 'about', now(), now())",
        {"id": user, "ext": f"x-{user}", "em": f"{user}@example.com"},
    )
    return team, user


_INVITE = (
    "INSERT INTO invites (id, team_id, email, github_user_id, role, token, status, "
    "created_at, expires_at) VALUES (:id, :t, :e, :g, 'member', :tok, 'pending', "
    "now(), now() + interval '1 day')"
)


def _invite(db: MigrationDatabase, team: uuid.UUID, email: str | None, gid: int | None) -> None:
    db.execute(
        _INVITE, {"id": uuid.uuid4(), "t": team, "e": email, "g": gid, "tok": uuid.uuid4().hex}
    )


def test_single_head_descends_from_previous() -> None:
    script = ScriptDirectory(str(API_DIR / "migrations"))
    # One head overall; later migrations (e.g. SOLUSDEV-236) may sit on top of this one.
    assert len(script.get_heads()) == 1
    head = script.get_revision(REVISION)
    assert head is not None and head.down_revision == PREVIOUS


def test_upgrade_downgrade_upgrade_round_trip(migration_db: MigrationDatabase) -> None:
    migration_db.upgrade(PREVIOUS)
    assert not _has_table(migration_db, "team_installations")
    migration_db.upgrade(REVISION)
    assert _has_table(migration_db, "team_installations")
    assert _has_table(migration_db, "github_webhook_deliveries")
    assert "installation_id" in _cols(migration_db, "sources")
    assert _cols(migration_db, "invites")["email"] == "YES"
    assert "team_id" in _cols(migration_db, "oauth_states")
    command.downgrade(migration_db.config, PREVIOUS)
    assert not _has_table(migration_db, "team_installations")
    assert not _has_table(migration_db, "github_webhook_deliveries")
    assert "installation_id" not in _cols(migration_db, "sources")
    assert "github_user_id" not in _cols(migration_db, "invites")
    assert _cols(migration_db, "invites")["email"] == "NO"
    assert "team_id" not in _cols(migration_db, "oauth_states")
    migration_db.upgrade(REVISION)
    assert _has_table(migration_db, "team_installations")


def test_existing_invites_keep_their_email(migration_db: MigrationDatabase) -> None:
    migration_db.upgrade(PREVIOUS)
    team, _ = _seed_team_user(migration_db)
    migration_db.execute(
        "INSERT INTO invites (id, team_id, email, role, token, status, created_at, expires_at) "
        "VALUES (:id, :t, 'a@example.com', 'member', 'tok1', 'pending', now(), now())",
        {"id": uuid.uuid4(), "t": team},
    )
    migration_db.upgrade(REVISION)
    rows = migration_db.rows("SELECT email, github_user_id FROM invites")
    assert rows == [{"email": "a@example.com", "github_user_id": None}]


def test_invite_requires_exactly_one_of_email_or_github_user(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(REVISION)
    team, _ = _seed_team_user(migration_db)
    _invite(migration_db, team, "a@example.com", None)
    _invite(migration_db, team, None, 42)
    with pytest.raises(IntegrityError, match="invites_email_xor_github_user"):
        _invite(migration_db, team, "b@example.com", 43)
    with pytest.raises(IntegrityError, match="invites_email_xor_github_user"):
        _invite(migration_db, team, None, None)


def test_source_rejects_both_installation_and_connection(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(REVISION)
    team, user = _seed_team_user(migration_db)
    project, conn, inst = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    migration_db.execute(
        "INSERT INTO projects (id, team_id, name, created_at, updated_at) "
        "VALUES (:p, :t, 'P', now(), now())",
        {"p": project, "t": team},
    )
    migration_db.execute(
        "INSERT INTO account_connections (id, user_id, provider, status, config, "
        "created_at, updated_at) VALUES (:c, :u, 'github', 'connected', '{}', now(), now())",
        {"c": conn, "u": user},
    )
    migration_db.execute(
        "INSERT INTO team_installations (id, team_id, provider, external_installation_id, "
        "account_login, account_external_id, account_type, repository_selection, status, "
        "api_base_url, web_base_url, linked_at, created_at, updated_at) VALUES (:i, :t, "
        "'github', 1, 'acme', 2, 'Organization', 'all', 'active', 'https://api.github.com', "
        "'https://github.com', now(), now(), now())",
        {"i": inst, "t": team},
    )
    insert = (
        "INSERT INTO sources (id, project_id, team_id, type, name, status, config, cursor, "
        "connection_id, installation_id, created_at, updated_at) VALUES (:id, :p, :t, "
        "'github', 'S', 'pending', '{}', '{}', :c, :i, now(), now())"
    )
    with pytest.raises(IntegrityError, match="sources_installation_xor_connection"):
        migration_db.execute(
            insert, {"id": uuid.uuid4(), "p": project, "t": team, "c": conn, "i": inst}
        )
    migration_db.execute(
        insert, {"id": uuid.uuid4(), "p": project, "t": team, "c": None, "i": inst}
    )
    migration_db.execute(
        insert, {"id": uuid.uuid4(), "p": project, "t": team, "c": conn, "i": None}
    )


def test_notification_check_accepts_org_member_removed_and_downgrade_restores(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(REVISION)
    _, user = _seed_team_user(migration_db)
    insert = (
        "INSERT INTO notifications (id, user_id, type, title, attrs, created_at) "
        "VALUES (:id, :u, :ty, 'x', '{}', now())"
    )
    migration_db.execute(insert, {"id": uuid.uuid4(), "u": user, "ty": "github_org.member_removed"})
    command.downgrade(migration_db.config, PREVIOUS)
    assert migration_db.rows("SELECT count(*) AS n FROM notifications")[0]["n"] == 0
    with pytest.raises(IntegrityError, match="notificationtype"):
        migration_db.execute(
            insert, {"id": uuid.uuid4(), "u": user, "ty": "github_org.member_removed"}
        )
    migration_db.execute(insert, {"id": uuid.uuid4(), "u": user, "ty": "member.left"})


def test_downgrade_deletes_github_invites_before_restoring_email_not_null(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(REVISION)
    team, _ = _seed_team_user(migration_db)
    _invite(migration_db, team, "keep@example.com", None)
    _invite(migration_db, team, None, 7)
    command.downgrade(migration_db.config, PREVIOUS)
    assert [r["email"] for r in migration_db.rows("SELECT email FROM invites")] == [
        "keep@example.com"
    ]
