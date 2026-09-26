"""Explicit CAD proposals from existing graph identity links; no name inference."""

from __future__ import annotations

import json
import math
import uuid
from typing import Any

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from solus_api.core.errors import APIError
from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef
from solus_api.graph.read_scope import resolve_scope
from solus_api.hardware.links import LinkSuggestion, LinkTier, list_suggestions, persist_suggestions
from solus_api.hardware.store import PART_KINDS, attach_existing_parts, robot_root
from solus_api.linking.linker import LINK_ORIGIN, RELATION_SAME_AS
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    HardwareSuggestion,
    Source,
    SuggestionStatus,
    utcnow,
)
from solus_api.services.physical_robots import ROBOT_CATEGORIES
from solus_api.services.solus_graph import lock_project


async def _owners(
    session: AsyncSession, project_id: uuid.UUID, part_id: uuid.UUID
) -> set[tuple[uuid.UUID, str]]:
    category, robot, parent = aliased(GraphEntity), aliased(GraphEntity), aliased(GraphEdge)
    rows = await session.execute(
        select(robot.id, category.attrs["category"].astext)
        .select_from(GraphEdge)
        .join(category, category.id == GraphEdge.src_id)
        .join(parent, parent.dst_id == category.id)
        .join(robot, robot.id == parent.src_id)
        .where(
            GraphEdge.project_id == project_id,
            GraphEdge.dst_id == part_id,
            GraphEdge.relation_type == "contains",
            GraphEdge.origin == "manual",
            GraphEdge.source_id.is_(None),
            GraphEdge.deleted_at.is_(None),
            category.project_id == project_id,
            category.kind == "robot_category",
            category.origin == "manual",
            category.source_id.is_(None),
            category.deleted_at.is_(None),
            category.attrs["robot_id"].astext == cast(robot.id, String),
            category.attrs["category"].astext.in_(ROBOT_CATEGORIES),
            parent.project_id == project_id,
            parent.relation_type == "contains",
            parent.origin == "manual",
            parent.source_id.is_(None),
            parent.deleted_at.is_(None),
            robot.project_id == project_id,
            robot.kind == "physical_robot",
            robot.origin == "manual",
            robot.source_id.is_(None),
            robot.deleted_at.is_(None),
        )
    )
    return {(row[0], row[1]) for row in rows}


async def _association(
    session: AsyncSession,
    project_id: uuid.UUID,
    part_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    allow_attached: bool = False,
) -> tuple[LinkSuggestion, str] | None:
    scope = await resolve_scope(session, project_id, user_id)
    part = await session.scalar(
        select(GraphEntity)
        .join(Source, Source.id == GraphEntity.source_id)
        .where(
            GraphEntity.id == part_id,
            scope.entity_predicate(),
            GraphEntity.project_id == project_id,
            GraphEntity.kind.in_(PART_KINDS),
            GraphEntity.domain == Domain.MECHANICAL,
            GraphEntity.origin == "connector",
            GraphEntity.deleted_at.is_(None),
            Source.project_id == project_id,
            Source.status == "connected",
        )
    )
    if part is None:
        raise APIError(404, "not_found", "Connected CAD part not found")
    existing = await _owners(session, project_id, part_id)
    if existing and not allow_attached:
        return None
    edges = list(
        await session.scalars(
            select(GraphEdge)
            .where(
                GraphEdge.project_id == project_id,
                scope.edge_predicate(),
                GraphEdge.relation_type == RELATION_SAME_AS,
                GraphEdge.origin == LINK_ORIGIN,
                GraphEdge.source_id.is_(None),
                GraphEdge.deleted_at.is_(None),
                or_(GraphEdge.src_id == part_id, GraphEdge.dst_id == part_id),
                GraphEdge.confidence >= 0.8,
            )
            .order_by(GraphEdge.id)
            .limit(65)
        )
    )
    if len(edges) > 64:
        return None
    owners: set[tuple[uuid.UUID, str]] = set()
    evidence: list[ModalityMatch] = []
    for edge in edges:
        if (
            edge.attrs.get("matched") is not True
            or not math.isfinite(float(edge.confidence))
            or edge.confidence > 1
        ):
            continue
        try:
            canonical = str(uuid.UUID(str(edge.attrs.get("canonical_id"))))
        except ValueError:
            continue
        counterpart_id = edge.dst_id if edge.src_id == part_id else edge.src_id
        counterpart = await session.scalar(
            select(GraphEntity).where(
                GraphEntity.id == counterpart_id,
                scope.entity_predicate(),
                GraphEntity.project_id == project_id,
                GraphEntity.kind.in_(PART_KINDS),
                GraphEntity.deleted_at.is_(None),
            )
        )
        if counterpart is None:
            continue
        targets = await _owners(session, project_id, counterpart.id)
        if not targets:
            continue
        owners.update(targets)
        evidence.append(
            ModalityMatch(
                modality=Modality.CAD_MODEL,
                source_ref=SourceRef(
                    graph_entity_id=part_id, source_connector=part.source_connector
                ),
                confidence=float(edge.confidence),
                state=MatchState.MATCHED,
                evidence={
                    "matched_on": "existing_same_as",
                    "edge_id": str(edge.id),
                    "canonical_id": canonical,
                    "counterpart_id": str(counterpart.id),
                    "source_id": str(part.source_id),
                    "part_version": part.version,
                    "counterpart_version": counterpart.version,
                    "targets": sorted(f"{robot}:{category}" for robot, category in targets),
                },
            )
        )
    if len(owners) != 1 or (existing and existing != owners) or not evidence:
        return None
    robot_id, category = next(iter(owners))
    return LinkSuggestion(
        subject_ref=str(part_id),
        subject_kind="part",
        candidate_robot_id=robot_id,
        confidence=min(item.confidence for item in evidence),
        tier=LinkTier.HIGH,
        evidence=evidence,
        reason="An existing matched CAD identity link points to a part owned by this robot",
    ), category


async def propose_cad_suggestions(
    session: AsyncSession, project_id: uuid.UUID, part_id: uuid.UUID, user_id: uuid.UUID
) -> list[HardwareSuggestion]:
    await lock_project(session, project_id)
    association = await _association(session, project_id, part_id, user_id)
    if association is None:
        return []
    proposal, _ = association
    current_evidence = [match.model_dump(mode="json") for match in proposal.evidence]
    for row in await list_suggestions(session, project_id):
        if (
            row.subject_kind == "part"
            and row.subject_ref == str(part_id)
            and is_cad_suggestion(row)
            and (
                row.candidate_robot_id != proposal.candidate_robot_id
                or row.evidence != current_evidence
            )
        ):
            row.status = SuggestionStatus.SUPERSEDED
            row.decided_at = utcnow()
    await session.flush()
    await persist_suggestions(session, project_id, [proposal])
    rows = await list_suggestions(session, project_id)
    return [
        row
        for row in rows
        if row.subject_kind == "part"
        and row.subject_ref == str(part_id)
        and row.candidate_robot_id == proposal.candidate_robot_id
        and row.evidence == [match.model_dump(mode="json") for match in proposal.evidence]
    ]


async def accept_cad_suggestion(
    session: AsyncSession, project_id: uuid.UUID, suggestion: HardwareSuggestion, user_id: uuid.UUID
) -> dict[str, Any]:
    await lock_project(session, project_id)
    if suggestion.project_id != project_id or suggestion.subject_kind != "part":
        raise APIError(404, "not_found", "CAD suggestion not found")
    try:
        part_id = uuid.UUID(suggestion.subject_ref)
    except ValueError:
        raise APIError(409, "conflict", "CAD suggestion does not identify a graph part") from None
    association = await _association(session, project_id, part_id, user_id, allow_attached=True)
    if association is None:
        raise APIError(409, "conflict", "CAD identity evidence changed; request a new review")
    proposal, category = association
    evidence = [match.model_dump(mode="json") for match in proposal.evidence]
    if (
        suggestion.status is not SuggestionStatus.ACCEPTED
        or proposal.candidate_robot_id != suggestion.candidate_robot_id
        or json.dumps(evidence, sort_keys=True) != json.dumps(suggestion.evidence, sort_keys=True)
    ):
        raise APIError(409, "conflict", "CAD identity evidence changed; request a new review")
    robot = await robot_root(session, project_id, proposal.candidate_robot_id)
    attached, _, _ = await attach_existing_parts(
        session, project_id, robot, entity_ids=[part_id], category=category, created_by=user_id
    )
    return {
        "attached_count": len(attached),
        "bound": True,
        "robot_id": robot.id,
        "session_id": None,
        "session_error": None,
        "bind_error": None,
    }


def is_cad_suggestion(row: HardwareSuggestion) -> bool:
    """Distinguish this evidence-backed attachment from legacy part decisions."""
    return (
        row.subject_kind == "part"
        and bool(row.evidence)
        and all(
            isinstance(item, dict)
            and item.get("modality") == "cad_model"
            and isinstance(item.get("evidence"), dict)
            and item["evidence"].get("matched_on") == "existing_same_as"
            for item in row.evidence
        )
    )


async def filter_visible_cad_suggestions(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    rows: list[HardwareSuggestion],
) -> list[HardwareSuggestion]:
    """Filter personal revision references without rewriting the shared decision journal."""
    required: dict[uuid.UUID, set[uuid.UUID]] = {}
    for row in rows:
        if row.project_id != project_id or not is_cad_suggestion(row):
            continue
        try:
            subject = uuid.UUID(row.subject_ref)
            references = {subject, row.candidate_robot_id}
            for item in row.evidence:
                if uuid.UUID(str(item["source_ref"]["graph_entity_id"])) != subject:
                    raise ValueError("Mismatched CAD subject")
                references.add(uuid.UUID(str(item["evidence"]["counterpart_id"])))
            required[row.id] = references
        except (KeyError, TypeError, ValueError):
            continue
    wanted = set().union(*required.values()) if required else set()
    visible: set[uuid.UUID] = set()
    if wanted:
        scope = await resolve_scope(session, project_id, user_id)
        visible = set(
            await session.scalars(
                select(GraphEntity.id).where(
                    GraphEntity.id.in_(wanted),
                    scope.entity_predicate(),
                    GraphEntity.deleted_at.is_(None),
                )
            )
        )
    return [
        row
        for row in rows
        if row.project_id == project_id
        and (not is_cad_suggestion(row) or (row.id in required and required[row.id] <= visible))
    ]
