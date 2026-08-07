"""App factory wiring."""

import pytest
from fastapi import FastAPI


def test_create_app_mounts_v1_routes(app: FastAPI) -> None:
    paths = {route.path for route in app.routes}  # type: ignore[attr-defined]
    expected = {
        "/healthz",
        "/readyz",
        "/api/v1/version",
        "/api/v1/users/me",
        "/api/v1/users/me/settings",
        "/api/v1/users/me/notifications",
        "/api/v1/teams",
        "/api/v1/teams/{team_id}",
        "/api/v1/teams/{team_id}/members/{user_id}",
        "/api/v1/teams/{team_id}/invites",
        "/api/v1/invites/{invite_token}/accept",
        "/api/v1/teams/{team_id}/activity",
        "/api/v1/teams/{team_id}/projects",
        "/api/v1/projects/{project_id}",
        "/api/v1/projects/{project_id}/jobs",
        "/api/v1/jobs/{job_id}",
        "/api/v1/jobs/{job_id}/cancel",
    }
    missing = expected - paths
    assert not missing, f"missing routes: {missing}"


def test_sentry_init_is_noop_without_dsn(app: FastAPI) -> None:
    """SYS-02: no SOLUS_SENTRY_DSN → the SDK is never initialized, so every
    capture in the tool executor is a documented no-op (keyless-safe)."""
    import sentry_sdk

    assert app.state.settings.sentry_dsn is None
    assert sentry_sdk.get_client().is_active() is False


def test_sentry_init_kwargs_scrub_requests_and_disable_log_events(
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Sec review C1/M1: the DSN-configured init must strip request query data
    (OAuth ?code=…) and must not auto-convert ERROR logs into Sentry events."""
    from typing import Any

    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration
    from solus_api.core.config import Settings
    from solus_api.main import _scrub_sentry_event, create_app

    captured: dict[str, Any] = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: captured.update(kwargs))
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]  # valid pydantic-settings runtime kwarg
        supabase_jwt_secret="test-secret",
        sentry_dsn="https://key@sentry.example.invalid/1",
    )
    create_app(settings=settings)

    assert captured["send_default_pii"] is False
    assert captured["include_local_variables"] is False
    assert captured["max_request_body_size"] == "never"
    assert captured["before_send"] is _scrub_sentry_event
    (integration,) = captured["integrations"]
    assert isinstance(integration, LoggingIntegration)

    event = {"request": {"query_string": "code=LIVE-OAUTH-CODE", "url": "https://a/x?code=SECRET"}}
    scrubbed = _scrub_sentry_event(event, {})
    assert "query_string" not in scrubbed["request"]
    assert scrubbed["request"]["url"] == "https://a/x"
