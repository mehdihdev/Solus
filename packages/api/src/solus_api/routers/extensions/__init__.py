"""Extensions router aggregator (SOLUSDEV-235 / ADR-035, docs/api/extensions.md).

One `APIRouter` that `main.create_app` includes. It carries no prefix because the
surface spans three roots — `/api/v1/extensions` (catalog + publishing),
`/api/v1/projects/{project_id}/extensions|widget-layout` (installs, storage,
layout) and `/api/v1/teams/{team_id}/extensions/policies` (policy). Each EXT
task mounts its own sub-router here (`router.include_router(catalog.router)`);
this module itself defines no routes.
"""

from fastapi import APIRouter

router = APIRouter()

__all__ = ["router"]
