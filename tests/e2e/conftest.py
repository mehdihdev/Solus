"""E2E harness for the SOLUS-FND-09 foundation integration checkpoint (SOLUSDEV-89).

Runs the foundation path with pytest + httpx, in one of two modes:

* **In-process (default)** — no ``SOLUS_E2E_BASE_URL`` set. Builds the ASGI app
  against an in-memory SQLite DB and mints local Supabase-shaped HS256 JWTs. This
  is what runs green locally and in CI; it exercises the real router/middleware
  stack without needing a deployed environment.

* **Staging** — ``SOLUS_E2E_BASE_URL`` set (e.g. the ECS staging URL that CI
  deploys on merge to main). httpx hits the live API. Because Solus runs **no**
  signup/login endpoints (ADR-009 — auth is Supabase Auth), the three test
  identities' JWTs are supplied via env, obtained from Supabase *after* signup +
  email verification:

      SOLUS_E2E_TOKEN_ALICE   SOLUS_E2E_TOKEN_BOB   SOLUS_E2E_TOKEN_CAROL

  A missing token in staging mode skips the affected test with instructions —
  the harness never fabricates a token the real server would reject.

The identities map to the API.md tenancy roles: Alice (team owner), Bob (invited
member), Carol (outsider — used to prove no cross-team leakage).
"""

import os
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

# In-process only: the JWT signing value read by the local app. A throwaway test
# value, never a real credential (staging validates against the real Supabase
# secret, which is why staging mode requires env-supplied tokens instead).
_TEST_JWT_SECRET = "dummy-e2e-jwt-signing-value-tests-only"  # placeholder, not a real secret
_TEST_AUDIENCE = "authenticated"

_BASE_URL = os.environ.get("SOLUS_E2E_BASE_URL")
IN_PROCESS = _BASE_URL is None

# Stable per-identity subject/email for in-process runs. Staging mode ignores
# these and derives sub/email from the supplied token instead.
_DEFAULT_IDENTITIES = {
    "alice": ("00000000-0000-0000-0000-00000000a11c", "alice.fnd09@example.com"),
    "bob": ("00000000-0000-0000-0000-0000000000b0b0", "bob.fnd09@example.com"),
    "carol": ("00000000-0000-0000-0000-00000000ca01", "carol.fnd09@example.com"),
}


@dataclass(frozen=True)
class Identity:
    """One authenticated actor: the bearer headers plus the sub/email the server
    will see once the token is decoded."""

    name: str
    sub: str
    email: str
    headers: dict[str, str]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "e2e: end-to-end gate test (run explicitly, not in the unit suite)"
    )


def _mint_token(sub: str, email: str) -> str:
    payload = {
        "sub": sub,
        "email": email,
        "aud": _TEST_AUDIENCE,
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return jwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")


def _identity_in_process(name: str) -> Identity:
    sub, email = _DEFAULT_IDENTITIES[name]
    return Identity(name, sub, email, {"Authorization": f"Bearer {_mint_token(sub, email)}"})


def _identity_from_env(name: str) -> Identity:
    token = os.environ.get(f"SOLUS_E2E_TOKEN_{name.upper()}")
    if not token:
        pytest.skip(
            f"staging mode: SOLUS_E2E_TOKEN_{name.upper()} not set. Supply a Supabase "
            f"JWT for the '{name}' identity (signup + email-verify against Supabase "
            "first — ADR-009: Solus has no signup endpoint)."
        )
    # Trust the server to verify the signature; we only need sub/email to make
    # assertions and to address invites at the right email.
    claims = jwt.decode(token, options={"verify_signature": False})
    return Identity(
        name,
        str(claims.get("sub", "")),
        str(claims.get("email", "")),
        {"Authorization": f"Bearer {token}"},
    )


#: Throwaway database for in-process gate runs; override with SOLUS_E2E_DATABASE_URL
#: (CI would set it to its own postgres service). Never the suite-wide test DB.
_DEFAULT_E2E_DATABASE_URL = "postgresql+asyncpg://solus:solus@localhost:5432/solus_test_e2e"


async def _ensure_database(url: str) -> None:
    """Create the throwaway gate database if it does not exist yet (mirrors
    packages/api/tests/conftest.py::_ensure_test_database) so the documented
    one-liner works on a fresh checkout."""
    import asyncpg

    name = url.rsplit("/", 1)[1]
    admin_dsn = url.rsplit("/", 1)[0].replace("+asyncpg", "") + "/postgres"
    conn = await asyncpg.connect(admin_dsn)
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    if IN_PROCESS:
        # Local imports: staging runs must not require the backend package to be
        # importable, only httpx + a base URL.
        from solus_api.core.config import Settings
        from solus_api.main import create_app
        from solus_api.models import Base
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        # Postgres, not SQLite: the graph/billing tables this gate walks use
        # JSONB and pgvector, which SQLite cannot compile (`create_all` raised
        # UnsupportedCompilationError: can't render element of type JSONB).
        #
        # Deliberately its OWN database (and its own env var, not the suite-wide
        # SOLUS_TEST_DATABASE_URL): this fixture drops and recreates the schema
        # per test, which would wipe the tables the packages/api suite builds via
        # Alembic if both shared one database in a single pytest session.
        database_url = os.environ.get("SOLUS_E2E_DATABASE_URL", _DEFAULT_E2E_DATABASE_URL)
        await _ensure_database(database_url)
        engine = create_async_engine(database_url, poolclass=NullPool)
        async with engine.begin() as conn:
            # pgvector must exist before create_all: the graph embedding columns
            # are `vector` typed (packages/api/tests/conftest.py gets this from
            # running the Alembic migrations; this gate builds the schema
            # directly, so it enables the extension itself).
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        settings = Settings(
            supabase_jwt_secret=_TEST_JWT_SECRET,
            supabase_jwt_audience=_TEST_AUDIENCE,
            database_url=database_url,
            rate_limit_per_minute=1_000_000,  # never throttle the gate run
        )
        app = create_app(settings=settings, engine=engine)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://e2e.test") as c:
            yield c
        await engine.dispose()
    else:
        assert _BASE_URL is not None  # guaranteed when not IN_PROCESS
        async with AsyncClient(base_url=_BASE_URL, timeout=30.0) as c:
            yield c


@pytest.fixture
def get_identity() -> Callable[[str], Identity]:
    """Return a resolver: ``get_identity("alice")`` -> an :class:`Identity`.

    In-process mints; staging reads a Supabase JWT from the environment.
    """
    resolver = _identity_in_process if IN_PROCESS else _identity_from_env
    return resolver


@pytest.fixture
def unique_name() -> Callable[[str], str]:
    """A collision-free display name so staging reruns don't clash on prior state."""

    def make(prefix: str) -> str:
        return f"{prefix} {uuid.uuid4().hex[:8]}"

    return make
