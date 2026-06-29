"""App factory wiring."""

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
