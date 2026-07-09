"""Tests for the SOLUSDEV-55 integration glue: CORS for the renderer and the
dev-only create_all table bootstrap."""

import pytest
from httpx import ASGITransport, AsyncClient
from solus_api.core.config import Settings
from solus_api.main import create_all_tables, create_app
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

SECRET = "dummy-jwt-signing-value-tests-only"  # placeholder, not a real secret


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "supabase_jwt_secret": SECRET,
        "database_url": "sqlite+aiosqlite://",
    }
    base.update(overrides)
    # _env_file=None keeps the test hermetic: a developer's local .env (e.g.
    # SOLUS_AUTO_CREATE_TABLES=true for dev) must not leak into defaults tests.
    return Settings(_env_file=None, **base)  # type: ignore[call-arg, arg-type]


def test_cors_origins_parsed_into_list() -> None:
    settings = _settings(cors_origins="http://a.test, http://b.test ,")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


@pytest.mark.asyncio
async def test_cors_header_present_for_allowed_origin() -> None:
    app = create_app(_settings(cors_origins="http://localhost:5173"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://api") as client:
        resp = await client.get("/healthz", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


async def test_create_all_tables_builds_schema(engine: AsyncEngine) -> None:
    # Dev bootstrap path on Postgres (models use pgvector columns SQLite cannot host).
    # Idempotent against the already-migrated test DB; also exercises the
    # CREATE EXTENSION step the embedding columns require.
    await create_all_tables(engine)
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert {"users", "teams", "projects", "graph_entity"} <= set(tables)


def test_auto_create_tables_defaults_off() -> None:
    assert _settings().auto_create_tables is False
