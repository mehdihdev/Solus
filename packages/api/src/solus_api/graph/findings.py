"""Findings as graph nodes (SOLUSDEV-320, docs/api/findings.md §1-§2).

A finding is the durable form of a checker `Warning`, an observer event, a run comparison,
a SOL diagnosis or a simulation result: one `graph_entity` of kind `finding`, upserted on
`canonical_key`, with `observed` edges to its subjects. Flushes, never commits.

Every string here is UNTRUSTED (CLAUDE.md §7): the headline and evidence carry entity names
and connector text. Readers render them as text, never as markup.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from solus_contracts.relations import (
    EdgeEvidence,
    EdgeOrigin,
    EvidenceKind,
    MatrixCell,
    RelationType,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.checkers.interface import Severity, Warning
from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, encode_cursor, page_meta
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.models import Domain, GraphEdge, GraphEntity, SolusEntry, SolusSection, utcnow
from solus_api.services.activity import record_project_activity
from solus_api.services.solus_config import MAX_TEXT_CHARS, add_text_entry
from solus_api.services.solus_graph import lock_project
from solus_api.services.solus_payloads import ErrorMeta

logger = logging.getLogger("solus.graph.findings")

FindingSource = Literal["observer", "checker", "run_compare", "sol", "simulation"]
FindingStatus = Literal["open", "acknowledged", "dismissed", "resolved"]
SeverityName = Literal["info", "warning", "critical"]

ORIGIN = EdgeOrigin.SYSTEM.value
MAX_EVIDENCE_ITEMS = 20
MAX_EVIDENCE_BYTES = 16 * 1024  # one raise's serialized evidence; producers trim, not readers
MAX_LIMIT = 500
ROBOT_DEPTH = 3
#: Attrs that describe a status a reopened finding no longer has.
_STALE_ON_OPEN = ("dismissed_until", "resolved_by", "note", "acknowledged_by")


class FindingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=128)
    severity: Severity
    source: FindingSource
    headline: str = Field(min_length=1, max_length=4000)
    subjects: list[uuid.UUID] = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)
    matrix_cell: MatrixCell | None = None
    domain: Domain
    bucket: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _bounded_evidence(self) -> FindingSpec:
        if len(json.dumps(self.evidence, default=str)) > MAX_EVIDENCE_BYTES:
            raise ValueError(f"evidence exceeds {MAX_EVIDENCE_BYTES} bytes serialized")
        return self


def canonical_finding_key(project_id: uuid.UUID, spec: FindingSpec) -> str:
    subjects = ",".join(sorted(map(str, spec.subjects)))
    raw = f"{project_id}|{spec.rule_id}|{subjects}|{spec.bucket or ''}"
    return hashlib.sha1(raw.encode()).hexdigest()  # noqa: S324 — an identity, not a secret


def finding_from_warning(warning: Warning, *, source: FindingSource = "checker") -> FindingSpec:
    # A checker spanning no domain still blames entities; PROJECT is the cross-domain home.
    domain = Domain(warning.domains[0]) if warning.domains else Domain.PROJECT
    return FindingSpec(
        rule_id=warning.checker_id,
        severity=warning.severity,
        source=source,
        headline=warning.message,
        subjects=list(warning.entity_ids),
        evidence=dict(warning.evidence),
        domain=domain,
    )


# ------------------------------------------------------------------- reads


async def _live_subjects(
    session: AsyncSession, project_id: uuid.UUID, ids: list[uuid.UUID]
) -> dict[uuid.UUID, GraphEntity]:
    """Every id must be a live entity of THIS project, else 404 (no existence oracle)."""
    wanted = set(ids)
    rows = list(
        await session.scalars(
            select(GraphEntity).where(
                GraphEntity.id.in_(wanted),
                GraphEntity.project_id == project_id,
                GraphEntity.deleted_at.is_(None),
            )
        )
    )
    if len(rows) != len(wanted):
        raise APIError(404, "not_found", "Subject entity not found in this project")
    return {row.id: row for row in rows}


async def load_finding(
    session: AsyncSession, project_id: uuid.UUID, finding_id: uuid.UUID
) -> GraphEntity:
    row = await session.get(GraphEntity, finding_id)
    if (
        row is None
        or row.project_id != project_id
        or row.deleted_at is not None
        or row.kind != kinds.FINDING
    ):
        raise APIError(404, "not_found", "Finding not found")
    return row


async def subject_rows(session: AsyncSession, finding: GraphEntity) -> list[GraphEntity]:
    """The finding's live subjects in blame order."""
    ids = [uuid.UUID(s) for s in finding.attrs.get("subjects", [])]
    rows = {
        row.id: row
        for row in await session.scalars(
            select(GraphEntity).where(
                GraphEntity.id.in_(ids),
                GraphEntity.project_id == finding.project_id,
                GraphEntity.deleted_at.is_(None),
            )
        )
    }
    return [rows[i] for i in ids if i in rows]


async def _contained_ids(
    session: AsyncSession, project_id: uuid.UUID, root: uuid.UUID, depth: int
) -> set[uuid.UUID]:
    """`root` and everything under it through live `contains` edges, `depth` hops at most."""
    seen, frontier = {root}, {root}
    for _ in range(depth):
        if not frontier:
            break
        children = set(
            await session.scalars(
                select(GraphEdge.dst_id).where(
                    GraphEdge.project_id == project_id,
                    GraphEdge.relation_type == RelationType.CONTAINS.value,
                    GraphEdge.src_id.in_(frontier),
                    GraphEdge.deleted_at.is_(None),
                )
            )
        )
        frontier = children - seen
        seen |= frontier
    return seen


async def list_findings(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    status: FindingStatus = "open",
    severity: SeverityName | None = None,
    subject: uuid.UUID | None = None,
    robot: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: int = 100,
) -> tuple[list[GraphEntity], dict[str, Any]]:
    """Newest first. `last_seen` moves with `updated_at` on every raise, so the row's own
    timestamp orders and pages this (a status change also bumps it — acceptable for a hint)."""
    stmt = select(GraphEntity).where(
        GraphEntity.project_id == project_id,
        GraphEntity.kind == kinds.FINDING,
        GraphEntity.deleted_at.is_(None),
        GraphEntity.attrs["status"].astext == status,
    )
    if severity is not None:
        stmt = stmt.where(GraphEntity.attrs["severity"].astext == severity)
    targets: set[uuid.UUID] | None = None
    if robot is not None:
        targets = await _contained_ids(session, project_id, robot, ROBOT_DEPTH)
    if subject is not None:
        targets = {subject} if targets is None else targets & {subject}
    if targets is not None:
        observed = select(GraphEdge.src_id).where(
            GraphEdge.project_id == project_id,
            GraphEdge.relation_type == RelationType.OBSERVED.value,
            GraphEdge.dst_id.in_(targets),
            GraphEdge.deleted_at.is_(None),
        )
        stmt = stmt.where(GraphEntity.id.in_(observed))
    if cursor:
        stmt = stmt.where(cursor_filter(GraphEntity.updated_at, GraphEntity.id, cursor))
    stmt = stmt.order_by(GraphEntity.updated_at.desc(), GraphEntity.id.desc()).limit(limit + 1)
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    if meta["next_cursor"] is not None:
        meta["next_cursor"] = encode_cursor(visible[-1].updated_at, visible[-1].id)
    return visible, meta


def serialize_finding(
    entity: GraphEntity, subjects: list[GraphEntity] | None = None
) -> dict[str, Any]:
    a = entity.attrs
    out: dict[str, Any] = {
        "id": entity.id,
        "rule_id": a.get("rule_id"),
        "severity": a.get("severity"),
        "source": a.get("source"),
        "status": a.get("status"),
        "headline": a.get("headline", entity.name),
        "explanation": a.get("explanation", ""),
        "detail": a.get("detail", ""),
        "subjects": [uuid.UUID(s) for s in a.get("subjects", [])],
        "evidence": a.get("evidence", {}),
        "count": a.get("count", 1),
        "first_seen": a.get("first_seen"),
        "last_seen": a.get("last_seen"),
        "matrix_cell": a.get("matrix_cell"),
        "domain": entity.domain.value,
        "dismissed_until": a.get("dismissed_until"),
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }
    if subjects is not None:
        out["subject_entities"] = [{"id": s.id, "kind": s.kind, "name": s.name} for s in subjects]
    return out


# ------------------------------------------------------------------ writes


def _merge_finding_evidence(existing: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Latest `MAX_EVIDENCE_ITEMS` under `items`; scalar keys take the newest value."""
    # The first raise stores the producer's dict verbatim; it becomes item 0 on the second.
    scalars = {k: v for k, v in existing.items() if k != "items"}
    items = list(existing.get("items") or ([scalars] if scalars else []))
    if isinstance(new.get("items"), list):
        merged = {**existing, **new}
        items.extend(new["items"])
    else:
        merged = {**existing, **{k: v for k, v in new.items() if not isinstance(v, list)}}
        items.append(new)
    merged["items"] = items[-MAX_EVIDENCE_ITEMS:]
    return merged


def _status_after_raise(attrs: dict[str, Any], now: datetime) -> FindingStatus:
    status = attrs.get("status")
    if status == "dismissed":
        until = attrs.get("dismissed_until")
        if until and datetime.fromisoformat(until) > now:
            return "dismissed"
        return "open"
    if status == "acknowledged":
        return "acknowledged"  # a person has seen it; one more occurrence changes nothing
    return "open"


async def raise_finding(
    session: AsyncSession, project_id: uuid.UUID, spec: FindingSpec
) -> GraphEntity:
    await lock_project(session, project_id)
    await _live_subjects(session, project_id, spec.subjects)
    key = canonical_finding_key(project_id, spec)
    now = utcnow()
    stamp = now.isoformat()
    subjects = [str(s) for s in spec.subjects]
    cell = spec.matrix_cell.value if spec.matrix_cell else None
    row = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kinds.FINDING,
            GraphEntity.canonical_key == key,
            GraphEntity.deleted_at.is_(None),
        )
    )
    if row is None:
        row = GraphEntity(
            project_id=project_id,
            kind=kinds.FINDING,
            domain=spec.domain,
            name=spec.headline[:512],
            origin=ORIGIN,
            canonical_key=key,
            attrs={
                "rule_id": spec.rule_id,
                "severity": spec.severity.value,
                "source": spec.source,
                "status": "open",
                "headline": spec.headline,
                "explanation": "",
                "detail": "",
                "evidence": dict(spec.evidence),
                "count": 1,
                "first_seen": stamp,
                "last_seen": stamp,
                "matrix_cell": cell,
                "subjects": subjects,
            },
        )
        session.add(row)
        logger.info("finding raised project=%s rule=%s", project_id, spec.rule_id)
    else:
        attrs = {
            **row.attrs,
            "rule_id": spec.rule_id,
            "severity": spec.severity.value,
            "source": spec.source,
            "headline": spec.headline,
            "evidence": _merge_finding_evidence(row.attrs.get("evidence", {}), spec.evidence),
            "count": int(row.attrs.get("count", 1)) + 1,
            "last_seen": stamp,
            "matrix_cell": cell,
            "subjects": subjects,
        }
        attrs["status"] = _status_after_raise(row.attrs, now)
        if attrs["status"] == "open":
            for stale in _STALE_ON_OPEN:
                attrs.pop(stale, None)
        row.attrs = attrs
        row.name = spec.headline[:512]
        row.domain = spec.domain
        row.version += 1
    await session.flush()
    for subject in spec.subjects:
        await write_edge(
            session,
            project_id=project_id,
            src_id=row.id,
            dst_id=subject,
            relation_type=RelationType.OBSERVED.value,
            origin=ORIGIN,
            confidence=1.0,
            evidence=[EdgeEvidence(kind=EvidenceKind.CHECKER, ref=spec.rule_id)],
            created_by=None,
            matrix_cell=spec.matrix_cell,
        )
    return row


async def _load_for_write(
    session: AsyncSession, project_id: uuid.UUID, finding_id: uuid.UUID
) -> GraphEntity:
    """Serialized against raises (project lock); a resolved finding only reopens via raise."""
    await lock_project(session, project_id)
    row = await load_finding(session, project_id, finding_id)
    if row.attrs.get("status") == "resolved":
        raise APIError(409, "conflict", "Finding is already resolved")
    return row


def _set_status(row: GraphEntity, status: FindingStatus, **extra: Any) -> None:
    row.attrs = {
        **{k: v for k, v in row.attrs.items() if k != "dismissed_until"},
        "status": status,
        **extra,
    }
    row.version += 1


async def _machine_from_evidence(
    session: AsyncSession, project_id: uuid.UUID, evidence: dict[str, Any]
) -> uuid.UUID | None:
    """The evidence's `machine_id` only when it names a live machine of THIS project."""
    try:
        wanted = uuid.UUID(str(evidence.get("machine_id")))
    except ValueError:
        return None
    found: uuid.UUID | None = await session.scalar(
        select(GraphEntity.id).where(
            GraphEntity.id == wanted,
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kinds.MACHINE,
            GraphEntity.deleted_at.is_(None),
        )
    )
    return found


async def resolve_finding(
    session: AsyncSession,
    project_id: uuid.UUID,
    finding_id: uuid.UUID,
    user_id: uuid.UUID,
    note: str,
    fix_ref: uuid.UUID | None,
) -> tuple[SolusEntry, GraphEdge | None]:
    """→ `resolved`; ONE `.solus` errors entry (ErrorMeta payload); `fixed_by` when named."""
    row = await _load_for_write(session, project_id, finding_id)
    if fix_ref is not None:
        await _live_subjects(session, project_id, [fix_ref])
    a = row.attrs
    _set_status(row, "resolved", resolved_by=str(user_id), note=note)
    text = f"Resolved {a.get('rule_id')}: {a.get('headline', row.name)}\n\nFix: {note}"
    entry = await add_text_entry(
        session,
        project_id,
        SolusSection.ERRORS,
        text[:MAX_TEXT_CHARS],
        author="user",
        created_by=user_id,
    )
    subjects = a.get("subjects") or []
    entry.payload = ErrorMeta(
        entity_id=uuid.UUID(subjects[0]) if subjects else None,
        machine_id=await _machine_from_evidence(session, project_id, a.get("evidence", {})),
        dedupe_key=row.canonical_key or canonical_finding_key(project_id, _spec_of(row)),
        count=int(a.get("count", 1)),
        status="resolved",
        fix_ref=fix_ref,
        first_seen=datetime.fromisoformat(a["first_seen"]),
        last_seen=datetime.fromisoformat(a["last_seen"]),
    ).model_dump(mode="json")
    edge = None
    if fix_ref is not None:
        edge = await write_edge(
            session,
            project_id=project_id,
            src_id=row.id,
            dst_id=fix_ref,
            relation_type=RelationType.FIXED_BY.value,
            origin=ORIGIN,
            confidence=1.0,
            evidence=[EdgeEvidence(kind=EvidenceKind.USER_CONFIRMED, ref=str(user_id))],
            created_by=user_id,
        )
    # SOLUSDEV-320 P5-T7 (solus.md §9): the fix is the "why" of the history row.
    await record_project_activity(
        session,
        project_id,
        "finding.resolved",
        actor_id=user_id,
        domain=row.domain.value,
        payload={"finding_id": str(row.id), "rule_id": a.get("rule_id"), "entry_id": str(entry.id)},
        entity_ids=[row.id, *(uuid.UUID(s) for s in subjects)],
        why_ref=str(fix_ref) if fix_ref is not None else None,
    )
    await session.flush()
    logger.info("finding resolved project=%s finding=%s by=%s", project_id, row.id, user_id)
    return entry, edge


def _spec_of(row: GraphEntity) -> FindingSpec:
    """Rebuild the key input from a row whose `canonical_key` is missing (defensive only)."""
    a = row.attrs
    return FindingSpec(
        rule_id=a["rule_id"],
        severity=Severity(a["severity"]),
        source=a["source"],
        headline=a.get("headline", row.name),
        subjects=[uuid.UUID(s) for s in a["subjects"]],
        domain=row.domain,
        bucket=a.get("bucket"),
    )


async def dismiss_finding(
    session: AsyncSession,
    project_id: uuid.UUID,
    finding_id: uuid.UUID,
    user_id: uuid.UUID,
    cooldown_hours: int = 24,
) -> GraphEntity:
    row = await _load_for_write(session, project_id, finding_id)
    until = (utcnow() + timedelta(hours=cooldown_hours)).isoformat()
    _set_status(row, "dismissed", dismissed_until=until)
    await session.flush()
    logger.info("finding dismissed project=%s finding=%s by=%s", project_id, row.id, user_id)
    return row


async def acknowledge_finding(
    session: AsyncSession, project_id: uuid.UUID, finding_id: uuid.UUID, user_id: uuid.UUID
) -> GraphEntity:
    row = await _load_for_write(session, project_id, finding_id)
    _set_status(row, "acknowledged", acknowledged_by=str(user_id))
    await session.flush()
    return row
