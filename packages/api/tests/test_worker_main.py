"""The ARQ worker entrypoint builds a valid WorkerSettings (functions + cron)."""

import importlib

import pytest


def test_worker_settings_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLUS_SUPABASE_JWT_SECRET", "x-dummy-not-a-secret")
    monkeypatch.setenv("SOLUS_REDIS_URL", "redis://localhost:6379/0")
    mod = importlib.reload(importlib.import_module("solus_api.worker_main"))
    assert hasattr(mod.WorkerSettings, "functions")
    assert hasattr(mod.WorkerSettings, "cron_jobs")
