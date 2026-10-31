"""`publishes` / `subscribes` ROS node → topic from what a sync landed (SOLUSDEV-321 P6).

A connector lands `ros_node` and `ros_topic` entities from a workspace's package texts
(`software/ros_reader.py`); each node carries the topics its module declares (`attrs.publishes`,
`attrs.subscribes`), the launch line that starts it (`attrs.launched_at`) and each declaring call
(`attrs.declared_at`). `infer` joins each node to the SAME source's topic of that name at 0.9,
`origin=inferred`, evidence `config` with `ref` the launch line and the call in `detail`, through
`EdgeWriter` (`write_edge`), and retires the module's own inferred edges that a re-sync no longer
declares. A manual edge is never touched.

`confirm_live` (R131) takes a live listing (`code.ros2_nodes` / `code.ros2_topics`) and only
RAISES edges that already stand: each live inferred edge whose node, or whose topic, was listed
goes to 1.0 through `annotate_edge(confirmed_by=…)`. A listed name that no edge carries writes
nothing, since any DDS participant on the network can announce one.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from typing import Final
from uuid import UUID

from solus_contracts.relations import EdgeEvidence, EdgeOrigin, EvidenceKind, RelationType
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from solus_api.graph import kinds
from solus_api.graph.edges import annotate_edge, retire_edge
from solus_api.graph.inference.common import EdgeWriter, InferenceReport
from solus_api.models import GraphEdge, GraphEntity
from solus_api.software.ros_reader import MAX_NAME_CHARS, ROS_NAME

logger = logging.getLogger("solus.graph.inference.ros_edges")

MODULE: Final = "ros_edges"
CONFIDENCE: Final = 0.9
#: A node attribute → the relation it states.
DIRECTIONS: Final = {
    "publishes": RelationType.PUBLISHES.value,
    "subscribes": RelationType.SUBSCRIBES.value,
}
RELATIONS: Final = tuple(DIRECTIONS.values())
#: At most this many names of one live listing are matched (the companion caps the same).
MAX_LIVE_NAMES: Final = 512
#: At most this many edges are raised by one live listing.
MAX_LIVE_EDGES: Final = 1024


async def infer(session: AsyncSession, project_id: UUID) -> InferenceReport:
    nodes = await session.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kinds.ROS_NODE,
            GraphEntity.deleted_at.is_(None),
        )
        .order_by(GraphEntity.id)
    )
    topics = {
        (row.source_id, row.name): row
        for row in await session.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == project_id,
                GraphEntity.kind == kinds.ROS_TOPIC,
                GraphEntity.deleted_at.is_(None),
            )
        )
    }
    writer = await EdgeWriter.open(session, project_id, MODULE, RELATIONS)
    kept: set[UUID] = set()
    for node in nodes:
        for attr, relation in DIRECTIONS.items():
            for name in _ros_names(node.attrs.get(attr)):
                topic = topics.get((node.source_id, name))
                if topic is None:
                    continue
                evidence = _launch_evidence(node, name)
                edge = await writer.write(
                    node, topic, relation, confidence=CONFIDENCE, evidence=[evidence]
                )
                kept.add(edge.id)
    retired = await _retire_undeclared(session, project_id, kept)
    if retired:
        logger.info("ros_edges retired=%d project=%s", retired, project_id)
    return writer.report


def _ros_names(value: object) -> list[str]:
    return [name for name in value if isinstance(name, str)] if isinstance(value, list) else []


def _launch_evidence(node: GraphEntity, topic: str) -> EdgeEvidence:
    """`config` at the launch line that starts the node; the declaring call in `detail`."""
    launched = node.attrs.get("launched_at")
    declared = node.attrs.get("declared_at")
    at = declared.get(topic) if isinstance(declared, dict) else None
    return EdgeEvidence(
        kind=EvidenceKind.CONFIG,
        ref=(launched if isinstance(launched, str) and launched else node.name)[:512],
        detail=f"declared at {at}"[:1024] if isinstance(at, str) else None,
    )


async def _retire_undeclared(session: AsyncSession, project_id: UUID, kept: set[UUID]) -> int:
    """This module's live inferred edges that no node declares any more: retired."""
    node = aliased(GraphEntity)
    stale = list(
        await session.scalars(
            select(GraphEdge)
            .join(node, node.id == GraphEdge.src_id)
            .where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type.in_(RELATIONS),
                GraphEdge.origin == EdgeOrigin.INFERRED.value,
                GraphEdge.deleted_at.is_(None),
                node.kind == kinds.ROS_NODE,
                GraphEdge.id.not_in(kept),
            )
        )
    )
    for edge in stale:
        retire_edge(edge)
    if stale:
        await session.flush()
    return len(stale)


def live_names(names: Iterable[object]) -> list[str]:
    """The listed names that are ROS graph names (the R3 grammar, at most MAX_NAME_CHARS), each
    once and at most MAX_LIVE_NAMES: nothing else from a live listing reaches a writer."""
    kept = dict.fromkeys(
        name
        for name in names
        if isinstance(name, str) and len(name) <= MAX_NAME_CHARS and re.fullmatch(ROS_NAME, name)
    )
    return list(kept)[:MAX_LIVE_NAMES]


async def confirm_live(
    session: AsyncSession,
    project_id: UUID,
    *,
    ref: str,
    nodes: Iterable[str] = (),
    topics: Mapping[str, str | None] | None = None,
) -> int:
    """Raise this project's live inferred `publishes`/`subscribes` edges that a listing confirms:
    a listed node confirms every such edge from it, a listed topic every such edge to it (when
    the live and declared types are both known they must agree). Names pass `live_names` here
    too, whatever the caller applied (m3); the caller holds `lock_project`. Returns how many
    edges were raised."""
    given = topics or {}
    listed_topics = {name: given[name] for name in live_names(given)}
    listed_nodes = set(live_names(nodes))
    raised = 0
    for edge_id, node, topic, declared in await _live_matches(
        session, project_id, listed_nodes, set(listed_topics)
    ):
        if node in listed_nodes:
            seen = node
        elif topic in listed_topics and _types_agree(listed_topics[topic], declared):
            seen = topic
        else:
            continue
        evidence = EdgeEvidence(
            kind=EvidenceKind.BUS_ENUMERATION, ref=ref, detail=f"seen live: {seen}"
        )
        raised += (
            await annotate_edge(session, project_id, edge_id, confirmed_by=evidence) is not None
        )
    return raised


def _types_agree(live: str | None, declared: object) -> bool:
    return live is None or not isinstance(declared, str) or not declared or live == declared


async def _live_matches(
    session: AsyncSession, project_id: UUID, nodes: set[str], topics: set[str]
) -> list[tuple[UUID, str, str, object]]:
    """`(edge id, node name, topic name, declared topic type)` for each live inferred edge below
    1.0 between live ROS entities whose node or topic was listed."""
    if not nodes and not topics:
        return []
    node, topic = aliased(GraphEntity), aliased(GraphEntity)
    rows = await session.execute(
        select(GraphEdge.id, node.name, topic.name, topic.attrs["type"])
        .join(node, node.id == GraphEdge.src_id)
        .join(topic, topic.id == GraphEdge.dst_id)
        .where(
            GraphEdge.project_id == project_id,
            GraphEdge.relation_type.in_(RELATIONS),
            GraphEdge.origin == EdgeOrigin.INFERRED.value,
            GraphEdge.deleted_at.is_(None),
            GraphEdge.confidence < 1.0,
            node.kind == kinds.ROS_NODE,
            node.deleted_at.is_(None),
            topic.kind == kinds.ROS_TOPIC,
            topic.deleted_at.is_(None),
            or_(node.name.in_(nodes), topic.name.in_(topics)),
        )
        .order_by(GraphEdge.id)
        .limit(MAX_LIVE_EDGES)
    )
    return [(row[0], row[1], row[2], row[3]) for row in rows.all()]
