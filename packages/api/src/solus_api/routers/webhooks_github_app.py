"""SOLUSDEV-216 route stub (docs/api/github-orgs.md); routes land in a later task."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/webhooks/github", tags=["github-app-webhooks"])
