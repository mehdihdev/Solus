"""`commands` / `reads` code → part from accepted extraction evidence + the robot's bus map.

A reviewed row (`hardware_evidence_for`, `attrs.row` = TopologyEvidence) names a bus address
or an analog pin at `provenance[].source_ref = "file:line"`. The code entity is resolved by
path suffix; a row whose source is not a path in the graph (a local `source:<uuid>` reference)
resolves to nothing and infers nothing — the ceiling, by design.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from solus_contracts.relations import EdgeEvidence, EvidenceKind, RelationType
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.graph.inference.common import (
    EdgeWriter,
    InferenceReport,
    accepted_evidence,
    resolve_code_entity,
    split_source_ref,
)
from solus_api.models import GraphEdge, GraphEntity

MODULE: Final = "firmware_edges"
COMMANDS_CONFIDENCE: Final = 0.8
CONFIG_LITERAL_CONFIDENCE: Final = 0.55
READS_CONFIDENCE: Final = 0.55
ANALOG: Final = "analog"


def normalize_address(value: Any) -> str | None:
    """`"0x03"`, `"06"` and `"3"` are one address; anything else compares case-folded."""
    if value is None:
        return None
    text = str(value).strip()
    for base in (0, 10):
        try:
            return str(int(text, base))
        except ValueError:
            continue
    return text.lower() or None


async def _bus_map(
    session: AsyncSession, project_id: UUID, robot_id: UUID
) -> dict[str, list[UUID]]:
    from solus_api.hardware.runtime import resolve_runtime_config

    try:
        config = await resolve_runtime_config(session, project_id, robot_id)
    except APIError:
        return {}
    by_address: dict[str, list[UUID]] = {}
    for item in config.bus_map:
        key = normalize_address(item.address)
        if key is not None and item.part_entity_id is not None:
            by_address.setdefault(key, []).append(item.part_entity_id)
    return by_address


async def _wired_pins(
    session: AsyncSession, project_id: UUID, brain_id: UUID
) -> dict[str, list[UUID]]:
    """pin on the brain → the parts a `wires` edge joins it to on that pin."""
    edges = await session.scalars(
        select(GraphEdge).where(
            GraphEdge.project_id == project_id,
            GraphEdge.relation_type == RelationType.WIRES.value,
            GraphEdge.deleted_at.is_(None),
            or_(GraphEdge.src_id == brain_id, GraphEdge.dst_id == brain_id),
        )
    )
    pins: dict[str, list[UUID]] = {}
    for edge in edges:
        other = edge.dst_id if edge.src_id == brain_id else edge.src_id
        for pin in edge.attrs.get("pins", {}).get(str(brain_id), []):
            pins.setdefault(str(pin), []).append(other)
    return pins


class _FirmwareRun:
    """One pass over the accepted rows with per-robot / per-brain / per-file caches."""

    def __init__(self, session: AsyncSession, project_id: UUID, writer: EdgeWriter) -> None:
        self.session, self.project_id, self.writer = session, project_id, writer
        self.bus_maps: dict[UUID, dict[str, list[UUID]]] = {}
        self.pins: dict[UUID, dict[str, list[UUID]]] = {}
        self.code: dict[str, GraphEntity | None] = {}

    async def bus_map(self, robot_id: UUID) -> dict[str, list[UUID]]:
        if robot_id not in self.bus_maps:
            self.bus_maps[robot_id] = await _bus_map(self.session, self.project_id, robot_id)
        return self.bus_maps[robot_id]

    async def wired(self, brain_id: UUID) -> dict[str, list[UUID]]:
        if brain_id not in self.pins:
            self.pins[brain_id] = await _wired_pins(self.session, self.project_id, brain_id)
        return self.pins[brain_id]

    async def code_entity(self, file: str) -> GraphEntity | None:
        if file not in self.code:
            self.code[file] = await resolve_code_entity(self.session, self.project_id, file)
        return self.code[file]

    async def part(self, part_id: UUID) -> GraphEntity | None:
        row = await self.session.get(GraphEntity, part_id)
        if row is None or row.project_id != self.project_id or row.deleted_at is not None:
            return None
        return row

    async def reads(
        self, edge: GraphEdge, code: GraphEntity, pin: Any, evidence: list[EdgeEvidence]
    ) -> None:
        for part_id in (await self.wired(edge.src_id)).get(str(pin), []):
            part = await self.part(part_id)
            if part is not None:
                await self.writer.write(
                    code,
                    part,
                    RelationType.READS.value,
                    confidence=READS_CONFIDENCE,
                    evidence=evidence,
                    attrs={"pin": str(pin)},
                )

    async def commands(
        self, edge: GraphEdge, code: GraphEntity, row: dict[str, Any], evidence: list[EdgeEvidence]
    ) -> None:
        key = normalize_address(row.get("address"))
        try:
            robot_id = UUID(str(edge.attrs.get("robot_id")))
        except ValueError:
            return
        matches = (await self.bus_map(robot_id)).get(key, []) if key else []
        if len(matches) != 1:
            return
        part = await self.part(matches[0])
        if part is None:
            return
        literal = edge.attrs.get("source_kind") == "host_config"
        await self.writer.write(
            code,
            part,
            RelationType.COMMANDS.value,
            confidence=CONFIG_LITERAL_CONFIDENCE if literal else COMMANDS_CONFIDENCE,
            evidence=evidence,
            attrs={"address": str(row.get("address")), "protocol": row.get("protocol")},
        )

    async def handle(self, edge: GraphEdge) -> None:
        row = edge.attrs.get("row") or {}
        provenance = row.get("provenance") or [{}]
        source_ref = str(provenance[0].get("source_ref") or row.get("source_ref") or "")
        file, line = split_source_ref(source_ref)
        code = await self.code_entity(file) if line is not None else None
        if code is None:
            return
        evidence = [EdgeEvidence(kind=EvidenceKind.FIRMWARE_SYMBOL, ref=source_ref)]
        if row.get("protocol") == ANALOG:
            pin = row.get("address") or provenance[0].get("pin_ref")
            if pin:
                await self.reads(edge, code, pin, evidence)
        elif row.get("address") is not None:
            await self.commands(edge, code, row, evidence)


async def infer(session: AsyncSession, project_id: UUID) -> InferenceReport:
    writer = await EdgeWriter.open(
        session, project_id, MODULE, (RelationType.COMMANDS.value, RelationType.READS.value)
    )
    run = _FirmwareRun(session, project_id, writer)
    for edge in await accepted_evidence(session, project_id):
        await run.handle(edge)
    return writer.report
