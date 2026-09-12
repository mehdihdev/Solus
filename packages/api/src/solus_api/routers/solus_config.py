"""docs/api/solus.md — the project-level `.solus` (SOLUSDEV-240). Read the five
sections, file typed text or an already-uploaded artifact into one, edit or remove
an entry. All scoped through `ProjectCtx` (§7 tenant isolation; non-member → 404).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, require_role
from solus_api.models import Artifact, Role, SolusEntryKind, SolusSection
from solus_api.schemas import SolusEntryIn, SolusEntryPatch
from solus_api.services.code_env import CodeEnvironment, upsert_code_environment
from solus_api.services.events import emit_event
from solus_api.services.solus_config import (
    add_artifact_entry,
    add_text_entry,
    delete_entry,
    ensure_solus_node,
    get_entry,
    load_sections,
    parse_section,
    serialize_entry,
    update_text,
    validate_config_payload,
)
from solus_api.storage import ArtifactStore

router = APIRouter(prefix="/api/v1/projects/{project_id}/solus")


class SolusConfigEntryIn(BaseModel):
    """SOLUSDEV-252: `{kind: "config", payload}` — a code environment document, validated
    by the section's model (`validate_config_payload`). Lives beside the route rather than
    in `schemas.SolusEntryIn` so the W1 text/artifact shape is untouched."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["config"]
    payload: dict[str, Any]


def _emit_solus_event(
    ctx: ProjectCtx, session: SessionDep, event_type: str, payload: dict[str, Any]
) -> None:
    emit_event(
        session,
        user=ctx.user,
        event_type=event_type,
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload=payload,
    )


@router.get("")
async def get_solus(ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    node = await ensure_solus_node(session, ctx.project.id)
    sections = await load_sections(session, ctx.project.id)
    await session.commit()  # a self-healed node must persist
    return envelope({"entity_id": node.id, "sections": sections})


@router.post("/{section}/entries", status_code=201)
async def add_entry(
    section: str,
    body: SolusEntryIn | SolusConfigEntryIn,
    ctx: ProjectCtx,
    session: SessionDep,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    parsed = parse_section(section)
    artifact: Artifact | None = None
    if isinstance(body, SolusConfigEntryIn):
        if parsed is not SolusSection.CODE:
            # Hardware configs are written only through the hardware routes (solus.md §2).
            raise APIError(422, "validation_error", "Only the code section accepts config entries")
        env = validate_config_payload(parsed, body.payload)
        assert isinstance(env, CodeEnvironment)
        entry = await upsert_code_environment(
            session, ctx.project.id, env, created_by=ctx.user.id, author="user"
        )
    elif body.kind == "artifact":
        assert body.artifact_id is not None and body.name is not None  # SolusEntryIn validator
        entry = await add_artifact_entry(
            session,
            ctx.project.id,
            parsed,
            artifact_id=body.artifact_id,
            name=body.name.strip(),
            created_by=ctx.user.id,
        )
        artifact = await session.scalar(
            select(Artifact).where(
                Artifact.id == entry.artifact_id,
                Artifact.project_id == ctx.project.id,
                Artifact.deleted_at.is_(None),
            )
        )
    else:
        assert body.text is not None  # SolusEntryIn validator
        entry = await add_text_entry(
            session, ctx.project.id, parsed, body.text, author="user", created_by=ctx.user.id
        )
    _emit_solus_event(
        ctx,
        session,
        "solus.entry_added",
        {"entry_id": str(entry.id), "section": parsed.value, "kind": entry.kind.value},
    )
    await session.commit()
    return envelope(serialize_entry(entry, artifact))


@router.patch("/entries/{entry_id}")
async def patch_entry(
    entry_id: uuid.UUID, body: SolusEntryPatch, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    entry = await update_text(
        session, await get_entry(session, ctx.project.id, entry_id), body.text
    )
    _emit_solus_event(ctx, session, "solus.entry_updated", {"entry_id": str(entry.id)})
    await session.commit()
    return envelope(serialize_entry(entry))


@router.delete("/entries/{entry_id}", status_code=204)
async def remove_entry(
    entry_id: uuid.UUID, request: Request, ctx: ProjectCtx, session: SessionDep
) -> Response:
    require_role(ctx, Role.MEMBER)
    entry = await get_entry(session, ctx.project.id, entry_id)
    store: ArtifactStore = request.app.state.artifact_store
    await delete_entry(session, store, entry)
    _emit_solus_event(
        ctx,
        session,
        "solus.entry_deleted",
        {
            "entry_id": str(entry.id),
            "section": entry.section.value,
            "kind": entry.kind.value,
            "removed_document": entry.kind == SolusEntryKind.ARTIFACT,
        },
    )
    await session.commit()
    return Response(status_code=204)
