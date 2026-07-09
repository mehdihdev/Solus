"""Alembic migration environment (async) — SOLUSDEV-72.

The database URL comes from `-x url=...` (used by the test harness) or the
SOLUS_DATABASE_URL env var; it is never read from config or a secret store.
"""

import asyncio
import os

from alembic import context
from solus_api.models import Base
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
target_metadata = Base.metadata

DEFAULT_URL = "postgresql+asyncpg://solus:solus@localhost:5432/solus"


def _database_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    return x_args.get("url") or os.environ.get("SOLUS_DATABASE_URL", DEFAULT_URL)


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
