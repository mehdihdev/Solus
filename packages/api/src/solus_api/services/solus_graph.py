"""Project-serialized graph identities for `.solus` navigation (SOLUSDEV-242, 320).

Entry rows own the text; the graph owns selectable identities and containment:
`.solus → section → [subsection →] entry`. `SECTION_TREE` is the one vocabulary of
sections, labels and fixed subsections (docs/api/solus.md §1). All callers hold the
project lock until their transaction commits, including section-limit checks and
writes made by the SOL tool.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Final

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    Project,
    SolusEntry,
    SolusEntryKind,
    SolusSection,
)

SOLUS_KIND = kinds.SOLUS_CONFIG
DOCUMENT_KIND = kinds.DOCUMENT
CONFIG_NODE_KIND = kinds.HARDWARE_CONFIG  # a physical entity's hardware configuration
ORIGIN = "manual"
#: section → (display label, fixed subsections). An empty tuple means the section has no
#: fixed vocabulary: goals/members take validated free values, errors/history none.
SECTION_TREE: Final[Mapping[SolusSection, tuple[str, tuple[str, ...]]]] = {
    SolusSection.GOALS: ("Goals", ()),
    SolusSection.CONSTRAINTS: ("Constraints", ("rules", "compliance", "style", "budgets")),
    SolusSection.DOCUMENTATION: (
        "Documentation",
        ("datasheets", "guides", "references", "decisions"),
    ),
    SolusSection.ERRORS: ("Error logging", ()),
    SolusSection.ENVIRONMENT: ("Environment", ("spec", "hardware", "software", "divergences")),
    SolusSection.MEMBERS: ("Members", ()),
    SolusSection.HISTORY: ("History", ()),
}
SECTION_LABELS: Final[Mapping[SolusSection, str]] = {
    section: label for section, (label, _) in SECTION_TREE.items()
}
_TREE_KINDS = (SOLUS_KIND, kinds.SOLUS_SECTION, kinds.SOLUS_SUBSECTION)
_ENTRY_KINDS: Final[Mapping[SolusSection, str]] = {
    SolusSection.ERRORS: kinds.SOLUS_ERROR,
    SolusSection.GOALS: kinds.SOLUS_GOAL,
    SolusSection.CONSTRAINTS: kinds.SOLUS_CONSTRAINT,
}


def entry_label(text: str | None) -> str:
    """A bounded, single-line preview, never an authoritative copy of the text."""
    return " ".join((text or "").split())[:120] or "Untitled note"


def entry_node_kind(entry: SolusEntry) -> str:
    """document (ARTIFACT) · hardware_config (entity-bound CONFIG in environment/hardware) ·
    solus_error / solus_goal / solus_constraint by section · solus_note otherwise."""
    if entry.kind == SolusEntryKind.ARTIFACT:
        return DOCUMENT_KIND
    if (
        entry.kind == SolusEntryKind.CONFIG
        and entry.configured_entity_id is not None
        and entry.section == SolusSection.ENVIRONMENT
        and entry.subsection == "hardware"
    ):
        return CONFIG_NODE_KIND
    return _ENTRY_KINDS.get(entry.section, kinds.SOLUS_NOTE)


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
        self.pending_edges: list[tuple[uuid.UUID, uuid.UUID, str, dict[str, Any]]] = []
        self.root = next((node for node in nodes if node.kind == SOLUS_KIND), None) or self._node(
            SOLUS_KIND, ".solus", {}
        )
        self.sections: dict[SolusSection, GraphEntity] = {}
        self.subsections: dict[tuple[SolusSection, str], GraphEntity] = {}
        for node in nodes:
            if node.kind == kinds.SOLUS_SUBSECTION:
                try:
                    key = (
                        SolusSection(str(node.attrs.get("section"))),
                        str(node.attrs["subsection"]),
                    )
                except (ValueError, KeyError):
                    continue  # a retired or malformed node is not part of the tree
                self.subsections.setdefault(key, node)
        for section, (label, fixed) in SECTION_TREE.items():
            found = next(
                (
                    node
                    for node in nodes
                    if node.kind == kinds.SOLUS_SECTION
                    and node.attrs.get("section") == section.value
                ),
                None,
            )
            self.sections[section] = found or self._node(
                kinds.SOLUS_SECTION, label, {"section": section.value}
            )
            self._edge(self.root, self.sections[section], "contains")
            for subsection in fixed:
                self.subsection_node(section, subsection)

    def subsection_node(self, section: SolusSection, subsection: str) -> GraphEntity:
        """The `solus_subsection` node under a section, created on first use (fixed ones
        at ensure(), free goals/members slugs on their first entry)."""
        key = (section, subsection)
        node = self.subsections.get(key)
        if node is None:
            node = self._node(
                kinds.SOLUS_SUBSECTION,
                subsection,
                {"section": section.value, "subsection": subsection},
            )
            self.subsections[key] = node
        self._edge(self.sections[section], node, "contains")
        return node

    @classmethod
    async def ensure(cls, session: AsyncSession, project_id: uuid.UUID) -> SolusGraph:
        await lock_project(session, project_id)
        deleted_config_identity = (
            select(GraphEntity.id)
            .where(
                GraphEntity.id == SolusEntry.entity_id,
                GraphEntity.project_id == project_id,
                GraphEntity.domain == Domain.PROJECT,
                GraphEntity.origin == ORIGIN,
                GraphEntity.source_id.is_(None),
                GraphEntity.deleted_at.is_not(None),
            )
            .exists()
        )
        entries = list(
            await session.scalars(
                select(SolusEntry).where(
                    SolusEntry.project_id == project_id,
                    SolusEntry.deleted_at.is_(None),
                    # Deleted entity-bound CONFIG graph identities are history, not
                    # candidates for navigation repair. Foreign or malformed references
                    # still reach attach_entry's fail-closed validation below.
                    or_(
                        SolusEntry.kind != SolusEntryKind.CONFIG,
                        SolusEntry.configured_entity_id.is_(None),
                        ~deleted_config_identity,
                    ),
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
                        GraphEntity.kind.in_(_TREE_KINDS),
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
                    GraphEdge.src_id.in_([node.id for node in nodes if node.kind in _TREE_KINDS]),
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
        pending, self.pending_edges = self.pending_edges, []
        for src_id, dst_id, kind, attrs in pending:
            await write_edge(
                self.session,
                project_id=self.project_id,
                src_id=src_id,
                dst_id=dst_id,
                relation_type=kind,
                origin=ORIGIN,
                confidence=1.0,
                evidence=[],
                created_by=None,
                attrs=attrs,
            )
        await self.session.flush()

    def _node(self, kind: str, name: str, attrs: dict[str, Any]) -> GraphEntity:
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
            attrs = {"section": child.attrs["section"]}
            if child.attrs.get("subsection") is not None:
                attrs["subsection"] = child.attrs["subsection"]
            self.pending_edges.append((parent.id, child.id, kind, attrs))
            self.edges.add(key)

    def attach_entry(self, entry: SolusEntry) -> GraphEntity:
        """Keep legacy document IDs, or create a note identity, then attach it."""
        if entry.project_id != self.project_id:
            raise APIError(404, "not_found", "Entry not found")
        kind = entry_node_kind(entry)
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
        attrs = {
            **node.attrs,
            "solus_entry_id": str(entry.id),
            "section": entry.section.value,
            "subsection": entry.subsection,
        }
        if attrs != node.attrs:
            node.attrs = attrs
        parent = (
            self.subsection_node(entry.section, entry.subsection)
            if entry.subsection
            else self.sections[entry.section]
        )
        self._edge(parent, node, "contains")
        if entry.kind == SolusEntryKind.ARTIFACT:
            self._edge(self.root, node, "references")
        return node
