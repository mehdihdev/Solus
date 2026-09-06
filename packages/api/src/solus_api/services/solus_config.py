"""The project-level `.solus` (SOLUSDEV-240 / WORKSPACE W1, docs/api/solus.md).

One `solus_config` graph node per project, created with the project, plus
`solus_entries` rows under five sections. The `.solus` is configuration, not a
second store for graph facts: parts live in the graph, their configs live here.
An imported file is an `artifacts` row (retained — exempt from the TTL sweep)
wrapped in a `document` graph node that hangs off the `.solus` node through a
`references` edge, so `load_neighborhood` — and therefore Impact — reaches it.
Typed text is deliberately NOT a graph node.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.models import (
    Artifact,
    Domain,
    GraphEdge,
    GraphEntity,
    SolusEntry,
    SolusEntryKind,
    SolusSection,
    utcnow,
)

if TYPE_CHECKING:
    from solus_api.storage import ArtifactStore

SOLUS_KIND = "solus_config"
DOCUMENT_KIND = "document"
REFERENCES = "references"
#: `.solus` rows are user-editable, so they carry the existing editable origin.
ORIGIN = "manual"
MAX_TEXT_CHARS = 4000
MAX_ENTRIES_PER_SECTION = 500
SECTION_LABELS: dict[SolusSection, str] = {
    SolusSection.HARDWARE: "Hardware configs",
    SolusSection.DETAILS: "Project details",
    SolusSection.ERRORS: "Error logging",
    SolusSection.DOCS: "Documentation",
    SolusSection.CODE: "Code environment",
}


def parse_section(raw: str) -> SolusSection:
    try:
        return SolusSection(raw)
    except ValueError:
        raise APIError(404, "not_found", "Unknown .solus section") from None


def clean_text(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise APIError(422, "validation_error", "text must not be blank")
    if len(text) > MAX_TEXT_CHARS:
        raise APIError(422, "validation_error", f"text must be at most {MAX_TEXT_CHARS} characters")
    return text


async def ensure_solus_node(session: AsyncSession, project_id: uuid.UUID) -> GraphEntity:
    """Get-or-create the project's `.solus` node. Idempotent, so pre-existing
    projects self-heal on their first read instead of needing a data migration."""
    node = await session.scalar(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == SOLUS_KIND,
            GraphEntity.deleted_at.is_(None),
        )
        .order_by(GraphEntity.created_at)
        .limit(1)
    )
    if node is None:
        node = GraphEntity(
            project_id=project_id,
            kind=SOLUS_KIND,
            domain=Domain.PROJECT,
            name=".solus",
            origin=ORIGIN,
            attrs={},
        )
        session.add(node)
        await session.flush()
    return node


async def _section_full(
    session: AsyncSession, project_id: uuid.UUID, section: SolusSection
) -> None:
    count = await session.scalar(
        select(func.count())
        .select_from(SolusEntry)
        .where(
            SolusEntry.project_id == project_id,
            SolusEntry.section == section,
            SolusEntry.deleted_at.is_(None),
        )
    )
    if int(count or 0) >= MAX_ENTRIES_PER_SECTION:
        raise APIError(
            422, "validation_error", f"Section holds at most {MAX_ENTRIES_PER_SECTION} entries"
        )


async def add_text_entry(
    session: AsyncSession,
    project_id: uuid.UUID,
    section: SolusSection,
    text: str,
    *,
    author: str,
    created_by: uuid.UUID | None,
) -> SolusEntry:
    await _section_full(session, project_id, section)
    entry = SolusEntry(
        project_id=project_id,
        section=section,
        kind=SolusEntryKind.SOL if author == "sol" else SolusEntryKind.TEXT,
        text=clean_text(text),
        author=author,
        created_by=created_by,
    )
    session.add(entry)
    await session.flush()
    return entry


async def add_artifact_entry(
    session: AsyncSession,
    project_id: uuid.UUID,
    section: SolusSection,
    *,
    artifact_id: uuid.UUID,
    name: str,
    created_by: uuid.UUID,
) -> SolusEntry:
    """File an already-uploaded artifact: mark it retained, wrap it in a `document`
    node edged from `.solus`, and record the entry. The artifact must be live and
    belong to THIS project — anything else is 404 (no existence oracle)."""
    artifact = await session.scalar(
        select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.project_id == project_id,
            Artifact.deleted_at.is_(None),
        )
    )
    if artifact is None:
        raise APIError(404, "not_found", "Artifact not found")
    await _section_full(session, project_id, section)
    node = await ensure_solus_node(session, project_id)
    artifact.retained = True
    document = GraphEntity(
        project_id=project_id,
        kind=DOCUMENT_KIND,
        domain=Domain.PROJECT,
        name=name,
        origin=ORIGIN,
        attrs={
            "artifact_id": str(artifact.id),
            "media_type": artifact.media_type,
            "size_bytes": artifact.size_bytes,
            "filename": name,
            "section": section.value,
        },
    )
    session.add(document)
    await session.flush()
    session.add(
        GraphEdge(
            project_id=project_id,
            src_id=node.id,
            dst_id=document.id,
            relation_type=REFERENCES,
            domain_pair=f"{Domain.PROJECT.value}<->{Domain.PROJECT.value}",
            origin=ORIGIN,
            attrs={"section": section.value},
        )
    )
    entry = SolusEntry(
        project_id=project_id,
        section=section,
        kind=SolusEntryKind.ARTIFACT,
        text=name,
        artifact_id=artifact.id,
        entity_id=document.id,
        author="user",
        created_by=created_by,
    )
    session.add(entry)
    await session.flush()
    return entry


async def get_entry(
    session: AsyncSession, project_id: uuid.UUID, entry_id: uuid.UUID
) -> SolusEntry:
    entry = await session.scalar(
        select(SolusEntry).where(
            SolusEntry.id == entry_id,
            SolusEntry.project_id == project_id,
            SolusEntry.deleted_at.is_(None),
        )
    )
    if entry is None:
        raise APIError(404, "not_found", "Entry not found")
    return entry


def update_text(entry: SolusEntry, text: str) -> SolusEntry:
    if entry.kind == SolusEntryKind.ARTIFACT:
        raise APIError(409, "conflict", "An imported file has no editable text")
    entry.text = clean_text(text)
    return entry


async def delete_entry(session: AsyncSession, store: ArtifactStore, entry: SolusEntry) -> None:
    """Soft-delete the entry and, for an imported file, its document node, the
    node's edges, and the artifact row (bytes removed)."""
    now = utcnow()
    entry.deleted_at = now
    if entry.entity_id is not None:
        document = await session.get(GraphEntity, entry.entity_id)
        if document is not None and document.deleted_at is None:
            document.deleted_at = now
        edges = await session.scalars(
            select(GraphEdge).where(
                or_(GraphEdge.src_id == entry.entity_id, GraphEdge.dst_id == entry.entity_id),
                GraphEdge.deleted_at.is_(None),
            )
        )
        for edge in edges:
            edge.deleted_at = now
    if entry.artifact_id is not None:
        artifact = await session.get(Artifact, entry.artifact_id)
        if artifact is not None and artifact.deleted_at is None:
            await store.delete(str(artifact.id))
            artifact.deleted_at = now
    await session.flush()


def serialize_entry(entry: SolusEntry, artifact: Artifact | None = None) -> dict[str, Any]:
    return {
        "id": entry.id,
        "section": entry.section.value,
        "kind": entry.kind.value,
        "author": entry.author,
        "text": entry.text if entry.kind != SolusEntryKind.ARTIFACT else None,
        "name": entry.text if entry.kind == SolusEntryKind.ARTIFACT else None,
        "artifact_id": entry.artifact_id,
        "entity_id": entry.entity_id,
        "media_type": artifact.media_type if artifact is not None else None,
        "size_bytes": artifact.size_bytes if artifact is not None else None,
        "created_by": entry.created_by,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


async def load_sections(
    session: AsyncSession, project_id: uuid.UUID
) -> dict[str, list[dict[str, Any]]]:
    """Every live entry, grouped by section in creation order — the panel's payload."""
    entries = (
        await session.scalars(
            select(SolusEntry)
            .where(SolusEntry.project_id == project_id, SolusEntry.deleted_at.is_(None))
            .order_by(SolusEntry.created_at, SolusEntry.id)
        )
    ).all()
    artifact_ids = [e.artifact_id for e in entries if e.artifact_id is not None]
    artifacts: dict[uuid.UUID, Artifact] = {}
    if artifact_ids:
        rows = await session.scalars(select(Artifact).where(Artifact.id.in_(artifact_ids)))
        artifacts = {a.id: a for a in rows}
    sections: dict[str, list[dict[str, Any]]] = {s.value: [] for s in SolusSection}
    for entry in entries:
        artifact = artifacts.get(entry.artifact_id) if entry.artifact_id is not None else None
        sections[entry.section.value].append(serialize_entry(entry, artifact))
    return sections
