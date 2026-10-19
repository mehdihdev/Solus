"""The destructive-action confirmation round-trip — SOLUS-ONS-A5.

`confirmation_refusal` has been a hard refusal since SEC-H1: a tool declaring
`requires_confirmation` was structurally un-dispatchable, because the flow that
would let a user approve one did not exist. This is that flow, and it is what
unblocks every Onshape write.

**Why it parks rather than prompts.** A SOL turn is a one-shot SSE stream; it
cannot block for minutes waiting for a click, and holding a request open would
pin a worker. So a gated call records what it wants to do, the turn streams the
request and ends, and the user decides through
`POST /api/v1/projects/{p}/sol/confirmations/{id}`. The tool runs at decision
time, with the registry rebuilt under the deciding user's own scope.

**The load-bearing property: arguments are server-side.** `ToolConfirmation.args`
holds exactly what the user was shown, and exactly what executes. The decide
endpoint accepts a decision and nothing else — a body carrying its own `args` is
a 422, not a merge. Otherwise a user could approve "change width" and a client
could execute "change everything" (CLAUDE.md §7: the concrete action is shown,
and no silent execution).

Every refusal is a `ToolResult`, never an exception — the W0-04 never-raises
story holds through this path too.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.command_gate import ARGV_TOOLS, policy_refusal, record_proposed
from solus_api.agent.command_outcome import command_outcome_text, output_tail
from solus_api.agent.command_output import STREAMING_TOOLS
from solus_api.agent.command_policy import classify
from solus_api.agent.errors_filing import file_tool_error
from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.tools.exec import run_tool
from solus_api.agent.tools.knowledge import record_write_outcome
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import (
    ToolCall,
    ToolDescriptor,
    ToolError,
    ToolErrorCode,
    ToolResult,
)
from solus_api.agent.tools.untrusted import call_display_paths, redact_text, redact_value
from solus_api.models import ConfirmationStatus, Conversation, ToolConfirmation, User, utcnow

logger = logging.getLogger("solus.agent.confirmations")

#: How long a parked action stays approvable. Short on purpose: an approval is
#: consent to a specific edit against a specific model state, and CAD moves.
CONFIRMATION_TTL: Final = timedelta(minutes=30)

#: Cap on the rendered action description.
_SUMMARY_CAP: Final = 2048
#: Bounds on the rendered diff. Preview content can originate upstream.
_LABEL_CAP: Final = 200
_VALUE_CAP: Final = 500
_MAX_PREVIEW_ROWS: Final = 50
#: SEC-M3: a preview is a live network read, and the decide-time call runs
#: under a FOR UPDATE row lock — it must never hang the connection.
_PREVIEW_TIMEOUT_SECONDS: Final = 10.0


@dataclass(frozen=True)
class ParkedCall:
    """What the turn streams so the user can decide. Carries the concrete action,
    never just an id — an opaque handle cannot be meaningfully approved."""

    #: None when nothing was parked (SEC-H3: invalid args are refused, never
    #: persisted or streamed) — carriers of None must not emit a confirmation.
    confirmation_id: uuid.UUID | None
    tool: str
    args: dict[str, Any]
    summary: str
    #: The diff being approved: `[{"label", "before", "after"}, ...]`.
    preview: list[dict[str, Any]]
    result: ToolResult


def _summarize(descriptor: ToolDescriptor, args: dict[str, Any]) -> str:
    """The action in words: what it does, plus the arguments it will run with.

    **Whose words these are matters.** For an in-process tool the `description`
    is Solus-authored. For a BRIDGE tool it is advertised by an upstream fork
    (`bridge/allowlist.py`) — untrusted text that must never phrase the sentence
    a human reads before approving something destructive: a fork could describe
    a destructive tool as "read-only" and the user would be approving a lie.

    So a descriptor may carry `consent_summary`, which Solus writes; when it is
    present the untrusted description is not used here at all.
    """
    allowed_paths = call_display_paths(descriptor.name, args)
    rendered = ", ".join(
        f"{_single_line(key, _LABEL_CAP)}={_single_line(repr(value), _VALUE_CAP)}"
        for key, value in sorted(redact_value(args, allowed_paths=allowed_paths).items())
    )
    trusted = descriptor.consent_summary
    if trusted is None and descriptor.description_trusted:
        # FAIL CLOSED (SEC-C1): with no Solus-authored summary AND an untrusted
        # description, the sentence is built from the tool NAME alone — a fork
        # never phrases what the user approves.
        trusted = descriptor.description
    prose = _single_line(trusted, _SUMMARY_CAP) if trusted else None
    text = f"{prose} ({descriptor.name})" if prose else descriptor.name
    if rendered:
        text = f"{text} with {rendered}"
    return text[:_SUMMARY_CAP]


#: Whitespace that would break the row in two (or pad text off-screen).
_CONTROL_WHITESPACE = re.compile(r"\s")
_RUNS = re.compile(r" {2,}")


def _single_line(value: object, cap: int) -> str:
    """A consent-card field, stripped to printable characters and capped.

    THE ONE PLACE THE `_sanitize` IDIOM APPLIES. SOL's prose is free-form English
    and cannot be charset-restricted, but a preview LABEL or VALUE is not prose —
    so the fingerprint escalator's "reject anything not shaped like the thing"
    gate works here, and it closes consent forgery.

    Without it, anyone who can name a CAD feature can write multi-line text onto
    the approval card ("Approve this, it is safe\n\nAll changes reverted") or
    reverse its rendering with U+202E. Capping length stops neither: `str.isprintable`
    is False for control characters, bidi overrides and zero-width joiners, and
    True for the ASCII space, which is exactly the distinction wanted.

    Line breaks collapse to ONE SPACE rather than vanishing. Deleting them fused
    the lines of a file the person was approving into words nobody wrote — a
    Dockerfile preview read `FROM python:3.12-slimWORKDIR /app` (SOLUSDEV-252,
    live) — which is a misrepresentation of the change, not a defence against
    one. The row still cannot become two rows, so the forgery is still closed.
    """
    spaced = _CONTROL_WHITESPACE.sub(" ", str(value))
    return _RUNS.sub(" ", "".join(ch for ch in spaced if ch.isprintable()))[:cap].strip()


class QuotaPreviewUnavailable(PreviewRefusal):
    """Connector-owned quota classification crosses the preview refusal boundary."""

    def __init__(self, *, exhausted: bool) -> None:
        super().__init__(
            "Onshape API quota is exhausted. Nothing was executed."
            if exhausted
            else "Onshape API quota has reached its conservation threshold. "
            "SOL actions are paused to reserve the remaining allowance. Nothing was executed."
        )


async def _build_preview(
    tool: Any,
    args: dict[str, Any],
    *,
    force_complete: bool = False,
    quota_failures: list[str] | None = None,
) -> list[dict[str, Any]]:
    """The diff a user is asked to approve, from the tool itself.

    Duck-typed exactly like `list_selectable`: a tool that can describe its own
    change implements `async preview(args) -> list[{label, before, after}]`; one
    that cannot simply does not, and the summary carries the consent. Generic by
    construction — a CAD edit, a firmware flash and a robot command all render
    the same rows.

    A preview is a read against a live system and can fail. Legacy tools retain
    argument rows as a fallback. Tools requiring a complete preview return no
    rows on failure so the caller refuses to park or execute the action.
    """
    required = force_complete or getattr(tool, "requires_complete_preview", False) is True
    allowed_paths = call_display_paths(
        getattr(getattr(tool, "descriptor", None), "name", None), args
    )
    fallback = [] if required else _argument_rows(args, allowed_paths=allowed_paths)
    builder = getattr(tool, "preview", None)
    if builder is None:
        return fallback
    try:
        # Bounded (SEC-M3): a preview is a live network read and one call site
        # runs under a row lock — a hanging tool must not pin the connection.
        async with asyncio.timeout(_PREVIEW_TIMEOUT_SECONDS):
            rows = await builder(dict(args))
    except PreviewRefusal as error:
        # A quota block or a refused `code.plan` (SOLUSDEV-317): the reason is
        # Solus-composed and sanitised, and the call is refused, not parked.
        if quota_failures is not None:
            quota_failures.append(error.safe_message)
        return []
    except Exception:
        name = getattr(getattr(tool, "descriptor", None), "name", "?")
        logger.warning("preview failed for %s (complete preview required=%s)", name, required)
        return fallback
    if required and not _complete_preview(rows):
        return []
    cleaned: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or "label" not in row:
            continue
        # redact_text (SEC-M4): before/after are read from the customer's live
        # system and are persisted + streamed to the browser — the same
        # redaction gate every other persistence path applies.
        cleaned.append(
            {
                "label": redact_text(_single_line(row.get("label", ""), _LABEL_CAP)),
                "before": None
                if row.get("before") is None
                else redact_text(
                    row["before"] if required else _single_line(row["before"], _VALUE_CAP),
                    allowed_paths=allowed_paths,
                ),
                "after": None
                if row.get("after") is None
                else redact_text(
                    row["after"] if required else _single_line(row["after"], _VALUE_CAP),
                    allowed_paths=allowed_paths,
                ),
            }
        )
    return cleaned[:_MAX_PREVIEW_ROWS] if cleaned else fallback


def _complete_preview(rows: Any) -> bool:
    if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_PREVIEW_ROWS:
        return False
    return all(
        isinstance(row, dict)
        and set(row) == {"label", "before", "after"}
        and isinstance(row["label"], str)
        and bool(row["label"].strip())
        and len(row["label"]) <= _LABEL_CAP
        and all(character.isprintable() for character in row["label"])
        and all(
            row[key] is None
            or (
                isinstance(row[key], str)
                and len(row[key]) <= _VALUE_CAP
                and all(character.isprintable() or character in "\n\t" for character in row[key])
            )
            for key in ("before", "after")
        )
        for row in rows
    )


def _argument_rows(
    args: dict[str, Any], *, allowed_paths: frozenset[str] = frozenset()
) -> list[dict[str, Any]]:
    """The diff for an action that has no before → after: what it will run with.

    A shell command, a firmware flash and a robot move do not REPLACE a value,
    so a before/after diff is the wrong shape for them — but the arguments are
    known exactly, and they are read from the same stored dict that executes
    (`ToolConfirmation.args`). Displayed IS executed, which is the whole point.

    Without this, every tool kind that cannot describe its own change reduced to
    "could not preview its change" — i.e. consent to a bare action name.
    """
    return [
        {
            "label": redact_text(_single_line(key, _LABEL_CAP)),
            "before": None,
            "after": redact_text(
                _single_line(
                    value if isinstance(value, str) else json.dumps(value, default=str),
                    _VALUE_CAP,
                ),
                allowed_paths=allowed_paths,
            ),
        }
        for key, value in sorted(redact_value(args, allowed_paths=allowed_paths).items())
    ][:_MAX_PREVIEW_ROWS]


def _refusal(call_id: str, message: str, code: ToolErrorCode) -> ToolResult:
    return ToolResult.failure(call_id, ToolError(code=code, message=message, retryable=False))


def validate_tool_arguments(descriptor: ToolDescriptor, args: dict[str, Any]) -> str | None:
    """Validate before either preview/automatic execution or confirmation storage."""
    validator = Draft202012Validator(descriptor.params)
    errors = sorted(validator.iter_errors(dict(args)), key=lambda error: str(error.path))
    return "; ".join(error.message[:120] for error in errors[:3]) if errors else None


async def request_confirmation(
    session: AsyncSession,
    registry: ToolRegistry,
    call: ToolCall,
    *,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None = None,
) -> ParkedCall | None:
    """Park `call` if its tool requires confirmation; otherwise return None.

    Returning None means "not gated, dispatch normally" — so a runner's whole
    integration is: park, or invoke. The caller commits.
    """
    descriptor = next((d for d in registry.list() if d.name == call.tool), None)
    if descriptor is None or not descriptor.requires_confirmation:
        return None

    # SEC-H3: validate BEFORE parking. Unvalidated args would be persisted,
    # rendered on the consent card, and streamed — a token-shaped extra key
    # ("token": "ghp_…") would land in Postgres and on the wire even though
    # execution later rejects it. Invalid args are refused, never parked.
    detail = validate_tool_arguments(descriptor, call.args)
    if detail:
        return ParkedCall(
            confirmation_id=None,
            tool=call.tool,
            args={},
            summary="",
            preview=[],
            result=_refusal(
                call.call_id,
                f"{call.tool} arguments are invalid and were not parked: {detail}",
                ToolErrorCode.INVALID_ARGS,
            ),
        )

    # SOLUSDEV-317 §4: a denied argv is refused BEFORE any preview read or park.
    denied = await policy_refusal(
        session, call, user_id=user_id, team_id=team_id, project_id=project_id
    )
    if denied is not None:
        return ParkedCall(None, call.tool, {}, "", [], denied)

    if conversation_id is not None:
        # Serialize cross-turn check/insert under the same owner-private chat.
        # The caller commits immediately after parking, releasing this lock.
        owned = await session.scalar(
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.project_id == project_id,
                Conversation.team_id == team_id,
                Conversation.created_by == user_id,
                Conversation.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if owned is None:
            return ParkedCall(
                None,
                call.tool,
                {},
                "",
                [],
                _refusal(call.call_id, "Conversation not found", ToolErrorCode.NOT_FOUND),
            )
        candidates = await session.scalars(
            select(ToolConfirmation)
            .where(
                ToolConfirmation.conversation_id == conversation_id,
                ToolConfirmation.project_id == project_id,
                ToolConfirmation.team_id == team_id,
                ToolConfirmation.user_id == user_id,
                ToolConfirmation.tool == call.tool,
                ToolConfirmation.status == ConfirmationStatus.PENDING,
                ToolConfirmation.expires_at > utcnow(),
            )
            .order_by(ToolConfirmation.created_at, ToolConfirmation.id)
        )
        key = json.dumps(call.args, sort_keys=True, separators=(",", ":"))
        for existing in candidates:
            if json.dumps(existing.args, sort_keys=True, separators=(",", ":")) == key:
                return ParkedCall(
                    existing.id,
                    existing.tool,
                    dict(existing.args),
                    existing.summary,
                    existing.preview,
                    _refusal(
                        call.call_id,
                        f"{call.tool} is already waiting for the person's approval. "
                        "The original approval card has been restored. Do not propose it again.",
                        ToolErrorCode.UNAUTHORIZED,
                    ),
                )

    summary = _summarize(descriptor, call.args)
    tool = next((t for t in registry.tools() if t.descriptor.name == call.tool), None)
    quota_failures: list[str] = []
    preview = (
        await _build_preview(tool, call.args, quota_failures=quota_failures)
        if tool is not None
        else []
    )
    if quota_failures or (
        getattr(tool, "requires_complete_preview", False) is True and not preview
    ):
        return ParkedCall(
            confirmation_id=None,
            tool=call.tool,
            args={},
            summary="",
            preview=[],
            result=_refusal(
                call.call_id,
                quota_failures[0]
                if quota_failures
                else "The complete change preview is unavailable. Nothing was parked or applied; "
                "read the current design and try again.",
                ToolErrorCode.UNAVAILABLE,
            ),
        )
    row = ToolConfirmation(
        project_id=project_id,
        team_id=team_id,
        user_id=user_id,
        conversation_id=conversation_id,
        tool=call.tool,
        args=dict(call.args),
        summary=summary,
        preview=preview,
        expires_at=utcnow() + CONFIRMATION_TTL,
    )
    session.add(row)
    await session.flush()
    if call.tool in ARGV_TOOLS:
        argv = call.args.get("argv")
        await record_proposed(
            session,
            call.tool,
            argv,
            classify(argv),
            user_id=user_id,
            team_id=team_id,
            project_id=project_id,
        )
    logger.info("parked %s for confirmation (project=%s)", call.tool, project_id)
    return ParkedCall(
        confirmation_id=row.id,
        tool=call.tool,
        args=dict(call.args),
        summary=summary,
        preview=preview,
        result=_refusal(
            call.call_id,
            # This sentence is the ONLY thing the model learns about the park, and
            # after SOLUSDEV-168's loop change it keeps reasoning afterwards — so
            # it has to say three things: the action is waiting for a PERSON, it
            # is not a failure, and proposing it again this turn achieves nothing.
            # Without the last clause a model reads UNAUTHORIZED as "try harder".
            f"{call.tool} is now waiting for the person to approve it — they have "
            f"been shown exactly what it would do. This is not a failure and it "
            f"does not need retrying: do not propose it again in this turn. "
            f"Carry on with anything else the task needs. {summary}",
            ToolErrorCode.UNAUTHORIZED,
        ),
    )


async def decide_confirmation(
    session: AsyncSession,
    registry: ToolRegistry,
    confirmation_id: uuid.UUID,
    *,
    approve: bool,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ToolResult:
    """Approve or reject a parked action; on approval, run it.

    Every failure path returns NOT_FOUND rather than a more specific code when
    the row is not this caller's — wrong project, wrong user, or absent are
    indistinguishable from outside, so there is no existence oracle (the
    `get_entity` rule).
    """
    call_id = uuid.uuid4().hex
    row = await session.scalar(
        select(ToolConfirmation)
        .where(
            ToolConfirmation.id == confirmation_id,
            ToolConfirmation.project_id == project_id,
            # Only the user whose turn proposed the action may decide it — a
            # teammate never saw what it was.
            ToolConfirmation.user_id == user_id,
        )
        # LOCK the row: the status check below is a check-then-act, and without
        # this two concurrent approvals both read PENDING and both execute. The
        # loser blocks here, then sees APPROVED and takes the refusal path.
        .with_for_update()
    )
    if row is None:
        return _refusal(call_id, "No such pending action.", ToolErrorCode.NOT_FOUND)

    if row.status is not ConfirmationStatus.PENDING:
        # Single use. One approval is not an unlimited licence to repeat a
        # destructive action.
        return _refusal(
            call_id,
            f"This action was already {row.status.value}.",
            ToolErrorCode.UNAUTHORIZED,
        )

    if row.expires_at <= utcnow():
        row.status = ConfirmationStatus.EXPIRED
        row.decided_at = utcnow()
        return _refusal(
            call_id,
            "This action expired before it was approved; ask again.",
            ToolErrorCode.UNAUTHORIZED,
        )

    row.decided_at = utcnow()
    if not approve:
        row.status = ConfirmationStatus.REJECTED
        return _refusal(call_id, "You rejected this action.", ToolErrorCode.UNAUTHORIZED)

    descriptor = next((d for d in registry.list() if d.name == row.tool), None)
    if descriptor is None:
        # The registry is rebuilt per request — a source disconnected between
        # request and approval means the tool is simply gone.
        return _refusal(
            call_id,
            f"{row.tool} is no longer available in this project.",
            ToolErrorCode.NOT_FOUND,
        )

    tool = next((t for t in registry.tools() if t.descriptor.name == row.tool), None)
    quota_failures: list[str] = []
    current_preview = (
        await _build_preview(tool, row.args, quota_failures=quota_failures)
        if tool is not None
        else []
    )
    missing_preview = (
        getattr(tool, "requires_complete_preview", False) is True and not current_preview
    )
    if tool is not None and (
        quota_failures or missing_preview or _diverged(list(row.preview), current_preview)
    ):
        # THE R1 GUARANTEE, enforced once at the gate rather than in each tool.
        #
        # A preview is resolved against a live system, and the world can move
        # while the card waits — a geometry selector that meant one face when
        # shown can mean another by the time it is clicked. Applying that would
        # execute something the user never saw. Refusing is recoverable: they
        # ask again and approve the current truth.
        row.status = ConfirmationStatus.STALE
        row.decided_at = utcnow()
        await session.commit()
        logger.info("refused stale confirmation %s for %s", row.id, row.tool)
        return _refusal(
            call_id,
            quota_failures[0]
            if quota_failures
            else "What this action would do has changed since it was shown to you. "
            "Nothing was applied — ask again to see the current change.",
            ToolErrorCode.UNAVAILABLE if quota_failures else ToolErrorCode.UNAUTHORIZED,
        )

    # Mark decided BEFORE dispatch, and make it DURABLE: holding the transition
    # as an un-flushed attribute means any later failure rolls APPROVED back to
    # PENDING after the destructive action already landed. Losing an execution
    # is recoverable; repeating one is not.
    row.status = ConfirmationStatus.APPROVED
    await session.commit()

    # The STORED args, never anything the client sent with the decision.
    # Wrapped in exec.run_tool so an APPROVED destructive dispatch gets the same
    # duration/outcome logging and Sentry capture as every other dispatch path.
    stored = ToolCall(tool=row.tool, args=dict(row.args), call_id=call_id)

    async def _approved(call: ToolCall) -> ToolResult:
        return await registry.invoke(call)  # the sanctioned post-approval site

    from solus_api.agent.command_output import current_output, output_store

    progress = (
        output_store.start((project_id, user_id, confirmation_id))
        if row.tool in STREAMING_TOOLS
        else None
    )
    token = current_output.set(progress)
    try:
        result = await run_tool(_approved, stored)
    finally:
        current_output.reset(token)
        if progress is not None:
            progress.finish()
    # Plain values, captured BEFORE the best-effort hooks: a hook may roll the
    # session back, which expires the row — touching it afterwards would lazy-load
    # outside the async context.
    tool_name, team_id = row.tool, row.team_id
    await _feed_back_outcome(
        session, tool_name, result, user_id=user_id, team_id=team_id, project_id=project_id
    )
    # S5 Error logging (sol-artifacts.md §4). THIS is where a gated command,
    # install or flash actually runs — the turn only parked it, so the runner's
    # post-dispatch hook cannot see this execution at all and filed nothing.
    # `executed=True` is a fact, not an inference: run_tool just returned.
    # The caller's session is reused because the decide route owns the only one;
    # `file_tool_error` rolls it back rather than poisoning it if filing fails.
    await file_tool_error(
        lambda: nullcontext(session),
        project_id=project_id,
        user_id=user_id,
        call=stored,
        result=result,
        descriptor=descriptor,
        executed=True,
    )
    return result


async def _feed_back_outcome(
    session: AsyncSession,
    tool_name: str,
    result: ToolResult,
    *,
    user_id: uuid.UUID,
    team_id: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """SOLUSDEV-251: the outcome of a confirmed write is one observation on the
    vendor control it acts on — the correction loop into tool knowledge. The
    write has ALREADY landed: nothing here may change or lose the result, so
    the whole block is best-effort and leaves the session usable on failure."""
    try:
        voter = await session.get(User, user_id)
        if voter is None:
            return
        await record_write_outcome(
            session,
            tool_name=tool_name,
            result=result,
            user=voter,
            team_id=team_id,
            project_id=project_id,
        )
        await session.commit()
    except Exception:  # noqa: BLE001 — feedback never fails the action that ran
        logger.warning("tool knowledge feedback failed after %s", tool_name, exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("session rollback after feedback failure also failed")


def _diverged(shown: list[Any], current: list[dict[str, Any]]) -> bool:
    """Whether the effect described on the card still describes what will happen.

    Compared on the rendered rows rather than on tool internals, so it works for
    every tool kind — which is what makes this a gate guarantee rather than an
    Onshape one. A tool with no describable effect yields argument rows, which
    are derived from the stored args and therefore cannot drift.
    """

    def key(rows: Any) -> list[tuple[Any, Any, Any]]:
        return sorted(
            (row.get("label"), row.get("before"), row.get("after"))
            for row in (rows if isinstance(rows, list) else [])
            if isinstance(row, dict)
        )

    return key(shown) != key(current)


__all__ = [
    "CONFIRMATION_TTL",
    "ParkedCall",
    "command_outcome_text",
    "output_tail",
    "decide_confirmation",
    "request_confirmation",
]
