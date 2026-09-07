"""Sourcing reads and writes against the graph (SOLUSDEV-246 ST5).

Every query is project-scoped. The assembly read walks the graph's containment
(`part_of` child → parent, `contains` parent → child) one level down and reads
each part's placement from the edge and its mass from the part's attributes —
never inventing either. Rules layer defaults ← the repo `[ext.sourcing]`
table (a CONNECTOR-landed `solus_project_toml` row only) ← the project's rules
document (a `sourcing_rules` node this module owns). Selecting a candidate
creates ONE manual `part` node, lifecycle `planned`, under the chosen robot
category, so the Workspace navigator and the BOM see it through the graph.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.models import Domain, GraphEdge, GraphEntity, SourcingRequest, utcnow
from solus_api.sourcing.candidates import Candidate
from solus_api.sourcing.rules import SourcingRules, merge_rules, rules_from_repo_table
from solus_api.sourcing.torque import AssemblyPart
from solus_api.widgets.solus_config import SOLUS_CONFIG_KIND

RULES_KIND = "sourcing_rules"
PART_KIND = "part"
ORIGIN = "manual"
#: Robot categories whose parts are electrical by nature; the rest are mechanical.
ELECTRICAL_CATEGORIES = frozenset({"sensors", "controllers", "power", "wiring"})
MAX_ASSEMBLY_PARTS = 500
MASS_KEYS = ("mass_kg", "mass")


@dataclass(frozen=True)
class AssemblyRead:
    assembly: GraphEntity
    parts: list[AssemblyPart]


def _mass_of(attrs: dict[str, Any], override: float | None) -> float | None:
    if override is not None:
        return override
    for key in MASS_KEYS:
        value = attrs.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value < 1e6:
            return float(value)
    return None


def _placement_of(edge_attrs: dict[str, Any]) -> tuple[float, float, float] | None:
    placement = edge_attrs.get("placement")
    if not isinstance(placement, list) or len(placement) != 3:
        return None
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in placement):
        return None
    return (float(placement[0]), float(placement[1]), float(placement[2]))


async def read_assembly(
    session: AsyncSession,
    project_id: uuid.UUID,
    assembly_id: uuid.UUID,
    *,
    masses: dict[uuid.UUID, float] | None = None,
) -> AssemblyRead:
    """The assembly and its DIRECT child parts with placement + mass, or 404. A child that is
    itself an assembly counts like any part: it contributes when the graph carries its rolled-up
    mass and placement and is NAMED as unknown otherwise — never silently dropped."""
    assembly = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.id == assembly_id,
            GraphEntity.project_id == project_id,
            GraphEntity.deleted_at.is_(None),
        )
    )
    if assembly is None:
        raise APIError(404, "not_found", "Assembly not found")
    rows = (
        await session.execute(
            select(GraphEntity, GraphEdge)
            .join(
                GraphEdge,
                or_(
                    (GraphEdge.src_id == GraphEntity.id)
                    & (GraphEdge.dst_id == assembly_id)
                    & (GraphEdge.relation_type == "part_of"),
                    (GraphEdge.dst_id == GraphEntity.id)
                    & (GraphEdge.src_id == assembly_id)
                    & (GraphEdge.relation_type == "contains"),
                ),
            )
            .where(
                GraphEntity.project_id == project_id,
                GraphEdge.project_id == project_id,
                GraphEntity.deleted_at.is_(None),
                GraphEdge.deleted_at.is_(None),
                GraphEntity.kind == PART_KIND,
            )
            .order_by(GraphEntity.name, GraphEntity.id)
            .limit(MAX_ASSEMBLY_PARTS)
        )
    ).all()
    overrides = masses or {}
    parts = [
        AssemblyPart(
            id=entity.id,
            name=entity.name,
            mass_kg=_mass_of(entity.attrs or {}, overrides.get(entity.id)),
            position_mm=_placement_of(edge.attrs or {}),
        )
        for entity, edge in rows
    ]
    return AssemblyRead(assembly=assembly, parts=parts)


MAX_ASSEMBLY_NAMES = 20


async def list_assemblies(session: AsyncSession, project_id: uuid.UUID) -> list[GraphEntity]:
    """The project's CAD assemblies (parts flagged `is_assembly`), by name, bounded."""
    rows = await session.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == PART_KIND,
            GraphEntity.deleted_at.is_(None),
            GraphEntity.attrs["is_assembly"].as_boolean().is_(True),
        )
        .order_by(GraphEntity.name, GraphEntity.id)
        .limit(MAX_ASSEMBLY_NAMES)
    )
    return list(rows)


async def find_assembly(session: AsyncSession, project_id: uuid.UUID, name: str) -> GraphEntity:
    """Resolve an assembly by name (case-insensitive, whitespace-folded) inside ONE project.
    Unknown → 404 naming the assemblies that exist; ambiguous → 422 naming the ids."""
    wanted = " ".join(name.lower().split())
    candidates = await list_assemblies(session, project_id)
    matches = [a for a in candidates if " ".join(a.name.lower().split()) == wanted]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        known = ", ".join(a.name for a in candidates) or "none"
        raise APIError(
            404, "not_found", f"No assembly named {name!r} in this project; assemblies: {known}"
        )
    ids = ", ".join(str(a.id) for a in matches)
    raise APIError(
        422,
        "validation_error",
        f"{len(matches)} assemblies are named {name!r}; pass assembly_entity_id ({ids})",
    )


# ------------------------------------------------------------------- rules


async def _repo_rules(session: AsyncSession, project_id: uuid.UUID) -> SourcingRules:
    row = await session.scalar(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == SOLUS_CONFIG_KIND,
            GraphEntity.origin == "connector",
            GraphEntity.deleted_at.is_(None),
        )
        .order_by(GraphEntity.updated_at.desc())
        .limit(1)
    )
    ext = (row.attrs or {}).get("ext") if row is not None else None
    table = ext.get("sourcing") if isinstance(ext, dict) else None
    return rules_from_repo_table(table) if isinstance(table, dict) else SourcingRules()


async def _rules_row(session: AsyncSession, project_id: uuid.UUID) -> GraphEntity | None:
    row: GraphEntity | None = await session.scalar(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == RULES_KIND,
            GraphEntity.origin == ORIGIN,
            GraphEntity.deleted_at.is_(None),
        )
        .order_by(GraphEntity.created_at)
        .limit(1)
    )
    return row


async def load_rules(session: AsyncSession, project_id: uuid.UUID) -> SourcingRules:
    """Effective rules: defaults ← repo `[ext.sourcing]` ← the project's document."""
    row = await _rules_row(session, project_id)
    project = SourcingRules()
    if row is not None:
        try:
            project = SourcingRules.model_validate(row.attrs or {})
        except ValueError:
            project = SourcingRules()
    return merge_rules(await _repo_rules(session, project_id), project)


async def save_rules(
    session: AsyncSession, project_id: uuid.UUID, rules: SourcingRules
) -> GraphEntity:
    """Upsert the project's rules document. Does NOT commit."""
    row = await _rules_row(session, project_id)
    if row is None:
        row = GraphEntity(
            project_id=project_id,
            kind=RULES_KIND,
            domain=Domain.PROJECT,
            name="Sourcing rules",
            origin=ORIGIN,
            attrs=rules.model_dump(mode="json"),
        )
        session.add(row)
    else:
        row.attrs = rules.model_dump(mode="json")
        row.version = (row.version or 1) + 1
    await session.flush()
    return row


# ---------------------------------------------------------------- requests


async def get_request(
    session: AsyncSession, project_id: uuid.UUID, request_id: uuid.UUID
) -> SourcingRequest:
    row = await session.scalar(
        select(SourcingRequest).where(
            SourcingRequest.id == request_id, SourcingRequest.project_id == project_id
        )
    )
    if row is None:
        raise APIError(404, "not_found", "Sourcing request not found")
    return row


async def list_requests(
    session: AsyncSession, project_id: uuid.UUID, *, limit: int = 50
) -> list[SourcingRequest]:
    rows = await session.scalars(
        select(SourcingRequest)
        .where(SourcingRequest.project_id == project_id)
        .order_by(SourcingRequest.created_at.desc(), SourcingRequest.id.desc())
        .limit(limit)
    )
    return list(rows)


def candidate_of(request: SourcingRequest, candidate_id: str) -> Candidate | None:
    for raw in request.candidates:
        if isinstance(raw, dict) and raw.get("id") == candidate_id:
            try:
                return Candidate.model_validate(raw)
            except ValueError:
                return None
    return None


async def _category(
    session: AsyncSession, project_id: uuid.UUID, category_id: uuid.UUID
) -> GraphEntity:
    row = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.id == category_id,
            GraphEntity.project_id == project_id,
            GraphEntity.kind == "robot_category",
            GraphEntity.origin == ORIGIN,
            GraphEntity.deleted_at.is_(None),
        )
    )
    if row is None:
        raise APIError(404, "not_found", "Robot category not found")
    return row


def _planned_attrs(
    request: SourcingRequest, candidate: Candidate, *, quantity: int, user_id: uuid.UUID | None
) -> dict[str, Any]:
    return {
        "lifecycle": "planned",
        "quantity": quantity,
        "part_number": candidate.part_number,
        "manufacturer": candidate.manufacturer,
        "supplier": candidate.supplier,
        "unit_cost": candidate.cost,
        "currency": candidate.currency,
        "torque_nm": candidate.torque_nm,
        "weight_kg": candidate.weight_kg,
        "protocol": candidate.protocol,
        "voltage_v": candidate.voltage_v,
        "vendor_cad_url": candidate.vendor_cad_url,
        "sourcing": {
            "request_id": str(request.id),
            "candidate_id": candidate.id,
            "grounding": candidate.grounding,
            "source_url": candidate.source_url,
            "optimizes_for": candidate.optimizes_for,
            "gives_up": candidate.gives_up,
            "required_torque_nm": (request.torque or {}).get("required_torque_nm"),
        },
        "created_by": str(user_id) if user_id else None,
    }


async def select_candidate(
    session: AsyncSession,
    *,
    request: SourcingRequest,
    candidate: Candidate,
    user_id: uuid.UUID | None,
    category_id: uuid.UUID | None,
    quantity: int,
) -> GraphEntity:
    """The selected candidate enters the graph as ONE planned manual part
    (R5 `planned`), contained by the chosen robot category when given. Does
    NOT commit. Selecting twice re-points the request at the new node; the
    earlier node stays (it is the user's data)."""
    category = await _category(session, request.project_id, category_id) if category_id else None
    domain = (
        Domain.ELECTRICAL
        if category is not None and category.attrs.get("category") in ELECTRICAL_CATEGORIES
        else Domain.MECHANICAL
    )
    part = GraphEntity(
        project_id=request.project_id,
        kind=PART_KIND,
        domain=domain,
        name=candidate.name[:512],
        origin=ORIGIN,
        attrs=_planned_attrs(request, candidate, quantity=quantity, user_id=user_id),
        modality_hints={"part_number": candidate.part_number} if candidate.part_number else {},
    )
    session.add(part)
    await session.flush()
    if category is not None:
        session.add(
            GraphEdge(
                project_id=request.project_id,
                src_id=category.id,
                dst_id=part.id,
                relation_type="contains",
                domain_pair=f"project<->{domain.value}",
                origin=ORIGIN,
            )
        )
    request.selected_candidate_id = candidate.id
    request.selected_entity_id = part.id
    request.updated_at = utcnow()
    await session.flush()
    return part
