"""`code.ros2_nodes` / `code.ros2_topics` raise what the graph already holds (SOLUSDEV-321 P6,
R131; docs/api/code-command-execution.md §12).

`live_graph_tool` wraps the two bridge tools, keyed on the composed name AND the unconfirmed
gate, both every time (the `link_environment` rule). The companion's answer reaches the model
unchanged. Then, never failing the call, the wrapper re-applies the ROS name grammar
(`ros_edges.live_names`) and raises this project's standing inferred edges through
`ros_edges.confirm_live` under the project lock; a listed name no edge carries writes nothing.
The event `ros.live_confirmed {tool, seen, bumped}` carries counts only.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.agent.tools.tool import Tool
from solus_api.graph.inference import ros_edges
from solus_api.models import User
from solus_api.services.events import emit_event
from solus_api.services.solus_graph import lock_project

logger = logging.getLogger("solus.agent.tools.ros_live")

#: The composed bridge name → (the answer's list key, the evidence `ref`).
LIVE_TOOLS: Final = {
    "code.ros2_nodes": ("nodes", "ros2 node list"),
    "code.ros2_topics": ("topics", "ros2 topic list"),
}
EVENT: Final = "ros.live_confirmed"


def live_graph_tool(
    tool: Tool,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    team_id: uuid.UUID,
) -> Tool:
    """`tool` itself unless it is one of the two live reads AND unconfirmed."""
    if tool.descriptor.name not in LIVE_TOOLS or tool.descriptor.requires_confirmation:
        return tool
    return LiveGraphTool(tool, sessions, project_id, user_id=user_id, team_id=team_id)


class LiveGraphTool:
    """A live ROS read whose answer also raises the standing edges it names."""

    def __init__(
        self,
        tool: Tool,
        sessions: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        team_id: uuid.UUID,
    ) -> None:
        self._tool = tool
        self._sessions = sessions
        self._project_id = project_id
        self._user_id = user_id
        self._team_id = team_id

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._tool.descriptor

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        answer = await self._tool.invoke(args)
        try:
            await self._raise_standing(answer)
        except Exception as exc:  # noqa: BLE001 — the answer stands whatever the raise does
            logger.warning(
                "ros live confirmation failed tool=%s project=%s (%s)",
                self.descriptor.name,
                self._project_id,
                type(exc).__name__,
            )
        return answer

    async def _raise_standing(self, answer: dict[str, Any]) -> None:
        key, ref = LIVE_TOOLS[self.descriptor.name]
        listed = answer.get(key) if answer.get("ok") is True else None
        if not isinstance(listed, list) or not listed:
            return
        nodes, topics = _listed_names(key, listed)
        async with self._sessions() as session:
            await lock_project(session, self._project_id)
            bumped = await ros_edges.confirm_live(
                session, self._project_id, ref=ref, nodes=nodes, topics=topics
            )
            user = await session.get(User, self._user_id)
            if user is not None:
                emit_event(
                    session,
                    user=user,
                    event_type=EVENT,
                    team_id=self._team_id,
                    project_id=self._project_id,
                    payload={
                        "tool": self.descriptor.name,
                        "seen": len(nodes) + len(topics),
                        "bumped": bumped,
                    },
                )
            await session.commit()


def _listed_names(key: str, listed: list[Any]) -> tuple[list[str], dict[str, str | None]]:
    """One listing's grammar-checked names: the nodes, or each topic with its live type."""
    if key == "nodes":
        return ros_edges.live_names(listed), {}
    typed = {
        item["name"]: item.get("type")
        for item in listed
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    kept = set(ros_edges.live_names(typed))
    return [], {
        name: kind if isinstance(kind, str) else None
        for name, kind in typed.items()
        if name in kept
    }
