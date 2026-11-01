"""SOLUSDEV-319 `bench_views` (docs/schemas/bench-view.md): constraints, FK actions, migration."""

import uuid
from typing import Any

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from solus_api.models import BenchView, Project, Team, User
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_data_migration import API_DIR, MigrationDatabase
from test_hardware_data_migration import migration_db as migration_db

PREVIOUS = "a32100000001"
REVISION = "a31900000001"


async def _world(db: AsyncSession) -> tuple[Project, User]:
    team = Team(name="Bench team")
    user = User(supabase_user_id=f"sb-{uuid.uuid4()}", email="bench@example.com")
    db.add_all([team, user])
    await db.flush()
    project = Project(team_id=team.id, name="Bench project")
    db.add(project)
    await db.flush()
    return project, user


async def _insert_rejected(db: AsyncSession, constraint: str, **fields: Any) -> None:
    project, _ = await _world(db)
    db.add(BenchView(project_id=project.id, **fields))
    with pytest.raises(IntegrityError, match=constraint):
        await db.flush()
    await db.rollback()


async def test_defaults_are_empty_arrays_and_round_trip(db: AsyncSession) -> None:
    project, user = await _world(db)
    db.add(BenchView(project_id=project.id, version=1, updated_by=user.id))
    await db.commit()
    row = (await db.execute(select(BenchView))).scalar_one()
    assert (row.version, row.display, row.derived) == (1, [], [])
    assert row.updated_by == user.id
    assert row.created_at is not None and row.updated_at is not None


async def test_rejects_negative_version(db: AsyncSession) -> None:
    await _insert_rejected(db, "ck_bench_views_version_nonnegative", version=-1)


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("display", {"a": 1}, "ck_bench_views_display_array"),
        ("derived", "text", "ck_bench_views_derived_array"),
        ("display", [{}] * 513, "ck_bench_views_display_bound"),
        ("derived", [{}] * 33, "ck_bench_views_derived_bound"),
    ],
)
async def test_rejects_non_array_and_oversized_json(
    db: AsyncSession, field: str, value: Any, constraint: str
) -> None:
    await _insert_rejected(db, constraint, version=1, **{field: value})


async def test_accepts_arrays_at_the_bounds(db: AsyncSession) -> None:
    project, _ = await _world(db)
    db.add(BenchView(project_id=project.id, version=0, display=[{}] * 512, derived=[{}] * 32))
    await db.commit()


async def test_one_row_per_project(db: AsyncSession) -> None:
    project, _ = await _world(db)
    db.add(BenchView(project_id=project.id, version=1))
    await db.commit()
    with pytest.raises(IntegrityError):
        await db.execute(
            text(
                "INSERT INTO bench_views (project_id, version, display, derived, created_at, "
                "updated_at) VALUES (:p, 2, '[]', '[]', now(), now())"
            ),
            {"p": project.id},
        )
    await db.rollback()


async def test_project_delete_cascades(db: AsyncSession) -> None:
    project, _ = await _world(db)
    db.add(BenchView(project_id=project.id, version=1))
    await db.commit()
    await db.execute(delete(Project).where(Project.id == project.id))
    await db.commit()
    assert (await db.execute(select(BenchView))).scalars().all() == []


async def test_user_delete_sets_updated_by_null(db: AsyncSession) -> None:
    project, user = await _world(db)
    db.add(BenchView(project_id=project.id, version=3, updated_by=user.id))
    await db.commit()
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
    db.expunge_all()
    row = (await db.execute(select(BenchView))).scalar_one()
    assert (row.updated_by, row.version) == (None, 3)


# --------------------------------------------------------------------- migration


def _has_table(db: MigrationDatabase) -> bool:
    return bool(db.rows("SELECT to_regclass('public.bench_views') AS t")[0]["t"])


def test_revision_descends_from_previous_single_head() -> None:
    script = ScriptDirectory(str(API_DIR / "migrations"))
    assert len(script.get_heads()) == 1
    revision = script.get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS


def test_upgrade_downgrade_upgrade_round_trip(migration_db: MigrationDatabase) -> None:
    migration_db.upgrade(PREVIOUS)
    assert not _has_table(migration_db)
    migration_db.upgrade(REVISION)
    assert _has_table(migration_db)
    checks = {
        r["conname"]
        for r in migration_db.rows(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'bench_views'::regclass"
        )
    }
    assert {
        "ck_bench_views_version_nonnegative",
        "ck_bench_views_display_array",
        "ck_bench_views_derived_array",
        "ck_bench_views_display_bound",
        "ck_bench_views_derived_bound",
    } <= checks
    command.downgrade(migration_db.config, PREVIOUS)
    assert not _has_table(migration_db)
    migration_db.upgrade(REVISION)
    assert _has_table(migration_db)


def test_migration_defaults_display_and_derived_to_empty_arrays(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(REVISION)
    team, project = uuid.uuid4(), uuid.uuid4()
    migration_db.execute(
        "INSERT INTO teams (id, name, kind, plan_status, settings, created_at, updated_at) "
        "VALUES (:id, 'T', 'collaborative', 'trial', '{}', now(), now())",
        {"id": team},
    )
    migration_db.execute(
        "INSERT INTO projects (id, team_id, name, created_at, updated_at) "
        "VALUES (:p, :t, 'P', now(), now())",
        {"p": project, "t": team},
    )
    migration_db.execute(
        "INSERT INTO bench_views (project_id, version, created_at, updated_at) "
        "VALUES (:p, 1, now(), now())",
        {"p": project},
    )
    rows = migration_db.rows("SELECT display, derived, updated_by FROM bench_views")
    assert rows == [{"display": [], "derived": [], "updated_by": None}]
