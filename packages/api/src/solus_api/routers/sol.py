"""SOL chat — the agent's conversation surface (SOLUSDEV-135 / SOLUS-SYS-01).

PROPOSED route plan (docs/api has SOL as a later phase — flagged in the completion
report for human approval). Project-scoped and owner-private: every route resolves
through `ProjectCtx` (tenant isolation) and the conversation service's owner scope, so
one teammate's thread never leaks to another. Writes require MEMBER; reads need only a
resolvable project. The streaming turn (SSE) runs the reasoning loop behind the
`AgentRunner` seam and invokes tools through the per-request W0-04 registry.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy.ext.asyncio import async_sessionmaker

from solus_api.agent.conversation import (
    ConversationService,
    serialize_conversation,
    serialize_turn,
)
from solus_api.agent.runtime import (
    MAX_TOOL_CALLS,
    AgentRunContext,
    TurnView,
    build_sol_registry,
)
from solus_api.agent.stream import AgentEvent, AgentEventType, format_sse
from solus_api.agent.tools import ToolRegistry
from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import (
    AgentRunnerDep,
    ProjectCtx,
    SessionDep,
    SessionMakerDep,
    SolSystemsDep,
    require_role,
)
from solus_api.models import Conversation, ConversationTurn, Role, TurnRole, User, utcnow
from solus_api.schemas import StrictModel
from solus_api.services.events import emit_event

logger = logging.getLogger("solus.sol")

router = APIRouter(prefix="/api/v1/projects/{project_id}/sol")

SERVICE = ConversationService()
MAX_MESSAGE_CHARS = 8000
MAX_LIMIT = 200
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
# §7 loop/timeout guards enforced at the SEAM (in plumbing that outlives the swappable
# runner), not inside the runner: an upper bound on tool calls per turn and a wall-clock
# budget on the whole turn. The scaffold never trips these; they protect the transport
# once the model-backed runner (SOL-01/02) swaps in with no endpoint change.
SOL_TURN_TIMEOUT_SECONDS = 120.0
_ABORT_MESSAGES = {
    "timeout": "The SOL turn timed out.",
    "loop_limit": "SOL stopped: too many tool calls in one turn.",
}


class ConversationCreate(StrictModel):
    title: str | None = Field(default=None, max_length=512)


class MessageCreate(StrictModel):
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


def _tool_descriptors(registry: ToolRegistry) -> list[dict[str, Any]]:
    return [d.model_dump(mode="json") for d in registry.list()]


@router.get("/tools")
async def list_tools(ctx: ProjectCtx, sessionmaker: SessionMakerDep) -> dict[str, Any]:
    """The tool set SOL may invoke for this project — the W0-04 descriptors the model
    reads. The set is fixed by Solus code, identical for every caller in the project."""
    registry = build_sol_registry(sessionmaker, ctx.project.id)
    return envelope(_tool_descriptors(registry))


@router.post("/conversations", status_code=201)
async def create_conversation(
    body: ConversationCreate, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    conversation = await SERVICE.create(
        session,
        project_id=ctx.project.id,
        team_id=ctx.team.id,
        user_id=ctx.user.id,
        title=body.title,
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="sol.conversation.created",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"conversation_id": str(conversation.id)},
    )
    await session.commit()
    await session.refresh(conversation)
    return envelope(serialize_conversation(conversation))


@router.get("/conversations")
async def list_conversations(
    ctx: ProjectCtx,
    session: SessionDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
) -> dict[str, Any]:
    stmt = SERVICE.owned_query(project_id=ctx.project.id, user_id=ctx.user.id)
    if cursor:
        stmt = stmt.where(cursor_filter(Conversation.created_at, Conversation.id, cursor))
    stmt = stmt.order_by(Conversation.created_at.desc(), Conversation.id.desc()).limit(limit + 1)
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    return envelope([serialize_conversation(c) for c in visible], meta=meta)


async def _owned_or_404(
    ctx: ProjectCtx, session: SessionDep, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await SERVICE.get_owned(
        session, conversation_id=conversation_id, project_id=ctx.project.id, user_id=ctx.user.id
    )
    if conversation is None:
        raise APIError(404, "not_found", "Conversation not found")
    return conversation


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    conversation = await _owned_or_404(ctx, session, conversation_id)
    return envelope(serialize_conversation(conversation))


@router.get("/conversations/{conversation_id}/turns")
async def list_turns(
    conversation_id: uuid.UUID,
    ctx: ProjectCtx,
    session: SessionDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 100,
) -> dict[str, Any]:
    await _owned_or_404(ctx, session, conversation_id)
    stmt = SERVICE.turns_query(
        conversation_id=conversation_id, project_id=ctx.project.id, newest_first=True
    )
    if cursor:
        stmt = stmt.where(cursor_filter(ConversationTurn.created_at, ConversationTurn.id, cursor))
    stmt = stmt.limit(limit + 1)
    rows = list((await session.scalars(stmt)).all())
    visible, meta = page_meta(rows, limit)
    return envelope([serialize_turn(t) for t in visible], meta=meta)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep
) -> Response:
    require_role(ctx, Role.MEMBER)
    conversation = await _owned_or_404(ctx, session, conversation_id)
    conversation.deleted_at = utcnow()
    await session.commit()
    return Response(status_code=204)


def _tool_turn_summary(call: dict[str, Any], result: dict[str, Any]) -> str:
    outcome = "ok" if result.get("ok") else (result.get("error") or {}).get("code", "error")
    return f"{call.get('tool', 'tool')} → {outcome}"


async def _persist_turn(
    *,
    sessionmaker: async_sessionmaker[Any],
    conversation_id: uuid.UUID,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    sol_mode: str,
    tool_turns: list[tuple[dict[str, Any], dict[str, Any]]],
    final_text: str,
    aborted: str | None,
) -> uuid.UUID:
    """Persist the completed turn (tool turns + the assistant turn) in a FRESH session and
    log the interaction. Returns the assistant turn id for the `done` marker."""
    async with sessionmaker() as session:
        for call, result in tool_turns:
            await SERVICE.append_turn(
                session,
                conversation_id=conversation_id,
                project_id=project_id,
                role=TurnRole.TOOL,
                content=_tool_turn_summary(call, result),
                attrs={"call": call, "result": result},
            )
        assistant = await SERVICE.append_turn(
            session,
            conversation_id=conversation_id,
            project_id=project_id,
            role=TurnRole.ASSISTANT,
            content=final_text,
            attrs={"sol_mode": sol_mode, "tool_calls": len(tool_turns), "aborted": aborted},
        )
        user = await session.get(User, user_id)
        if user is not None:
            emit_event(
                session,
                user=user,
                event_type="sol.turn.completed",
                team_id=team_id,
                project_id=project_id,
                payload={
                    "conversation_id": str(conversation_id),
                    "tool_calls": len(tool_turns),
                    "aborted": aborted,
                },
            )
        await session.commit()
        return assistant.id


async def _run_and_persist(
    *,
    runner: AgentRunnerDep,
    ctx: AgentRunContext,
    sessionmaker: async_sessionmaker[Any],
    conversation_id: uuid.UUID,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    sol_mode: str,
) -> AsyncIterator[str]:
    """Stream the runner's events and, once the turn completes, persist the tool and
    assistant turns in a FRESH session (the request session is gone by the time the
    response body streams). The turn is bounded at the seam by a tool-call loop guard and
    a wall-clock timeout (§7). Any failure is logged server-side and surfaced only as a
    generic, author-safe `error` event — never a traceback (§7)."""
    pending: dict[str, dict[str, Any]] = {}
    tool_turns: list[tuple[dict[str, Any], dict[str, Any]]] = []
    final_text = ""
    tool_calls = 0
    aborted: str | None = None
    try:
        try:
            async with asyncio.timeout(SOL_TURN_TIMEOUT_SECONDS):
                async for event in runner.run(ctx):
                    if event.type is AgentEventType.TOOL_CALL:
                        tool_calls += 1
                        # Loop guard enforced HERE, independent of the runner: a runaway
                        # (real, model-driven) runner is cut off by the plumbing, not by
                        # its own restraint.
                        if tool_calls > MAX_TOOL_CALLS:
                            aborted = "loop_limit"
                            break
                        pending[event.data["call_id"]] = event.data
                    elif event.type is AgentEventType.TOOL_RESULT:
                        tool_turns.append((pending.get(event.data["call_id"], {}), event.data))
                    elif event.type is AgentEventType.MESSAGE:
                        final_text = event.data["content"]
                    yield format_sse(event)
        except TimeoutError:
            aborted = "timeout"

        # Persist whatever completed — for a clean turn OR a bounded abort (a truncated
        # transcript is still worth keeping). A hard failure below falls to the outer except.
        done_turn_id = await _persist_turn(
            sessionmaker=sessionmaker,
            conversation_id=conversation_id,
            project_id=project_id,
            team_id=team_id,
            user_id=user_id,
            sol_mode=sol_mode,
            tool_turns=tool_turns,
            final_text=final_text,
            aborted=aborted,
        )
        if aborted is not None:
            yield format_sse(AgentEvent.error(aborted, _ABORT_MESSAGES[aborted]))
        yield format_sse(
            AgentEvent.done(conversation_id=str(conversation_id), turn_id=str(done_turn_id))
        )
    except Exception:
        logger.exception("SOL turn failed for conversation %s", conversation_id)
        yield format_sse(AgentEvent.error("internal", "The SOL turn failed."))


@router.post("/conversations/{conversation_id}/messages")
async def post_message(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    ctx: ProjectCtx,
    session: SessionDep,
    sessionmaker: SessionMakerDep,
    systems: SolSystemsDep,
    runner: AgentRunnerDep,
) -> StreamingResponse:
    """Append the user's message and stream SOL's reply as Server-Sent Events. The user
    turn is persisted (and the interaction logged) BEFORE streaming; the assistant/tool
    turns are persisted as the stream completes."""
    require_role(ctx, Role.MEMBER)
    content = body.content.strip()
    if not content:
        raise APIError(422, "validation_error", "Message content must not be blank")
    await _owned_or_404(ctx, session, conversation_id)

    # BUDGET GATE (MO-01 seam): once a model-backed runner is wired, a pre-flight
    # `orchestration.cost.has_sufficient_credits(ctx.user.id, estimate, session=session)`
    # gate goes HERE, and `track_cost(...)` runs after the runner reports usage. Both are
    # IMPLEMENTED (orchestration/cost.py) — MO-01 wires them at this seam, it does not
    # rebuild them. The ScaffoldRunner makes no paid call, so nothing is metered yet — but
    # the enforcement point must live here so the model spend path can never ship
    # unmetered (CLAUDE.md §7 rate/budget; ADR-019/024).
    prior = await SERVICE.history(
        session, conversation_id=conversation_id, project_id=ctx.project.id
    )
    history = tuple(TurnView(role=t.role.value, content=t.content) for t in prior)
    await SERVICE.append_turn(
        session,
        conversation_id=conversation_id,
        project_id=ctx.project.id,
        role=TurnRole.USER,
        content=content,
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="sol.message",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"conversation_id": str(conversation_id), "chars": len(content)},
    )
    await session.commit()

    # Scope is bound HERE, by Solus code, before the runner sees any user content (§7).
    registry = build_sol_registry(sessionmaker, ctx.project.id)
    run_ctx = AgentRunContext(
        prompt=content,
        registry=registry,
        systems=systems,
        project_id=ctx.project.id,
        sol_mode=ctx.user.sol_mode,
        history=history,
    )
    stream = _run_and_persist(
        runner=runner,
        ctx=run_ctx,
        sessionmaker=sessionmaker,
        conversation_id=conversation_id,
        project_id=ctx.project.id,
        team_id=ctx.team.id,
        user_id=ctx.user.id,
        sol_mode=ctx.user.sol_mode.value,
    )
    return StreamingResponse(stream, media_type="text/event-stream", headers=_SSE_HEADERS)
