"""First-party bundle capability routes (SOLUSDEV-246, docs/api/widget-bundles.md §3).

`/api/v1/projects/{project_id}/widgets/<slug>/…` — one mount per discovered
capability that exports a router, each under `require_bundle(slug)` so a
capability's handlers can only ever run for a project where the bundle is
installed, enabled and unblocked. This module defines no routes of its own.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from solus_api.widgets.guard import require_bundle
from solus_api.widgets.registry import discover_capabilities

router = APIRouter(prefix="/api/v1/projects/{project_id}/widgets")

for _capability in discover_capabilities().values():
    if _capability.router is not None:
        router.include_router(
            _capability.router,
            prefix=f"/{_capability.id}",
            dependencies=[Depends(require_bundle(_capability.id))],
        )

__all__ = ["router"]
