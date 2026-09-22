"""Per-turn reconciliation bookkeeping, never a source of tool authority."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import BackgroundTasks, Response

from solus_api.agent.tools.shapes import ToolCall, ToolResult

logger = logging.getLogger("solus.onshape_turn_sync")
_FALLBACK_TASKS: set[asyncio.Task[Any]] = set()


def _fallback_done(task: asyncio.Task[Any]) -> None:
    _FALLBACK_TASKS.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("Deferred graph reconciliation task failed")


def launch_background(background: BackgroundTasks) -> None:
    if background.tasks:
        task = asyncio.create_task(background())
        _FALLBACK_TASKS.add(task)
        task.add_done_callback(_fallback_done)


class OnshapeTurnSync:
    def __init__(
        self, maker: Any, *, project_id: uuid.UUID, team_id: uuid.UUID, store: Any, enqueue: Any
    ) -> None:
        self.maker, self.project_id, self.team_id = maker, project_id, team_id
        self.store, self.enqueue = store, enqueue
        self.turn_id = uuid.uuid4()
        self.deadline = datetime.now(UTC) + timedelta(seconds=300)
        self._calls: dict[str, uuid.UUID] = {}
        self._released: set[uuid.UUID] = set()

    async def start(self, call: ToolCall) -> None:
        from solus_api.services.onshape_write_sync import hold_onshape_write_sync

        source = await hold_onshape_write_sync(
            self.maker,
            project_id=self.project_id,
            team_id=self.team_id,
            tool_name=call.tool,
            args=call.args,
            store=self.store,
            turn_id=self.turn_id,
            turn_deadline=self.deadline,
        )
        if source is not None:
            self._calls[call.call_id] = source

    def outcome(self, call: ToolCall, result: ToolResult) -> ToolResult:
        if result.ok and call.call_id in self._calls and isinstance(result.value, dict):
            return result.model_copy(
                update={
                    "value": {
                        **result.value,
                        "graph_sync": {
                            "status": "deferred",
                            "message": "Graph reconciliation will run after this turn finishes.",
                        },
                    }
                }
            )
        return result

    async def flush(self) -> None:
        from solus_api.services.onshape_write_sync import release_onshape_write_sync

        for source in set(self._calls.values()) - self._released:
            self._released.add(source)
            try:
                await release_onshape_write_sync(
                    self.maker,
                    project_id=self.project_id,
                    team_id=self.team_id,
                    source_id=source,
                    turn_id=self.turn_id,
                    enqueue=self.enqueue,
                )
            except Exception:
                logger.warning("Turn reconciliation release failed; durable expiry will recover")


def create_turn_sync(request: Any, settings: Any, ctx: Any, maker: Any) -> OnshapeTurnSync:
    async def enqueue(session: Any, source: Any) -> uuid.UUID:
        from solus_api.routers.sources import enqueue_sync

        background = BackgroundTasks()
        job = await enqueue_sync(
            session,
            ctx,
            source,
            request,
            background,
            settings.model_copy(update={"sync_inline": False}),
            Response(),
        )
        launch_background(background)
        return job

    return OnshapeTurnSync(
        maker,
        project_id=ctx.project.id,
        team_id=ctx.team.id,
        store=getattr(request.app.state, "integration_store", None),
        enqueue=enqueue,
    )
