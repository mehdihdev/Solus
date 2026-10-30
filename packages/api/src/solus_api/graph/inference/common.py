"""What every inference module shares: the report, the counting edge writer, two lookups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from solus_contracts.relations import EdgeEvidence, EdgeOrigin, matrix_cell
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.graph import kinds
from solus_api.graph.edges import is_candidate, write_edge
from solus_api.models import GraphEdge, GraphEntity

#: Kinds a firmware or manifest reference can resolve to by path.
CODE_FILE_KINDS = frozenset({kinds.CODE_FILE, kinds.ARDUINO_SKETCH, kinds.CODE_MODULE})
#: `hardware/topology.py:EVIDENCE_MARKER`, spelled here so this package never imports the
#: hardware tree at module load (store.py imports this package for its config hook).
EVIDENCE_MARKER = "hardware_extraction_evidence_v1"
EVIDENCE_RELATION = "hardware_evidence_for"


@dataclass
class InferenceReport:
    module: str
    created: int = 0
    updated: int = 0
    skipped: int = 0
    candidates: int = 0


class EdgeWriter:
    """`write_edge` with `origin=inferred`, counting created / updated / skipped per run.

    `open` snapshots the live rows (any origin) of the relation types a module writes, so a
    rerun with identical inputs counts as `skipped` (same ids, nothing changed) and a manual
    edge the module lands on counts as `updated` or `skipped`, never `created`.
    """

    def __init__(self, session: AsyncSession, project_id: UUID, module: str) -> None:
        self.session = session
        self.project_id = project_id
        self.report = InferenceReport(module)
        self._prior: dict[UUID, tuple[float, dict[str, Any]]] = {}

    @classmethod
    async def open(
        cls, session: AsyncSession, project_id: UUID, module: str, relation_types: tuple[str, ...]
    ) -> EdgeWriter:
        writer = cls(session, project_id, module)
        rows = await session.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type.in_(relation_types),
                GraphEdge.deleted_at.is_(None),
            )
        )
        writer._prior = {row.id: (row.confidence, dict(row.attrs)) for row in rows}
        return writer

    async def write(
        self,
        src: GraphEntity,
        dst: GraphEntity,
        relation_type: str,
        *,
        confidence: float,
        evidence: list[EdgeEvidence],
        attrs: dict[str, Any] | None = None,
    ) -> GraphEdge:
        edge = await write_edge(
            self.session,
            project_id=self.project_id,
            src_id=src.id,
            dst_id=dst.id,
            relation_type=relation_type,
            origin=EdgeOrigin.INFERRED.value,
            confidence=confidence,
            evidence=evidence,
            created_by=None,
            matrix_cell=matrix_cell(src.domain.value, dst.domain.value),
            attrs=attrs,
        )
        prior = self._prior.get(edge.id)
        if edge.deleted_at is not None:  # a declined tombstone: not re-proposed
            self.report.skipped += 1
        elif prior is None:
            self.report.created += 1
            self._prior[edge.id] = (edge.confidence, dict(edge.attrs))
        elif prior != (edge.confidence, edge.attrs):
            self.report.updated += 1
            self._prior[edge.id] = (edge.confidence, dict(edge.attrs))
        else:
            self.report.skipped += 1
        if edge.deleted_at is None and is_candidate(edge):
            self.report.candidates += 1
        return edge


def behaviour_class_of(entity: GraphEntity) -> str | None:
    """`attrs.behaviour_class`, else the part definition's (`attrs.definition_id`)."""
    declared = entity.attrs.get("behaviour_class")
    if isinstance(declared, str):
        return declared
    definition_id = entity.attrs.get("definition_id")
    if not isinstance(definition_id, str):
        return None
    from solus_api.hardware.library import DefinitionError, load_library

    try:
        definition = load_library().get("part", definition_id)
    except DefinitionError:
        return None
    return getattr(definition, "behaviour_class", None)


def split_source_ref(ref: str) -> tuple[str, int | None]:
    """`"path/file.ino:42"` → `("path/file.ino", 42)`; no numeric tail → `(ref, None)`."""
    head, sep, tail = ref.rpartition(":")
    if sep and tail.isdigit():
        return head, int(tail)
    return ref, None


async def resolve_code_entity(
    session: AsyncSession, project_id: UUID, file: str
) -> GraphEntity | None:
    """The live code entity whose path is `file`, or the one path that ends with it.

    ponytail: suffix matching on `/` boundaries; an ambiguous suffix resolves to nothing.
    """
    rows = list(
        await session.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == project_id,
                GraphEntity.kind.in_(CODE_FILE_KINDS),
                GraphEntity.deleted_at.is_(None),
            )
        )
    )
    wanted = file.strip("/")
    if not wanted:
        return None

    def path_of(row: GraphEntity) -> str:
        path = row.attrs.get("path") or row.external_ref or ""
        return str(path).strip("/")

    exact = [row for row in rows if path_of(row) == wanted]
    if exact:
        return exact[0]
    suffix = [
        row
        for row in rows
        if path_of(row).endswith("/" + wanted) or wanted.endswith("/" + path_of(row))
        if path_of(row)
    ]
    return suffix[0] if len(suffix) == 1 else None


async def accepted_evidence(session: AsyncSession, project_id: UUID) -> list[GraphEdge]:
    """The live reviewed extraction rows (`TopologyAcceptanceService.confirm`), oldest first."""
    return list(
        await session.scalars(
            select(GraphEdge)
            .where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type == EVIDENCE_RELATION,
                GraphEdge.attrs["managed_by"].astext == EVIDENCE_MARKER,
                GraphEdge.deleted_at.is_(None),
            )
            .order_by(GraphEdge.created_at, GraphEdge.id)
        )
    )
