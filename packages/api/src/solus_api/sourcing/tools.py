"""SOL tool `sourcing.derive_torque` (SOLUSDEV-246 ST5) — Solus arithmetic over the graph.

A read: the assembly's direct parts (placement from CAD, mass from the graph
or the caller) → the static holding torque with its assumptions. Registered
per project by `build_sol_registry`; the model never computes torque itself.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, Tool, ToolException
from solus_api.core.errors import APIError
from solus_api.sourcing.service import find_assembly, read_assembly
from solus_api.sourcing.torque import (
    DEFAULT_SAFETY_FACTOR,
    MAX_SAFETY_FACTOR,
    MIN_SAFETY_FACTOR,
    derive_torque,
    loads_from_assembly,
)

DERIVE_TORQUE = ToolDescriptor(
    name="sourcing.derive_torque",
    description=(
        "Compute the static holding torque an actuator needs for a CAD assembly in this "
        "project: Solus sums each direct child part's mass x g x horizontal distance from the "
        "pivot (the assembly origin unless pivot_mm is given), times a safety factor. Parts "
        "with no mass in the graph are listed as unknown, never guessed; pass masses (kg by "
        "entity id) when you have them, e.g. from onshape.get_mass_properties. Name the "
        "assembly by assembly_entity_id, or by assembly_name when you only know its name — an "
        "unknown name answers with the assemblies this project has."
    ),
    params={
        "type": "object",
        "properties": {
            "assembly_entity_id": {"type": "string", "format": "uuid"},
            "assembly_name": {"type": "string", "minLength": 1, "maxLength": 200},
            "pivot_mm": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
            "masses": {
                "type": "object",
                "additionalProperties": {"type": "number", "minimum": 0, "maximum": 1000000},
                "maxProperties": 500,
            },
            "safety_factor": {
                "type": "number",
                "minimum": MIN_SAFETY_FACTOR,
                "maximum": MAX_SAFETY_FACTOR,
            },
        },
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {
            "assembly": {"type": "string"},
            "static_torque_nm": {"type": "number"},
            "required_torque_nm": {"type": "number"},
            "safety_factor": {"type": "number"},
            "loads": {"type": "array"},
            "unknown": {"type": "array"},
            "assumptions": {"type": "array"},
        },
        "required": ["assembly", "static_torque_nm", "required_torque_nm", "safety_factor"],
        "additionalProperties": False,
    },
)


def _masses(raw: Any) -> dict[uuid.UUID, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[uuid.UUID, float] = {}
    for key, value in raw.items():
        try:
            out[uuid.UUID(str(key))] = float(value)
        except (TypeError, ValueError):
            continue
    return out


async def derive_for_assembly(
    session: AsyncSession,
    project_id: uuid.UUID,
    assembly_id: uuid.UUID,
    *,
    pivot_mm: tuple[float, float, float] | None,
    masses: dict[uuid.UUID, float] | None,
    safety_factor: float,
) -> dict[str, Any]:
    """The one derivation both the route and the tool use."""
    read = await read_assembly(session, project_id, assembly_id, masses=masses)
    loads, unknown = loads_from_assembly(read.parts, pivot_mm=pivot_mm or (0.0, 0.0, 0.0))
    result = derive_torque(loads, unknown=unknown, safety_factor=safety_factor)
    return {
        "assembly": read.assembly.name,
        "assembly_entity_id": str(read.assembly.id),
        "parts": [
            {
                "entity_id": str(p.id),
                "name": p.name,
                "mass_kg": p.mass_kg,
                "position_mm": list(p.position_mm) if p.position_mm else None,
            }
            for p in read.parts
        ],
        **result.payload(),
    }


async def _resolve_assembly(
    session: AsyncSession, project_id: uuid.UUID, args: dict[str, Any]
) -> uuid.UUID:
    """`assembly_entity_id` wins; else `assembly_name` within THIS project; else invalid."""
    raw_id = args.get("assembly_entity_id")
    if raw_id is not None:
        try:
            return uuid.UUID(str(raw_id))
        except ValueError:
            raise ToolException(
                "assembly_entity_id is not a uuid", code=ToolErrorCode.INVALID_ARGS
            ) from None
    name = args.get("assembly_name")
    if isinstance(name, str) and name.strip():
        return (await find_assembly(session, project_id, name)).id
    raise ToolException("Give assembly_entity_id or assembly_name", code=ToolErrorCode.INVALID_ARGS)


def build_derive_torque_tool(
    session_factory: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> Tool:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        pivot = args.get("pivot_mm")
        pivot_mm = (
            (float(pivot[0]), float(pivot[1]), float(pivot[2]))
            if isinstance(pivot, list) and len(pivot) == 3
            else None
        )
        async with session_factory() as session:
            try:
                assembly_id = await _resolve_assembly(session, project_id, args)
                payload = await derive_for_assembly(
                    session,
                    project_id,
                    assembly_id,
                    pivot_mm=pivot_mm,
                    masses=_masses(args.get("masses")),
                    safety_factor=float(args.get("safety_factor", DEFAULT_SAFETY_FACTOR)),
                )
            except APIError as exc:
                code = (
                    ToolErrorCode.NOT_FOUND
                    if exc.status_code == 404
                    else ToolErrorCode.INVALID_ARGS
                )
                raise ToolException(exc.message, code=code) from None
            except ValueError as exc:
                raise ToolException(str(exc), code=ToolErrorCode.INVALID_ARGS) from None
        payload.pop("assembly_entity_id", None)
        payload.pop("parts", None)
        return payload

    return InProcessTool(DERIVE_TORQUE, handler)
