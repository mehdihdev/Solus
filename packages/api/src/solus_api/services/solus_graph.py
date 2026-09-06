"""Project-serialized graph identities for `.solus` navigation (SOLUSDEV-242).

Entry rows own the text; the graph owns selectable identities and containment.
All callers hold the project lock until their transaction commits, including
section-limit checks and writes made by the SOL tool.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from solus_api.core.errors import APIError
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    Project,
    SolusEntry,
    SolusEntryKind,
    SolusSection,
)

SOLUS_KIND = "solus_config"
DOCUMENT_KIND = "document"
ORIGIN = "manual"
SECTION_LABELS: dict[SolusSection, str] = {
    SolusSection.HARDWARE: "Hardware configs",
    SolusSection.DETAILS: "Project details",
    SolusSection.ERRORS: "Error logging",
    SolusSection.DOCS: "Documentation",
    SolusSection.CODE: "Code environment",
}


def entry_label(text: str | None) -> str:
    """A bounded, single-line preview, never an authoritative copy of the text."""
    return " ".join((text or "").split())[:120] or "Untitled note"


async def lock_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    project = await session.scalar(
        select(Project.id)
        .where(Project.id == project_id, Project.deleted_at.is_(None))
        .with_for_update()
    )
    if project is None:
        raise APIError(404, "not_found", "Project not found")


class SolusGraph:
    """One locked project snapshot; repair uses bounded bulk reads, not N+1 queries."""

    def __init__(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
        nodes: list[GraphEntity],
        edges: list[GraphEdge],
    ) -> None:
        self.session = session
        self.project_id = project_id
        self.nodes = {node.id: node for node in nodes}
        self.edges = {(edge.src_id, edge.dst_id, edge.relation_type) for edge in edges}
        self.pending_edges: list[GraphEdge] = []
        self.root = next((node for node in nodes if node.kind == SOLUS_KIND), None) or self._node(
            SOLUS_KIND, ".solus", {}
        )
        self.sections: dict[SolusSection, GraphEntity] = {}
        for section, label in SECTION_LABELS.items():
            node = next(
                (
                    node
                    for node in nodes
                    if node.kind == "solus_section" and node.attrs.get("section") == section.value
                ),
                None,
            )
            self.sections[section] = node or self._node(
                "solus_section", label, {"section": section.value}
            )
            self._edge(self.root, self.sections[section], "contains")

    @classmethod
    async def ensure(cls, session: AsyncSession, project_id: uuid.UUID) -> SolusGraph:
        await lock_project(session, project_id)
        entries = list(
            await session.scalars(
                select(SolusEntry).where(
                    SolusEntry.project_id == project_id, SolusEntry.deleted_at.is_(None)
                )
            )
        )
        entry_node_ids = [entry.entity_id for entry in entries if entry.entity_id is not None]
        nodes = list(
            await session.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.domain == Domain.PROJECT,
                    GraphEntity.origin == ORIGIN,
                    GraphEntity.source_id.is_(None),
                    GraphEntity.deleted_at.is_(None),
                    or_(
                        GraphEntity.kind.in_((SOLUS_KIND, "solus_section")),
                        GraphEntity.id.in_(entry_node_ids),
                    ),
                )
                .order_by(GraphEntity.created_at, GraphEntity.id)
            )
        )
        edges = list(
            await session.scalars(
                select(GraphEdge).where(
                    GraphEdge.project_id == project_id,
                    GraphEdge.deleted_at.is_(None),
                    GraphEdge.src_id.in_(
                        [node.id for node in nodes if node.kind in (SOLUS_KIND, "solus_section")]
                    ),
                    GraphEdge.relation_type.in_(("contains", "references")),
                )
            )
        )
        graph = cls(session, project_id, nodes, edges)
        for entry in entries:
            graph.attach_entry(entry)
        await graph.flush()
        return graph

    async def flush(self) -> None:
        # These mappers intentionally have no ORM relationships. Explicit ordering
        # ensures the node FKs exist before new edges and entry references flush.
        await self.session.flush(list(self.nodes.values()))
        self.session.add_all(self.pending_edges)
        self.pending_edges.clear()
        await self.session.flush()

    def _node(self, kind: str, name: str, attrs: dict[str, str]) -> GraphEntity:
        node = GraphEntity(
            id=uuid7(),
            project_id=self.project_id,
            kind=kind,
            domain=Domain.PROJECT,
            name=name,
            origin=ORIGIN,
            attrs=attrs,
        )
        self.session.add(node)
        self.nodes[node.id] = node
        return node

    def _edge(self, parent: GraphEntity, child: GraphEntity, kind: str) -> None:
        key = (parent.id, child.id, kind)
        if key not in self.edges:
            self.pending_edges.append(
                GraphEdge(
                    project_id=self.project_id,
                    src_id=parent.id,
                    dst_id=child.id,
                    relation_type=kind,
                    domain_pair="project<->project",
                    origin=ORIGIN,
                    attrs={"section": child.attrs["section"]},
                )
            )
            self.edges.add(key)

    def attach_entry(self, entry: SolusEntry) -> GraphEntity:
        """Keep legacy document IDs, or create a note identity, then attach it."""
        if entry.project_id != self.project_id:
            raise APIError(404, "not_found", "Entry not found")
        kind = (
            DOCUMENT_KIND
            if entry.kind == SolusEntryKind.ARTIFACT
            else ("solus_error" if entry.section == SolusSection.ERRORS else "solus_note")
        )
        node = self.nodes.get(entry.entity_id) if entry.entity_id is not None else None
        if entry.entity_id is not None:
            # No FK alone proves tenancy, ownership, or that this is an entry node.
            if (
                node is None
                or node.kind != kind
                or node.attrs.get("solus_entry_id") not in (None, str(entry.id))
            ):
                raise APIError(404, "not_found", "Entry entity not found")
            if kind == DOCUMENT_KIND and node.attrs.get("artifact_id") != str(entry.artifact_id):
                raise APIError(404, "not_found", "Entry artifact not found")
        elif kind == DOCUMENT_KIND:
            raise APIError(404, "not_found", "Entry document not found")
        else:
            node = self._node(kind, entry_label(entry.text), {})
            entry.entity_id = node.id
        assert node is not None
        attrs = {**node.attrs, "solus_entry_id": str(entry.id), "section": entry.section.value}
        if attrs != node.attrs:
            node.attrs = attrs
        self._edge(self.sections[entry.section], node, "contains")
        if entry.kind == SolusEntryKind.ARTIFACT:
            self._edge(self.root, node, "references")
        return node
