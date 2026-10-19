"""Deciding a parked SOL action (SOLUS-ONS-A5) and reading its live output
(SOLUSDEV-317 §5.4), split out of `routers/sol.py`.

The turn that proposed an action has long since ended — a one-shot SSE stream
cannot block for a click — so the tool runs HERE, with the registry rebuilt
under the deciding user's own scope and the ARGUMENTS TAKEN FROM THE STORED ROW.
The request body carries a decision and nothing else, so what the user approved
is what executes (CLAUDE.md §7). After it runs, this module records the decision
turn the next model reads, the command facts (§5.6, basename-only) and the audit
event.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.command_gate import completion_events
from solus_api.agent.confirmations import command_outcome_text, decide_confirmation
from solus_api.agent.conversation import ConversationService
from solus_api.agent.tools.shapes import ToolResult
from solus_api.agent.tools.untrusted import call_display_paths, redact_value
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import (
    ProjectCtx,
    RequireVerified,
    SessionDep,
    SettingsDep,
    SolRegistryDep,
    require_role,
)
from solus_api.models import Role, Source, ToolConfirmation, TurnRole
from solus_api.orchestration.config import load_orchestration_config
from solus_api.orchestration.gates import FrequencyCapExceededError, check_frequency_cap
from solus_api.schemas import ConfirmationDecision
from solus_api.services.events import emit_event
from solus_api.services.onshape_write_sync import schedule_onshape_write_sync

router = APIRouter(prefix="/api/v1/projects/{project_id}/sol")

SERVICE = ConversationService()
_ORCHESTRATION_LIMITS = load_orchestration_config().limits
#: Call arguments a decision turn may keep: validated, call-bound display paths.
_DISPLAY_ARGS = frozenset({"path", "schematic_path"})

SyncEnqueue = Callable[[AsyncSession, Source], Awaitable[uuid.UUID]]


def sync_enqueuer(
    request: Request, background_tasks: BackgroundTasks, settings: SettingsDep, ctx: ProjectCtx
) -> SyncEnqueue:
    """The post-write graph sync enqueue, shared by the decide route and Build."""
    from solus_api.routers.sources import enqueue_sync

    async def enqueue_after_write(sync_session: AsyncSession, source: Source) -> uuid.UUID:
        return await enqueue_sync(
            sync_session,
            ctx,
            source,
            request,
            background_tasks,
            settings.model_copy(update={"sync_inline": False}),
            Response(),
        )

    return enqueue_after_write


def _decision_summary(decision: str, result: ToolResult, tool: str | None = None) -> str:
    """What the decision did, in the words the next turn's model reads.

    Deliberately distinguishes the three outcomes a person can produce from the
    one the gate produces: a rejection is not a failure, and a STALE refusal is
    not a rejection — it means the world moved and NOTHING was applied, which is
    the one the model most needs to understand before it tries again.
    """
    if result.ok:
        outcome = (
            command_outcome_text(result.value, tool=tool)
            if isinstance(result.value, dict)
            else None
        )
        if outcome is not None:
            return "approved by you" + outcome
        sync = result.value.get("graph_sync") if isinstance(result.value, dict) else None
        sync_note = ""
        if isinstance(sync, dict):
            sync_note = (
                "; graph sync queued"
                if sync.get("status") == "queued"
                else "; graph sync unavailable — retry source sync, not the CAD change"
            )
        return "approved by you and applied ok" + sync_note
    if decision != "approve":
        return "rejected by you; nothing was applied"
    code = result.error.code.value if result.error is not None else "error"
    return f"not applied ({code}) — ask again to see the current change"


@router.get("/confirmations/{confirmation_id}/output")
async def confirmation_output(
    confirmation_id: uuid.UUID,
    ctx: ProjectCtx,
    session: SessionDep,
    cursor: Annotated[int, Query(ge=0, le=256)] = 0,
) -> dict[str, Any]:
    from solus_api.agent.command_output import output_store

    owned = await session.scalar(
        select(ToolConfirmation.id).where(
            ToolConfirmation.id == confirmation_id,
            ToolConfirmation.project_id == ctx.project.id,
            ToolConfirmation.user_id == ctx.user.id,
        )
    )
    if owned is None:
        raise APIError(404, "not_found", "No such action.")
    return {"data": output_store.read((ctx.project.id, ctx.user.id, confirmation_id), cursor)}


async def _admit_decision(request: Request, ctx: ProjectCtx, session: AsyncSession) -> None:
    """SEC (SOLX-04 review): the decide endpoint is a destructive EXECUTION point
    — REST source creation requires a verified account (ADR-009), so executing
    the identical mutation from chat must too; and it gets the same admission
    gate as the message route."""
    require_role(ctx, Role.MEMBER)
    try:
        await check_frequency_cap(
            ctx.user.id,
            redis=getattr(request.app.state, "redis", None),
            limits=_ORCHESTRATION_LIMITS,
            session=session,
        )
    except FrequencyCapExceededError as exc:
        raise APIError(429, "frequency_cap", "Too many decisions right now; slow down.") from exc


async def _decided_row(
    session: AsyncSession, ctx: ProjectCtx, confirmation_id: uuid.UUID
) -> Row[Any] | None:
    """SCOPED, like `decide_confirmation`'s own read. `session.get` by id alone
    would let another project's confirmation name a tool in this project's event
    stream — the same no-existence-oracle rule, applied to the audit path."""
    return (
        await session.execute(
            select(
                ToolConfirmation.tool, ToolConfirmation.conversation_id, ToolConfirmation.args
            ).where(
                ToolConfirmation.id == confirmation_id,
                ToolConfirmation.project_id == ctx.project.id,
                ToolConfirmation.user_id == ctx.user.id,
            )
        )
    ).first()


async def _with_graph_sync(
    request: Request, enqueue: SyncEnqueue, ctx: ProjectCtx, decided: Row[Any], result: ToolResult
) -> ToolResult:
    graph_sync = await schedule_onshape_write_sync(
        request.app.state.sessionmaker,
        project_id=ctx.project.id,
        team_id=ctx.team.id,
        tool_name=decided.tool,
        args=decided.args,
        store=getattr(request.app.state, "integration_store", None),
        enqueue=enqueue,
    )
    if graph_sync is not None and isinstance(result.value, dict):
        return result.model_copy(update={"value": {**result.value, "graph_sync": graph_sync}})
    return result


async def _record_decision_turn(
    session: AsyncSession,
    ctx: ProjectCtx,
    confirmation_id: uuid.UUID,
    decided: Row[Any],
    decision: str,
    result: ToolResult,
) -> None:
    """THE OTHER HALF OF THE HISTORY FIX. The turn that proposed this recorded it
    as "parked, awaiting your approval" and then ended. Without a second turn
    recording what the decision actually did, the transcript stops at "parked"
    forever — so the next message shows SOL a change it proposed, never learned
    the fate of, and will helpfully propose again."""
    paths = call_display_paths(decided.tool, decided.args)
    await SERVICE.append_turn(
        session,
        conversation_id=decided.conversation_id,
        project_id=ctx.project.id,
        role=TurnRole.TOOL,
        content=f"{decided.tool} → {_decision_summary(decision, result, decided.tool)}",
        attrs=redact_value(
            {
                "confirmation_id": str(confirmation_id),
                "call": {
                    "tool": decided.tool,
                    "args": {
                        key: value
                        for key, value in decided.args.items()
                        if key in _DISPLAY_ARGS and isinstance(value, str) and value in paths
                    },
                },
                "result": result.model_dump(mode="json"),
            },
            allowed_paths=paths,
        ),
    )


def _emit_decision_events(
    session: AsyncSession,
    ctx: ProjectCtx,
    confirmation_id: uuid.UUID,
    decided: Row[Any] | None,
    decision: str,
    result: ToolResult,
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    if decision == "approve" and result.ok and decided is not None:
        # SOLUSDEV-317 §5.6: basename-only command facts, never the argv.
        value = result.value if isinstance(result.value, dict) else {}
        events.extend(completion_events(decided.tool, dict(decided.args), value))
    # SEC-L3: abuse detection must answer "which destructive tool was approved"
    # from the event stream alone.
    events.append(
        (
            "sol.tool_confirmation_decided",
            {
                "decision": decision,
                "ok": result.ok,
                "confirmation_id": str(confirmation_id),
                "tool": decided.tool if decided is not None else None,
            },
        )
    )
    for event_type, payload in events:
        emit_event(
            session,
            user=ctx.user,
            event_type=event_type,
            team_id=ctx.team.id,
            project_id=ctx.project.id,
            payload=payload,
        )


@router.post("/confirmations/{confirmation_id}")
async def decide_tool_confirmation(
    request: Request,
    background_tasks: BackgroundTasks,
    confirmation_id: uuid.UUID,
    body: ConfirmationDecision,
    ctx: ProjectCtx,
    session: SessionDep,
    registry: SolRegistryDep,
    settings: SettingsDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    """Approve or reject a destructive action SOL parked (SOLUS-ONS-A5)."""
    await _admit_decision(request, ctx, session)
    result = await decide_confirmation(
        session,
        registry,
        confirmation_id,
        approve=body.decision == "approve",
        project_id=ctx.project.id,
        user_id=ctx.user.id,
    )
    decided = await _decided_row(session, ctx, confirmation_id)
    if body.decision == "approve" and result.ok and decided is not None:
        enqueue = sync_enqueuer(request, background_tasks, settings, ctx)
        result = await _with_graph_sync(request, enqueue, ctx, decided, result)
    if decided is not None and decided.conversation_id is not None:
        await _record_decision_turn(session, ctx, confirmation_id, decided, body.decision, result)
    _emit_decision_events(session, ctx, confirmation_id, decided, body.decision, result)
    await session.commit()
    return envelope(result.model_dump(mode="json"))
