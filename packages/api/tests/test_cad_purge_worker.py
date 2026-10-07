"""ADR-038 §1: the worker cron and API startup drain due CAD purges."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from solus_api.connectors.worker import build_worker_settings, purge_cad_accounts
from solus_api.core.config import Settings
from solus_api.models import CadPurgeRequest
from solus_api.services.cad_purge import PASSES, run_startup_cad_purges, scope_hash
from solus_api.storage.cad_store import LocalCadStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

MIB = 1024 * 1024


def _due(scope_account: str) -> CadPurgeRequest:
    return CadPurgeRequest(
        account_hash=scope_hash("onshape", scope_account),
        passes_remaining=PASSES,
        attempts=2,
        next_attempt_at=datetime.now(UTC) - timedelta(minutes=1),
    )


async def test_the_purge_cron_deletes_what_is_due(
    engine: AsyncEngine, db: AsyncSession, tmp_path: Path
) -> None:
    cad = LocalCadStore(str(tmp_path / "cad"), max_object_bytes=64 * MIB)
    key = await cad.put("onshape:acct", b"revoked export")
    db.add(_due("acct"))
    await db.commit()
    maker = async_sessionmaker(engine, expire_on_commit=False)

    done = await purge_cad_accounts({"sessionmaker": maker, "cad_store": cad})

    assert done == 1
    assert await cad.get(key) is None
    db.expire_all()
    [row] = (await db.scalars(select(CadPurgeRequest))).all()
    assert row.passes_remaining == PASSES - 1  # the delayed second pass is still owed


async def test_the_purge_cron_without_a_store_is_a_no_op(
    engine: AsyncEngine, db: AsyncSession
) -> None:
    db.add(_due("acct"))
    await db.commit()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    assert await purge_cad_accounts({"sessionmaker": maker, "cad_store": None}) == 0


async def test_api_startup_drains_due_purges(
    engine: AsyncEngine, db: AsyncSession, tmp_path: Path
) -> None:
    cad = LocalCadStore(str(tmp_path / "cad"), max_object_bytes=64 * MIB)
    key = await cad.put("onshape:acct", b"left over from before a restart")
    db.add(_due("acct"))
    await db.commit()
    maker = async_sessionmaker(engine, expire_on_commit=False)

    await run_startup_cad_purges(maker, cad)

    assert await cad.get(key) is None


async def test_startup_purge_never_raises_even_when_the_database_is_broken(
    tmp_path: Path,
) -> None:
    def broken() -> Any:
        raise RuntimeError("database unreachable")

    cad = LocalCadStore(str(tmp_path / "cad"), max_object_bytes=64 * MIB)
    await run_startup_cad_purges(broken, cad)  # must not raise


def test_the_purge_cron_is_registered_every_minute_and_at_startup() -> None:
    settings: Any = build_worker_settings(
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            supabase_jwt_secret="test-only",
            redis_url="redis://localhost:6379",
        )
    )
    crons = {job.coroutine.__name__: job for job in settings.cron_jobs}
    assert crons["purge_cad_accounts"].minute is None
    assert crons["purge_cad_accounts"].second == 0
    assert crons["purge_cad_accounts"].run_at_startup is True
