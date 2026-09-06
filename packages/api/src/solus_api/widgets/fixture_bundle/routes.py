"""The fixture bundle's routes (SOLUSDEV-246, widget-bundles.md §3).

Mounted by `routers/widgets.py` at `/api/v1/projects/{project_id}/widgets/fixture-bundle`
under `require_bundle("fixture-bundle")`; the handler receives the resolved
`BundleContext` and never does its own auth (CLAUDE.md §7).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from solus_api.core.responses import envelope
from solus_api.deps import SessionDep
from solus_api.models import GraphEntity
from solus_api.widgets.fixture_bundle.tools import NOTE_KIND, SLUG
from solus_api.widgets.guard import BundleDep

router = APIRouter()
NOTES_LIMIT = 200


@router.get("/notes")
async def list_notes(bundle: BundleDep(SLUG), session: SessionDep) -> dict[str, Any]:  # type: ignore[valid-type]
    rows = await session.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == bundle.ctx.project.id,
            GraphEntity.kind == NOTE_KIND,
            GraphEntity.deleted_at.is_(None),
        )
        .order_by(GraphEntity.created_at.desc(), GraphEntity.id.desc())
        .limit(NOTES_LIMIT)
    )
    notes = [
        {"id": str(row.id), "name": row.name, "created_at": row.created_at.isoformat()}
        for row in rows
    ]
    return envelope({"slug": SLUG, "notes": notes})
