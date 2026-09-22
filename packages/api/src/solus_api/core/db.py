"""Async database wiring (ADR-002/003). The engine is created once per app;
the session dependency hands out request-scoped sessions."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from solus_api.billing.development import SESSION_SETTINGS_KEY
from solus_api.core.config import Settings


def build_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def build_sessionmaker(
    engine: AsyncEngine, *, settings: Settings | None = None
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        info={SESSION_SETTINGS_KEY: settings} if settings is not None else {},
    )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    maker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with maker() as session:
        yield session
