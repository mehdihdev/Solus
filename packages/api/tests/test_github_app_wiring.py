"""SOLUSDEV-216 T1 wiring: routers mounted, worker cron, app-startup configuration."""

from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from solus_api import main
from solus_api.connectors import github_app
from solus_api.connectors.worker import build_worker_settings
from solus_api.core.config import Settings
from solus_api.main import create_app
from solus_api.routers import (
    team_github,
    team_github_members,
    team_github_repos,
    webhooks_github_app,
)

TEAM_PREFIX = "/api/v1/teams/{team_id}/github"


def test_routers_have_expected_prefixes() -> None:
    for mod in (team_github, team_github_repos, team_github_members):
        assert isinstance(mod.router, APIRouter)
        assert mod.router.prefix == TEAM_PREFIX
    assert webhooks_github_app.router.prefix == "/api/v1/webhooks/github"


def test_routers_are_included_in_the_app(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    included: list[APIRouter] = []
    original = FastAPI.include_router

    def record(self: FastAPI, router: APIRouter, *args: object, **kwargs: object) -> None:
        included.append(router)
        original(self, router, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(FastAPI, "include_router", record)
    create_app(settings=settings)
    for mod in (team_github, team_github_repos, team_github_members, webhooks_github_app):
        assert mod.router in included


def test_every_planned_route_is_served(app: FastAPI) -> None:
    """docs/api/github-orgs.md §2: each planned route is mounted with its method."""
    served = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    teams = "/api/v1/teams/{team_id}/github"
    assert {
        ("POST", f"{teams}/install/start"),
        ("POST", f"{teams}/install/complete"),
        ("GET", f"{teams}/installation"),
        ("DELETE", f"{teams}/installation"),
        ("GET", f"{teams}/repos"),
        ("GET", f"{teams}/members"),
        ("POST", "/api/v1/webhooks/github/app"),
    } <= served


def test_worker_cron_includes_prune_github_deliveries() -> None:
    ws = build_worker_settings(
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            supabase_jwt_secret="test-only",
            redis_url="redis://localhost:6379",
        )
    )
    crons = {job.coroutine.__name__: job for job in ws.cron_jobs}  # type: ignore[attr-defined]
    prune = crons["prune_github_deliveries"]
    assert prune.minute == {0} and prune.second == 0 and prune.run_at_startup is False


async def test_worker_startup_configures_the_github_app(monkeypatch: pytest.MonkeyPatch) -> None:
    from solus_api.connectors import worker

    seen: list[tuple[Settings, object]] = []
    monkeypatch.setattr(worker, "configure_github_app", lambda s, sm=None: seen.append((s, sm)))
    monkeypatch.setenv("SOLUS_SUPABASE_JWT_SECRET", "test-only")
    monkeypatch.setenv("SOLUS_DATABASE_URL", "postgresql+asyncpg://u:p@localhost/none")
    ctx: dict[str, object] = {}
    await worker._on_startup(ctx)
    await worker._on_shutdown(ctx)
    assert len(seen) == 1 and isinstance(seen[0][0], Settings)
    # The worker's own sessionmaker is handed over, not the NullPool fallback.
    assert seen[0][1] is not None and seen[0][1] is ctx["sessionmaker"]


def test_create_app_configures_the_github_app(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    seen: list[tuple[Settings, object]] = []
    monkeypatch.setattr(main, "configure_github_app", lambda s, sm=None: seen.append((s, sm)))
    app = create_app(settings=settings)
    assert len(seen) == 1 and seen[0][0] is settings
    # The app's own sessionmaker is handed over, not the NullPool fallback.
    assert seen[0][1] is not None and seen[0][1] is app.state.sessionmaker


def _configured(**overrides: str | None) -> Settings:
    fields: dict[str, Any] = {
        "github_app_id": "1",
        "github_app_slug": "s",
        "github_app_client_id": "c",
        "github_app_client_secret": "x",
        "github_app_private_key": "k",
        "github_app_webhook_secret": "w",
        **overrides,
    }
    return Settings(_env_file=None, supabase_jwt_secret="test-only", **fields)  # type: ignore[call-arg]


def test_module_holder_round_trips() -> None:
    try:
        github_app.configure_github_app(_configured())
        assert github_app.is_configured() is True
        github_app.configure_github_app(_configured(github_app_slug=None))
        assert github_app.is_configured() is False
    finally:
        github_app.configure_github_app(
            Settings(_env_file=None, supabase_jwt_secret="test-only")  # type: ignore[call-arg]
        )
