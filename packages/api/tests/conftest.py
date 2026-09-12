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

The SOLUS_TEST_DATABASE_URL override is respected (CI sets it); under `pytest -n`
each xdist worker appends its worker id so workers never share a database.
"""

import asyncio
import hashlib
import os
from collections.abc import AsyncIterator, Callable, Iterator
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
from solus_api.agent.runtime import ScaffoldRunner
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
from solus_api.connectors.step_parser import step_reader_available
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
from sqlalchemy.pool import NullPool

API_DIR = Path(__file__).resolve().parent.parent

#: Ambient `SOLUS_*` this suite must NOT strip.
#: - `SOLUS_TEST_DATABASE_URL` names the database to test against (CI sets it).
#: - `SOLUS_LIVE_*` are opt-in gates for the live-provider smoke tests; removing
#:   them would silently skip the very tests a developer exported them to run.
_KEEP_AMBIENT_ENV = ("SOLUS_TEST_DATABASE_URL",)
_KEEP_AMBIENT_PREFIXES = ("SOLUS_LIVE_",)


def _strip_ambient_solus_env() -> None:
    """Make the suite immune to the developer's shell.

    `Settings(_env_file=None, ...)` only disables the .env FILE — pydantic still
    reads `os.environ`, and real environment variables outrank both. So a shell
    that has sourced the root `.env` (which is exactly what running the API asks
    you to do) leaks all ~80 keys into every test: `test_config` then sees a real
    `stripe_webhook_secret` where it asserts None, and `test_secrets` gets the
    encrypted store where it asserts the in-memory fallback.

    CI never hits this — there is no `.env` in a clean checkout — so the suite
    passes there and fails on the machine of whoever just ran the app. Strip the
    ambient values here, once, before anything reads them; the tests that want a
    value set it explicitly.
    """
    for name in [k for k in os.environ if k.startswith("SOLUS_")]:
        if name in _KEEP_AMBIENT_ENV or name.startswith(_KEEP_AMBIENT_PREFIXES):
            continue
        del os.environ[name]


_strip_ambient_solus_env()


def _default_test_db_url() -> str:
    """Per-checkout (path hash) database name — see the module docstring's
    concurrent-suite isolation notes."""
    checkout = hashlib.sha1(str(API_DIR).encode()).hexdigest()[:8]
    return f"postgresql+asyncpg://solus:solus@localhost:5432/solus_test_{checkout}"


def _xdist_worker_suffix() -> str:
    """Under `pytest -n`, every worker gets its own database (`..._gw0`, `..._gw1`)
    — applied to the env override too, or CI's single URL would be shared by all
    workers and their per-test TRUNCATEs would wipe each other's rows."""
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    return f"_{worker}" if worker else ""


TEST_DATABASE_URL = (
    os.environ.get("SOLUS_TEST_DATABASE_URL", _default_test_db_url()) + _xdist_worker_suffix()
)
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


async def _truncate_all_tables() -> None:
    """Wipe every mapped table. Used at session start and per-test teardown."""
    eng = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with eng.begin() as conn:
            await conn.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))
    finally:
        await eng.dispose()


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """Build the schema once per session by running the migration to head, then
    start from a clean slate: per-test isolation truncates in TEARDOWN, so a
    killed/interrupted previous run can leave rows behind (e.g. a deleted-account
    tombstone) that would poison the first test of the next run."""
    asyncio.run(_ensure_test_database())
    os.environ["SOLUS_DATABASE_URL"] = TEST_DATABASE_URL
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(cfg, "head")
    asyncio.run(_truncate_all_tables())


def make_token(
    sub: str,
    email: str,
    *,
    secret: str = TEST_JWT_SECRET,
    audience: str = TEST_AUDIENCE,
    expires_in: int = 3600,
    email_verified: bool | None = None,
) -> str:
    payload: dict[str, Any] = {
        "sub": sub,
        "email": email,
        "aud": audience,
        "exp": datetime.now(UTC) + timedelta(seconds=expires_in),
    }
    # Only emit the claim when a test cares about it. Absent ⇒ the decoder treats
    # the user as verified (SOLUSDEV-82: Supabase may omit the claim), so existing
    # tokens keep passing the require_verified gate unchanged.
    if email_verified is not None:
        payload["email_verified"] = email_verified
    return jwt.encode(payload, secret, algorithm="HS256")


def bearer(sub: str, email: str, **kwargs: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub, email, **kwargs)}"}


@pytest.fixture
def settings() -> Settings:
    # `_env_file=None` keeps the suite hermetic: a developer's local packages/api/.env
    # must not leak into tests (it makes them diverge from CI, which has no .env).
    return Settings(
        _env_file=None,  # type: ignore[call-arg]  # valid pydantic-settings runtime kwarg
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience=TEST_AUDIENCE,
        database_url=TEST_DATABASE_URL,
        rate_limit_per_minute=100_000,
        write_rate_limit_per_minute=100_000,
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

    def authorize_url(self, *, state: str, redirect_uri: str, access: str | None = None) -> str:
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

    async def list_selectable(self, creds: Credentials) -> list[dict[str, Any]]:
        return [
            {
                "id": repo["full_name"],
                "name": repo["full_name"],
                "config": {"repo": repo["full_name"], "branch": repo["default_branch"]},
            }
            for repo in await self.list_repositories(creds)
        ]


@pytest.fixture
def fake_registry() -> ConnectorRegistry:
    from solus_api.connectors.altium import AltiumConnector
    from solus_api.connectors.kicad import KicadConnector

    registry = ConnectorRegistry()
    registry.register("github", FakeGitHub)
    # The EDA family (Altium SOLUSDEV-102, KiCad SOLUSDEV-100) is real
    # committed-export connectors — no external calls to fake — so the roster's
    # EDA members are available in source tests.
    registry.register("altium", AltiumConnector)
    registry.register("kicad", KicadConnector)
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
async def app(settings: Settings, engine: AsyncEngine, tmp_path: Path) -> AsyncIterator[FastAPI]:
    from solus_api.hardware.runtime_owner import RuntimeOwner

    application = create_app(settings=settings, engine=engine)
    application.state.hardware_connections.owner = RuntimeOwner(home=tmp_path, location=tmp_path)
    close_connections = application.state.hardware_connections.aclose
    # The shipped runner is `LlmRunner`, which makes a real provider call. The
    # transport suites (loop guard, timeout, error masking, pagination) are about
    # the plumbing around a runner, not about the model, so they run against the
    # model-free scaffold. Tests that DO exercise the model swap in their own
    # scripted adapter (see test_sol_red_team.py).
    application.state.agent_runner = ScaffoldRunner()
    try:
        yield application
    finally:
        await close_connections()


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


@pytest.fixture
def unverified_headers() -> dict[str, str]:
    # A token whose email is NOT verified — for RequireVerified gate tests.
    # A fixture (not an import) so subdirectory suites can use it despite the
    # conftest module-name shadowing that breaks `from conftest import ...` there.
    return bearer("unverified-sub", "unverified@example.com", email_verified=False)


@pytest.fixture
def make_entry() -> "Callable[..., Any]":
    """Factory for a valid published tool_knowledge row (LANE D toolkb suite).

    Lives HERE, not in a tests/toolkb/conftest.py — a second module named
    `conftest` shadows this one and breaks every root-level `from conftest
    import ...` when the full suite runs. Direct row construction is allowed in
    tests only; production code goes through toolkb.guard (tripwire-tested).
    """
    from solus_api.contracts import tool_knowledge as ctr
    from solus_api.toolkb.schema import AcquisitionMethod, KnowledgeStatus, ToolKnowledgeEntry

    def _entry(**overrides: object) -> ToolKnowledgeEntry:
        fields: dict[str, object] = {
            "tool": ctr.ToolFamily.KICAD,
            "version_range": ">=8.0 <9.0",
            "surface": ctr.UiSurface.MENU,
            "control_id": "kicad.eeschema.place_net_label",
            "label": "Add Net Label",
            "effect": ctr.ControlEffect.CREATE_FEATURE,
            "description": "Places a named net label on the current wire.",
            "menu_path": ["Place", "Net Label"],
            "shortcut": "L",
            "provenance": ctr.Provenance.VENDOR_DOCS,
            "status": KnowledgeStatus.PUBLISHED,
            "acquired_via": AcquisitionMethod.DOCS,
            "confidence": 0.8,
            "version_min_key": "0008.0000.0000",
            "version_max_key": "0009.0000.0000",
        }
        fields.update(overrides)
        return ToolKnowledgeEntry(**fields)

    return _entry


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


# --- Bridge (SOLUSDEV-154) WS-test fixtures — shared by test_bridge*.py ---

BRIDGE_ALLOWLIST_ROOT = str(Path(__file__).parent / "fixtures" / "bridge_allowlist")


def bridge_settings(**overrides: Any) -> Settings:
    fields: dict[str, Any] = {
        # Hermetic, like `settings()` above: `Settings.env_file` is anchored to the
        # repo root, so without this every UNSPECIFIED field below would come from
        # the developer's real `.env` — green here, different in CI, and live
        # secrets pulled into a test process.
        "_env_file": None,
        "supabase_jwt_secret": TEST_JWT_SECRET,
        "supabase_jwt_audience": TEST_AUDIENCE,
        "database_url": TEST_DATABASE_URL,
        "rate_limit_per_minute": 100_000,
        "write_rate_limit_per_minute": 100_000,
        "sync_inline": True,
        "bridge_allowlist_root": BRIDGE_ALLOWLIST_ROOT,
    }
    fields.update(overrides)
    return Settings(**fields)


@pytest.fixture
def make_app(tmp_path: Path) -> Iterator[Callable[..., FastAPI]]:
    """App factory for sync WS tests (starlette TestClient). TestClient runs
    its own event loop, so the shared async `engine` fixture (bound to the
    pytest-asyncio loop) cannot be used; each app gets a NullPool engine —
    every connection opens and closes inside TestClient's loop."""

    from solus_api.hardware.runtime_owner import RuntimeOwner

    owners: list[RuntimeOwner] = []

    def _make(**overrides: Any) -> FastAPI:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        application = create_app(settings=bridge_settings(**overrides), engine=engine)
        owner = RuntimeOwner(home=tmp_path, location=tmp_path / str(len(owners)))
        application.state.hardware_connections.owner = owner
        owners.append(owner)
        return application

    yield _make
    for owner in owners:
        owner.close()
    asyncio.run(_truncate_all_tables())


@pytest.fixture
def bridge_app(make_app: Callable[..., FastAPI]) -> FastAPI:
    return make_app()


@pytest.fixture(autouse=True)
def _reset_circuit_breaker() -> Iterator[None]:
    """SYS-05: the process-wide provider circuit breaker accumulates consecutive
    failures across calls BY DESIGN; across tests that would let one suite's
    deliberate provider failures trip the circuit for the next. Reset per test."""
    from solus_api.orchestration.retry import DEFAULT_BREAKER

    DEFAULT_BREAKER.reset()
    yield
    DEFAULT_BREAKER.reset()


#: SOLUSDEV-167. The OCCT wheel imports only where an OpenGL runtime is present
#: (`libGL.so.1`), which `bookworm-slim` does not ship. Every test that drives a
#: REAL STEP parse carries this, so a box without the optional `cad` extra skips
#: cleanly instead of failing with an assertion about something else entirely —
#: the CI run that prompted this reported "assert 120 < 120" for a missing
#: shared library. CI installs libgl1 and asserts the reader IS available, so
#: these can never silently vanish where they are meant to run.
requires_occt = pytest.mark.skipif(
    not step_reader_available(), reason="STEP reading needs the optional 'cad' extra"
)
