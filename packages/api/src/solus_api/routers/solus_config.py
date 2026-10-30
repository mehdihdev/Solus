"""docs/api/solus.md — the project-level `.solus` (SOLUSDEV-240, 320). Read the seven
sections, file typed text, an already-uploaded artifact or an environment/software
config into one, edit an entry's text or typed metadata, or remove it. All scoped
through `ProjectCtx` (§7 tenant isolation; non-member → 404).
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
from solus_api.graph.live import graph_changed_frame
from solus_api.models import Artifact, Role, SolusEntry, SolusEntryKind, SolusSection, utcnow
from solus_api.schemas import SolusEntryIn, SolusEntryPatch, SolusEntryPayloadPatch
from solus_api.services.code_env import SUBSECTION, CodeEnvironment, upsert_code_environment
from solus_api.services.events import emit_event
from solus_api.services.physical_robots import GraphChangeCounts
from solus_api.services.solus_config import (
    add_artifact_entry,
    add_text_entry,
    delete_entry,
    ensure_solus_node,
    get_entry,
    load_sections,
    parse_section,
    serialize_entry,
    set_payload,
    update_text,
    validate_config_payload,
    validate_subsection,
)
from solus_api.storage import ArtifactStore

router = APIRouter(prefix="/api/v1/projects/{project_id}/solus")


class SolusConfigEntryIn(BaseModel):
    """SOLUSDEV-252: `{kind: "config", payload}` — a code environment document, validated
    by the section's model (`validate_config_payload`). Lives beside the route rather than
    in `schemas.SolusEntryIn` so the W1 text/artifact shape is untouched."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["config"]
    subsection: str | None = None
    payload: dict[str, Any]


def _entry_event(entry: SolusEntry) -> dict[str, Any]:
    """What every entry event names: the entry and the cell it lives in."""
    return {
        "entry_id": str(entry.id),
        "section": entry.section.value,
        "subsection": entry.subsection,
        "kind": entry.kind.value,
    }


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
    if parsed is SolusSection.HISTORY:
        raise APIError(422, "validation_error", "history owns no entries")
    if parsed is SolusSection.MEMBERS:
        raise APIError(
            422, "validation_error", "members entries are written through the preferences route"
        )
    subsection = validate_subsection(parsed, body.subsection)
    artifact: Artifact | None = None
    if isinstance(body, SolusConfigEntryIn):
        if (parsed, subsection) != (SolusSection.ENVIRONMENT, SUBSECTION):
            # Hardware configs are written only through the hardware routes (solus.md §2.2).
            raise APIError(
                422, "validation_error", "Only environment/software accepts config entries here"
            )
        env = validate_config_payload(parsed, subsection, body.payload)
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
            subsection=subsection,
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
            session,
            ctx.project.id,
            parsed,
            body.text,
            author="user",
            created_by=ctx.user.id,
            subsection=subsection,
        )
    _emit_solus_event(ctx, session, "solus.entry_added", _entry_event(entry))
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
    _emit_solus_event(ctx, session, "solus.entry_updated", _entry_event(entry))
    await session.commit()
    return envelope(serialize_entry(entry))


@router.patch("/entries/{entry_id}/payload")
async def patch_entry_payload(
    entry_id: uuid.UUID,
    body: SolusEntryPayloadPatch,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
) -> dict[str, Any]:
    """solus.md §3.2: a text/SOL entry's typed metadata, by its (section, subsection) model."""
    require_role(ctx, Role.MEMBER)
    entry = await set_payload(
        session,
        await get_entry(session, ctx.project.id, entry_id),
        body.payload,
        user_id=ctx.user.id,
        team_id=ctx.team.id,
    )
    _emit_solus_event(ctx, session, "solus.entry_updated", _entry_event(entry))
    data = serialize_entry(entry)
    await session.commit()
    # A limit (mass/cost) or goal link is graph state: `graph.changed` is what recomputes
    # the budgets document (services/budgets.BudgetTrigger), as every edge decision does.
    await request.app.state.graph_hub.publish(
        ctx.project.id,
        graph_changed_frame(
            project_id=ctx.project.id,
            source_id=None,
            sync_id=None,
            counts=GraphChangeCounts(entities_updated=1),
            at=utcnow().isoformat(),
        ),
    )
    return envelope(data)


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
