"""SOLUSDEV-321 P2-T1 fix 1 — which joint and which channel belong to a part.

The first tier (`agent/deterministic_facts.py`) and the envelopes
(`livebench/findings/envelopes.py`) both ask the graph two things of a part: the scene joint it is
bound to, and the telemetry channel it has for a quantity. They are answered here, once, in a
module both may import (this package imports from neither), so the two cannot drift:

- `bound_scenes` reads, for any number of parts at once, the project's scene models whose bindings
  name one of them (jsonb containment, so a scene that binds none of them is never read), at
  most `SCENES` of them, by id.
- `scene_joint_for_part` is the pure rule over those rows: the joint their bindings map the part
  to, whose bounds are both finite numbers, in the scene's own unit (`rad`, or `m` for a
  prismatic joint). Two joints that disagree on the range answer None: which one is meant is not
  known.
- `channel_for_quantity` is the pure rule for channels: the one channel whose last dotted segment
  is the quantity (`<role>.<quantity>`). Two: which is meant is not known, so none.
- `finite_number` is the one reading of a number a source states, here and in the envelopes: a
  finite float, never a bool, text, nan, inf or an integer too big for a float.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from solus_api.graph import kinds
from solus_api.models import GraphEntity
from sqlalchemy import or_, select

if TYPE_CHECKING:
    from solus_api.hardware.config import TelemetryChannel
    from sqlalchemy.ext.asyncio import AsyncSession

#: The most scene models read for the bindings of the parts asked about: a bound on the query,
#: never a scan.
SCENES: Final = 50


@dataclass(frozen=True)
class JointRange:
    """The scene joint bound to a part: its bounds in the scene's units (`rad`, or `m` for a
    prismatic joint)."""

    scene_id: uuid.UUID
    joint: str
    lower: float
    upper: float
    unit: str


async def bound_scenes(
    session: AsyncSession, project_id: uuid.UUID, part_ids: Iterable[uuid.UUID]
) -> list[tuple[uuid.UUID, dict[str, Any]]]:
    """(id, attrs) of the project's scene models whose bindings name any of `part_ids`, by id,
    at most `SCENES`; none for no parts."""
    binds = [GraphEntity.attrs["bindings"].contains([{"part_entity_id": str(i)}]) for i in part_ids]
    if not binds:
        return []
    rows = await session.execute(
        select(GraphEntity.id, GraphEntity.attrs)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kinds.BENCH_SCENE_MODEL,
            GraphEntity.deleted_at.is_(None),
            or_(*binds),
        )
        .order_by(GraphEntity.id)
        .limit(SCENES)
    )
    return list(rows.tuples())


def scene_joint_for_part(
    scenes: Iterable[tuple[uuid.UUID, Mapping[str, Any]]], part_id: uuid.UUID
) -> JointRange | None:
    """The joint the scenes' bindings map the part to; None when there is none, or when the
    joints found do not all state the same range and unit."""
    joints = [
        JointRange(scene_id, *joint)
        for scene_id, attrs in scenes
        for joint in _bound_joints(attrs, part_id)
    ]
    ranges = {(joint.lower, joint.upper, joint.unit) for joint in joints}
    return joints[0] if len(ranges) == 1 else None


def channel_for_quantity(
    channels: Iterable[TelemetryChannel], quantity: str
) -> TelemetryChannel | None:
    """The one channel of the part named for `quantity`; none when it has no such channel or
    two."""
    named = [channel for channel in channels if channel.name.rsplit(".", 1)[-1] == quantity]
    return named[0] if len(named) == 1 else None


def finite_number(value: object) -> float | None:
    """`value` as a finite float. A bool, a string, nan, inf or an integer too big for a float
    states nothing: None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _bound_joints(
    attrs: Mapping[str, Any], part_id: uuid.UUID
) -> list[tuple[str, float, float, str]]:
    """(joint, lower, upper, unit) of each joint a scene's bindings map the part to whose
    bounds are both finite numbers."""
    bindings = attrs.get("bindings")
    names = {
        binding.get("joint")
        for binding in (bindings if isinstance(bindings, list) else [])
        if isinstance(binding, dict) and binding.get("part_entity_id") == str(part_id)
    }
    model = attrs.get("model")
    joints = model.get("joints") if isinstance(model, dict) else None
    found: list[tuple[str, float, float, str]] = []
    for joint in joints if isinstance(joints, list) else []:
        if not isinstance(joint, dict) or joint.get("name") not in names:
            continue
        lower, upper = finite_number(joint.get("lower")), finite_number(joint.get("upper"))
        if lower is not None and upper is not None:
            unit = "m" if joint.get("type") == "prismatic" else "rad"
            found.append((str(joint["name"]), lower, upper, unit))
    return found
