"""The environment spec (SOLUSDEV-320 P5-T3, docs/api/solus.md §2.1 `environment/spec`).

What the project's graph says a machine needs: every live `depends_on` / `requires` edge
onto a requirement entity, grouped per (ecosystem, package). Values are transcribed from
the requirement's attrs — a missing specifier stays `null`, never guessed — and `tools`
stays empty until the graph records required tools (nothing does today). Candidates
(`origin=inferred`, confidence < 0.8) are not facts and are skipped. Stored as ONE CONFIG
entry bound to the project's `.solus` root and recomputed in place.
"""

from __future__ import annotations

import logging
import uuid
from typing import Final, Literal

from solus_contracts.relations import RelationType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from solus_api.graph import kinds
from solus_api.graph.edges import is_candidate
from solus_api.graph.inference.manifest_edges import REQUIREMENT_KINDS
from solus_api.models import GraphEdge, GraphEntity, SolusEntry, SolusSection, utcnow
from solus_api.services.solus_config import put_config_entry
from solus_api.services.solus_graph import SolusGraph
from solus_api.services.solus_payloads import MAX_LINKED_IDS, EnvironmentSpec, SpecPackage

logger = logging.getLogger("solus.services.environment_spec")

SPEC_SUBSECTION: Final = "spec"
_RELATIONS: Final = (RelationType.DEPENDS_ON.value, RelationType.REQUIRES.value)


def _normalize_name(name: str) -> str:
    """PEP 503-style: case-insensitive, `_` and `-` equal."""
    return name.strip().lower().replace("_", "-")[:128]


def _ecosystem(requirement: GraphEntity) -> str | None:
    value = requirement.attrs.get("ecosystem")
    if isinstance(value, str) and value:
        return value[:32]
    return "python" if requirement.kind == kinds.PYTHON_REQUIREMENT else None


async def build_environment_spec(session: AsyncSession, project_id: uuid.UUID) -> EnvironmentSpec:
    requirement = aliased(GraphEntity)
    rows = (
        await session.execute(
            select(GraphEdge, requirement)
            .join(requirement, requirement.id == GraphEdge.dst_id)
            .where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type.in_(_RELATIONS),
                GraphEdge.deleted_at.is_(None),
                requirement.project_id == project_id,
                requirement.deleted_at.is_(None),
                requirement.kind.in_(sorted(REQUIREMENT_KINDS)),
            )
            .order_by(requirement.name, GraphEdge.id)
        )
    ).all()
    groups: dict[tuple[str, str], SpecPackage] = {}
    for edge, req in rows:
        if is_candidate(edge):
            continue
        ecosystem = _ecosystem(req)
        raw_name = req.attrs.get("name") or req.name
        if ecosystem is None or not isinstance(raw_name, str) or not raw_name.strip():
            continue
        raw_spec = req.attrs.get("specifier")
        specifier = (
            raw_spec.strip()[:128] if isinstance(raw_spec, str) and raw_spec.strip() else None
        )
        source: Literal["manifest", "config"] = (
            "manifest" if req.attrs.get("source_file") else "config"
        )
        key = (ecosystem, _normalize_name(raw_name))
        package = groups.get(key)
        if package is None:
            groups[key] = SpecPackage(
                name=key[1],
                ecosystem=ecosystem,
                specifier=specifier,
                required_by=[edge.src_id],
                source=source,
            )
            continue
        if edge.src_id not in package.required_by and len(package.required_by) < MAX_LINKED_IDS:
            package.required_by.append(edge.src_id)
        if package.specifier is None:
            package.specifier = specifier
        if source == "manifest":
            package.source = "manifest"
    packages = [groups[key] for key in sorted(groups)]
    for package in packages:
        package.required_by.sort()
    return EnvironmentSpec(computed_at=utcnow(), packages=packages, tools=[])


async def recompute_environment_spec(session: AsyncSession, project_id: uuid.UUID) -> SolusEntry:
    """Build and store the spec as the ONE `environment/spec` CONFIG of the `.solus` root
    (same entry id each time; a version only when the packages changed)."""
    spec = await build_environment_spec(session, project_id)
    root = (await SolusGraph.ensure(session, project_id)).root
    entry = await put_config_entry(
        session,
        project_id,
        SolusSection.ENVIRONMENT,
        SPEC_SUBSECTION,
        spec,
        text="Environment spec",
        configured_entity_id=root.id,
        created_by=None,
        author="system",
        ignore=("computed_at",),
    )
    logger.info(
        "environment spec project=%s packages=%d version=%d",
        project_id,
        len(spec.packages),
        entry.config_version,
    )
    return entry
