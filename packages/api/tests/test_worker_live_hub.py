"""SOLUSDEV-312: the ARQ worker's sessions carry the live hub, so worker commits publish."""

from __future__ import annotations

from typing import Any

import pytest
from solus_api.connectors import worker
from solus_api.core.config import Settings
from solus_api.graph.live import HUB_INFO_KEY, LiveHub


async def test_worker_startup_puts_the_hub_into_the_sessionmaker_session_info(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[LiveHub] = []

    async def fake_start(self: LiveHub) -> None:
        started.append(self)

    class _Engine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr("solus_api.core.config.Settings", lambda: settings)
    monkeypatch.setattr(worker, "build_engine", lambda _url: _Engine())
    monkeypatch.setattr(worker, "build_integration_cache", lambda *_a, **_k: object())
    monkeypatch.setattr(worker, "build_registry", lambda *_a, **_k: object())
    monkeypatch.setattr(worker, "build_secret_store", lambda *_a, **_k: object())
    monkeypatch.setattr("solus_api.storage.build_artifact_store", lambda _s: object())
    monkeypatch.setattr(LiveHub, "start", fake_start)
    redis = object()
    ctx: dict[str, Any] = {"redis": redis}

    await worker._on_startup(ctx)

    hub = ctx["graph_hub"]
    assert isinstance(hub, LiveHub) and hub.fanout_mode == "redis"
    assert started == [hub], "the relay must be started"
    assert ctx["sessionmaker"].kw["info"][HUB_INFO_KEY] is hub


async def test_worker_startup_without_redis_still_wires_a_local_hub(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Engine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr("solus_api.core.config.Settings", lambda: settings)
    monkeypatch.setattr(worker, "build_engine", lambda _url: _Engine())
    monkeypatch.setattr(worker, "build_integration_cache", lambda *_a, **_k: object())
    monkeypatch.setattr(worker, "build_registry", lambda *_a, **_k: object())
    monkeypatch.setattr(worker, "build_secret_store", lambda *_a, **_k: object())
    monkeypatch.setattr("solus_api.storage.build_artifact_store", lambda _s: object())
    ctx: dict[str, Any] = {}

    await worker._on_startup(ctx)

    assert ctx["sessionmaker"].kw["info"][HUB_INFO_KEY] is ctx["graph_hub"]
    await worker._on_shutdown(ctx)
