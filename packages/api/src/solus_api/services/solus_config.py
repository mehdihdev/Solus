"""The project-level `.solus` (SOLUSDEV-240 / WORKSPACE W1, docs/api/solus.md).

One `solus_config` graph node per project, created with the project, plus
`solus_entries` rows under seven sections with optional subsections (SOLUSDEV-320).
The `.solus` is configuration, not a second store for graph facts: parts live in the
graph, their configs live here. An imported file is an `artifacts` row (retained —
exempt from the TTL sweep) wrapped in a `document` graph node that hangs off the
`.solus` node through a `references` edge, so `load_neighborhood` — and therefore
Impact — reaches it. Every section, subsection and entry has a graph identity; full
text stays in the entry row.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ValidationError
from solus_contracts.relations import EdgeEvidence, EdgeOrigin, EvidenceKind, RelationType
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.edges import retire_edge, write_edge
from solus_api.hardware.config import EntityHardwareConfig
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
from solus_api.services.activity import record_activity
from solus_api.services.solus_graph import (
    DOCUMENT_KIND,
    ORIGIN,
    SECTION_TREE,
    SolusGraph,
    entry_label,
    lock_project,
)
from solus_api.services.solus_graph import SECTION_LABELS as SECTION_LABELS
from solus_api.services.solus_payloads import PAYLOAD_MODELS, GoalMeta, payload_unchanged

if TYPE_CHECKING:
    from solus_api.storage import ArtifactStore

MAX_TEXT_CHARS = 4000
MAX_ENTRIES_PER_SECTION = 500
GOAL_SLUG: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
MEMBER_HEX: Final = re.compile(r"^[0-9a-f]{32}$")
#: The fixed subsection vocabulary per section (docs/api/solus.md §1). Empty = none fixed:
#: goals take a free slug (default `general`), members a user's `uuid.hex`, errors and
#: history nothing at all.
SUBSECTIONS: Final[Mapping[SolusSection, tuple[str, ...]]] = {
    section: fixed for section, (_, fixed) in SECTION_TREE.items()
}
_FREE_SUBSECTIONS: Final[Mapping[SolusSection, tuple[re.Pattern[str], str | None]]] = {
    SolusSection.GOALS: (GOAL_SLUG, "general"),
    SolusSection.MEMBERS: (MEMBER_HEX, None),
}


def parse_section(raw: str) -> SolusSection:
    try:
        return SolusSection(raw)
    except ValueError:
        raise APIError(404, "not_found", "Unknown .solus section") from None


def validate_subsection(section: SolusSection, raw: str | None) -> str | None:
    """The subsection an entry may carry in `section`, or 422. Fixed vocabularies admit
    their values or nothing (the entry then hangs off the section node); goals default
    to `general`; members need a user id; errors and history take none."""
    if section == SolusSection.HISTORY:
        raise APIError(422, "validation_error", "history owns no entries")
    free = _FREE_SUBSECTIONS.get(section)
    if free is not None:
        pattern, default = free
        if raw is None:
            if default is None:
                raise APIError(422, "validation_error", f"{section.value} needs a subsection")
            return default
        if not pattern.fullmatch(raw):
            raise APIError(
                422, "validation_error", f"{section.value}/{raw} is not a valid subsection"
            )
        return raw
    if raw is None:
        return None
    fixed = SUBSECTIONS[section]
    if raw not in fixed:
        held = f"one of {', '.join(fixed)}" if fixed else "no subsection"
        raise APIError(422, "validation_error", f"{section.value} takes {held}, not {raw!r}")
    return raw


_CONFIG_MODELS: Final[dict[tuple[str, str | None], type[BaseModel]]] = {
    (SolusSection.ENVIRONMENT.value, "hardware"): EntityHardwareConfig,
}


def validate_config_payload(
    section: SolusSection, subsection: str | None, payload: Mapping[str, Any]
) -> BaseModel:
    """A CONFIG entry's payload, validated by the model its CELL owns: environment/hardware →
    `EntityHardwareConfig` (written only through the hardware routes), environment/software →
    `CodeEnvironment`, then the registry in `solus_payloads`. Other cells hold none (422)."""
    from solus_api.services.code_env import CodeEnvironment  # circular at module level

    models: dict[tuple[str, str | None], type[BaseModel]] = {
        **PAYLOAD_MODELS,
        **_CONFIG_MODELS,
        (SolusSection.ENVIRONMENT.value, "software"): CodeEnvironment,
    }
    model = models.get((section.value, subsection))
    if model is None and section in _FREE_SUBSECTIONS:  # members/<uid.hex> → one model
        model = models.get((section.value, None))
    if model is None:
        raise APIError(
            422, "validation_error", f"{section.value}/{subsection} holds no config entries"
        )
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(loc) for loc in first["loc"]) or "document"
        raise APIError(422, "validation_error", f"{where}: {first['msg']}") from None


def clean_text(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise APIError(422, "validation_error", "text must not be blank")
    if len(text) > MAX_TEXT_CHARS:
        raise APIError(422, "validation_error", f"text must be at most {MAX_TEXT_CHARS} characters")
    return text


async def ensure_solus_node(session: AsyncSession, project_id: uuid.UUID) -> GraphEntity:
    """Create/repair the project hierarchy, preserving existing live identities."""
    return (await SolusGraph.ensure(session, project_id)).root


async def _section_full(
    session: AsyncSession, project_id: uuid.UUID, section: SolusSection
) -> None:
    """The per-section cap. Entity-bound CONFIG rows are bounded by the entities they
    configure, so they never count (resolution 20)."""
    count = await session.scalar(
        select(func.count())
        .select_from(SolusEntry)
        .where(
            SolusEntry.project_id == project_id,
            SolusEntry.section == section,
            SolusEntry.deleted_at.is_(None),
            SolusEntry.configured_entity_id.is_(None),
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
    subsection: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> SolusEntry:
    cleaned = clean_text(text)
    subsection = validate_subsection(section, subsection)
    graph = await SolusGraph.ensure(session, project_id)
    await _section_full(session, project_id, section)
    entry = SolusEntry(
        project_id=project_id,
        section=section,
        subsection=subsection,
        kind=SolusEntryKind.SOL if author == "sol" else SolusEntryKind.TEXT,
        text=cleaned,
        author=author,
        created_by=created_by,
        payload=dict(payload) if payload is not None else None,
    )
    session.add(entry)
    await session.flush()
    graph.attach_entry(entry)
    await graph.flush()
    return entry


async def add_artifact_entry(
    session: AsyncSession,
    project_id: uuid.UUID,
    section: SolusSection,
    *,
    artifact_id: uuid.UUID,
    name: str,
    created_by: uuid.UUID,
    subsection: str | None = None,
) -> SolusEntry:
    """File an already-uploaded artifact: mark it retained, wrap it in a `document`
    node edged from `.solus`, and record the entry. The artifact must be live and
    belong to THIS project — anything else is 404 (no existence oracle)."""
    subsection = validate_subsection(section, subsection)
    graph = await SolusGraph.ensure(session, project_id)
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
            "subsection": subsection,
        },
    )
    session.add(document)
    await session.flush()
    entry = SolusEntry(
        project_id=project_id,
        section=section,
        subsection=subsection,
        kind=SolusEntryKind.ARTIFACT,
        text=name,
        artifact_id=artifact.id,
        entity_id=document.id,
        author="user",
        created_by=created_by,
    )
    session.add(entry)
    await session.flush()
    graph.nodes[document.id] = document
    graph.attach_entry(entry)
    await graph.flush()
    return entry


async def get_entry(
    session: AsyncSession, project_id: uuid.UUID, entry_id: uuid.UUID
) -> SolusEntry:
    await lock_project(session, project_id)
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


def _editable(entry: SolusEntry) -> None:
    if entry.kind == SolusEntryKind.ARTIFACT:
        raise APIError(409, "conflict", "An imported file has no editable text")
    if entry.kind == SolusEntryKind.CONFIG:
        raise APIError(409, "conflict", "A config entry is edited through its own routes")


async def update_text(session: AsyncSession, entry: SolusEntry, text: str) -> SolusEntry:
    _editable(entry)
    entry.text = clean_text(text)
    graph = await SolusGraph.ensure(session, entry.project_id)
    node = graph.attach_entry(entry)
    node.name = entry_label(entry.text)
    node.version += 1
    return entry


async def set_payload(
    session: AsyncSession,
    entry: SolusEntry,
    payload: Mapping[str, Any],
    *,
    user_id: uuid.UUID,
    team_id: uuid.UUID,
) -> SolusEntry:
    """§3.2: replace a TEXT/SOL entry's typed metadata with the validated document of its
    (section, subsection) cell; config and artifact entries are 409. A goal's run links
    are mirrored as edges and its status change recorded (P5-T5). Flushes, never commits."""
    from solus_api.services.solus_payloads import GoalMeta, validate_entry_payload

    _editable(entry)
    validated = validate_entry_payload(
        entry.section.value, entry.subsection, entry.kind.value, payload
    )
    previous = dict(entry.payload or {})
    entry.payload = validated.model_dump(mode="json")
    if isinstance(validated, GoalMeta):
        await _sync_goal(session, entry, validated, previous, user_id=user_id, team_id=team_id)
    return entry


async def _sync_goal(
    session: AsyncSession,
    entry: SolusEntry,
    meta: GoalMeta,
    previous: Mapping[str, Any],
    *,
    user_id: uuid.UUID,
    team_id: uuid.UUID,
) -> None:
    """`verified_by` goal → bench_run mirrors `linked_run_ids`: the ids are member input, so
    each must be a live `bench_run` of THIS project (else 422, nothing written); a run no
    longer listed retires its edge, a re-listed one revives it. A status change is one
    `goal.status_changed` history row whose "why" is the first linked conversation."""
    wanted = set(meta.linked_run_ids)
    if wanted:
        known = set(
            await session.scalars(
                select(GraphEntity.id).where(
                    GraphEntity.project_id == entry.project_id,
                    GraphEntity.id.in_(wanted),
                    GraphEntity.kind == kinds.BENCH_RUN,
                    GraphEntity.deleted_at.is_(None),
                )
            )
        )
        missing = sorted(map(str, wanted - known))
        if missing:
            raise APIError(422, "validation_error", f"Unknown run in this project: {missing[0]}")
    graph = await SolusGraph.ensure(session, entry.project_id)
    node = graph.attach_entry(entry)
    await graph.flush()
    existing: dict[uuid.UUID, GraphEdge] = {}
    for edge in await session.scalars(
        select(GraphEdge)
        .where(
            GraphEdge.project_id == entry.project_id,
            GraphEdge.src_id == node.id,
            GraphEdge.relation_type == RelationType.VERIFIED_BY.value,
        )
        .order_by(GraphEdge.deleted_at.is_(None), GraphEdge.created_at)
    ):
        existing[edge.dst_id] = edge  # the live row (ordered last) wins over tombstones
    for run_id, edge in existing.items():
        if run_id not in wanted and edge.deleted_at is None:
            retire_edge(edge)
    for run_id in sorted(wanted, key=str):
        prior = existing.get(run_id)
        await write_edge(
            session,
            project_id=entry.project_id,
            src_id=node.id,
            dst_id=run_id,
            relation_type=RelationType.VERIFIED_BY.value,
            origin=EdgeOrigin.MANUAL.value,
            confidence=1.0,
            evidence=[EdgeEvidence(kind=EvidenceKind.RUN, ref=str(run_id))],
            created_by=user_id,
            edge_id=prior.id if prior is not None else None,
        )
    before = str(previous.get("status") or "open")
    if before != meta.status:
        record_activity(
            session,
            team_id=team_id,
            activity_type="goal.status_changed",
            actor_id=user_id,
            project_id=entry.project_id,
            domain=Domain.PROJECT.value,
            payload={"entry_id": str(entry.id), "from": before, "to": meta.status},
            entity_ids=[node.id],
            why_ref=(
                str(meta.linked_conversation_ids[0]) if meta.linked_conversation_ids else None
            ),
        )


async def find_config_entry(
    session: AsyncSession,
    project_id: uuid.UUID,
    section: SolusSection,
    subsection: str | None,
    *,
    configured_entity_id: uuid.UUID | None = None,
    any_subject: bool = False,
) -> SolusEntry | None:
    """The live CONFIG entry of one cell and subject (`None` = the cell's unbound entry;
    `any_subject` = the cell's first entry whatever it is bound to)."""
    stmt = select(SolusEntry).where(
        SolusEntry.project_id == project_id,
        SolusEntry.section == section,
        SolusEntry.subsection == subsection,
        SolusEntry.kind == SolusEntryKind.CONFIG,
        SolusEntry.deleted_at.is_(None),
    )
    if not any_subject:
        stmt = stmt.where(
            SolusEntry.configured_entity_id == configured_entity_id
            if configured_entity_id is not None
            else SolusEntry.configured_entity_id.is_(None)
        )
    entry: SolusEntry | None = await session.scalar(
        stmt.order_by(SolusEntry.created_at, SolusEntry.id).limit(1)
    )
    return entry


async def put_config_entry(
    session: AsyncSession,
    project_id: uuid.UUID,
    section: SolusSection,
    subsection: str | None,
    document: BaseModel,
    *,
    text: str,
    configured_entity_id: uuid.UUID | None,
    created_by: uuid.UUID | None,
    author: str,
    ignore: tuple[str, ...] = (),
) -> SolusEntry:
    """ONE system/member CONFIG entry per (cell, subject): created on the first write and
    replaced in place after (same id; `config_version` +1 when entity-bound). A document
    equal to the stored one apart from the `ignore`d keys (a recompute timestamp) is
    refreshed without a version. The caller commits."""
    graph = await SolusGraph.ensure(session, project_id)  # holds the project lock
    payload = document.model_dump(mode="json")
    entry = await find_config_entry(
        session, project_id, section, subsection, configured_entity_id=configured_entity_id
    )
    if entry is not None:
        unchanged = payload_unchanged(entry.payload, payload, ignore)
        entry.payload = payload
        if unchanged:
            return entry
        entry.text = text
        if configured_entity_id is not None:
            entry.config_version += 1
        node = graph.attach_entry(entry)
        node.name = entry_label(text)
        node.version += 1
        await graph.flush()
        return entry
    if configured_entity_id is None:
        await _section_full(session, project_id, section)
    elif await session.scalar(
        select(SolusEntry.id).where(
            SolusEntry.project_id == project_id,
            SolusEntry.configured_entity_id == configured_entity_id,
            SolusEntry.kind == SolusEntryKind.CONFIG,
            SolusEntry.deleted_at.is_(None),
        )
    ):
        # uq_solus_config_subject_live: one live CONFIG row per subject across every cell.
        raise APIError(409, "conflict", "This entity already has a live configuration entry")
    entry = SolusEntry(
        project_id=project_id,
        section=section,
        subsection=subsection,
        kind=SolusEntryKind.CONFIG,
        text=text,
        payload=payload,
        author=author,
        created_by=created_by,
        configured_entity_id=configured_entity_id,
        config_version=1 if configured_entity_id is not None else 0,
    )
    session.add(entry)
    await session.flush()
    graph.attach_entry(entry)
    await graph.flush()
    return entry


async def delete_entry(session: AsyncSession, store: ArtifactStore, entry: SolusEntry) -> None:
    """Remove this entry identity and edges; only artifact entries remove bytes."""
    graph = await SolusGraph.ensure(session, entry.project_id)
    node = graph.attach_entry(entry)
    now = utcnow()
    entry.deleted_at = now
    node.deleted_at = now
    if entry.entity_id is not None:
        edges = await session.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == entry.project_id,
                or_(GraphEdge.src_id == entry.entity_id, GraphEdge.dst_id == entry.entity_id),
                GraphEdge.deleted_at.is_(None),
            )
        )
        for edge in edges:
            edge.deleted_at = now
    if entry.kind == SolusEntryKind.ARTIFACT and entry.artifact_id is not None:
        artifact = await session.scalar(
            select(Artifact).where(
                Artifact.id == entry.artifact_id,
                Artifact.project_id == entry.project_id,
            )
        )
        if artifact is not None and artifact.deleted_at is None:
            await store.delete(str(artifact.id))
            artifact.deleted_at = now
    await session.flush()


def serialize_entry(entry: SolusEntry, artifact: Artifact | None = None) -> dict[str, Any]:
    return {
        "id": entry.id,
        "section": entry.section.value,
        "subsection": entry.subsection,
        "kind": entry.kind.value,
        "author": entry.author,
        "text": entry.text if entry.kind != SolusEntryKind.ARTIFACT else None,
        "name": entry.text if entry.kind == SolusEntryKind.ARTIFACT else None,
        "artifact_id": entry.artifact_id,
        "entity_id": entry.entity_id,
        "media_type": artifact.media_type if artifact is not None else None,
        "size_bytes": artifact.size_bytes if artifact is not None else None,
        # A CONFIG's validated document, or a text entry's typed metadata (§2.1).
        "payload": entry.payload,
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
        rows = await session.scalars(
            select(Artifact).where(
                Artifact.id.in_(artifact_ids),
                Artifact.project_id == project_id,
                Artifact.deleted_at.is_(None),
            )
        )
        artifacts = {a.id: a for a in rows}
    sections: dict[str, list[dict[str, Any]]] = {s.value: [] for s in SolusSection}
    for entry in entries:
        artifact = artifacts.get(entry.artifact_id) if entry.artifact_id is not None else None
        sections[entry.section.value].append(serialize_entry(entry, artifact))
    return sections
