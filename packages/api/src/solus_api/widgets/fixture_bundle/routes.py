"""The fixture bundle's routes (SOLUSDEV-246, widget-bundles.md §3).

Mounted by `routers/widgets.py` at `/api/v1/projects/{project_id}/widgets/fixture-bundle`
under `require_bundle("fixture-bundle")`; the handler receives the resolved
`BundleContext` and never does its own auth (CLAUDE.md §7).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select

from solus_api.core.responses import envelope
from solus_api.deps import SessionDep
from solus_api.models import GraphEntity
from solus_api.widgets.fixture_bundle.tools import NOTE_KIND, NOTE_MAX_LEN, SLUG, write_note
from solus_api.widgets.guard import BundleContext, require_bundle

router = APIRouter()
NOTES_LIMIT = 200
#: The resolved install this router's handlers run against — the SAME dependency
#: object the mount applies, so it resolves once per request.
FixtureBundle = Annotated[BundleContext, Depends(require_bundle(SLUG))]


class NoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: Annotated[str, StringConstraints(min_length=1, max_length=NOTE_MAX_LEN)]


@router.get("/notes")
async def list_notes(bundle: FixtureBundle, session: SessionDep) -> dict[str, Any]:
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


@router.post("/notes", status_code=201)
async def create_note(body: NoteBody, bundle: FixtureBundle, session: SessionDep) -> dict[str, Any]:
    """A capability WRITE: the guard already applied the member floor and the
    install-write budget before this handler ran (widget-bundles.md §3)."""
    note = await write_note(
        session,
        project_id=bundle.ctx.project.id,
        user_id=bundle.ctx.user.id,
        text=body.text,
        manifest=bundle.manifest,
    )
    await session.commit()
    return envelope({"id": str(note.id), "name": note.name, "kind": NOTE_KIND})
