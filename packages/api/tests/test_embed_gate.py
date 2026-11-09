"""SOLUSDEV-321 P0-T6 — SOL embeds only with SOLUS_FINGERPRINT_EMBEDDING_ENABLED.

Off by default: the app's `DbSolSystems` gets no embed fn, so SOL's retrieval runs full-text
only and a turn makes zero embedding calls. On, the factory builds the embed fn once.
"""

from __future__ import annotations

from typing import Any

import pytest
from solus_api.core.config import Settings
from solus_api.main import create_app


def test_no_embed_calls_when_flag_off(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    built: list[dict[str, Any]] = []

    async def embed(text: str) -> list[float] | None:
        raise AssertionError("no embedding call is expected")

    def factory(*args: Any, **kwargs: Any) -> Any:
        built.append(kwargs)
        return embed

    monkeypatch.setattr("solus_api.main.build_embed_fn", factory)
    assert settings.fingerprint_embedding_enabled is False  # the default

    off = create_app(settings=settings)
    assert built == [] and off.state.sol_systems._embed is None

    flagged = settings.model_copy(update={"fingerprint_embedding_enabled": True})
    on = create_app(settings=flagged)
    assert len(built) == 1 and on.state.sol_systems._embed is embed
