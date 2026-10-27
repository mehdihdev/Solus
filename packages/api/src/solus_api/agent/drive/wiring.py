"""Assemble `drive.step` from the live session (sol-drive.md §4).

Present only when the requesting user's companion advertises all three INTERNAL
drive tools (allowlist `exposure: internal`) and a secret store exists for the
metered model call. The pieces are bound here, by Solus code, before any model
or ingested content is seen: the helper port (that user's companion only), the
gateway round (that user's identity: gates + debit), and the event recorder.
"""

import uuid
from typing import TYPE_CHECKING, Any, Final

from solus_api.agent.drive.executor import Budget, DriveExecutor, Progress, StepOutcome
from solus_api.agent.drive.port import BridgeDrivePort
from solus_api.agent.drive.tool import DriveStepTool
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.bridge.registry import BridgeSessionRegistry
    from solus_api.connectors.secrets import SecretStore
    from solus_api.orchestration.gateway import Completion

DRIVE_TOOLS: Final = ("drive.identify", "drive.capture", "drive.act")


def build_drive_step(
    *,
    bridge: "BridgeSessionRegistry",
    user_id: uuid.UUID,
    team_id: uuid.UUID,
    project_id: uuid.UUID,
    call_cap_bytes: int,
    session_factory: "async_sessionmaker[AsyncSession]",
    secret_store: "SecretStore",
    redis: Any,
    enqueue: Any,
    budget: Budget,
) -> DriveStepTool | None:
    from solus_api.bridge.service import fetch_artifact
    from solus_api.bridge.tool import BridgeTool

    session = bridge.get(user_id, team_id, project_id)
    if session is None:
        return None
    specs = {
        spec.descriptor.name: spec
        for spec in session.inventory
        if spec.internal and spec.server == "drive"
    }
    if not set(DRIVE_TOOLS) <= specs.keys():
        return None
    tools = {
        name: BridgeTool(
            descriptor=specs[name].descriptor,
            sessions=bridge,
            user_id=user_id,
            team_id=team_id,
            project_id=project_id,
            call_cap_bytes=call_cap_bytes,
        )
        for name in DRIVE_TOOLS
    }

    async def fetch(artifact_id: str) -> bytes:
        live = bridge.get(user_id, team_id, project_id)
        if live is None:
            raise ToolException("bridge offline", code=ToolErrorCode.UNAVAILABLE, retryable=True)
        return await fetch_artifact(live, artifact_id)

    port = BridgeDrivePort(
        identify=tools["drive.identify"],
        capture=tools["drive.capture"],
        act=tools["drive.act"],
        fetch=fetch,
    )

    async def model(
        *, system: str, messages: "Sequence[dict[str, Any]]", tools: "Sequence[dict[str, Any]]"
    ) -> "Completion":
        from solus_api.orchestration import gateway

        # One session per round: the gates read it and the debit commits on it.
        async with session_factory() as db:
            return await gateway.computer_use(
                system=system,
                messages=messages,
                tools=tools,
                secret_store=secret_store,
                user_id=user_id,
                session=db,
                redis=redis,
                enqueue=enqueue,
            )

    async def run_step(
        intent: str, drivable: frozenset[str], on_progress: "Callable[[Progress], None]"
    ) -> StepOutcome:
        executor = DriveExecutor(port, model, budget=budget, on_progress=on_progress)
        return await executor.run(intent, drivable)

    async def record(event_type: str, payload: dict[str, Any]) -> None:
        from solus_api.models import User
        from solus_api.services.events import emit_event

        async with session_factory() as db:
            user = await db.get(User, user_id)
            if user is None:
                return
            emit_event(
                db,
                user=user,
                event_type=event_type,
                team_id=team_id,
                project_id=project_id,
                payload=payload,
            )
            await db.commit()

    return DriveStepTool(run_step=run_step, record=record, budget=budget)
