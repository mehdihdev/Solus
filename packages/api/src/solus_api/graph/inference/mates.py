"""`mounts` structure → device from a fastened `mates_with` edge (relations.md §1).

`mates_with` itself is connector-written (the mechanical mapping, from a mirrored assembly
definition); this module only promotes a FASTENED mate between a `structural` part and a
`device` part into a 0.7 candidate.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from solus_contracts.relations import EdgeEvidence, EvidenceKind, RelationType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from solus_api.graph.inference.common import EdgeWriter, InferenceReport, behaviour_class_of
from solus_api.models import GraphEdge, GraphEntity

MODULE: Final = "mates"
MOUNTS_CONFIDENCE: Final = 0.7
FASTENED: Final = frozenset({"FASTENED", "fastened"})


async def infer(session: AsyncSession, project_id: UUID) -> InferenceReport:
    a, b = aliased(GraphEntity), aliased(GraphEntity)
    rows = (
        await session.execute(
            select(GraphEdge, a, b)
            .join(a, a.id == GraphEdge.src_id)
            .join(b, b.id == GraphEdge.dst_id)
            .where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type == RelationType.MATES_WITH.value,
                GraphEdge.deleted_at.is_(None),
                a.deleted_at.is_(None),
                b.deleted_at.is_(None),
            )
            .order_by(GraphEdge.id)
        )
    ).all()
    writer = await EdgeWriter.open(session, project_id, MODULE, (RelationType.MOUNTS.value,))
    for edge, src, dst in rows:
        if edge.attrs.get("mate_type") not in FASTENED:
            continue
        classes = {behaviour_class_of(src): src, behaviour_class_of(dst): dst}
        structure, device = classes.get("structural"), classes.get("device")
        if structure is None or device is None:
            continue
        ref = edge.attrs.get("feature_id") or str(edge.id)
        await writer.write(
            structure,
            device,
            RelationType.MOUNTS.value,
            confidence=MOUNTS_CONFIDENCE,
            evidence=[EdgeEvidence(kind=EvidenceKind.MATE, ref=str(ref))],
            attrs={"mate_type": edge.attrs.get("mate_type")},
        )
    return writer.report
