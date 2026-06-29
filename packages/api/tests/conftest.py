"""Shared fixtures for the solus-api Phase 1 test suite.

Tests run against an in-memory SQLite database (StaticPool) and a dummy JWT
signing value that exists only in tests. Production uses PostgreSQL + the
Supabase secret from the environment (ADR-003 / ADR-009).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from solus_api.core.config import Settings
from solus_api.main import create_app
from solus_api.models import Base
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

TEST_JWT_SECRET = "dummy-jwt-signing-value-tests-only"  # placeholder, not a real secret
TEST_AUDIENCE = "authenticated"

ALICE = {"sub": "00000000-0000-0000-0000-00000000a11c", "email": "alice@example.com"}
BOB = {"sub": "00000000-0000-0000-0000-0000000000b0", "email": "bob@example.com"}


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
        database_url="sqlite+aiosqlite://",
        rate_limit_per_minute=100_000,
    )


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
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
