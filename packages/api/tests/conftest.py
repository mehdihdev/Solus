"""Shared fixtures for the solus-api test suite (SOLUSDEV-72).

Tests run against a real PostgreSQL + pgvector database — pgvector's `Vector`
columns and ivfflat indexes cannot run on SQLite. The schema is built once per
session by running the Alembic migration (so every run also proves the migration
applies on a fresh database), and each test is isolated by truncating all tables
afterwards. Point tests at a throwaway database via SOLUS_TEST_DATABASE_URL; it
defaults to the local docker-compose Postgres (`make db-up`).

Concurrent-suite isolation (MO-02b): the default database NAME is derived from
this checkout's path (plus the xdist worker id when running `pytest -n`), so
suites running in DIFFERENT worktrees/checkouts get different databases and
never collide — two agents/branches can test in parallel out of the box.
Two suites in the SAME checkout still share a database; give one of them its
own via the env override, e.g.:

    SOLUS_TEST_DATABASE_URL=postgresql+asyncpg://solus:solus@localhost:5432/solus_test_b \\
        uv run pytest -q

The SOLUS_TEST_DATABASE_URL override is always respected verbatim (CI sets it).
"""

import asyncio
import hashlib
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import jwt
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from solus_api.connectors.contracts import (
    AccountInfo,
    ConnectorError,
    Credentials,
    Domain,
    EntityOut,
    OAuthConnector,
    RelationOut,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.core.config import Settings
from solus_api.main import create_app
from solus_api.models import Base
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

API_DIR = Path(__file__).resolve().parent.parent


def _default_test_db_url() -> str:
    """Per-checkout (path hash) + per-xdist-worker database name — see the
    module docstring's concurrent-suite isolation notes."""
    checkout = hashlib.sha1(str(API_DIR).encode()).hexdigest()[:8]
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    name = f"solus_test_{checkout}" + (f"_{worker}" if worker else "")
    return f"postgresql+asyncpg://solus:solus@localhost:5432/{name}"


TEST_DATABASE_URL = os.environ.get("SOLUS_TEST_DATABASE_URL", _default_test_db_url())
_ALL_TABLES = ", ".join(t.name for t in Base.metadata.sorted_tables)

TEST_JWT_SECRET = "dummy-jwt-signing-value-tests-only"  # placeholder, not a real secret
TEST_AUDIENCE = "authenticated"

ALICE = {"sub": "00000000-0000-0000-0000-00000000a11c", "email": "alice@example.com"}
BOB = {"sub": "00000000-0000-0000-0000-0000000000b0", "email": "bob@example.com"}


async def _ensure_test_database() -> None:
    """Create the throwaway test database if it does not exist yet."""
    name = TEST_DATABASE_URL.rsplit("/", 1)[1]
    admin_dsn = TEST_DATABASE_URL.rsplit("/", 1)[0].replace("+asyncpg", "") + "/postgres"
    conn = await asyncpg.connect(admin_dsn)
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """Build the schema once per session by running the migration to head."""
    asyncio.run(_ensure_test_database())
    os.environ["SOLUS_DATABASE_URL"] = TEST_DATABASE_URL
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(cfg, "head")


def make_token(
    sub: str,
    email: str,
    *,
    secret: str = TEST_JWT_SECRET,
    audience: str = TEST_AUDIENCE,
    expires_in: int = 3600,
) -> str:
    payload = {
        "sub": sub,
        "email": email,
        "aud": audience,
        "exp": datetime.now(UTC) + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def bearer(sub: str, email: str, **kwargs: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub, email, **kwargs)}"}


@pytest.fixture
def settings() -> Settings:
    return Settings(
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience=TEST_AUDIENCE,
        database_url=TEST_DATABASE_URL,
        rate_limit_per_minute=100_000,
        sync_inline=True,  # deterministic syncs in tests (no ARQ/background)
        public_api_base_url="http://testserver",
        stripe_webhook_secret="whsec_test",  # SOLUSDEV-83 webhook signature tests
    )


class FakeGitHub(OAuthConnector):
    """A network-free stand-in for the GitHub connector, injected into the app's
    registry so API tests never hit github.com. Mirrors the real connector's
    surface: OAuth, validate, sync (incl. a W0-08 design export), repo list."""

    provider = "github"
    scopes = ("repo", "read:user")
    config_fields = ("repo", "branch")
    supports_token_connect = True

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        return f"https://gh.test/login/oauth/authorize?state={state}&redirect_uri={redirect_uri}&scope=repo"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> Credentials:
        if code == "bad-code":
            raise ConnectorError("oauth_exchange_failed", "bad verification code")
        return Credentials(token=f"ghu_{code}")

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        if creds.token == "ghu_revoked":
            raise ConnectorError("invalid_credentials", "token revoked")
        return AccountInfo(external_id="42", login="octocat", name="Octo Cat")

    async def sync(self, ctx: SyncContext) -> SyncResult:
        repo = str(ctx.config.get("repo", "octocat/strider-fw"))
        return SyncResult(
            entities=[
                EntityOut(source_key=":repo", type="code_repo", domain=Domain.CODE, name=repo),
                EntityOut(
                    source_key="src/main.py",
                    type="code_file",
                    domain=Domain.CODE,
                    name="main.py",
                ),
                EntityOut(
                    source_key="hardware/board.gbr",
                    type="design_export",
                    domain=Domain.ELECTRICAL,
                    name="board.gbr",
                    properties={"export_kind": "gerber"},
                ),
            ],
            relations=[
                RelationOut(from_key=":repo", to_key="src/main.py", type="contains"),
                RelationOut(from_key=":repo", to_key="hardware/board.gbr", type="contains"),
            ],
            cursor={"sha": "deadbeef"},
        )

    async def detect_changes(self, ctx: SyncContext) -> bool:
        return ctx.cursor.get("sha") != "deadbeef"

    async def list_repositories(self, creds: Credentials) -> list[dict[str, Any]]:
        return [
            {"full_name": "octocat/strider-fw", "default_branch": "main", "private": False},
            {"full_name": "octocat/strider-tools", "default_branch": "main", "private": True},
        ]


@pytest.fixture
def fake_registry() -> ConnectorRegistry:
    from solus_api.connectors.altium import AltiumConnector

    registry = ConnectorRegistry()
    registry.register("github", FakeGitHub)
    # Altium (SOLUSDEV-102) is a real committed-export connector — no external
    # calls to fake — so the roster's EDA member is available in source tests.
    registry.register("altium", AltiumConnector)
    return registry


@pytest.fixture
async def engine(_schema: None) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(TEST_DATABASE_URL)
    try:
        yield eng
    finally:
        # Isolate tests: wipe every table (CASCADE handles FK order) after each one,
        # and always dispose the pool even if truncation or the test body raised.
        try:
            async with eng.begin() as conn:
                await conn.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))
        finally:
            await eng.dispose()


@pytest.fixture
def app(settings: Settings, engine: AsyncEngine) -> FastAPI:
    return create_app(settings=settings, engine=engine)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest.fixture
def alice_headers() -> dict[str, str]:
    return bearer(ALICE["sub"], ALICE["email"])


@pytest.fixture
def bob_headers() -> dict[str, str]:
    return bearer(BOB["sub"], BOB["email"])


# The reusable conformance suite now ships in the package
# (`solus_api.connectors.conformance.assert_connector_contract`, W0-05 §10 / Decision B),
# so every connector's test imports it from there rather than from this conftest.


async def me(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    """Fetch (and implicitly auto-provision) the current user."""
    resp = await client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def create_team(
    client: AsyncClient, headers: dict[str, str], name: str = "Robotics Team"
) -> dict[str, Any]:
    resp = await client.post("/api/v1/teams", json={"name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def create_project(
    client: AsyncClient,
    headers: dict[str, str],
    team_id: str,
    name: str = "Rover",
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/teams/{team_id}/projects", json={"name": name}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def add_member(
    client: AsyncClient,
    owner_headers: dict[str, str],
    member_headers: dict[str, str],
    member: dict[str, str],
    team_id: str,
    role: str = "member",
) -> dict[str, Any]:
    """Invite + accept flow to put `member` on the team with `role`."""
    resp = await client.post(
        f"/api/v1/teams/{team_id}/invites",
        json={"email": member["email"], "role": role},
        headers=owner_headers,
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["data"]["token"]
    accept = await client.post(f"/api/v1/invites/{token}/accept", headers=member_headers)
    assert accept.status_code == 200, accept.text
    data: dict[str, Any] = accept.json()["data"]
    return data
