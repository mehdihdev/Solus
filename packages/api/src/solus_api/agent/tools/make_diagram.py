"""`make_diagram` — SOL draws a wiring / plug-in diagram of part of the graph
(SOLUSDEV-252 S5, docs/architecture/sol-artifacts.md).

Deliberately NOT confirmation-gated, like `add_solus_entry`: its only write is one
TTL artifact row + its bytes in the project's own store — a hand-off buffer the
sweep reclaims unless the person files it. None of CLAUDE.md §7's destructive
classes (flash, deploy, mutate an external system, delete graph data) is touched,
and nothing it produces re-enters a prompt as instructions: the model gets back ids
and a count of unknown pins, never the SVG.

Scope is bound at construction by Solus code (project, user, store); the model picks
only WHICH entities to focus and a title. Entities outside the project resolve to
nothing (`load_neighborhood` is project-scoped) → NOT_FOUND, no existence oracle.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.diagram.build import build_wiring_diagram
from solus_api.agent.diagram.svg import render_svg
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, Tool, ToolException
from solus_api.graph.neighborhood import load_neighborhood
from solus_api.hardware.config import HardwareConfig
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.store import ROBOT_KIND, read_entity_config
from solus_api.models import GraphEntity
from solus_api.services.artifacts import create_artifact
from solus_api.storage import ArtifactStore

MAX_FOCUS = 8
MAX_TITLE = 120
#: Bounded reads: a wiring view walks part → net → part (2 hops); plug-in is 1 hop.
_DEPTH = {"wiring": 2, "plug_in": 1}
_MAX_ENTITIES = 120

MAKE_DIAGRAM_DESCRIPTOR = ToolDescriptor(
    name="make_diagram",
    description=(
        "Draw a wiring diagram (kind=wiring: nets, buses and pins between parts) or a "
        "plug-in diagram (kind=plug_in: what plugs into what, one hop) around up to "
        f"{MAX_FOCUS} graph entities, from what the graph and the robot's hardware config "
        "record. Pins the graph does not name are drawn as dashed 'unknown pin' stubs and "
        "listed in unknown_pins — never guess them. Returns an artifact reference the "
        "person can view and file; do not describe the picture from memory."
    ),
    params={
        "type": "object",
        "properties": {
            "focus_entity_ids": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "minItems": 1,
                "maxItems": MAX_FOCUS,
            },
            "kind": {"type": "string", "enum": list(_DEPTH), "default": "wiring"},
            "title": {"type": "string", "minLength": 1, "maxLength": MAX_TITLE},
        },
        "required": ["focus_entity_ids"],
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string", "format": "uuid"},
            "uri": {"type": "string"},
            "media_type": {"type": "string"},
            "title": {"type": "string"},
            "unknown_pins": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"},
        },
        "required": ["artifact_id", "uri", "media_type", "title", "unknown_pins", "summary"],
        "additionalProperties": False,
    },
)


def _focus_ids(raw: object) -> list[uuid.UUID]:
    try:
        return [uuid.UUID(str(v)) for v in (raw if isinstance(raw, list) else [])]
    except ValueError:
        raise ToolException(
            "focus_entity_ids must be uuids", code=ToolErrorCode.INVALID_ARGS
        ) from None


async def _robot_config(
    session: AsyncSession, project_id: uuid.UUID, entities: list[GraphEntity]
) -> HardwareConfig | None:
    """The config of the first robot in view — its root, or a part's `attrs.robot_id`.
    Read-only: an absent config is None, never created here."""
    robot_ids = [e.id for e in entities if e.kind == ROBOT_KIND]
    robot_ids += [
        rid for e in entities if (rid := _uuid_or_none((e.attrs or {}).get("robot_id"))) is not None
    ]
    for rid in dict.fromkeys(robot_ids):
        root = await session.get(GraphEntity, rid)
        if (
            root is None
            or root.project_id != project_id
            or root.deleted_at is not None
            or root.kind != ROBOT_KIND
            or root.origin != "manual"
            or root.source_id is not None
        ):
            continue
        entry, _ = await read_entity_config(session, project_id, rid)
        if entry is not None:
            return await resolve_runtime_config(session, project_id, rid)

    return None


def _uuid_or_none(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def build_make_diagram_tool(
    session_factory: async_sessionmaker[AsyncSession],
    store: ArtifactStore,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Tool:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        focus = _focus_ids(args["focus_entity_ids"])
        kind = str(args.get("kind") or "wiring")
        title = " ".join(str(args.get("title") or f"{kind.replace('_', '-')} diagram").split())
        async with session_factory() as session:
            hood = await load_neighborhood(
                session, project_id, roots=focus, depth=_DEPTH[kind], max_entities=_MAX_ENTITIES
            )
            if not any(e.id in focus for e in hood.entities):
                raise ToolException("No such entity in this project", code=ToolErrorCode.NOT_FOUND)
            try:
                config = await _robot_config(session, project_id, hood.entities)
                diagram = build_wiring_diagram(hood, config, focus)
                svg = render_svg(diagram, title=title[:MAX_TITLE])
            except Exception:
                raise ToolException(
                    "The current graph could not be rendered as a diagram",
                    code=ToolErrorCode.TOOL_ERROR,
                ) from None
            artifact = await create_artifact(
                session,
                store,
                project_id=project_id,
                created_by=user_id,
                data=svg.encode(),
                media_type="image/svg+xml",
                source_tool=MAKE_DIAGRAM_DESCRIPTOR.name,
                # ponytail: the handler has no call id (Tool.invoke gets args only);
                # thread it through when a consumer needs the correlation.
                tool_call_id=None,
            )
            await session.commit()
        unknown = diagram.unknown_pins
        return {
            "artifact_id": str(artifact.id),
            "uri": artifact.uri,
            "media_type": artifact.media_type,
            "title": title,
            "unknown_pins": unknown,
            "summary": (
                f"{kind} diagram: {len(diagram.nodes)} nodes, {len(diagram.wires)} wires, "
                f"{len(unknown)} unknown pin(s)."
            ),
        }

    return InProcessTool(MAKE_DIAGRAM_DESCRIPTOR, handler)


def register_diagram_tools(
    registry: ToolRegistry,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    store: ArtifactStore,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Wire the diagram tools into a per-request registry (called by build_sol_registry)."""
    registry.register(build_make_diagram_tool(session_factory, store, project_id, user_id))
