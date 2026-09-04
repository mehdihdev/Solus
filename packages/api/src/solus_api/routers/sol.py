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

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator
from sqlalchemy.ext.asyncio import async_sessionmaker

from solus_api.agent.confirmations import ParkedCall, decide_confirmation, request_confirmation
from solus_api.agent.conversation import (
    ConversationService,
    serialize_conversation,
    serialize_turn,
)
from solus_api.agent.modes import ActionMode, build_mode_dispatch
from solus_api.agent.runtime import (
    MAX_TOOL_CALLS,
    AgentRunContext,
    TurnView,
    build_dispatch,
    build_sol_registry,
)
from solus_api.agent.stream import AgentEvent, AgentEventType, format_sse
from solus_api.agent.tools import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall
from solus_api.agent.tools.untrusted import redact_value
from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import (
    AgentRunnerDep,
    BridgeSessionsDep,
    ProjectCtx,
    RegistryDep,
    RequireVerified,
    SecretStoreDep,
    SessionDep,
    SessionMakerDep,
    SettingsDep,
    SolSystemsDep,
    require_role,
)
from solus_api.extensions.attribution import ExtensionAttribution
from solus_api.models import (
    Conversation,
    ConversationTurn,
    Role,
    ToolConfirmation,
    TurnRole,
    User,
    utcnow,
)
from solus_api.orchestration.config import load_orchestration_config
from solus_api.orchestration.cost import has_sufficient_credits
from solus_api.orchestration.gates import (
    FrequencyCapExceededError,
    InsufficientCreditsError,
    TrialCapReachedError,
    check_frequency_cap,
)
from solus_api.schemas import ConfirmationDecision, StrictModel
from solus_api.services.events import emit_event

logger = logging.getLogger("solus.sol")

# SEC-M6: policy blocks are caller-facing, not crashes — masked as "internal"
# they would read as an outage instead of a limit.
# Loaded once per process — static config, same source as the gateway's caps.
_ORCHESTRATION_LIMITS = load_orchestration_config().limits

_POLICY_BLOCKS: dict[type[BaseException], str] = {
    FrequencyCapExceededError: "frequency_cap",
    TrialCapReachedError: "trial_cap",
    InsufficientCreditsError: "insufficient_credits",
}


def _turn_failure_sse(exc: Exception, conversation_id: uuid.UUID) -> str:
    """One SSE error frame for a failed turn: a distinct, caller-facing code for
    a policy block; a generic, author-safe `internal` for everything else (§7)."""
    code = _POLICY_BLOCKS.get(type(exc))
    if code is not None:
        logger.info(
            "SOL turn blocked by %s for conversation %s", type(exc).__name__, conversation_id
        )
        return format_sse(
            AgentEvent.error(code, "SOL is rate-limited or out of credits for your team right now.")
        )
    logger.exception("SOL turn failed for conversation %s", conversation_id)
    return format_sse(AgentEvent.error("internal", "The SOL turn failed."))


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
#: Flat pre-flight estimate for one SOL turn.
#: ponytail: a turn is a variable number of model rounds, so this is a floor, not
#: a forecast. The real per-call enforcement is `assert_can_spend` inside the
#: gateway; this exists so a broke user gets a 402 instead of an error frame
#: mid-stream. Make it token-aware if turn cost varies enough to matter.
SOL_TURN_CREDIT_ESTIMATE = 1
_ABORT_MESSAGES = {
    "timeout": "The SOL turn timed out.",
    "loop_limit": "SOL stopped: too many tool calls in one turn.",
}


class ConversationCreate(StrictModel):
    title: str | None = Field(default=None, max_length=512)


class ConversationRename(StrictModel):
    """SOLUSDEV-233: the sidebar rename action — a non-blank title, trimmed."""

    title: str = Field(min_length=1, max_length=512)

    @field_validator("title")
    @classmethod
    def _trimmed_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class MessageCreate(StrictModel):
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    #: SOLX-01: how SOL may act on this message — guide (explain + point) or do
    #: (operate the tool). Guide is the safe default; per-action resolution
    #: inside a turn is the reasoning loop's refinement (SOL-02) on top of this
    #: request-level choice.
    action_mode: ActionMode = ActionMode.GUIDE


def _tool_descriptors(registry: ToolRegistry) -> list[dict[str, Any]]:
    return [d.model_dump(mode="json") for d in registry.list()]


@router.get("/tools")
async def list_tools(
    ctx: ProjectCtx,
    sessionmaker: SessionMakerDep,
    bridge_sessions: BridgeSessionsDep,
    settings: SettingsDep,
    secret_store: SecretStoreDep,
    connector_registry: RegistryDep,
    systems: SolSystemsDep,
) -> dict[str, Any]:
    """The tool set SOL may invoke for this project — the W0-04 descriptors the model
    reads. The set is fixed by Solus code, identical for every caller in the project."""
    registry = build_sol_registry(
        sessionmaker,
        ctx.project.id,
        bridge=bridge_sessions,
        user_id=ctx.user.id,
        team_id=ctx.team.id,
        bridge_call_cap_bytes=settings.bridge_tool_call_max_bytes,
        secret_store=secret_store,
        connectors=connector_registry,
        systems=systems,
    )
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


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: uuid.UUID, body: ConversationRename, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    """Rename an owned conversation (SOLUSDEV-233 sidebar context menu)."""
    require_role(ctx, Role.MEMBER)
    conversation = await _owned_or_404(ctx, session, conversation_id)
    conversation.title = body.title
    emit_event(
        session,
        user=ctx.user,
        event_type="sol.conversation.renamed",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        # Identifier only — titles are user-authored text (§7 event hygiene).
        payload={"conversation_id": str(conversation_id)},
    )
    await session.commit()
    await session.refresh(conversation)
    return envelope(serialize_conversation(conversation))


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
    action_mode: str,
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
                # Redacted before persistence, not just before model context:
                # this row is served back out of /turns to the browser, so a
                # secret-shaped tool value would otherwise sit in Postgres in the
                # clear AND render in the UI (SOLUS-RUN-01).
                attrs=redact_value({"call": call, "result": result}),
            )
        assistant = await SERVICE.append_turn(
            session,
            conversation_id=conversation_id,
            project_id=project_id,
            role=TurnRole.ASSISTANT,
            content=final_text,
            attrs={
                "sol_mode": sol_mode,
                "action_mode": action_mode,
                "tool_calls": len(tool_turns),
                "aborted": aborted,
            },
        )
        user = await session.get(User, user_id)
        if user is not None:
            # agent.tool_invoked (agent-tool contract §7): emitted by the loop
            # that holds the request context, one per dispatched call —
            # identifiers, mode, and outcome only, never argument values.
            for call, result in tool_turns:
                emit_event(
                    session,
                    user=user,
                    event_type="agent.tool_invoked",
                    team_id=team_id,
                    project_id=project_id,
                    payload={
                        "tool": call.get("tool"),
                        "call_id": call.get("call_id"),
                        "action_mode": action_mode,
                        "ok": result.get("ok"),
                    },
                )
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
    action_mode: str,
    parked: list[ParkedCall],
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
                    # SOLUS-ONS-A5: a call the gate parked streams straight after
                    # its result, so the client can show the concrete action and
                    # offer approve/reject inline.
                    while parked:
                        request = parked.pop(0)
                        yield format_sse(
                            AgentEvent.tool_confirmation(
                                confirmation_id=str(request.confirmation_id),
                                tool=request.tool,
                                args=request.args,
                                summary=request.summary,
                                preview=request.preview,
                            )
                        )
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
            action_mode=action_mode,
            tool_turns=tool_turns,
            final_text=final_text,
            aborted=aborted,
        )
        if aborted is not None:
            yield format_sse(AgentEvent.error(aborted, _ABORT_MESSAGES[aborted]))
        yield format_sse(
            AgentEvent.done(conversation_id=str(conversation_id), turn_id=str(done_turn_id))
        )
    except Exception as exc:
        yield _turn_failure_sse(exc, conversation_id)


@router.post("/conversations/{conversation_id}/messages")
async def post_message(
    request: Request,
    conversation_id: uuid.UUID,
    body: MessageCreate,
    ctx: ProjectCtx,
    session: SessionDep,
    sessionmaker: SessionMakerDep,
    systems: SolSystemsDep,
    runner: AgentRunnerDep,
    bridge_sessions: BridgeSessionsDep,
    settings: SettingsDep,
    secret_store: SecretStoreDep,
    connector_registry: RegistryDep,
    # SOLUSDEV-235 (extensions.md §9): `X-Solus-Extension` resolved as a
    # dependency, so an unauthorized header is 403 `scope_denied` BEFORE admission.
    attribution: ExtensionAttribution,
) -> StreamingResponse:
    """Append the user's message and stream SOL's reply as Server-Sent Events. The user
    turn is persisted (and the interaction logged) BEFORE streaming; the assistant/tool
    turns are persisted as the stream completes."""
    require_role(ctx, Role.MEMBER)
    content = body.content.strip()
    if not content:
        raise APIError(422, "validation_error", "Message content must not be blank")
    await _owned_or_404(ctx, session, conversation_id)

    # BUDGET GATE (SOLUS-RUN-01). `track_cost` needs NO wiring here — the gateway
    # fires it per model call from inside CompletionStream._finalize, which is the
    # point of that chokepoint. What belongs here is the PRE-FLIGHT, and its value
    # is a correct status code rather than enforcement: `assert_can_spend` already
    # runs per call inside the gateway, but it runs mid-stream, after the SSE
    # response has opened, so a user out of credits would get an error frame
    # instead of a 402 (CLAUDE.md §7; ADR-019/024).
    if not await has_sufficient_credits(ctx.user.id, SOL_TURN_CREDIT_ESTIMATE, session=session):
        raise APIError(402, "insufficient_credits", "Not enough credits for a SOL turn")
    # SEC-H3 (SOL-02 review): the context pull fires graph + pgvector work
    # BEFORE the first model round reaches the gateway's cap, so turn admission
    # is frequency-gated here too. This records the turn as one admission (the
    # gateway still records each model round — deliberate, both consume real
    # capacity); with no Redis deployed the cap fails open by policy and that
    # remains the flagged pre-GA infra blocker.
    try:
        await check_frequency_cap(
            ctx.user.id,
            redis=getattr(request.app.state, "redis", None),
            limits=_ORCHESTRATION_LIMITS,
            session=session,
        )
    except FrequencyCapExceededError as exc:
        raise APIError(429, "frequency_cap", "Too many SOL turns right now; slow down.") from exc
    prior = await SERVICE.history(
        session, conversation_id=conversation_id, project_id=ctx.project.id
    )
    history = tuple(TurnView(role=t.role.value, content=t.content) for t in prior)
    # Phase 4 H2: the transcript stores the ORIGINAL text with the attribution
    # on `attrs`; the Solus-authored framing exists only in model input.
    await SERVICE.append_turn(
        session,
        conversation_id=conversation_id,
        project_id=ctx.project.id,
        role=TurnRole.USER,
        content=content,
        attrs={"extension_slug": attribution.slug} if attribution else None,
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
    registry = build_sol_registry(
        sessionmaker,
        ctx.project.id,
        bridge=bridge_sessions,
        user_id=ctx.user.id,
        team_id=ctx.team.id,
        bridge_call_cap_bytes=settings.bridge_tool_call_max_bytes,
        secret_store=secret_store,
        connectors=connector_registry,
        systems=systems,
    )
    parked_calls: list[ParkedCall] = []

    async def park(call: ToolCall) -> ParkedCall | None:
        """SOLUS-ONS-A5: park a destructive call instead of running it.

        Its own session, because the turn streams long after this request's
        session is done with; committed immediately so the confirmation is
        approvable the moment the client sees the event.
        """
        async with sessionmaker() as parking:
            parked = await request_confirmation(
                parking,
                registry,
                call,
                project_id=ctx.project.id,
                team_id=ctx.team.id,
                user_id=ctx.user.id,
                conversation_id=conversation_id,
            )
            await parking.commit()
        # An invalid-args refusal carries no confirmation_id — nothing was
        # parked, so nothing streams a confirmation frame (SEC-H3).
        if parked is not None and parked.confirmation_id is not None:
            parked_calls.append(parked)
        return parked

    descriptors = tuple(registry.list())
    run_ctx = AgentRunContext(
        prompt=content,
        # Descriptors + a gated, MODE-WRAPPED dispatcher, never the registry
        # itself: a runner holds nothing it could invoke ungated (CLAUDE.md §7)
        # and, in guide mode, nothing that could mutate (SOLX-01).
        tools=descriptors,
        dispatch=build_mode_dispatch(body.action_mode, descriptors, build_dispatch(registry, park)),
        systems=systems,
        project_id=ctx.project.id,
        sol_mode=ctx.user.sol_mode,
        # SOLUSDEV-233: reaches the prompt only as a fenced data block.
        custom_instruction=ctx.user.sol_custom_instruction,
        action_mode=body.action_mode,
        history=history,
        # Model-call identity (ADR-018). Without these the gateway silently
        # skips every rate limit and every debit, so LlmRunner refuses outright.
        user_id=ctx.user.id,
        # A sessionmaker, not `session`: that one is closed by the time the SSE
        # body streams, which is why _persist_turn and park each open their own.
        sessionmaker=sessionmaker,
        secret_store=secret_store,
        # SEC-H2: the gateway's frequency cap and cost hook need these. Absent
        # from app.state today (Redis/ARQ not yet deployed for this app), the
        # cap FAILS OPEN inside the gateway — flagged in the completion report
        # as a pre-GA infrastructure blocker, not silently accepted.
        redis=getattr(request.app.state, "redis", None),
        enqueue=getattr(request.app.state, "enqueue", None),
        # Attribution only: the debit stays on `user_id` (ADR-018/024). The slug
        # frames the live message as an extension REQUEST (Phase 4 H2).
        extension_id=attribution.extension_id if attribution else None,
        extension_slug=attribution.slug if attribution else None,
    )
    stream = _run_and_persist(
        runner=runner,
        ctx=run_ctx,
        parked=parked_calls,
        sessionmaker=sessionmaker,
        conversation_id=conversation_id,
        project_id=ctx.project.id,
        team_id=ctx.team.id,
        user_id=ctx.user.id,
        sol_mode=ctx.user.sol_mode.value,
        action_mode=body.action_mode.value,
    )
    return StreamingResponse(stream, media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/confirmations/{confirmation_id}")
async def decide_tool_confirmation(
    request: Request,
    confirmation_id: uuid.UUID,
    body: ConfirmationDecision,
    ctx: ProjectCtx,
    session: SessionDep,
    sessionmaker: SessionMakerDep,
    bridge_sessions: BridgeSessionsDep,
    settings: SettingsDep,
    secret_store: SecretStoreDep,
    connector_registry: RegistryDep,
    systems: SolSystemsDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    """Approve or reject a destructive action SOL parked (SOLUS-ONS-A5).

    The turn that proposed it has long since ended — a one-shot SSE stream cannot
    block for a click — so the tool runs HERE, with the registry rebuilt under
    the deciding user's own scope and the ARGUMENTS TAKEN FROM THE STORED ROW.
    The request body carries a decision and nothing else, so what the user
    approved is what executes (CLAUDE.md §7).
    """
    require_role(ctx, Role.MEMBER)
    # SEC (SOLX-04 review): the decide endpoint is a destructive EXECUTION
    # point — REST source creation requires a verified account (ADR-009), so
    # executing the identical mutation from chat must too; and it gets the
    # same admission gate as the message route.
    try:
        await check_frequency_cap(
            ctx.user.id,
            redis=getattr(request.app.state, "redis", None),
            limits=_ORCHESTRATION_LIMITS,
            session=session,
        )
    except FrequencyCapExceededError as exc:
        raise APIError(429, "frequency_cap", "Too many decisions right now; slow down.") from exc
    registry = build_sol_registry(
        sessionmaker,
        ctx.project.id,
        bridge=bridge_sessions,
        user_id=ctx.user.id,
        team_id=ctx.team.id,
        bridge_call_cap_bytes=settings.bridge_tool_call_max_bytes,
        secret_store=secret_store,
        connectors=connector_registry,
        systems=systems,
    )
    result = await decide_confirmation(
        session,
        registry,
        confirmation_id,
        approve=body.decision == "approve",
        project_id=ctx.project.id,
        user_id=ctx.user.id,
    )
    row = await session.get(ToolConfirmation, confirmation_id)
    tool_name = row.tool if row is not None else None
    emit_event(
        session,
        user=ctx.user,
        event_type="sol.tool_confirmation_decided",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        # SEC-L3: abuse detection must answer "which destructive tool was
        # approved" from the event stream alone.
        payload={
            "decision": body.decision,
            "ok": result.ok,
            "confirmation_id": str(confirmation_id),
            "tool": tool_name,
        },
    )
    await session.commit()
    return envelope(result.model_dump(mode="json"))
