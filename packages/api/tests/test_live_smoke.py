"""MANUAL real-provider smoke tests — never run in CI.

Gated twice: the `live` marker (select with `-m live`) AND a skipif per test on
the env var that carries the key, so a plain `pytest -q` run skips them all.

    SOLUS_LIVE_ANTHROPIC_KEY=... uv run pytest -m live packages/api/tests/test_live_smoke.py
    SOLUS_LIVE_GOOGLE_KEY=...    (routes VISUAL_LOG → the Gemini-backed role)
    SOLUS_LIVE_OPENAI_KEY=... SOLUS_LIVE_OPENAI_MODEL=...  (the shipped catalog
    has no openai entry, so the model name comes from the env var)

These spend (tiny amounts of) real money.
"""

import os

import pytest
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.orchestration.config import (
    CostConfig,
    ModelCatalogEntry,
    OrchestrationConfig,
)
from solus_api.orchestration.enums import Complexity, RouteType
from solus_api.orchestration.gateway import complete
from solus_api.orchestration.providers import (
    ANTHROPIC_API_KEY_NAME,
    GOOGLE_API_KEY_NAME,
    OPENAI_API_KEY_NAME,
)

pytestmark = pytest.mark.live

_ANTHROPIC_KEY = os.environ.get("SOLUS_LIVE_ANTHROPIC_KEY")
_GOOGLE_KEY = os.environ.get("SOLUS_LIVE_GOOGLE_KEY")
_OPENAI_KEY = os.environ.get("SOLUS_LIVE_OPENAI_KEY")
_OPENAI_MODEL = os.environ.get("SOLUS_LIVE_OPENAI_MODEL")

_PROMPT = "Reply with the single word: pong"


async def _store_with(name: str, key: str) -> InMemorySecretStore:
    store = InMemorySecretStore()
    await store.put(name, key)
    return store


@pytest.mark.skipif(not _ANTHROPIC_KEY, reason="SOLUS_LIVE_ANTHROPIC_KEY not set")
async def test_anthropic_live_trivial_completion() -> None:
    assert _ANTHROPIC_KEY is not None
    store = await _store_with(ANTHROPIC_API_KEY_NAME, _ANTHROPIC_KEY)
    # TRIVIAL routes to the cheapest Claude-backed role in the shipped catalog.
    result = await complete(
        _PROMPT, secret_store=store, complexity=Complexity.TRIVIAL, max_tokens=32
    )
    assert result.text.strip()
    assert result.tokens_in > 0
    assert result.tokens_out > 0


@pytest.mark.skipif(not _GOOGLE_KEY, reason="SOLUS_LIVE_GOOGLE_KEY not set")
async def test_google_live_visual_log_completion() -> None:
    assert _GOOGLE_KEY is not None
    store = await _store_with(GOOGLE_API_KEY_NAME, _GOOGLE_KEY)
    # STANDARD × VISUAL_LOG routes to the Gemini-backed role in the shipped catalog.
    result = await complete(
        _PROMPT,
        secret_store=store,
        complexity=Complexity.STANDARD,
        type=RouteType.VISUAL_LOG,
        max_tokens=32,
    )
    assert result.model.provider == "google"
    assert result.text.strip()
    assert result.tokens_out > 0


@pytest.mark.skipif(
    not (_OPENAI_KEY and _OPENAI_MODEL),
    reason="SOLUS_LIVE_OPENAI_KEY / SOLUS_LIVE_OPENAI_MODEL not set",
)
async def test_openai_live_completion_via_config_override() -> None:
    assert _OPENAI_KEY is not None
    assert _OPENAI_MODEL is not None
    store = await _store_with(OPENAI_API_KEY_NAME, _OPENAI_KEY)
    config = OrchestrationConfig(
        version=1,
        catalog=[
            ModelCatalogEntry(
                provider="openai",
                name=_OPENAI_MODEL,
                price_in=1.0,
                price_out=2.0,
                context_window=100_000,
                roles=["only_role"],
            )
        ],
        matrix={},
        default_role="only_role",
        cost=CostConfig(credits_per_dollar=100.0),
    )
    result = await complete(_PROMPT, secret_store=store, config=config, max_tokens=32)
    assert result.model.provider == "openai"
    assert result.text.strip()
    assert result.tokens_out > 0
