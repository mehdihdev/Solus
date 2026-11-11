"""SOLUSDEV-322 P2-T1 — the sim session ownership ledger (`simulation/sessions_ledger.py`).

Ownership is proven by a row Solus itself wrote when it started a session; a session Solus
only attached to, an id nobody recorded, an ended session or another project's row is never
owned. Where ownership cannot be proven the per-call gate cards (P2-T2), so every negative here
is a card there.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from solus_api.models import Project, Team
from solus_api.simulation.sessions_ledger import OwnedSessionRunningError, SessionsLedger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

API_DIR = Path(__file__).resolve().parents[1]
PREVIOUS = "a32100000001"
PROVIDER = "provider-a"


async def _ledger_project(db: AsyncSession, name: str = "ledger") -> uuid.UUID:
    team = Team(name=f"sim-{name}")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name=f"sim-{name}")
    db.add(project)
    await db.commit()
    return project.id


def _ledger_for(engine: AsyncEngine) -> SessionsLedger:
    return SessionsLedger(async_sessionmaker(engine, expire_on_commit=False))


async def test_owned_start_is_owned_and_attached_is_not(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id = await _ledger_project(db)
    ledger = _ledger_for(engine)
    owned = await ledger.record_owned_start(
        project_id=project_id,
        provider=PROVIDER,
        session_id="s-owned",
        call_id="call-1",
        scene_ref="worlds/empty",
        created_by=None,
    )
    attached = await ledger.record_attached(
        project_id=project_id,
        provider=PROVIDER,
        session_id="s-attached",
        scene_ref=None,
        created_by=None,
    )

    assert owned.owner == "sol" and owned.started_by_call_id == "call-1"
    assert owned.scene_ref == "worlds/empty" and owned.ended_at is None
    assert attached.owner == "user" and attached.started_by_call_id is None
    assert await ledger.is_owned(project_id=project_id, provider=PROVIDER, session_id="s-owned")
    assert not await ledger.is_owned(
        project_id=project_id, provider=PROVIDER, session_id="s-attached"
    )
    running = await ledger.running(project_id=project_id)
    assert [(r.session_id, r.owner) for r in running] == [
        ("s-owned", "sol"),
        ("s-attached", "user"),
    ]
    assert await ledger.running(project_id=project_id, provider="provider-b") == []
    assert await ledger.owned_running_count(project_id=project_id, provider=PROVIDER) == 1


async def test_unknown_or_forged_id_is_not_owned(db: AsyncSession, engine: AsyncEngine) -> None:
    project_id = await _ledger_project(db)
    ledger = _ledger_for(engine)
    await ledger.record_owned_start(
        project_id=project_id,
        provider=PROVIDER,
        session_id="s-owned",
        call_id=None,
        scene_ref=None,
        created_by=None,
    )

    assert not await ledger.is_owned(project_id=project_id, provider=PROVIDER, session_id="nope")
    # The same id under another provider is a forgery, not an owned session.
    assert not await ledger.is_owned(
        project_id=project_id, provider="provider-b", session_id="s-owned"
    )
    assert not await ledger.is_owned(
        project_id=project_id, provider=PROVIDER, session_id="s-owned' OR 1=1 --"
    )


async def test_ended_session_is_not_owned(db: AsyncSession, engine: AsyncEngine) -> None:
    project_id = await _ledger_project(db)
    ledger = _ledger_for(engine)
    await ledger.record_owned_start(
        project_id=project_id,
        provider=PROVIDER,
        session_id="s-owned",
        call_id=None,
        scene_ref=None,
        created_by=None,
    )
    await ledger.end_session(project_id=project_id, provider=PROVIDER, session_id="s-owned")

    assert not await ledger.is_owned(project_id=project_id, provider=PROVIDER, session_id="s-owned")
    assert await ledger.running(project_id=project_id) == []
    assert await ledger.owned_running_count(project_id=project_id, provider=PROVIDER) == 0
    # Ending twice, or ending an id nobody recorded, is a no-op.
    await ledger.end_session(project_id=project_id, provider=PROVIDER, session_id="s-owned")
    await ledger.end_session(project_id=project_id, provider=PROVIDER, session_id="ghost")
    # The id may be started again once the previous session has ended.
    again = await ledger.record_owned_start(
        project_id=project_id,
        provider=PROVIDER,
        session_id="s-owned",
        call_id="call-2",
        scene_ref=None,
        created_by=None,
    )
    assert again.ended_at is None
    assert await ledger.is_owned(project_id=project_id, provider=PROVIDER, session_id="s-owned")


async def test_second_owned_start_same_provider_refuses(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id = await _ledger_project(db)
    ledger = _ledger_for(engine)
    await ledger.record_owned_start(
        project_id=project_id,
        provider=PROVIDER,
        session_id="s-1",
        call_id=None,
        scene_ref=None,
        created_by=None,
    )

    with pytest.raises(OwnedSessionRunningError):
        await ledger.record_owned_start(
            project_id=project_id,
            provider=PROVIDER,
            session_id="s-2",
            call_id=None,
            scene_ref=None,
            created_by=None,
        )
    assert await ledger.owned_running_count(project_id=project_id, provider=PROVIDER) == 1
    assert not await ledger.is_owned(project_id=project_id, provider=PROVIDER, session_id="s-2")
    # Another provider in the same project is its own slot; an attached session never counts.
    other = await ledger.record_owned_start(
        project_id=project_id,
        provider="provider-b",
        session_id="s-1",
        call_id=None,
        scene_ref=None,
        created_by=None,
    )
    assert other.owner == "sol"
    await ledger.record_attached(
        project_id=project_id,
        provider=PROVIDER,
        session_id="s-user",
        scene_ref=None,
        created_by=None,
    )
    assert await ledger.owned_running_count(project_id=project_id, provider=PROVIDER) == 1
    # Attaching to the live id again returns the row as it is: still owned by construction.
    twice = await ledger.record_attached(
        project_id=project_id,
        provider=PROVIDER,
        session_id="s-1",
        scene_ref=None,
        created_by=None,
    )
    assert twice.owner == "sol"


async def test_cross_project_id_is_not_owned(db: AsyncSession, engine: AsyncEngine) -> None:
    project_a = await _ledger_project(db, "a")
    project_b = await _ledger_project(db, "b")
    ledger = _ledger_for(engine)
    await ledger.record_owned_start(
        project_id=project_a,
        provider=PROVIDER,
        session_id="s-shared",
        call_id=None,
        scene_ref=None,
        created_by=None,
    )

    assert not await ledger.is_owned(project_id=project_b, provider=PROVIDER, session_id="s-shared")
    assert await ledger.running(project_id=project_b) == []
    assert await ledger.owned_running_count(project_id=project_b, provider=PROVIDER) == 0
    # Project B may own a session of the same id; ending it leaves A's untouched.
    await ledger.record_owned_start(
        project_id=project_b,
        provider=PROVIDER,
        session_id="s-shared",
        call_id=None,
        scene_ref=None,
        created_by=None,
    )
    await ledger.end_session(project_id=project_b, provider=PROVIDER, session_id="s-shared")
    assert await ledger.is_owned(project_id=project_a, provider=PROVIDER, session_id="s-shared")
    # A project that does not exist cannot own anything: the write is refused, not recorded.
    with pytest.raises(Exception, match="not found"):
        await ledger.record_owned_start(
            project_id=uuid.uuid4(),
            provider=PROVIDER,
            session_id="s-x",
            call_id=None,
            scene_ref=None,
            created_by=None,
        )


def _sim_session_table_present(url: str) -> bool:
    async def check() -> bool:
        eng = create_async_engine(url)
        try:
            async with eng.connect() as conn:
                return (
                    await conn.scalar(text("SELECT to_regclass('public.sim_session')")) is not None
                )
        finally:
            await eng.dispose()

    return asyncio.run(check())


def test_migration_round_trip(_schema: None) -> None:
    """`a32200000001` reverses cleanly and reapplies; head is restored in `finally` so a mid-test
    failure cannot poison the rest of the session (pattern `test_ingest`)."""
    url = os.environ["SOLUS_DATABASE_URL"]
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    assert _sim_session_table_present(url)
    try:
        command.downgrade(cfg, PREVIOUS)
        assert not _sim_session_table_present(url)
    finally:
        command.upgrade(cfg, "head")
    assert _sim_session_table_present(url)
