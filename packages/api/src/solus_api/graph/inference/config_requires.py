"""`requires` hardware config → package for the driver a CONFIG names (relations.md §1).

The driver roster lives in livebench, imported lazily: an API process without it (or with a
driver it does not know) infers nothing, never fails the config save.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from solus_contracts.relations import EdgeEvidence, EvidenceKind, RelationType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.graph import kinds
from solus_api.graph.inference.common import EdgeWriter, InferenceReport
from solus_api.models import Domain, GraphEntity

MODULE: Final = "config_requires"
EVIDENCE_REF: Final = "protocol.driver_id"


def requires_packages_for(driver_id: str) -> tuple[str, ...]:
    """The packages the driver plugin declares; ImportError when livebench is absent,
    `()` for a driver the roster does not know."""
    from livebench.hardware.registries import default_registries

    try:
        return default_registries().drivers.requires_packages(driver_id)
    except KeyError:
        return ()


async def _package_node(
    session: AsyncSession, project_id: UUID, name: str, driver_id: str
) -> GraphEntity:
    key = f"pkg:python:{name}"
    row = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.canonical_key == key,
            GraphEntity.deleted_at.is_(None),
        )
    )
    if row is None:
        row = GraphEntity(
            project_id=project_id,
            kind=kinds.PACKAGE_REQUIREMENT,
            domain=Domain.CODE,
            origin="system",
            name=name,
            canonical_key=key,
            attrs={"name": name, "ecosystem": "python", "source": f"driver:{driver_id}"},
        )
        session.add(row)
        await session.flush()
    return row


async def infer(
    session: AsyncSession, project_id: UUID, *, config_node_id: UUID, driver_id: str | None
) -> InferenceReport:
    report = InferenceReport(MODULE)
    if driver_id is None:
        return report
    try:
        packages = requires_packages_for(driver_id)
    except ImportError:
        return report
    node = await session.get(GraphEntity, config_node_id)
    if not packages or node is None or node.project_id != project_id:
        return report
    writer = await EdgeWriter.open(session, project_id, MODULE, (RelationType.REQUIRES.value,))
    for name in packages:
        package = await _package_node(session, project_id, name, driver_id)
        await writer.write(
            node,
            package,
            RelationType.REQUIRES.value,
            confidence=0.8,
            evidence=[EdgeEvidence(kind=EvidenceKind.CONFIG, ref=EVIDENCE_REF)],
        )
    return writer.report
