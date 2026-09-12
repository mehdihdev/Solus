"""`core/startup_checks.report_provider_refs` — names only, never raises."""

from __future__ import annotations

import logging

import pytest
from pydantic_settings import SettingsConfigDict
from solus_api.agent.tools.mcp_servers import WEB_SEARCH
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.core.config import Settings
from solus_api.core.startup_checks import EXPECTED_REFS, report_provider_refs
from solus_api.orchestration.providers import (
    ANTHROPIC_API_KEY_NAME,
    GOOGLE_API_KEY_NAME,
    OPENAI_API_KEY_NAME,
)

LOGGER = "solus.core.startup_checks"
VALUE = "placeholder-not-a-real-key-0123456789"  # test-only sentinel


class HermeticSettings(Settings):
    """Never reads a checkout's `.env` (same trick as tests/test_secrets.py)."""

    model_config = SettingsConfigDict(env_prefix="SOLUS_", env_file=None, extra="ignore")


def _settings(onshape_id: str | None = None, onshape_secret: str | None = None) -> Settings:
    return HermeticSettings(
        supabase_jwt_secret="dummy-jwt-signing-value-tests-only",
        database_url="sqlite+aiosqlite://",
        onshape_client_id=onshape_id,
        onshape_client_secret=onshape_secret,
    )


def test_expected_refs_cover_every_env_sourced_ref() -> None:
    assert EXPECTED_REFS == frozenset(
        {ANTHROPIC_API_KEY_NAME, OPENAI_API_KEY_NAME, GOOGLE_API_KEY_NAME}
        | set(WEB_SEARCH.required_secrets)
    )


async def test_two_missing_refs_warn_by_name_only(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemorySecretStore()
    await store.put(ANTHROPIC_API_KEY_NAME, VALUE)
    await store.put(OPENAI_API_KEY_NAME, VALUE)
    caplog.set_level(logging.INFO, logger=LOGGER)

    report = await report_provider_refs(store, _settings())

    assert report.present == (ANTHROPIC_API_KEY_NAME, OPENAI_API_KEY_NAME)
    assert report.missing == (*sorted(set(WEB_SEARCH.required_secrets) | {GOOGLE_API_KEY_NAME}),)
    assert report.onshape_pair_configured is False
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert sorted(r.getMessage() for r in warnings) == [
        f"SecretStore ref '{ref}' missing — SOL turns on {ref.removesuffix('_api_key')} "
        "will fail with ProviderCredentialsMissingError; run `make seed-secrets`"
        for ref in report.missing
    ]
    assert VALUE not in caplog.text
    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(infos) == 1 and ANTHROPIC_API_KEY_NAME in infos[0]


async def test_all_present_no_warnings(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemorySecretStore()
    for ref in EXPECTED_REFS:
        await store.put(ref, VALUE)
    caplog.set_level(logging.INFO, logger=LOGGER)

    report = await report_provider_refs(store, _settings("id", "s"))

    assert report.missing == ()
    assert set(report.present) == EXPECTED_REFS
    assert report.onshape_pair_configured is True
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    assert VALUE not in caplog.text


async def test_unexpected_store_error_reported_as_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class BrokenStore(InMemorySecretStore):
        async def get(self, ref: str) -> str:
            raise ConnectionError("db down")

    caplog.set_level(logging.INFO, logger=LOGGER)
    report = await report_provider_refs(BrokenStore(), _settings())

    assert report.present == ()
    assert set(report.missing) == EXPECTED_REFS
