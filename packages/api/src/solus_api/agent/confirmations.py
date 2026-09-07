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
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from solus_api.agent.tools.untrusted import redact_text
from solus_api.models import ConfirmationStatus, ToolConfirmation, User, utcnow

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
    rendered = ", ".join(
        f"{_single_line(key, _LABEL_CAP)}={_single_line(repr(value), _VALUE_CAP)}"
        for key, value in sorted(args.items())
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
    """
    return "".join(ch for ch in str(value) if ch.isprintable())[:cap]


async def _build_preview(tool: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
    """The diff a user is asked to approve, from the tool itself.

    Duck-typed exactly like `list_selectable`: a tool that can describe its own
    change implements `async preview(args) -> list[{label, before, after}]`; one
    that cannot simply does not, and the summary carries the consent. Generic by
    construction — a CAD edit, a firmware flash and a robot command all render
    the same rows.

    A preview is a READ against a live system, so it can fail. It degrades to no
    rows rather than blocking the park: losing the diff weakens the prompt, but
    refusing to park would make the action unreachable entirely.
    """
    builder = getattr(tool, "preview", None)
    if builder is None:
        return _argument_rows(args)
    try:
        # Bounded (SEC-M3): a preview is a live network read and one call site
        # runs under a row lock — a hanging tool must not pin the connection.
        async with asyncio.timeout(_PREVIEW_TIMEOUT_SECONDS):
            rows = await builder(dict(args))
    except Exception:
        name = getattr(getattr(tool, "descriptor", None), "name", "?")
        logger.warning("preview failed for %s; falling back to arguments", name)
        return _argument_rows(args)
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
                else redact_text(_single_line(row["before"], _VALUE_CAP)),
                "after": None
                if row.get("after") is None
                else redact_text(_single_line(row["after"], _VALUE_CAP)),
            }
        )
    return cleaned[:_MAX_PREVIEW_ROWS] if cleaned else _argument_rows(args)


def _argument_rows(args: dict[str, Any]) -> list[dict[str, Any]]:
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
                )
            ),
        }
        for key, value in sorted(args.items())
    ][:_MAX_PREVIEW_ROWS]


def _refusal(call_id: str, message: str, code: ToolErrorCode) -> ToolResult:
    return ToolResult.failure(call_id, ToolError(code=code, message=message, retryable=False))


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
    validator = Draft202012Validator(descriptor.params)
    errors = sorted(validator.iter_errors(dict(call.args)), key=lambda e: str(e.path))
    if errors:
        detail = "; ".join(e.message[:120] for e in errors[:3])
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

    summary = _summarize(descriptor, call.args)
    tool = next((t for t in registry.tools() if t.descriptor.name == call.tool), None)
    preview = await _build_preview(tool, call.args) if tool is not None else []
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
    if tool is not None and _diverged(list(row.preview), await _build_preview(tool, row.args)):
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
            "What this action would do has changed since it was shown to you. "
            "Nothing was applied — ask again to see the current change.",
            ToolErrorCode.UNAUTHORIZED,
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

    result = await run_tool(_approved, stored)
    # Plain values, captured BEFORE the best-effort hooks: a hook may roll the
    # session back, which expires the row — touching it afterwards would lazy-load
    # outside the async context.
    tool_name, team_id = row.tool, row.team_id
    await _feed_back_outcome(
        session, tool_name, result, user_id=user_id, team_id=team_id, project_id=project_id
    )
    await _file_failure(session, tool_name, result, user_id=user_id, project_id=project_id)
    return result


#: Confirmed commands whose non-zero exit is a project error worth filing (S5).
_FILED_COMMAND_TOOLS: Final = frozenset({"code.run", "code.test"})
_ERROR_STDERR_CAP: Final = 3000


def failure_entry_text(tool: str, value: dict[str, Any]) -> str | None:
    """The Error logging entry for a failed confirmed command, or None when the
    result is not a failure (exit 0, a refusal with no exit, a non-command)."""
    exit_code = value.get("exit_code")
    if not isinstance(exit_code, int) or exit_code == 0:
        return None
    argv = value.get("argv")
    command = (
        " ".join(str(a) for a in argv)
        if isinstance(argv, list) and all(isinstance(a, str) for a in argv)
        else tool
    )
    tail = output_tail(value, _ERROR_STDERR_CAP)
    text = f"{command} exited {exit_code}"
    return f"{text}\n\n{tail}" if tail else text


def output_tail(value: dict[str, Any], cap: int) -> str:
    """The last `cap` characters of what the command printed — stdout then
    stderr. pytest reports its FAILED lines on stdout; a crashing script puts
    its traceback on stderr; keeping only one of them loses the other.

    Security review H3: this text is persisted (Error logging, the tool turn)
    and replayed into the next prompt's history block, so it goes through the
    same scalar redaction as every other untrusted machine text, and control
    characters never ride along."""
    parts = [
        str(value[key]).strip()
        for key in ("stdout_tail", "stderr_tail")
        if isinstance(value.get(key), str) and str(value[key]).strip()
    ]
    joined = "\n".join(parts)
    printable = "".join(ch for ch in joined if ch.isprintable() or ch == "\n")
    return redact_text(printable)[-cap:]


_OUTCOME_TAIL_CAP: Final = 400
_REASON_CAP: Final = 200


def command_outcome_text(value: dict[str, Any]) -> str | None:
    """A short clause naming what a confirmed COMMAND did, for the tool turn
    the next model reads (SOLUSDEV-250). `ToolResult.ok` is the transport; the
    command's own exit lives in the value, and without it the model can only
    say "applied ok" about a test run that failed. None for non-commands — a
    result is a command's only when it carries an `exit_code` key (every
    `code.*` answer does, `null` for a refusal); a `reason` alone is not one
    (`local.open_in_tool` answers `reason: null` on success)."""
    if "exit_code" not in value:
        return None
    exit_code = value["exit_code"]
    if exit_code is None:
        return f"; the server refused to run it: {str(value.get('reason'))[:_REASON_CAP]}"
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        return None
    if exit_code == 0:
        return "; the command exited 0"
    tail = output_tail(value, _OUTCOME_TAIL_CAP)
    return f"; the command exited {exit_code}" + (f" — output tail: {tail}" if tail else "")


async def _file_failure(
    session: AsyncSession,
    tool_name: str,
    result: ToolResult,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """SOLUSDEV-250 (S5): a confirmed `code.run`/`code.test` that exited non-zero
    is filed as ONE entry in the project's `.solus` Error logging section. Best
    effort, after the fact; never alters the result."""
    if tool_name not in _FILED_COMMAND_TOOLS or not result.ok:
        return
    value = result.value if isinstance(result.value, dict) else {}
    text = failure_entry_text(tool_name, value)
    if text is None:
        return
    try:
        from solus_api.models import SolusSection
        from solus_api.services.solus_config import add_text_entry

        await add_text_entry(
            session, project_id, SolusSection.ERRORS, text, author="sol", created_by=user_id
        )
        await session.commit()
        logger.info("filed a failed %s into Error logging", tool_name)
    except Exception:  # noqa: BLE001 — filing never fails the action that ran
        logger.warning("could not file the failed %s into Error logging", tool_name, exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("session rollback after error filing also failed")


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
    "decide_confirmation",
    "request_confirmation",
]
