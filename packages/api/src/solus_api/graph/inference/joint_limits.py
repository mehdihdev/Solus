"""`limits` scene model → code file: a joint named by an accepted firmware constant.

Joints live in `bench_scene_model.attrs.model.joints`; there is no joint entity yet, so the
edge runs from the model to the code file (one per file) and lists every joint/constant match
in `attrs.matches` — a 0.5 candidate until someone confirms it.
"""

from __future__ import annotations

import json
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
from solus_api.models import GraphEntity

MODULE: Final = "joint_limits"
LIMITS_CONFIDENCE: Final = 0.5
CONSTANT_KINDS: Final = frozenset({"pin_constant", "motor_constant"})


@dataclass(frozen=True)
class _Constant:
    file: str
    line: int
    name: str

    @property
    def ref(self) -> str:
        return f"{self.file}:{self.line}"


def _canon(name: str) -> str:
    return name.lower().replace("-", "_")


def _constants(rows: list[dict[str, Any]]) -> list[_Constant]:
    found: list[_Constant] = []
    for row in rows:
        for item in row.get("provenance") or []:
            try:
                kind = json.loads(item.get("detail") or "{}").get("kind")
            except ValueError:
                continue
            name = item.get("entity_ref")
            file, line = split_source_ref(str(item.get("source_ref") or ""))
            if kind in CONSTANT_KINDS and name and line is not None:
                found.append(_Constant(file, line, str(name)))
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
            for joint in joints:
                if _canon(joint) in _canon(const.name):
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
                    "matches": [
                        {"joint": j, "constant": c.name, "line": c.line} for j, c in matches
                    ],
                },
            )
    return writer.report
