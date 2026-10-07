"""Async database wiring (ADR-002/003). The engine is created once per app;
the session dependency hands out request-scoped sessions."""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from solus_api.billing.development import SESSION_SETTINGS_KEY
from solus_api.core.config import Settings
from solus_api.graph.live import HUB_INFO_KEY, LiveHub


def build_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def build_sessionmaker(
    engine: AsyncEngine, *, settings: Settings | None = None, hub: LiveHub | None = None
) -> async_sessionmaker[AsyncSession]:
    """Every session carries `settings` and, when given, the live `hub`. The hub in
    `session.info` is what lets the ORM listeners publish committed changes (ADR-037 §3)."""
    # Function-local: the publisher imports the ORM models, which must not load just to
    # build an engine for a migration or a script.
    from solus_api.graph.live_publisher import install

    install()
    info: dict[str, Any] = {}
    if settings is not None:
        info[SESSION_SETTINGS_KEY] = settings
    if hub is not None:
        info[HUB_INFO_KEY] = hub
    return async_sessionmaker(engine, expire_on_commit=False, info=info)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    maker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with maker() as session:
        yield session
