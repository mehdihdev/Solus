#!/usr/bin/env python3
"""Dry-run-first QA pruning. Run with the API virtualenv and normal SOLUS settings.

Only explicitly allowlisted test creators and isolated, manual, named fixtures
qualify. Unknown attribution and any live graph/config references fail closed.
Back up the database and review the dry-run UUIDs before repeating with --apply.
Stop all API/worker writers first and keep them stopped through post-apply
inspection; --writers-stopped explicitly acknowledges this maintenance precondition.
No recursive graph cleanup, provider operation, or artifact deletion is performed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid

from solus_api.core.config import Settings
from solus_api.core.db import build_engine, build_sessionmaker
from solus_api.models import (
    DataEvent,
    GraphEdge,
    GraphEntity,
    HardwareSuggestion,
    Project,
    SolusEntry,
    SolusEntryKind,
    utcnow,
)
from sqlalchemy import Text, cast, delete, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

_QA_NAME = re.compile(r"(?<![a-z0-9])(qa|test|fixture|placeholder)(?![a-z0-9])", re.IGNORECASE)
_PROTECTED_KINDS = {"solus_config", "solus_section", "robot_category", "canonical_part"}


def _manual_fixture(node: GraphEntity) -> bool:
    return (
        node.origin == "manual"
        and node.source_id is None
        and node.source_connector is None
        and node.external_ref is None
        and node.canonical_part_id is None
        and node.canonical_key is None
        and node.kind not in _PROTECTED_KINDS
        and not node.kind.startswith("solus:")
        and bool(_QA_NAME.search(node.name))
    )


async def _unreferenced(session: AsyncSession, node: GraphEntity) -> bool:
    # Inspect incoming identities globally: corrupted cross-project references
    # must block deletion too, without exposing the other project's contents.
    edge = await session.scalar(
        select(GraphEdge.id)
        .where(
            GraphEdge.deleted_at.is_(None),
            or_(GraphEdge.src_id == node.id, GraphEdge.dst_id == node.id),
        )
        .limit(1)
    )
    canonical = await session.scalar(
        select(GraphEntity.id)
        .where(
            GraphEntity.canonical_part_id == node.id,
        )
        .limit(1)
    )
    entry = await session.scalar(
        select(SolusEntry.id)
        .where(
            SolusEntry.deleted_at.is_(None),
            or_(
                SolusEntry.configured_entity_id == node.id,
                cast(SolusEntry.payload, Text).contains(str(node.id)),
                SolusEntry.entity_id == node.id,
            ),
            or_(
                SolusEntry.project_id != node.project_id,
                SolusEntry.entity_id.is_(None),
                SolusEntry.entity_id != node.id,
            ),
        )
        .limit(1)
    )
    suggestion = await session.scalar(
        select(HardwareSuggestion.id)
        .where(
            HardwareSuggestion.project_id != node.project_id,
            or_(
                HardwareSuggestion.candidate_robot_id == node.id,
                HardwareSuggestion.subject_ref == f"entity:{node.id}",
            ),
        )
        .limit(1)
    )
    return edge is None and canonical is None and entry is None and suggestion is None


async def _creator_proven(
    session: AsyncSession, project: Project, node: GraphEntity, test_user_ids: set[uuid.UUID]
) -> bool:
    entries = list(
        await session.scalars(
            select(SolusEntry)
            .where(
                SolusEntry.project_id == project.id,
                SolusEntry.entity_id == node.id,
                SolusEntry.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
    )
    creators: set[uuid.UUID] = set()
    for entry in entries:
        if entry.kind == SolusEntryKind.ARTIFACT or entry.artifact_id is not None:
            return False
        if entry.configured_entity_id not in (None, node.id):
            return False
        for key in ("entity_id", "robot_entity_id"):
            subject = (entry.payload or {}).get(key)
            if subject is not None and subject != str(node.id):
                return False
        if entry.created_by is None:
            return False
        creators.add(entry.created_by)
    events = await session.scalars(
        select(DataEvent)
        .where(
            DataEvent.project_id == project.id,
            DataEvent.event_type == "workspace.robot_created",
            DataEvent.payload["entity_id"].astext == str(node.id),
        )
        .execution_options(populate_existing=True)
    )
    for event in events:
        if event.team_id != project.team_id or event.user_id is None:
            return False
        creators.add(event.user_id)
    return bool(creators) and creators <= test_user_ids


async def prune_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    test_user_ids: set[uuid.UUID],
    *,
    apply: bool = False,
) -> list[uuid.UUID]:
    """Return candidate UUIDs; mutate only on apply, leaving commit to the caller.

    Apply requires quiesced writers. Table locks protect revalidation only until
    commit: soft deletion cannot prevent a stale writer from inserting later.
    Callers must commit/rollback promptly and keep writers stopped until inspected.
    """
    if apply and not test_user_ids:
        raise ValueError("At least one explicit test user is required for apply")
    if session.get_bind().dialect.name != "postgresql":
        raise ValueError("QA pruning requires PostgreSQL")
    if apply:
        await session.execute(text("SET LOCAL lock_timeout = '2s'"))
        await session.execute(text("SET LOCAL statement_timeout = '10s'"))
        await session.execute(
            text(
                "LOCK TABLE projects, graph_entity, graph_edge, solus_entries, "
                "hardware_suggestions, data_events IN SHARE ROW EXCLUSIVE MODE"
            )
        )
    project = await session.scalar(
        select(Project)
        .where(
            Project.id == project_id,
            Project.deleted_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    if project is None:
        raise ValueError("A live project is required")
    if not test_user_ids:
        return []
    nodes = await session.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.deleted_at.is_(None),
        )
        .order_by(GraphEntity.id)
        .execution_options(populate_existing=True)
    )
    candidates = []
    for node in nodes:
        if (
            _manual_fixture(node)
            and await _unreferenced(session, node)
            and await _creator_proven(session, project, node, test_user_ids)
        ):
            candidates.append(node)
    if apply:
        await _soft_delete(session, project_id, candidates)
    return [node.id for node in candidates]


async def _soft_delete(
    session: AsyncSession, project_id: uuid.UUID, candidates: list[GraphEntity]
) -> None:
    ids = [node.id for node in candidates]
    if not ids:
        return
    now = utcnow()
    for node in candidates:
        node.deleted_at = now
        node.version += 1
    entries = await session.scalars(
        select(SolusEntry).where(
            SolusEntry.project_id == project_id,
            SolusEntry.entity_id.in_(ids),
            SolusEntry.deleted_at.is_(None),
        )
    )
    for entry in entries:
        entry.deleted_at = now
    # Suggestions have no soft-delete field. Remove only exact references in
    # this project; a device serial merely containing the UUID is not a match.
    await session.execute(
        delete(HardwareSuggestion).where(
            HardwareSuggestion.project_id == project_id,
            or_(
                HardwareSuggestion.candidate_robot_id.in_(ids),
                HardwareSuggestion.subject_ref.in_([f"entity:{item}" for item in ids]),
            ),
        )
    )
    # Any live binding would have blocked the candidate. Historical edges are
    # already non-operational and stay intact as evidence.
    await session.flush()


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True, type=uuid.UUID)
    parser.add_argument("--test-user-id", action="append", type=uuid.UUID, default=[])
    parser.add_argument("--apply", action="store_true", help="Apply reviewed candidates atomically")
    parser.add_argument(
        "--writers-stopped",
        action="store_true",
        help="Acknowledge all database writers are stopped until inspection",
    )
    return parser


async def _run(args: argparse.Namespace) -> None:
    settings = Settings()  # type: ignore[call-arg]  # Required fields come from environment.
    engine = build_engine(settings.database_url)
    try:
        async with build_sessionmaker(engine)() as session, session.begin():
            database = await session.scalar(text("SELECT current_database()"))
            ids = await prune_project(
                session, args.project_id, set(args.test_user_id), apply=args.apply
            )
        sys.stdout.write(
            json.dumps(
                {
                    "database": database,
                    "project_id": str(args.project_id),
                    "mode": "applied" if args.apply else "dry_run",
                    "candidate_ids": list(map(str, ids)),
                    "test_user_count": len(set(args.test_user_id)),
                }
            )
            + "\n"
        )
    finally:
        await engine.dispose()


def main() -> int:
    parser = argument_parser()
    args = parser.parse_args()
    if args.apply and (not args.writers_stopped or not args.test_user_id):
        parser.error("--apply requires --writers-stopped and at least one --test-user-id")
    try:
        asyncio.run(_run(args))
    except (SQLAlchemyError, ValueError):
        # Connection errors can contain credentials; never print exception text.
        sys.stderr.write(
            "QA pruning failed; no changes committed. Check scope and database access.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
