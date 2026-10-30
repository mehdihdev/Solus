"""Automatic Error logging (SOLUSDEV-252 S5, docs/architecture/sol-artifacts.md §4).

When a tool whose descriptor sets `files_errors` (a command, an install, a flash —
anything run on the person's machine) FAILS, the runner files ONE `.solus` entry in
the `errors` section as author `sol`, through the same `add_text_entry` the
`add_solus_entry` tool uses. Failure is both kinds: the call itself failing
(`ok=False`), and a call that was delivered fine and reported a failed run —
non-zero exit code or timeout (`run_failure`). The person edits or deletes it
from the Workspace like any note. Filings dedupe on `sha1(tool, redacted command,
error code)` (`ErrorMeta.dedupe_key`, SOLUSDEV-320): an open entry with the same key
gets `count += 1` and a fresh `last_seen`; a resolved one becomes `recurring`. This
module never raises: a filing failure is a warning line naming the exception class,
never a failed turn.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.shapes import ToolCall, ToolDescriptor, ToolResult
from solus_api.agent.tools.untrusted import REDACTED, redact_text, redact_value
from solus_api.models import GraphEntity, Project, SolusEntry, SolusSection, User
from solus_api.services.events import emit_event
from solus_api.services.solus_config import MAX_TEXT_CHARS, add_text_entry
from solus_api.services.solus_graph import lock_project
from solus_api.services.solus_payloads import ErrorMeta

logger = logging.getLogger("solus.agent.errors_filing")

MAX_ENTRY_CHARS = MAX_TEXT_CHARS  # the section's own bound (4000)
_FIELD_CAP = 1500
UNCERTAIN_COMMAND_OUTCOME = (
    "execution outcome is uncertain; the target may have changed. "
    "Inspect its current state before proposing another action. Do not retry automatically."
)
#: Keys redacted by NAME on top of `redact_value` (which already covers token/
#: secret/password/api_key/…): a bare `key` is a credential-shaped name too.
_SECRET_NAME = re.compile(r"token|secret|passw|key", re.IGNORECASE)
_ENTITY_KEYS = ("entity_id", "focus_entity_ids", "robot_id", "part_entity_id")


def _redact_args(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: REDACTED if isinstance(k, str) and _SECRET_NAME.search(k) else _redact_args(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_args(v) for v in value]
    return value


def _entity_of(args: dict[str, Any]) -> str:
    found = [str(args[k]) for k in _ENTITY_KEYS if args.get(k)]
    return ", ".join(found) if found else "-"


def _entity_ref(args: Mapping[str, Any]) -> uuid.UUID | None:
    """The first entity the call named, when it is a UUID (`ErrorMeta.entity_id`)."""
    for key in _ENTITY_KEYS:
        value = args.get(key)
        value = value[0] if isinstance(value, list) and value else value
        if not value:
            continue
        try:
            return uuid.UUID(str(value))
        except ValueError:
            continue
    return None


async def _project_entity(
    session: AsyncSession, project_id: Any, entity_id: uuid.UUID | None
) -> uuid.UUID | None:
    """The proposed id only when it names one of THIS project's entities: tool args are
    model-proposed, so a stored reference is verified, never copied."""
    if entity_id is None:
        return None
    found: uuid.UUID | None = await session.scalar(
        select(GraphEntity.id).where(
            GraphEntity.id == entity_id, GraphEntity.project_id == project_id
        )
    )
    return found


def _redacted_command(call: ToolCall) -> str:
    return json.dumps(redact_value(_redact_args(call.args)), sort_keys=True, default=str)


def _error_code(result: ToolResult) -> str:
    return result.error.code.value if result.error else "tool_error"


def error_dedupe_key(tool: str, redacted_command: str, code: str) -> str:
    """sha1 hex over (tool, redacted command, error code): the same failure again."""
    return hashlib.sha1(  # noqa: S324 — an identity, not a security hash
        f"{tool}\n{redacted_command}\n{code}".encode()
    ).hexdigest()


def format_error_entry(call: ToolCall, result: ToolResult, *, now: datetime | None = None) -> str:
    """The bounded, redacted text the entry carries — the fields the wireflow lists."""
    error = result.error
    command = _redacted_command(call)
    lines = [
        f"Tool failure: {call.tool}",
        f"When: {(now or datetime.now(UTC)).isoformat(timespec='seconds')}",
        f"Entity: {_entity_of(call.args)}",
        f"Command: {command[:_FIELD_CAP]}",
        "Executed argv: "
        + json.dumps(
            redact_value(
                _redact_args(result.value.get("argv", []) if isinstance(result.value, dict) else [])
            ),
            default=str,
        )[:_FIELD_CAP],
        f"Error [{_error_code(result)}]: "
        # `error.message` was already redacted at the bridge ingress
        # (`bridge/service.py`); `run_failure` reads the RESULT VALUE, whose only
        # gate there is `redact_value` — key names and single high-entropy tokens.
        # A command's stderr is neither: `export AWS_SECRET_ACCESS_KEY=…` in a
        # failing script's output would land verbatim in a durable, team-visible
        # Errors row that `GET /solus` serves and the context layer replays to the
        # model. Redact the text the same way the error channel is redacted.
        f"{(error.message if error else redact_text(run_failure(result) or ''))[:_FIELD_CAP]}",
        "Filed automatically by SOL — edit or delete this note if it is wrong.",
    ]
    return "\n".join(lines)[:MAX_ENTRY_CHARS]


def run_failure(result: ToolResult) -> str | None:
    """The message for a call that SUCCEEDED at the transport level and then
    reported a failed run — a non-zero exit code, or a timeout.

    `ok` says the tool was reached, not that the command worked. A
    `ModuleNotFoundError` comes back as a perfectly ok result carrying
    `exit_code: 1`, and that is exactly the failure Error logging exists to
    capture; keying on `ok` alone filed nothing for it (SOLUSDEV-252, found
    live). Returns None when the result is not a completed run — a clean exit,
    a dry-run plan, or any tool that reports neither.
    """
    value = result.value
    if not result.ok or not isinstance(value, dict) or value.get("dry_run") is True:
        return None
    return command_failure(value)


def command_failure(value: Mapping[str, Any]) -> str | None:
    """Describe a reported command failure for error filing and confirmed history."""
    if value.get("uncertain") is True:
        return UNCERTAIN_COMMAND_OUTCOME
    outcome = _failed_outcome(value)
    if outcome is None:
        return None
    prefix, run = outcome
    tail = "\n".join(
        str(run[key]).strip()
        for key in ("stdout_tail", "stderr_tail", "stdout", "stderr")
        if isinstance(run.get(key), str) and str(run[key]).strip()
    )
    tail = "".join(char for char in tail if char.isprintable() or char == "\n")
    if run.get("timed_out") is True:
        return f"{prefix}timed out after {run.get('duration_s', '?')}s. {tail}".strip()
    if run.get("ok") is False and run.get("exit_code") in (0, None):
        reason = str(run.get("reason") or "no verified successful outcome")
        return f"{prefix}failed after starting: {reason}. {tail}".strip()
    return f"{prefix}exit {run.get('exit_code')}. {tail}".strip()


def _failed_outcome(value: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]] | None:
    """The one command outcome that failed, and how to name it.

    Two shapes: ONE command (`run_command`, `install_package` — the outcome is
    the value itself) and an ORDERED BUILD (`create_environment` runs several
    steps and stops at the first failure, reporting them under `results`). The
    build shape carries no top-level `exit_code`, so reading only the flat one
    filed nothing for a `python -m venv` that failed — the same silent miss that
    keying on `ok` alone produced.
    """
    if _failed_run(value):
        return "", value
    steps = value.get("results")
    for index, step in enumerate(steps if isinstance(steps, list) else [], start=1):
        if isinstance(step, Mapping) and _failed_run(step):
            return f"step {index} ", step
    return None


def _failed_run(run: Mapping[str, Any]) -> bool:
    """A COMPLETED run that did not succeed. `True`/`False` are `int`s in Python
    and a float exit code is a fork serialising JSON loosely; neither is zero."""
    if run.get("timed_out") is True:
        return True
    code = run.get("exit_code")
    if run.get("ok") is False and run.get("started") is True:
        return True
    if isinstance(code, bool) or not isinstance(code, (int, float)):
        return False
    return code != 0 or run.get("ok") is False


def should_file(result: ToolResult, descriptor: ToolDescriptor | None, *, executed: bool) -> bool:
    """File a failure only for a call that actually RAN.

    `executed` is a fact the CALLER holds, never an inference from the result.
    A confirmation-gated call comes back from `dispatch` PARKED — the gate never
    dispatches it — and its refusal is a `ToolResult` with `ok=False`, so
    `not result.ok` alone filed a durable, team-visible Errors row (carrying the
    model's own argv on the `Command:` line) the moment SOL *proposed* an action,
    before any person saw the card. Sniffing the UNAUTHORIZED code instead would
    be a different lie: a tool that refuses AFTER running must still file. The
    two sites that know: the runner (a gated tool is never executed in a turn)
    and `confirmations.decide_confirmation` (the one place it is).
    """
    if not (executed and descriptor is not None and descriptor.files_errors):
        return False
    return not result.ok or run_failure(result) is not None


async def file_tool_error(
    sessionmaker: async_sessionmaker[AsyncSession] | Callable[[], Any],
    *,
    project_id: Any,
    user_id: Any,
    call: ToolCall,
    result: ToolResult,
    descriptor: ToolDescriptor | None,
    executed: bool,
) -> None:
    """File the failure (when the descriptor asks for it, and the call RAN) and
    emit `solus.entry_added`. Never raises — see the module docstring."""
    if not should_file(result, descriptor, executed=executed):
        return
    try:
        async with sessionmaker() as session:
            try:
                entry, event_type = await _file_or_bump(
                    session, project_id=project_id, user_id=user_id, call=call, result=result
                )
                user = await session.get(User, user_id)
                project = await session.get(Project, project_id)
                if user is not None:
                    emit_event(
                        session,
                        user=user,
                        event_type=event_type,
                        team_id=project.team_id if project is not None else None,
                        project_id=project_id,
                        payload={
                            "entry_id": str(entry.id),
                            "section": SolusSection.ERRORS.value,
                            "subsection": None,
                            "kind": entry.kind.value,
                            "tool": call.tool,
                            "auto": True,
                        },
                    )
                await session.commit()
            except Exception:
                # The session may be the CALLER's (decide_confirmation hands its
                # own in), and a half-applied statement would poison the outer
                # transaction for everything after. Hand it back usable.
                await session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — the filing must never fail the turn
        logger.warning(
            "error filing skipped tool=%.128r call_id=%.128r project=%s reason=%s",
            call.tool,
            call.call_id,
            project_id,
            type(exc).__name__,
        )


async def _file_or_bump(
    session: AsyncSession, *, project_id: Any, user_id: Any, call: ToolCall, result: ToolResult
) -> tuple[SolusEntry, str]:
    """One row per distinct failure: bump the live entry with this key, else file a new one.
    Returns the entry and the event it warrants."""
    now = datetime.now(UTC)
    key = error_dedupe_key(call.tool, _redacted_command(call), _error_code(result))
    await lock_project(session, project_id)
    existing = await session.scalar(
        select(SolusEntry).where(
            SolusEntry.project_id == project_id,
            SolusEntry.section == SolusSection.ERRORS,
            SolusEntry.deleted_at.is_(None),
            SolusEntry.payload["dedupe_key"].astext == key,
        )
    )
    if existing is not None:
        meta = ErrorMeta.model_validate(existing.payload)
        status = "recurring" if meta.status == "resolved" else meta.status
        existing.payload = meta.model_copy(
            update={"count": meta.count + 1, "last_seen": now, "status": status}
        ).model_dump(mode="json")
        await session.flush()
        return existing, "solus.entry_updated"
    meta = ErrorMeta(
        entity_id=await _project_entity(session, project_id, _entity_ref(call.args)),
        machine_id=None,
        dedupe_key=key,
        count=1,
        status="open",
        fix_ref=None,
        first_seen=now,
        last_seen=now,
    )
    entry = await add_text_entry(
        session,
        project_id,
        SolusSection.ERRORS,
        format_error_entry(call, result, now=now),
        author="sol",
        created_by=user_id,
        payload=meta.model_dump(mode="json"),
    )
    return entry, "solus.entry_added"
