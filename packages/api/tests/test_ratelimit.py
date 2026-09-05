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
        _env_file=None,  # type: ignore[call-arg]  # valid pydantic-settings runtime kwarg
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience=TEST_AUDIENCE,
        database_url="sqlite+aiosqlite://",
        rate_limit_per_minute=3,
        write_rate_limit_per_minute=2,
        classify_rate_limit_per_minute=5,
        panel_pair_rate_limit_per_minute=1,
        cors_origins="http://localhost:5173",
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


# SOLUSDEV-234: a single desktop session's steady-state polling (bench widget
# 2 req/s + ~1 req/s of bridge/sources/extensions/widget pollers, several
# mounted twice) plus a workspace load's graph pagination. Below this the app
# 429s ITSELF within ~30s of normal clicking. Kept as a floor so a future
# "tighten the limiter" change cannot silently reintroduce that.
DESKTOP_STEADY_STATE_PER_MINUTE = 600
# ...and a ceiling, because the limiter is the interim burst bound on model
# spend (config.py): the read budget must not drift upward unnoticed either,
# and the write budget must stay where the security review sized it.
MAX_SANE_READS_PER_MINUTE = 2_000
MAX_SANE_WRITES_PER_MINUTE = 120


def test_default_budgets_cover_a_desktop_session_without_lifting_writes() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]  # valid pydantic-settings runtime kwarg
        supabase_jwt_secret=TEST_JWT_SECRET,
        database_url="sqlite+aiosqlite://",
    )
    assert DESKTOP_STEADY_STATE_PER_MINUTE <= settings.rate_limit_per_minute
    assert settings.rate_limit_per_minute <= MAX_SANE_READS_PER_MINUTE
    assert settings.write_rate_limit_per_minute <= MAX_SANE_WRITES_PER_MINUTE
    assert settings.panel_pair_rate_limit_per_minute <= MAX_SANE_WRITES_PER_MINUTE


async def test_writes_have_their_own_smaller_bucket(limited_client: AsyncClient) -> None:
    """SOLUSDEV-234: the read raise must not lift the write budget. Writes
    (anything but GET/HEAD/OPTIONS) draw on `write_rate_limit_per_minute`
    and neither consume nor are blocked by the read budget. (401 = through
    the limiter, stopped at auth — the middleware runs first.)"""
    for _ in range(3):
        assert (await limited_client.get("/api/v1/version")).status_code == 200
    assert (await limited_client.get("/api/v1/version")).status_code == 429
    # Read budget spent; the write bucket is untouched.
    for _ in range(2):
        resp = await limited_client.post("/api/v1/teams", json={"name": "x"})
        assert resp.status_code == 401
        assert resp.headers["x-ratelimit-limit"] == "2"
    blocked = await limited_client.delete("/api/v1/teams/x")  # same write bucket
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


async def test_preflight_is_answered_by_cors_and_never_counted(
    limited_client: AsyncClient,
) -> None:
    """CORS must sit OUTSIDE the limiter: preflights are free, and a 429
    still carries the CORS headers the renderer needs to read the error."""
    for _ in range(10):
        resp = await limited_client.options(
            "/api/v1/version",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
    for _ in range(3):
        assert (await limited_client.get("/api/v1/version")).status_code == 200
    blocked = await limited_client.get(
        "/api/v1/version", headers={"Origin": "http://localhost:5173"}
    )
    assert blocked.status_code == 429
    assert blocked.headers.get("access-control-allow-origin") == "http://localhost:5173"


async def test_panel_pair_start_has_its_own_limit(limited_client: AsyncClient) -> None:
    resp = await limited_client.post("/api/v1/panel/pair/start", json={})
    assert resp.status_code != 429
    assert resp.headers["x-ratelimit-limit"] == "1"
    blocked = await limited_client.post("/api/v1/panel/pair/start", json={})
    assert blocked.status_code == 429


def test_counter_table_stays_bounded_under_a_flood_of_unique_keys() -> None:
    from solus_api.core.ratelimit import MAX_TRACKED_KEYS, RateLimitMiddleware

    mw = RateLimitMiddleware(app=lambda *_: None, limit_per_minute=1)  # type: ignore[arg-type]
    for i in range(MAX_TRACKED_KEYS + 500):
        mw._bump(f"ip:{i}", window=1)
    assert len(mw._counters) <= MAX_TRACKED_KEYS


async def test_health_probes_exempt_from_rate_limit(limited_client: AsyncClient) -> None:
    for _ in range(10):
        resp = await limited_client.get("/healthz")
        assert resp.status_code == 200


_CLASSIFY = "/api/v1/orchestration/classify"


async def test_classify_has_its_own_bucket_not_the_global_one(
    limited_client: AsyncClient,
) -> None:
    """MO-04: classify fires on typing pauses — exhausting the GLOBAL budget
    must not block it, and hitting classify must not consume the global budget.
    (Unauthenticated 401s still exercise the middleware, which runs first.)"""
    for _ in range(3):
        assert (await limited_client.get("/api/v1/version")).status_code == 200
    # Global budget (3) is spent: normal routes are 429...
    assert (await limited_client.get("/api/v1/version")).status_code == 429
    # ...but classify still gets through the limiter (401 = reached auth).
    resp = await limited_client.post(_CLASSIFY, json={"query": "hi"})
    assert resp.status_code == 401
    assert resp.headers["x-ratelimit-limit"] == "5"  # its own limit, not 3


async def test_classify_bucket_blocks_at_its_own_limit(
    limited_client: AsyncClient,
) -> None:
    for _ in range(5):
        resp = await limited_client.post(_CLASSIFY, json={"query": "hi"})
        assert resp.status_code == 401  # through the limiter, stopped at auth
    blocked = await limited_client.post(_CLASSIFY, json={"query": "hi"})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    # And the classify traffic did NOT consume the global budget:
    assert (await limited_client.get("/api/v1/version")).status_code == 200
