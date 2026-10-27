"""Assemble `drive.step` from the live session (sol-drive.md §4).

Present only when the requesting user's companion advertises all three INTERNAL
drive tools (allowlist `exposure: internal`) and a secret store exists for the
metered model call. The pieces are bound here, by Solus code, before any model
or ingested content is seen: the helper port (that user's companion only), the
gateway round (that user's identity: gates + debit), and the event recorder.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Final

from solus_api.agent.drive.executor import Budget, DriveExecutor, Progress, StepOutcome
from solus_api.agent.drive.port import BridgeDrivePort
from solus_api.agent.drive.tool import DriveStepTool
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.agent.tools.shapes import ToolDescriptor
    from solus_api.bridge.registry import BridgeSessionRegistry
    from solus_api.connectors.secrets import SecretStore
    from solus_api.orchestration.gateway import Completion

DRIVE_TOOLS: Final = ("drive.identify", "drive.capture", "drive.act")

#: One drive step at a time per user: two loops would double the budget and act
#: on each other's stale captures. Keyed on the user alone — the companion's
#: instance id is client-supplied (bridge contract §3: never authorization).
# ponytail: process-local, like the in-memory bridge registry it sits beside; a
# Redis lease (SET NX + TTL) replaces it when the API goes multi-instance.
_ACTIVE: set[uuid.UUID] = set()


@asynccontextmanager
async def drive_lease(key: uuid.UUID) -> AsyncIterator[None]:
    if key in _ACTIVE:
        raise ToolException(
            "Another drive step of yours is already running; wait for it to finish.",
            code=ToolErrorCode.TOOL_ERROR,
        )
    _ACTIVE.add(key)
    try:
        yield
    finally:
        _ACTIVE.discard(key)


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
    port = bridge_drive_port(
        bridge,
        {name: specs[name].descriptor for name in DRIVE_TOOLS},
        user_id=user_id,
        team_id=team_id,
        project_id=project_id,
        call_cap_bytes=call_cap_bytes,
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

    return DriveStepTool(
        run_step=run_step, record=record, budget=budget, lease=lambda: drive_lease(user_id)
    )


def bridge_drive_port(
    bridge: "BridgeSessionRegistry",
    descriptors: "dict[str, ToolDescriptor]",
    *,
    user_id: uuid.UUID,
    team_id: uuid.UUID,
    project_id: uuid.UUID,
    call_cap_bytes: int,
) -> BridgeDrivePort:
    """The helper port for ONE scope: every call and every artifact pull goes
    to the requesting user's own session for this team and project, looked up
    by that exact scope each time (contract §3) — never another session."""
    from solus_api.bridge.service import fetch_artifact
    from solus_api.bridge.tool import BridgeTool

    tools = {
        name: BridgeTool(
            descriptor=descriptors[name],
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

    return BridgeDrivePort(
        identify=tools["drive.identify"],
        capture=tools["drive.capture"],
        act=tools["drive.act"],
        fetch=fetch,
    )
