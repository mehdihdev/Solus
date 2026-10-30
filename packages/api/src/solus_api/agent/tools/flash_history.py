"""`firmware.flashed` history rows (SOLUSDEV-320 P5-T7, docs/api/solus.md §9).

The success twin of `agent/errors_filing.file_tool_error`: a `code.arduino_upload` call that
RAN and came back clean is one history row naming the entity the call named (only when it
is this project's — tool args are model-proposed). Meant for the same two sites, with the
same `executed` fact (the runner's post-dispatch hook and `confirmations.decide_confirmation`,
which is where a gated flash actually runs). Never raises.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.errors_filing import _entity_ref, _project_entity, logger, run_failure
from solus_api.agent.tools.shapes import ToolCall, ToolResult
from solus_api.models import Domain
from solus_api.services.activity import record_project_activity

#: The one companion tool whose clean run is a flash.
FLASH_TOOL: Final = "code.arduino_upload"


async def record_tool_history(
    sessionmaker: async_sessionmaker[AsyncSession] | Callable[[], Any],
    *,
    project_id: Any,
    user_id: Any,
    call: ToolCall,
    result: ToolResult,
    executed: bool,
) -> None:
    if not (executed and call.tool == FLASH_TOOL and result.ok and run_failure(result) is None):
        return
    try:
        async with sessionmaker() as session:
            try:
                entity_id = await _project_entity(session, project_id, _entity_ref(call.args))
                value = result.value if isinstance(result.value, dict) else {}
                port = value.get("port")
                await record_project_activity(
                    session,
                    project_id,
                    "firmware.flashed",
                    actor_id=user_id,
                    domain=Domain.CODE.value,
                    payload={"tool": call.tool, "port": port if isinstance(port, str) else None},
                    entity_ids=[entity_id] if entity_id is not None else [],
                )
                await session.commit()
            except Exception:
                await session.rollback()  # a shared session is handed back usable
                raise
    except Exception as exc:  # noqa: BLE001 — history must never fail the turn
        logger.warning(
            "flash history skipped call_id=%.128r project=%s reason=%s",
            call.call_id,
            project_id,
            type(exc).__name__,
        )
