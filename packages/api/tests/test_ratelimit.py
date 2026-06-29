"""Interim per-process rate limiting (§1.4; full ADR-019 system lands Phase 5)."""

from collections.abc import AsyncIterator

import pytest
from conftest import TEST_AUDIENCE, TEST_JWT_SECRET
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from solus_api.core.config import Settings
from solus_api.main import create_app
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture
def limited_app(engine: AsyncEngine) -> FastAPI:
    settings = Settings(
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience=TEST_AUDIENCE,
        database_url="sqlite+aiosqlite://",
        rate_limit_per_minute=3,
    )
    return create_app(settings=settings, engine=engine)


@pytest.fixture
async def limited_client(limited_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=limited_app), base_url="http://test") as c:
        yield c


async def test_rate_limit_headers_present(limited_client: AsyncClient) -> None:
    resp = await limited_client.get("/api/v1/version")
    assert resp.headers["x-ratelimit-limit"] == "3"
    assert int(resp.headers["x-ratelimit-remaining"]) >= 0
    assert "x-ratelimit-reset" in resp.headers


async def test_429_after_limit_exceeded(limited_client: AsyncClient) -> None:
    for _ in range(3):
        ok = await limited_client.get("/api/v1/version")
        assert ok.status_code == 200

    blocked = await limited_client.get("/api/v1/version")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert "retry-after" in blocked.headers


async def test_health_probes_exempt_from_rate_limit(limited_client: AsyncClient) -> None:
    for _ in range(10):
        resp = await limited_client.get("/healthz")
        assert resp.status_code == 200
