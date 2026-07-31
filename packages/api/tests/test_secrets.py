"""Secret store tests — credentials encrypted at rest, never plaintext in DB
(CLAUDE.md §7). Covers the in-memory, local-encrypted, and selection paths."""

import pytest
from cryptography.fernet import Fernet
from pydantic_settings import SettingsConfigDict
from solus_api.connectors.secrets import (
    InMemorySecretStore,
    LocalEncryptedSecretStore,
    SecretNotFoundError,
    build_secret_store,
)
from solus_api.core.config import Settings
from solus_api.models import ConnectorSecret
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

SECRET = "dummy-jwt-signing-value-tests-only"  # placeholder, not a real secret


class HermeticSettings(Settings):
    """`Settings` that never reads a checkout's `.env` file. The selection tests
    below must see exactly the fields they pass — a developer's `SOLUS_SECRETS_KEY`
    in `.env` otherwise flips `build_secret_store`'s backend choice.
    ponytail: exported SOLUS_* env vars can still leak in; scrub via monkeypatch if
    that ever bites."""

    model_config = SettingsConfigDict(env_prefix="SOLUS_", env_file=None, extra="ignore")


async def test_inmemory_roundtrip() -> None:
    store = InMemorySecretStore()
    await store.put("source/x", "token-123")
    assert await store.get("source/x") == "token-123"
    await store.delete("source/x")
    with pytest.raises(SecretNotFoundError):
        await store.get("source/x")


async def test_local_store_encrypts_at_rest(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    store = LocalEncryptedSecretStore(Fernet(Fernet.generate_key()), maker)
    await store.put("source/abc", "ghu_supersecret")

    assert await store.get("source/abc") == "ghu_supersecret"
    async with maker() as db:
        row = await db.get(ConnectorSecret, "source/abc")
    assert row is not None
    assert "ghu_supersecret" not in row.ciphertext  # stored ciphertext, not plaintext


async def test_local_store_overwrites_ref(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    store = LocalEncryptedSecretStore(Fernet(Fernet.generate_key()), maker)
    await store.put("r", "v1")
    await store.put("r", "v2")
    assert await store.get("r") == "v2"


async def test_local_store_missing_raises(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    store = LocalEncryptedSecretStore(Fernet(Fernet.generate_key()), maker)
    with pytest.raises(SecretNotFoundError):
        await store.get("nope")


def test_build_prefers_local_when_key_set(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    settings = HermeticSettings(
        supabase_jwt_secret=SECRET,
        database_url="sqlite+aiosqlite://",
        secrets_key=Fernet.generate_key().decode(),
    )
    store = build_secret_store(settings, maker)
    assert isinstance(store, LocalEncryptedSecretStore)


def test_build_treats_blank_backend_as_unset(engine: AsyncEngine) -> None:
    """SOLUSDEV-152: `SOLUS_SECRETS_BACKEND=` (blank) reaches Settings as "",
    which must behave exactly like unset — otherwise a blank env line silently
    disables AWS/Fernet auto-selection and credentials land in the in-memory
    store."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    settings = HermeticSettings(
        supabase_jwt_secret=SECRET,
        database_url="sqlite+aiosqlite://",
        secrets_key=Fernet.generate_key().decode(),
        secrets_backend="",
    )
    store = build_secret_store(settings, maker)
    assert isinstance(store, LocalEncryptedSecretStore)


def test_build_falls_back_to_inmemory_in_dev(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    settings = HermeticSettings(supabase_jwt_secret=SECRET, database_url="sqlite+aiosqlite://")
    store = build_secret_store(settings, maker)
    assert isinstance(store, InMemorySecretStore)


def test_build_hard_fails_in_prod_without_backend(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    settings = HermeticSettings(
        supabase_jwt_secret=SECRET,
        database_url="sqlite+aiosqlite://",
        app_env="production",
    )
    with pytest.raises(RuntimeError):
        build_secret_store(settings, maker)
