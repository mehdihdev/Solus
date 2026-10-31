"""`commands` / `reads` code → part from accepted extraction evidence + the robot's bus map.

A reviewed row (`hardware_evidence_for`, `attrs.row` = TopologyEvidence) names a bus address
or an analog pin at `provenance[].source_ref = "file:line"`. The code entity is resolved by
path suffix; a row whose source is not a path in the graph (a local `source:<uuid>` reference)
resolves to nothing and infers nothing — the ceiling, by design.

The commanded fact (SOLUSDEV-321 P3-T2). A reviewed goal call (`provenance[0].detail.kind ==
"goal_call"`, as the firmware extractor writes it) that states a numeric literal adds
`attrs.commanded = {min, max, unit, min_ref, max_ref}` to the `commands` edge its address writes —
the same write, never another edge: the range of every literal goal one file writes to that
address, `deg` when the call's name says so and `raw` otherwise, and the `path:line` of each end's
literal, so a finding opens the line that breaches. A goal with no literal, a call that names a
rate or an effort (a speed, a current: not a position), and goals in two units state none:
`commanded` is then None. Every write states the key, since `write_edge` merges attrs, so a
literal that no longer stands clears the old range. `checkers/cells/software_mechanical.py`
judges it against the part's position limits.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any, Final, NamedTuple
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
from solus_api.livebench.scene.part_bindings import finite_number
from solus_api.models import GraphEdge, GraphEntity

MODULE: Final = "firmware_edges"
COMMANDS_CONFIDENCE: Final = 0.8
CONFIG_LITERAL_CONFIDENCE: Final = 0.55
READS_CONFIDENCE: Final = 0.55
ANALOG: Final = "analog"
GOAL_CALL: Final = "goal_call"
#: A goal call that names a rate or an effort commands the part but states no position. An angular
#: rate is one too (M108): `omega`, `rad_per_s`, `rad_s`, `rpm` — each only as a whole token of the
#: name (snake_case or a camelCase hump on both sides, case-sensitive there), so plural `RADS`
#: (radians) and the `rpM` inside `warpMode` keep their position value.
_WORD_START: Final = r"(?-i:(?<![A-Za-z0-9])|(?<=[a-z])(?=[A-Z]))"
_WORD_END: Final = r"(?-i:(?![a-z0-9]))"
NOT_A_POSITION: Final = re.compile(
    r"vel|speed|rate|acc|torque|current|effort|"
    rf"{_WORD_START}(?:omega|rad_?per_?s|rad_s|rpm){_WORD_END}",
    re.IGNORECASE,
)


class GoalLiteral(NamedTuple):
    """One reviewed position goal: its literal, its unit and the `path:line` it is written at."""

    value: float
    unit: str
    ref: str


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


def goal_literal(row: Mapping[str, Any]) -> GoalLiteral | None:
    """The literal position goal a reviewed goal-call row states; None for any other row."""
    first = (row.get("provenance") or [{}])[0]
    if not isinstance(first, Mapping):
        return None
    detail = _detail(first)
    name, ref = first.get("entity_ref"), first.get("source_ref")
    value = finite_number(detail.get("value"))
    if detail.get("kind") != GOAL_CALL or not isinstance(name, str) or not isinstance(ref, str):
        return None
    if value is None or NOT_A_POSITION.search(name):
        return None
    return GoalLiteral(value, "deg" if "deg" in name.lower() else "raw", ref)


def _detail(item: Mapping[str, Any]) -> Mapping[str, Any]:
    """A provenance item's JSON `detail` as a mapping; empty when it is not one."""
    try:
        parsed = json.loads(item.get("detail") or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def commanded_goals(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """`attrs.commanded` per (file, bus address), over the literal goals the reviewed rows state."""
    goals: dict[tuple[str, str], list[GoalLiteral]] = {}
    for row in rows:
        goal, key = goal_literal(row), normalize_address(row.get("address"))
        if goal is not None and key is not None:
            goals.setdefault((split_source_ref(goal.ref)[0], key), []).append(goal)
    return {key: found for key, at in goals.items() if (found := _goal_range(at)) is not None}


def _goal_range(goals: list[GoalLiteral]) -> dict[str, Any] | None:
    """`{min, max, unit, min_ref, max_ref}` of one address's goals, each ref the line of that
    end's literal; None in two units."""
    if len({goal.unit for goal in goals}) != 1:
        return None
    low = min(goals, key=lambda goal: goal.value)
    top = max(goals, key=lambda goal: goal.value)
    return {
        "min": low.value,
        "max": top.value,
        "unit": top.unit,
        "min_ref": low.ref,
        "max_ref": top.ref,
    }


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
    """One pass over the accepted rows with per-robot / per-brain / per-file caches; `goals` is
    the commanded fact per (file, bus address), gathered from every row before the pass."""

    def __init__(
        self,
        session: AsyncSession,
        project_id: UUID,
        writer: EdgeWriter,
        goals: Mapping[tuple[str, str], dict[str, Any]],
    ) -> None:
        self.session, self.project_id, self.writer = session, project_id, writer
        self.goals = goals
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
        self,
        edge: GraphEdge,
        code: GraphEntity,
        row: dict[str, Any],
        evidence: list[EdgeEvidence],
        file: str,
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
        attrs: dict[str, Any] = {
            "address": str(row.get("address")),
            "protocol": row.get("protocol"),
        }
        commanded = self.goals.get((file, key)) if key else None
        await self.writer.write(
            code,
            part,
            RelationType.COMMANDS.value,
            confidence=CONFIG_LITERAL_CONFIDENCE if literal else COMMANDS_CONFIDENCE,
            evidence=evidence,
            attrs={**attrs, "commanded": commanded},
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
            await self.commands(edge, code, row, evidence, file)


async def infer(session: AsyncSession, project_id: UUID) -> InferenceReport:
    writer = await EdgeWriter.open(
        session, project_id, MODULE, (RelationType.COMMANDS.value, RelationType.READS.value)
    )
    accepted = await accepted_evidence(session, project_id)
    goals = commanded_goals(edge.attrs.get("row") or {} for edge in accepted)
    run = _FirmwareRun(session, project_id, writer, goals)
    for edge in accepted:
        await run.handle(edge)
    return writer.report
