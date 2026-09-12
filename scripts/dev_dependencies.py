"""Read-only startup checks; never print credentials or apply migrations."""

import asyncio
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from dotenv import dotenv_values
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]


def redis_mode(path: Path, environ: Mapping[str, str]) -> str:
    config = dotenv_values(path, interpolate=False)
    value = environ.get("SOLUS_REDIS_URL", config.get("SOLUS_REDIS_URL"))
    if not value:
        return "disabled"
    url = urlsplit(value)
    if url.scheme not in {"redis", "rediss"} or not url.hostname:
        raise ValueError("invalid Redis configuration")
    port = 6379 if url.port is None else url.port
    if not 1 <= port <= 65535:
        raise ValueError("invalid Redis port")
    return (
        "compose"
        if url.scheme == "redis" and url.hostname in {"localhost", "127.0.0.1"} and port == 6379
        else "external"
    )


async def check_dependencies() -> None:
    from solus_api.core.config import Settings

    settings = Settings()  # type: ignore[call-arg]  # pydantic-settings reads the root env
    expected = set(ScriptDirectory(str(ROOT / "packages/api/migrations")).get_heads())
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            actual = await connection.run_sync(
                lambda sync: set(MigrationContext.configure(sync).get_current_heads())
            )
            graph_exists = await connection.run_sync(
                lambda sync: inspect(sync).has_table("graph_entity")
            )
        if actual != expected or not graph_exists:
            raise ValueError("schema is not current")
    finally:
        await engine.dispose()
    if settings.redis_url:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        try:
            # Redis may still be finishing startup immediately after compose up.
            for attempt in range(10):
                try:
                    await client.ping()
                    break
                except (RedisConnectionError, OSError):
                    if attempt == 9:
                        raise
                    await asyncio.sleep(0.5)
        finally:
            await client.aclose()


def ready(port: str) -> bool:
    if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        return False
    try:
        # Ignore proxy environment and never follow a redirect away from loopback.
        response = httpx.get(f"http://127.0.0.1:{port}/readyz", timeout=1, trust_env=False)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--ready":
        return 0 if ready(sys.argv[2]) else 1
    try:
        if sys.argv[1:] == ["--redis-mode"]:
            print(redis_mode(ROOT / ".env", os.environ))
        elif sys.argv[1:] == ["--schema"]:
            asyncio.run(asyncio.wait_for(check_dependencies(), timeout=20))
        else:
            raise ValueError("unknown check")
    except Exception:
        print(
            "[dev:all] Dependencies are not ready. Check the configured database/Redis and "
            "selected Compose volume. For a new or outdated database, back up existing data "
            "then run: cd packages/api && uv run alembic upgrade head. "
            "No schema or credentials were changed.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
