"""`limits` scene model → code file: a joint named by an accepted firmware constant.

Joints live in `bench_scene_model.attrs.model.joints`; there is no joint entity yet, so the
edge runs from the model to the code file (one per file) and lists every joint/constant match
in `attrs.matches` — a 0.5 candidate until someone confirms it. A constant names the longest
joint name it holds (`JOINT10_MAX` names `joint10`, never `joint1`), and none when two of that
length tie.

A match whose row states a motor constant's number carries it as `value`, with the unit the
constant's name states (`unit_of`), so `joint_limit_vs_code_constant` can compare it with the
joint's range (SOLUSDEV-321 P3-T2). A pin constant's number is a pin, never a limit; a rate's or
an effort's (`NOT_A_POSITION`: a speed, a torque) is not a position.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from solus_contracts.relations import EdgeEvidence, EvidenceKind, RelationType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.graph import kinds
from solus_api.graph.inference.common import (
    EdgeWriter,
    InferenceReport,
    accepted_evidence,
    resolve_code_entity,
    split_source_ref,
)
from solus_api.graph.inference.firmware_edges import NOT_A_POSITION
from solus_api.livebench.scene.part_bindings import finite_number
from solus_api.models import GraphEntity

MODULE: Final = "joint_limits"
LIMITS_CONFIDENCE: Final = 0.5
MOTOR_CONSTANT: Final = "motor_constant"
CONSTANT_KINDS: Final = frozenset({"pin_constant", MOTOR_CONSTANT})
#: The words of a constant's name that state radians: `rad` alone, so a `RADIUS` states none.
RADIANS: Final = frozenset({"rad", "rads", "radian", "radians"})


@dataclass(frozen=True)
class _Constant:
    file: str
    line: int
    name: str
    #: The number a motor constant's row states: never a pin's, a rate's or an effort's.
    value: float | None = None

    @property
    def ref(self) -> str:
        return f"{self.file}:{self.line}"

    def match(self, joint: str) -> dict[str, Any]:
        """The joint/constant match `attrs.matches` lists, with the constant's value and the
        unit its name states when its row states a number."""
        found: dict[str, Any] = {"joint": joint, "constant": self.name, "line": self.line}
        if self.value is None:
            return found
        return {**found, "value": self.value, "unit": unit_of(self.name)}


def unit_of(name: str) -> str:
    """`deg` when the constant's name says so, `rad` when one of its words does, else `raw`."""
    if "deg" in name.lower():
        return "deg"
    words = re.split(r"[^a-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower())
    return "rad" if RADIANS.intersection(words) else "raw"


def _canon(name: str) -> str:
    return name.lower().replace("-", "_")


def _joint_named_by(joints: list[str], name: str) -> str | None:
    """The joint a constant's name names: the longest joint name it holds, so `JOINT10_MAX` names
    `joint10`, never `joint1`. A joint name followed by a digit is another joint's (M109:
    `JOINT11_MAX` names no `joint1`). None when it holds none, or two of that length."""
    canon = _canon(name)
    named = sorted(
        {j for j in joints if re.search(re.escape(_canon(j)) + r"(?!\d)", canon)},
        key=len,
        reverse=True,
    )
    if not named or (len(named) > 1 and len(named[1]) == len(named[0])):
        return None
    return named[0]


def _constants(rows: list[dict[str, Any]]) -> list[_Constant]:
    found: list[_Constant] = []
    for row in rows:
        for item in row.get("provenance") or []:
            try:
                detail = json.loads(item.get("detail") or "{}")
            except ValueError:
                continue
            kind = detail.get("kind") if isinstance(detail, dict) else None
            name = item.get("entity_ref")
            file, line = split_source_ref(str(item.get("source_ref") or ""))
            if kind in CONSTANT_KINDS and name and line is not None:
                position = kind == MOTOR_CONSTANT and not NOT_A_POSITION.search(str(name))
                value = finite_number(detail.get("value")) if position else None
                found.append(_Constant(file, line, str(name), value))
    return found


async def infer(session: AsyncSession, project_id: UUID) -> InferenceReport:
    writer = await EdgeWriter.open(session, project_id, MODULE, (RelationType.LIMITS.value,))
    constants = _constants(
        [e.attrs.get("row") or {} for e in await accepted_evidence(session, project_id)]
    )
    if not constants:
        return writer.report
    scenes = await session.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kinds.BENCH_SCENE_MODEL,
            GraphEntity.deleted_at.is_(None),
        )
        .order_by(GraphEntity.id)
    )
    code: dict[str, GraphEntity | None] = {}
    for scene in scenes:
        joints = [
            str(j.get("name"))
            for j in (scene.attrs.get("model") or {}).get("joints") or []
            if isinstance(j, dict) and j.get("name")
        ]
        by_file: dict[str, list[tuple[str, _Constant]]] = {}
        for const in constants:
            joint = _joint_named_by(joints, const.name)
            if joint is not None:
                by_file.setdefault(const.file, []).append((joint, const))
        for file, matches in by_file.items():
            if file not in code:
                code[file] = await resolve_code_entity(session, project_id, file)
            target = code[file]
            if target is None:
                continue
            joint, first = matches[0]
            await writer.write(
                scene,
                target,
                RelationType.LIMITS.value,
                confidence=LIMITS_CONFIDENCE,
                evidence=[
                    EdgeEvidence(kind=EvidenceKind.FIRMWARE_SYMBOL, ref=c.ref) for _, c in matches
                ],
                attrs={
                    "joint": joint,
                    "constant": first.name,
                    "line": first.line,
                    "matches": [c.match(j) for j, c in matches],
                },
            )
    return writer.report
