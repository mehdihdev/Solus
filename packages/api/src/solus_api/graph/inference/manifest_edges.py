"""`depends_on` owner → requirement for every connector-written `requires` edge whose
requirement names its manifest file (relations.md §1). The 0.8 `requires` a hardware config
infers (config_requires) is not a manifest and never becomes a 1.0 `depends_on`."""

from __future__ import annotations

from typing import Final
from uuid import UUID

from solus_contracts.relations import EdgeEvidence, EdgeOrigin, EvidenceKind, RelationType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from solus_api.graph import kinds
from solus_api.graph.inference.common import EdgeWriter, InferenceReport
from solus_api.models import GraphEdge, GraphEntity

MODULE: Final = "manifest_edges"
REQUIREMENT_KINDS: Final = frozenset({kinds.PYTHON_REQUIREMENT, kinds.PACKAGE_REQUIREMENT})


async def infer(session: AsyncSession, project_id: UUID) -> InferenceReport:
    owner, requirement = aliased(GraphEntity), aliased(GraphEntity)
    rows = (
        await session.execute(
            select(owner, requirement)
            .select_from(GraphEdge)
            .join(owner, owner.id == GraphEdge.src_id)
            .join(requirement, requirement.id == GraphEdge.dst_id)
            .where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type == RelationType.REQUIRES.value,
                GraphEdge.origin == EdgeOrigin.CONNECTOR.value,
                GraphEdge.deleted_at.is_(None),
                owner.deleted_at.is_(None),
                requirement.deleted_at.is_(None),
                requirement.kind.in_(REQUIREMENT_KINDS),
                requirement.attrs["source_file"].astext.isnot(None),
            )
            .order_by(GraphEdge.id)
        )
    ).all()
    writer = await EdgeWriter.open(session, project_id, MODULE, (RelationType.DEPENDS_ON.value,))
    for src, dst in rows:
        source_file = dst.attrs["source_file"]
        await writer.write(
            src,
            dst,
            RelationType.DEPENDS_ON.value,
            confidence=1.0,
            evidence=[EdgeEvidence(kind=EvidenceKind.MANIFEST, ref=str(source_file))],
        )
    return writer.report
