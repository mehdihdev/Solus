"""SOL chat — the agent's conversation surface (SOLUSDEV-135 / SOLUS-SYS-01).

PROPOSED route plan (docs/api has SOL as a later phase — flagged in the completion
report for human approval). Project-scoped and owner-private: every route resolves
through `ProjectCtx` (tenant isolation) and the conversation service's owner scope, so
one teammate's thread never leaks to another. Writes require MEMBER; reads need only a
resolvable project. The streaming turn (SSE) runs the reasoning loop behind the
`AgentRunner` seam and invokes tools through the per-request W0-04 registry.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import Field, StrictBool, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.command_gate import completion_events
from solus_api.agent.confirmations import (
    ParkedCall,
    _feed_back_outcome,
    request_confirmation,
)
from solus_api.agent.conversation import (
    ConversationService,
    serialize_conversation,
    serialize_turn,
)
from solus_api.agent.execution_policy import BuildExecutionPolicy
from solus_api.agent.history_evidence import enrich_history
from solus_api.agent.modes import ActionMode, build_mode_dispatch
from solus_api.agent.onshape_turn_sync import OnshapeTurnSync, create_turn_sync
from solus_api.agent.preferences import EngineeringPreferences
from solus_api.agent.reason import MAX_ANCHORS
from solus_api.agent.runtime import (
    AgentRunContext,
    TurnView,
    build_dispatch,
)
from solus_api.agent.screen import (
    MAX_DIMENSION,
    ScreenshotBlock,
    ScreenshotError,
    ScreenshotSource,
    decode_screenshot,
)
from solus_api.agent.stream import AgentEvent, AgentEventType, format_sse
from solus_api.agent.tools import ToolRegistry
from solus_api.agent.tools.knowledge import load_knowledge_notes, with_knowledge_notes
from solus_api.agent.tools.shapes import ToolCall, ToolError, ToolErrorCode, ToolResult
from solus_api.agent.tools.untrusted import call_display_paths, redact_value
from solus_api.agent.turn_limits import turn_limits
from solus_api.core.errors import APIError
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import (
    AgentRunnerDep,
    ProjectCtx,
    SecretStoreDep,
    SessionDep,
    SessionMakerDep,
    SettingsDep,
    SolRegistryDep,
    SolSystemsDep,
    require_role,
)
from solus_api.extensions.attribution import ExtensionAttribution
from solus_api.models import (
    ConfirmationStatus,
    Conversation,
    ConversationTurn,
    GraphEntity,
    Role,
    Source,
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
from solus_api.orchestration.providers import ProviderTransientError
from solus_api.routers.sol_confirmations import sync_enqueuer
from solus_api.routers.sol_resume import (
    ResumeTicket,
    check_resume,
    claim_resume,
    resume_prompt,
)
from solus_api.schemas import StrictModel
from solus_api.services.events import emit_event
from solus_api.services.onshape_write_sync import schedule_onshape_write_sync

logger = logging.getLogger("solus.sol")

# SEC-M6: policy blocks are caller-facing, not crashes — masked as "internal"
# they would read as an outage instead of a limit.
# Loaded once per process — static config, same source as the gateway's caps.
_ORCHESTRATION_LIMITS = load_orchestration_config().limits

_LIMIT_MESSAGE = "SOL is rate-limited or out of credits for your team right now."
#: SOLUSDEV-252, live: a turn that parked a gated call then hit the account's own
#: 10k-TPM window ("Please try again in 39.456s") reported `internal` — an outage,
#: as far as the person could tell, from a limit no retry inside the request can
#: outlast. Both MESSAGES here are Solus-authored: the upstream text names the
#: model, the organization and the token counts, and none of that is caller-facing
#: (§7 / ADR-026).
_POLICY_BLOCKS: dict[type[BaseException], tuple[str, str]] = {
    FrequencyCapExceededError: ("frequency_cap", _LIMIT_MESSAGE),
    TrialCapReachedError: ("trial_cap", _LIMIT_MESSAGE),
    InsufficientCreditsError: ("insufficient_credits", _LIMIT_MESSAGE),
    ProviderTransientError: (
        "provider_unavailable",
        "The reasoning service is busy right now. Try that again in a moment.",
    ),
}


def _turn_failure_sse(exc: Exception, conversation_id: uuid.UUID) -> str:
    """One SSE error frame for a failed turn: a distinct, caller-facing code for
    a policy block; a generic, author-safe `internal` for everything else (§7)."""
    block = _POLICY_BLOCKS.get(type(exc))
    if block is not None:
        code, message = block
        # A budget/rate policy is expected traffic; a provider that will not answer
        # is an OPERATOR's problem, and the reason (which model, rate-limited vs
        # overloaded) only exists in the exception. Logging it at info with just a
        # class name is how a run of failed turns looks like nothing at all.
        if code == "provider_unavailable":
            logger.warning("SOL turn failed for conversation %s: %s", conversation_id, exc)
        else:
            logger.info(
                "SOL turn blocked by %s for conversation %s", type(exc).__name__, conversation_id
            )
        return format_sse(AgentEvent.error(code, message))
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
#: Flat pre-flight estimate for one SOL turn.
#: ponytail: a turn is a variable number of model rounds, so this is a floor, not
#: a forecast. The real per-call enforcement is `assert_can_spend` inside the
#: gateway; this exists so a broke user gets a 402 instead of an error frame
#: mid-stream. Make it token-aware if turn cost varies enough to matter.
SOL_TURN_CREDIT_ESTIMATE = 1
#: S3 review L4: a screenshot adds the VISUAL_LOG extractor call plus image
#: tokens on the live turn — a broke user learns that up front, not mid-stream.
SCREENSHOT_EXTRA_CREDITS = 2
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


class ScreenshotIn(StrictModel):
    """SOLUSDEV-252 S3 (sol-window.md §8): one screenshot on this turn.

    `data` is deliberately NOT length-capped here: a pydantic failure echoes the
    offending input back in the 422 body, and this field is megabytes of pixels.
    `agent/screen.py` caps it (3.5 MiB encoded, 2.5 MiB decoded) and sniffs the
    magic bytes; the route turns its reason into a 422 that never echoes data.
    """

    media_type: Literal["image/png", "image/jpeg"]
    data: str
    #: Accepted for wire compatibility, ignored: dims come from the image header
    #: (`agent/screen.py`, review L1) so the transcript never records a lie.
    width: int | None = Field(default=None, ge=1, le=MAX_DIMENSION)
    height: int | None = Field(default=None, ge=1, le=MAX_DIMENSION)
    source: ScreenshotSource | None = None
    #: The downscaled surrounding screen as base64 PNG (sol-window.md §8) — read by
    #: the extractor pass only, never the reasoning turn. Same never-echo posture
    #: as `data`: capped in `agent/screen.py` (1.5 MiB decoded), not here.
    context: str | None = None

    def decode(self) -> ScreenshotBlock:
        try:
            return decode_screenshot(
                media_type=self.media_type,
                data=self.data,
                width=self.width,
                height=self.height,
                source=self.source,
                context=self.context,
            )
        except ScreenshotError as exc:
            raise APIError(422, "validation_error", str(exc)) from exc


class MessageCreate(StrictModel):
    #: Required unless `resume_confirmation_id` is set (SOLUSDEV-317 §5.5).
    content: str | None = Field(default=None, min_length=1, max_length=MAX_MESSAGE_CHARS)
    #: SOLUSDEV-317 §5.5: continue after a decided command card. Mutually
    #: exclusive with `content` and `screenshot` — a resume carries no words or
    #: pixels from the person, and no user turn is stored.
    resume_confirmation_id: uuid.UUID | None = None
    #: SOLX-01: how SOL may act on this message — guide (explain + point) or do
    #: (operate the tool). Guide is the safe default; per-action resolution
    #: inside a turn is the reasoning loop's refinement (SOL-02) on top of this
    #: request-level choice.
    action_mode: ActionMode = ActionMode.GUIDE
    #: A review request can reduce Build authority; prompt text cannot restore it.
    force_confirmation: StrictBool = False
    #: S1-W3: the composer's "Think harder" — the runner bumps the estimator's
    #: tier by one for this turn. Never a model name: routing stays Solus's.
    think_harder: bool = False
    #: SOLUSDEV-168: graph entities the user pointed at explicitly (the
    #: composer's `@`). Integration-agnostic on purpose — an entity id addresses
    #: any node in the graph at any depth, so one field serves Onshape, KiCad,
    #: ROS and whatever connector lands next, where a per-tool "selection" field
    #: would need widening for each.
    #:
    #: Bounded by the anchor cap ITSELF, not a copy of its value — two
    #: constants would drift. The cap is also re-applied in `plan_query` rather
    #: than trusted from here: it is what bounds the neighbourhood query's DB
    #: work, so it must hold for every caller, not just this route.
    #:
    #: Not checked for existence. `load_neighborhood` is project-scoped, so an id
    #: from another team yields nothing — answering differently for "exists
    #: elsewhere" than for "does not exist" would be a cross-tenant existence
    #: oracle (the posture `agent/tools/get_entity.py` documents).
    mentions: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_ANCHORS)
    #: SOLUSDEV-244 / HOME H3: the person's engineering conventions, read by the
    #: desktop from their own `~/.solus/preferences.json` and attached per turn.
    #: The server keeps no copy (ADR-034 amendment 2026-09-06); the schema
    #: re-applies the file's caps so a non-desktop caller cannot smuggle an
    #: unbounded document into the system prompt.
    preferences: EngineeringPreferences | None = None
    #: SOLUSDEV-252 S3: at most one screenshot per turn. Pixels live for this
    #: turn only — the transcript keeps `{width, height, app}`.
    screenshot: ScreenshotIn | None = None

    @model_validator(mode="after")
    def _content_or_resume(self) -> "MessageCreate":
        if self.resume_confirmation_id is None and self.content is None:
            # Reported as the field's own `missing` error (the API.md shape a
            # required `content` always had); the error handler redacts `input`.
            raise ValidationError.from_exception_data(
                type(self).__name__,
                [{"type": "missing", "loc": ("content",), "input": {}}],
            )
        if self.resume_confirmation_id is not None and (
            self.content is not None or self.screenshot is not None
        ):
            raise ValueError("a resume carries no content or screenshot")
        return self


def _tool_descriptors(registry: ToolRegistry) -> list[dict[str, Any]]:
    return [d.model_dump(mode="json") for d in registry.list()]


@router.get("/tools")
async def list_tools(_ctx: ProjectCtx, registry: SolRegistryDep) -> dict[str, Any]:
    """The tool set SOL may invoke for this project — the W0-04 descriptors the model
    reads. The set is fixed by Solus code, identical for every caller in the project."""
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


@router.get("/conversations/{conversation_id}/confirmations")
async def list_conversation_confirmations(
    conversation_id: uuid.UUID, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    await _owned_or_404(ctx, session, conversation_id)
    rows = await session.scalars(
        select(ToolConfirmation)
        .where(
            ToolConfirmation.conversation_id == conversation_id,
            ToolConfirmation.project_id == ctx.project.id,
            ToolConfirmation.team_id == ctx.team.id,
            ToolConfirmation.user_id == ctx.user.id,
            ToolConfirmation.status == ConfirmationStatus.PENDING,
            ToolConfirmation.expires_at > utcnow(),
        )
        .order_by(ToolConfirmation.created_at, ToolConfirmation.id)
    )
    return envelope(
        [
            {
                "confirmation_id": str(row.id),
                "tool": row.tool,
                "summary": row.summary,
                "preview": row.preview,
                "expires_at": row.expires_at.isoformat(),
            }
            for row in rows
        ]
    )


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


def _tool_turn_summary(
    call: dict[str, Any], result: dict[str, Any], parked_tools: frozenset[str] = frozenset()
) -> str:
    """What the NEXT turn's model is told this call did.

    A parked call is not a failed one. It comes back UNAUTHORIZED because the
    gate refused to run it *yet* — but recording that verbatim told the model
    `"onshape.add_feature → unauthorized"`, and `ConversationService.history`
    replays every role, so on the next message SOL was shown its own write as
    FAILED even when the person had approved it seconds earlier. A model that
    believes its change did not land will propose it again.
    """
    tool = str(call.get("tool", "tool"))
    if result.get("ok"):
        return f"{tool} → ok"
    # Keyed on what the gate ACTUALLY parked this turn, never on the error code:
    # UNAUTHORIZED is also what a revoked grant returns, and the two must not
    # read the same in the transcript.
    if tool in parked_tools:
        return f"{tool} → parked, awaiting your approval"
    return f"{tool} → {(result.get('error') or {}).get('code', 'error')}"


def _action_key(call: ToolCall) -> str:
    """The identity of a proposed ACTION, for per-turn deduplication.

    Tool plus arguments, canonically ordered — two calls that would do the same
    thing are the same action however the model happened to order the keys.
    """
    return f"{call.tool}:{json.dumps(call.args, sort_keys=True, default=str)}"


def _refusal_result(call_id: str, message: str) -> ToolResult:
    return ToolResult.failure(
        call_id, ToolError(code=ToolErrorCode.UNAUTHORIZED, message=message, retryable=False)
    )


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
    parked_tools: frozenset[str] = frozenset(),
    assistant_attrs: dict[str, Any] | None = None,
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
                content=_tool_turn_summary(call, result, parked_tools),
                # Redacted before persistence, not just before model context:
                # this row is served back out of /turns to the browser, so a
                # secret-shaped tool value would otherwise sit in Postgres in the
                # clear AND render in the UI (SOLUS-RUN-01).
                attrs=redact_value(
                    {"call": call, "result": result},
                    allowed_paths=call_display_paths(call.get("tool"), call.get("args")),
                ),
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
                **(assistant_attrs or {}),
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


async def _close_runner(stream: AsyncIterator[AgentEvent]) -> None:
    close = getattr(stream, "aclose", None)
    if close is not None:
        try:
            await _bounded_await(close(), 5.0)
        except (TimeoutError, RuntimeError):
            logger.warning("SOL runner cleanup did not complete within its bound")


async def _cleanup_turn(
    stream: AsyncIterator[AgentEvent], turn_sync: OnshapeTurnSync | None
) -> None:
    async def cleanup() -> None:
        await _close_runner(stream)
        if turn_sync is not None:
            await turn_sync.flush()

    try:
        await _bounded_await(cleanup(), 5.0)
    except TimeoutError:
        logger.warning("Turn cleanup grace expired; durable holds will recover")


def _consume_task(task: asyncio.Future[Any]) -> None:
    if not task.cancelled():
        task.exception()


async def _bounded_await(awaitable: Any, seconds: float) -> Any:
    task = asyncio.ensure_future(awaitable)
    task.add_done_callback(_consume_task)
    try:
        done, _ = await asyncio.wait({task}, timeout=max(0.0, seconds))
        if not done:
            raise TimeoutError
        return task.result()
    finally:
        if not task.done():
            task.cancel()


async def _bounded_events(
    stream: AsyncIterator[AgentEvent], seconds: float
) -> AsyncIterator[AgentEvent]:
    deadline = asyncio.get_running_loop().time() + seconds
    while True:
        try:
            event = await _bounded_await(
                anext(stream), deadline - asyncio.get_running_loop().time()
            )
        except StopAsyncIteration:
            return
        yield event


def _abort_code(error: BaseException) -> str:
    return "timeout" if isinstance(error, TimeoutError) else "cancelled"


def _abort_event(code: str, error: BaseException | None) -> AgentEvent:
    if code == "cancelled":
        assert error is not None
        raise error
    return AgentEvent.error(code, _ABORT_MESSAGES[code])


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
    turn_sync: OnshapeTurnSync | None = None,
    assistant_attrs: dict[str, Any] | None = None,
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
    abort_error: BaseException | None = None
    limits = turn_limits(ctx.action_mode)
    stream = runner.run(ctx)
    try:
        try:
            async with asyncio.timeout(limits.timeout_seconds):
                async for event in _bounded_events(stream, limits.timeout_seconds):
                    if event.type is AgentEventType.TOOL_CALL:
                        tool_calls += 1
                        # Loop guard enforced HERE, independent of the runner: a runaway
                        # (real, model-driven) runner is cut off by the plumbing, not by
                        # its own restraint.
                        if tool_calls > limits.tool_calls:
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
        except (TimeoutError, asyncio.CancelledError, GeneratorExit) as error:
            aborted = _abort_code(error)
            abort_error = error
        finally:
            await _cleanup_turn(stream, turn_sync)

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
            parked_tools=frozenset(p.tool for p in parked if p.confirmation_id is not None),
            assistant_attrs=assistant_attrs,
        )
        if aborted is not None:
            yield format_sse(_abort_event(aborted, abort_error))
        yield format_sse(
            AgentEvent.done(conversation_id=str(conversation_id), turn_id=str(done_turn_id))
        )
    except Exception as exc:
        yield _turn_failure_sse(exc, conversation_id)


async def _validate_mentions(
    session: SessionDep, project_id: uuid.UUID, mentions: list[uuid.UUID]
) -> None:
    from solus_api.graph.read_scope import current_scope
    from solus_api.models import GraphEntity

    if mentions:
        visible_mentions = set(
            (
                await session.scalars(
                    select(GraphEntity.id).where(
                        GraphEntity.id.in_(mentions),
                        GraphEntity.deleted_at.is_(None),
                        current_scope(project_id).entity_predicate(),
                    )
                )
            ).all()
        )
        if visible_mentions != set(mentions):
            raise APIError(
                409,
                "stale_mentions",
                "The selected source view changed. Refresh and select these mentions again.",
            )


async def _record_build_outcome(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
    ctx: ProjectCtx,
    sessionmaker: async_sessionmaker[AsyncSession],
    call: ToolCall,
    result: ToolResult,
    turn_sync: OnshapeTurnSync | None = None,
) -> ToolResult:
    """Record Build provenance and retain the normal post-write graph sync path."""
    if turn_sync is not None:
        result = turn_sync.outcome(call, result)
    if result.ok and turn_sync is None:
        graph_sync = await schedule_onshape_write_sync(
            sessionmaker,
            project_id=ctx.project.id,
            team_id=ctx.team.id,
            tool_name=call.tool,
            args=call.args,
            store=getattr(request.app.state, "integration_store", None),
            enqueue=sync_enqueuer(request, background_tasks, settings, ctx),
        )
        if graph_sync is not None and result.value is not None:
            result = result.model_copy(update={"value": {**result.value, "graph_sync": graph_sync}})
    try:
        async with sessionmaker() as recording:
            await _feed_back_outcome(
                recording,
                call.tool,
                result,
                user_id=ctx.user.id,
                team_id=ctx.team.id,
                project_id=ctx.project.id,
            )
            # §10.1: an auto-run command reports like an approved one, `auto: true`.
            value = result.value if result.ok and isinstance(result.value, dict) else None
            for event_type, payload in (
                completion_events(call.tool, call.args, value, auto=True) if value else []
            ):
                emit_event(
                    recording,
                    user=ctx.user,
                    event_type=event_type,
                    team_id=ctx.team.id,
                    project_id=ctx.project.id,
                    payload=payload,
                )
            emit_event(
                recording,
                user=ctx.user,
                event_type="sol.build_action_executed",
                team_id=ctx.team.id,
                project_id=ctx.project.id,
                payload={
                    "tool": call.tool,
                    "call_id": call.call_id,
                    "authorization_origin": "build_policy",
                    "ok": result.ok,
                },
            )
            await recording.commit()
    except Exception:
        logger.warning("Build outcome recording failed for %s", call.tool)
    return result


async def _resume_ticket(
    session: AsyncSession, ctx: ProjectCtx, conversation_id: uuid.UUID, body: MessageCreate
) -> ResumeTicket | None:
    if body.resume_confirmation_id is None:
        return None
    return await check_resume(
        session,
        confirmation_id=body.resume_confirmation_id,
        conversation_id=conversation_id,
        project_id=ctx.project.id,
        team_id=ctx.team.id,
        user_id=ctx.user.id,
    )


async def _admit_resume(
    session: AsyncSession, ctx: ProjectCtx, conversation_id: uuid.UUID, ticket: ResumeTicket
) -> None:
    """SOLUSDEV-317 §5.5: claim the resume (after the budget pre-flight, so a
    402/429 never consumes it) and log it. No user turn is stored."""
    await claim_resume(session, ticket, conversation_id=conversation_id, project_id=ctx.project.id)
    emit_event(
        session,
        user=ctx.user,
        event_type="sol.turn_resumed",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={
            "confirmation_id": str(ticket.confirmation_id),
            "tool": ticket.tool,
            "chain": ticket.chain,
        },
    )


async def _record_user_message(
    session: AsyncSession,
    ctx: ProjectCtx,
    conversation_id: uuid.UUID,
    content: str,
    body: MessageCreate,
    attribution: Any,
    screenshot: ScreenshotBlock | None,
) -> None:
    # Phase 4 H2: the transcript stores the ORIGINAL text with the attribution
    # on `attrs`; the Solus-authored framing exists only in model input. S3: a
    # screenshot leaves dims + app only — never pixels (sol-window.md §8.3).
    user_attrs: dict[str, Any] = {}
    if attribution:
        user_attrs["extension_slug"] = attribution.slug
    if screenshot is not None:
        user_attrs["screenshot"] = screenshot.summary()
    await SERVICE.append_turn(
        session,
        conversation_id=conversation_id,
        project_id=ctx.project.id,
        role=TurnRole.USER,
        content=content,
        attrs=user_attrs or None,
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="sol.message",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={
            "conversation_id": str(conversation_id),
            "chars": len(content),
            # SOLUSDEV-244: how much the person's conventions add to the system
            # prompt this turn — a COUNT for cost attribution, never the text.
            "preference_chars": (
                sum(len(v) for v in body.preferences.prompt_payload().values())
                if body.preferences is not None
                else 0
            ),
            # S3: a flag for cost/usage attribution — never dims, title or pixels.
            "screenshot": screenshot is not None,
        },
    )


@router.post("/conversations/{conversation_id}/messages")
async def post_message(
    request: Request,
    background_tasks: BackgroundTasks,
    conversation_id: uuid.UUID,
    body: MessageCreate,
    ctx: ProjectCtx,
    session: SessionDep,
    sessionmaker: SessionMakerDep,
    systems: SolSystemsDep,
    runner: AgentRunnerDep,
    settings: SettingsDep,
    secret_store: SecretStoreDep,
    registry: SolRegistryDep,
    # SOLUSDEV-235 (extensions.md §9): `X-Solus-Extension` resolved as a
    # dependency, so an unauthorized header is 403 `scope_denied` BEFORE admission.
    attribution: ExtensionAttribution,
) -> StreamingResponse:
    """Append the user's message and stream SOL's reply as Server-Sent Events. The user
    turn is persisted (and the interaction logged) BEFORE streaming; the assistant/tool
    turns are persisted as the stream completes."""
    require_role(ctx, Role.MEMBER)
    resuming = body.resume_confirmation_id is not None
    content = "" if resuming else (body.content or "").strip()
    if not resuming and not content:
        raise APIError(422, "validation_error", "Message content must not be blank")
    await _owned_or_404(ctx, session, conversation_id)
    ticket = await _resume_ticket(session, ctx, conversation_id, body)
    if ticket is not None:
        content = resume_prompt(ticket)
    # S3: decode + sniff BEFORE admission — a bad attachment is a 422, not a spent turn.
    screenshot = body.screenshot.decode() if body.screenshot is not None else None

    await _validate_mentions(session, ctx.project.id, body.mentions)

    # BUDGET GATE (SOLUS-RUN-01). `track_cost` needs NO wiring here — the gateway
    # fires it per model call from inside CompletionStream._finalize, which is the
    # point of that chokepoint. What belongs here is the PRE-FLIGHT, and its value
    # is a correct status code rather than enforcement: `assert_can_spend` already
    # runs per call inside the gateway, but it runs mid-stream, after the SSE
    # response has opened, so a user out of credits would get an error frame
    # instead of a 402 (CLAUDE.md §7; ADR-019/024).
    estimate = SOL_TURN_CREDIT_ESTIMATE + (SCREENSHOT_EXTRA_CREDITS if screenshot else 0)
    if not await has_sufficient_credits(ctx.user.id, estimate, session=session):
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
    history = tuple(
        TurnView(role=role, content=content)
        for role, content in enrich_history([(t.role.value, t.content, t.attrs) for t in prior])
    )
    if ticket is not None:
        await _admit_resume(session, ctx, conversation_id, ticket)
    else:
        await _record_user_message(
            session, ctx, conversation_id, content, body, attribution, screenshot
        )
    await session.commit()

    # Scope is bound by Solus code, before the runner sees any user content (§7) —
    # in `deps.get_sol_registry`, which is the ONE place a registry is built.
    parked_calls: list[ParkedCall] = []
    #: What this turn has already parked, keyed by the concrete action. The loop
    #: keeps running after a park, so a model that re-proposes would otherwise
    #: mint a second identical row, a second card, and a second LIVE preview read
    #: against the customer's CAD. One action, one card.
    parked_by_action: dict[str, ParkedCall] = {}

    async def park(call: ToolCall) -> ParkedCall | None:
        """SOLUS-ONS-A5: park a destructive call instead of running it.

        Its own session, because the turn streams long after this request's
        session is done with; committed immediately so the confirmation is
        approvable the moment the client sees the event.
        """
        already = parked_by_action.get(_action_key(call))
        if already is not None:
            # Deliberately NOT a fresh park: same confirmation, and a message
            # that tells the model this exact action is already waiting.
            return replace(
                already,
                result=_refusal_result(
                    call.call_id,
                    f"{call.tool} was already proposed earlier in this turn and is "
                    f"waiting for the person to approve it. Do not propose it again.",
                ),
            )
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
            parked_by_action[_action_key(call)] = parked
        return parked

    # SOLUSDEV-251: vendor-documented tool knowledge rides each mapped write
    # tool's description as a fenced note (global table, never project data).
    descriptors = with_knowledge_notes(tuple(registry.list()), await load_knowledge_notes(session))
    routine_policy = BuildExecutionPolicy(
        registry, body.action_mode, force_confirmation=body.force_confirmation
    )
    turn_sync = create_turn_sync(request, settings, ctx, sessionmaker)

    async def routine_outcome(call: ToolCall, result: ToolResult) -> ToolResult:
        return await _record_build_outcome(
            request, background_tasks, settings, ctx, sessionmaker, call, result, turn_sync
        )

    run_ctx = AgentRunContext(
        prompt=content,
        # Descriptors + a gated, MODE-WRAPPED dispatcher, never the registry
        # itself: a runner holds nothing it could invoke ungated (CLAUDE.md §7)
        # and, in guide mode, nothing that could mutate (SOLX-01).
        tools=descriptors,
        dispatch=build_mode_dispatch(
            body.action_mode,
            descriptors,
            build_dispatch(
                registry,
                park,
                routine_policy=routine_policy,
                routine_outcome=routine_outcome,
                routine_start=turn_sync.start,
            ),
        ),
        executed_build_calls=routine_policy.executed_calls,
        systems=systems,
        project_id=ctx.project.id,
        sol_mode=ctx.user.sol_mode,
        # SOLUSDEV-233: reaches the prompt only as a fenced data block.
        custom_instruction=ctx.user.sol_custom_instruction,
        # SOLUSDEV-244: labelled sections only, fenced by the prompt builder.
        engineering_preferences=(
            body.preferences.prompt_payload()
            if body.preferences is not None and not body.preferences.is_empty()
            else None
        ),
        action_mode=body.action_mode,
        think_harder=body.think_harder,
        # Entities the user pointed at with `@`. They lead the neighbourhood's
        # anchors, so SOL grounds on the node meant rather than the one
        # similarity search happened to rank first.
        mentions=tuple(body.mentions),
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
        # S3: pixels for this turn only; the runner's extractor pass reads them.
        screenshot=screenshot,
    )
    stream = _run_and_persist(
        runner=runner,
        ctx=run_ctx,
        parked=parked_calls,
        turn_sync=turn_sync,
        sessionmaker=sessionmaker,
        conversation_id=conversation_id,
        project_id=ctx.project.id,
        team_id=ctx.team.id,
        user_id=ctx.user.id,
        sol_mode=ctx.user.sol_mode.value,
        action_mode=body.action_mode.value,
        assistant_attrs=(
            {"resume_of": str(ticket.confirmation_id)} if ticket is not None else None
        ),
    )
    from solus_api.graph.read_scope import current_scope, scoped_stream

    return StreamingResponse(
        scoped_stream(current_scope(ctx.project.id), stream),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


def create_scene_enqueue(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
    ctx: ProjectCtx,
) -> Callable[[AsyncSession, GraphEntity], Awaitable[uuid.UUID]]:
    """Share the source queue and actor scope; never retain the SSE dependency session."""

    async def enqueue_scene(session: AsyncSession, pending: GraphEntity) -> uuid.UUID:
        from solus_api.graph.live import graph_changed_frame
        from solus_api.routers.sources import enqueue_sync
        from solus_api.services.physical_robots import GraphChangeCounts

        require_role(ctx, Role.MEMBER)
        source = await session.scalar(
            select(Source).where(
                Source.id == uuid.UUID(pending.attrs["cad_source_id"]),
                Source.project_id == ctx.project.id,
                Source.team_id == ctx.team.id,
            )
        )
        if source is None:
            raise APIError(404, "not_found", "CAD source not found")
        emit_event(
            session,
            user=ctx.user,
            event_type="bench.scene_cad_import_requested",
            team_id=ctx.team.id,
            project_id=ctx.project.id,
            payload={"import_id": str(pending.id)},
        )
        job_id = await enqueue_sync(
            session,
            ctx,
            source,
            request,
            background_tasks,
            settings.model_copy(update={"sync_inline": False}),
            Response(),
        )
        await request.app.state.graph_hub.publish(
            ctx.project.id,
            graph_changed_frame(
                project_id=ctx.project.id,
                source_id=None,
                sync_id=None,
                counts=GraphChangeCounts(entities_created=1),
                at=utcnow().isoformat(),
            ),
        )
        return job_id

    return enqueue_scene
