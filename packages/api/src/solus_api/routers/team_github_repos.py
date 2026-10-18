"""SOLUSDEV-216 route stub (docs/api/github-orgs.md); routes land in a later task."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/teams/{team_id}/github", tags=["github-org-repos"])
