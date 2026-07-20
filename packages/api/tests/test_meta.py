"""§2.0 Infrastructure & meta — /healthz, /readyz, /api/v1/version."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from solus_api.core.config import Settings
from solus_api.main import create_app
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# Nothing listens on the discard port — asyncpg fails fast with ECONNREFUSED.
UNREACHABLE_DB_URL = "postgresql+asyncpg://solus:solus@127.0.0.1:9/unreachable"


@asynccontextmanager
async def app_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def get_readyz(app: FastAPI) -> Response:
    async with app_client(app) as c:
        return await c.get("/readyz")


async def test_healthz_returns_ok_without_auth(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"data": {"status": "ok"}}


async def test_readyz_reports_dependency_checks(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
    # No SOLUS_REDIS_URL in the test settings: the queue is genuinely not
    # configured, and /readyz must say so (accepted degraded mode — see
    # infrastructure/aws/README.md) while still reporting ready (200).
    assert body["checks"]["redis"] == "not_configured"
    assert body["checks"]["queue"] == "not_configured"


async def test_readyz_reports_queue_configured_when_redis_url_set(
    settings: Settings, engine: AsyncEngine
) -> None:
    configured = settings.model_copy(update={"redis_url": "redis://localhost:6379/9"})
    resp = await get_readyz(create_app(settings=configured, engine=engine))
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "ok"
    assert body["checks"]["redis"] == "configured"
    assert body["checks"]["queue"] == "configured"


async def test_readyz_treats_empty_redis_url_as_not_configured(
    settings: Settings, engine: AsyncEngine
) -> None:
    # The staging taskdef ships SOLUS_REDIS_URL="" until the worker's Redis
    # exists (SOLUSDEV-144) — an empty DSN must read as "no queue", matching
    # the dispatch fallback in sources._dispatch_sync.
    configured = settings.model_copy(update={"redis_url": ""})
    resp = await get_readyz(create_app(settings=configured, engine=engine))
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["checks"]["redis"] == "not_configured"
    assert body["checks"]["queue"] == "not_configured"


async def test_readyz_returns_503_when_database_unreachable(settings: Settings) -> None:
    dead_engine = create_async_engine(UNREACHABLE_DB_URL)
    try:
        resp = await get_readyz(create_app(settings=settings, engine=dead_engine))
    finally:
        await dead_engine.dispose()
    assert resp.status_code == 503
    error = resp.json()["error"]
    assert error["code"] == "unavailable"
    assert error["details"][0]["database"] == "error"


async def test_version_is_unversioned_path_and_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/version")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["version"] == "0.1.0"
    assert body["build_sha"] == "dev"
