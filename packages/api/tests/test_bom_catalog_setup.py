"""Shipped BOM release and automatic setup use the real registry lifecycle."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from solus_api.core.config import Settings
from solus_api.extensions import bom_catalog_setup as setup
from solus_api.extensions.bundle import inspect_bundle


def settings(**kwargs: object) -> Settings:
    return Settings(_env_file=None, supabase_jwt_secret="test-only-signing-value", **kwargs)


def test_shipped_release_is_deterministic_and_valid() -> None:
    first = setup.bom_bundle()
    assert first == setup.bom_bundle()
    report = inspect_bundle(first)
    assert report.ok, report.problems
    assert report.manifest is not None
    assert report.manifest.extension.id == "bom"
    assert report.manifest.extension.requires == [["eda", "cad"]]


async def test_configured_publisher_runs_real_provisioner(monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = uuid4()
    provision = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(setup, "ensure_bom_catalog", provision)
    health = AsyncMock()
    monkeypatch.setattr(setup, "check_bom_catalog", health)
    config = settings(staff_user_ids=str(publisher), first_party_publisher_id=publisher)
    await setup.prepare_catalog("sessions", "store", config)
    provision.assert_awaited_once_with("sessions", "store", config, publisher, setup.bom_bundle())
    health.assert_awaited_once_with("sessions", "store")


async def test_existing_catalog_needs_no_staff_to_remain_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    health = AsyncMock(return_value=None)
    monkeypatch.setattr(setup, "check_bom_catalog", health)
    await setup.prepare_catalog("sessions", "store", settings())
    health.assert_awaited_once_with("sessions", "store")


async def test_production_missing_catalog_fails_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup, "check_bom_catalog", AsyncMock(side_effect=RuntimeError("missing")))
    with pytest.raises(RuntimeError, match="missing"):
        await setup.prepare_catalog("sessions", "store", settings(app_env="prod"))


async def test_dev_missing_catalog_reports_setup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(setup, "check_bom_catalog", AsyncMock(side_effect=RuntimeError("missing")))
    with caplog.at_level(logging.WARNING):
        await setup.prepare_catalog("sessions", "store", settings())
    assert "SOLUS_FIRST_PARTY_PUBLISHER_ID" in caplog.text


async def test_configured_setup_failure_is_never_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = uuid4()
    monkeypatch.setattr(
        setup, "ensure_bom_catalog", AsyncMock(side_effect=RuntimeError("conflict"))
    )
    with pytest.raises(RuntimeError, match="conflict"):
        await setup.prepare_catalog(
            "sessions", "store", settings(first_party_publisher_id=publisher)
        )


@pytest.mark.parametrize("healthy", [True, False])
async def test_operator_command_checks_health_and_always_disposes(
    monkeypatch: pytest.MonkeyPatch, healthy: bool
) -> None:
    from types import SimpleNamespace

    engine = SimpleNamespace(dispose=AsyncMock())
    health = AsyncMock(side_effect=None if healthy else RuntimeError("missing bundle"))
    monkeypatch.setattr(setup, "Settings", lambda: settings())
    monkeypatch.setattr(setup, "build_engine", lambda _url: engine)
    monkeypatch.setattr(setup, "build_sessionmaker", lambda *_args, **_kwargs: "sessions")
    monkeypatch.setattr(setup, "build_artifact_store", lambda _settings: "store")
    monkeypatch.setattr(setup, "prepare_catalog", AsyncMock())
    monkeypatch.setattr(setup, "check_bom_catalog", health)
    if healthy:
        await setup._run()
    else:
        with pytest.raises(RuntimeError, match="missing bundle"):
            await setup._run()
    health.assert_awaited_once_with("sessions", "store")
    engine.dispose.assert_awaited_once()
