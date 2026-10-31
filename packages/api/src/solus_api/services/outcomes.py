"""SOLUSDEV-321 P8 — outcomes as data: every decision on a SOL proposal is one `proposal_outcomes`
row (`models.ProposalOutcome`; the table: `docs/schemas/proposal-outcomes.md`).

A person approves, rejects or lets a card expire, the gate finds a card stale, or Build auto-runs an
owned routine. The router that saw the decision records it once — `routers/sol_confirmations.py`
for a card, `routers/sol.py:_record_build_outcome` for an auto-run — with the design as it stood:
each source's change token (`change_signals.snapshot_signals`), which the card route reads at the
click, before an approved tool runs (M5). A row holds identifiers and digests only, never the
arguments, a preview or a credential:

- `user_id`: the person who decided (R146). The project's members all list its outcomes; only the
  decider is shown a row's `machine_id`, decision turn and digest (`routers/outcomes.py`).
- `proposal_digest`: a code command's plan fingerprint as its card showed it (I2: only for a tool
  whose card is the server's `code.plan`), else sha256 of the call's redacted arguments (R147).
- `entity_ids`: every entity the call named under `ENTITY_KEYS` that is this project's own (M191;
  each verified as `agent/errors_filing.py` verifies its one, since arguments are model-proposed).
- `stale_reason`: a stale card's `diverged` or `quota` (M190), from the gate's refusal.
- `machine_id`: the person's own machine, when their companion is live in the project (the owner
  rule of `agent/project_card.py:machine_block`).

Each row emits one consent-gated `sol.proposal_outcome` event. Recording never fails a decision: it
runs in a savepoint of the caller's transaction, and a failure is one warning line.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.command_gate import PLAN_PREVIEW_TOOLS
from solus_api.agent.confirmations import NO_PREVIEW_MESSAGE
from solus_api.agent.errors_filing import _project_entity, _redact_args
from solus_api.agent.project_card import owns_machine
from solus_api.agent.tools.shapes import ToolErrorCode, ToolResult
from solus_api.agent.tools.untrusted import redact_value
from solus_api.models import ConfirmationStatus, ProposalOutcome
from solus_api.services.change_signals import snapshot_signals
from solus_api.services.events import emit_event
from solus_api.services.machines import find_machine

if TYPE_CHECKING:
    from solus_api.bridge.registry import BridgeSessionRegistry
    from solus_api.deps import ProjectContext

logger = logging.getLogger("solus.services.outcomes")

OutcomeDecision = Literal["accepted", "rejected", "edited", "accepted_auto", "expired", "stale"]
StaleReason = Literal["diverged", "quota", "no_preview"]
OUTCOME_EVENT: Final = "sol.proposal_outcome"
#: The column's width (`tool str64`); a longer tool name is cut to it.
TOOL_CHARS: Final = 64
#: A settled card's status → its outcome. A card still pending (its tool is gone) decided nothing.
_SETTLED: Final[Mapping[ConfirmationStatus, OutcomeDecision]] = {
    ConfirmationStatus.APPROVED: "accepted",
    ConfirmationStatus.REJECTED: "rejected",
    ConfirmationStatus.EXPIRED: "expired",
    ConfirmationStatus.STALE: "stale",
}
_FINGERPRINT_LABEL: Final = "plan fingerprint"
_SHA256_HEX: Final = re.compile(r"[0-9a-f]{64}")


#: The argument keys `entity_ids` is read from (M191), in this order.
ENTITY_KEYS: Final = (
    "entity_id",
    "focus_entity_ids",
    "robot_entity_id",
    "source_entity_id",
    "part_entity_id",
)
#: At most this many named ids are checked and kept: the arguments are model-proposed.
MAX_ENTITY_IDS: Final = 32


def stale_reason(decision: OutcomeDecision | None, result: ToolResult) -> StaleReason | None:
    """Why the gate found a card stale (M190), from its refusal: `quota` when its live preview was
    refused (the gate's UNAVAILABLE), `no_preview` when a tool that needs a complete preview
    produced none (`confirmations.NO_PREVIEW_MESSAGE`), else `diverged`. None for any other
    decision."""
    if decision != "stale" or result.error is None:
        return None
    if result.error.code is ToolErrorCode.UNAVAILABLE:
        return "quota"
    return "no_preview" if result.error.message == NO_PREVIEW_MESSAGE else "diverged"


def _named_ids(args: Mapping[str, Any]) -> list[uuid.UUID]:
    """Each well-formed id `args` names under `ENTITY_KEYS`, once, in order, at most
    `MAX_ENTITY_IDS`."""
    named: list[uuid.UUID] = []
    for key in ENTITY_KEYS:
        value = args.get(key)
        for item in value if isinstance(value, list) else [value]:
            try:
                found = uuid.UUID(str(item))
            except ValueError:
                continue
            if found not in named:
                named.append(found)
    return named[:MAX_ENTITY_IDS]


async def _project_entity_ids(
    session: AsyncSession, project_id: uuid.UUID, args: Mapping[str, Any]
) -> list[str]:
    """Every id the call names that is this project's own (M191), each verified, never copied.

    ponytail: one lookup per id (≤ `MAX_ENTITY_IDS`); one `IN` query if decisions get hot."""
    kept: list[str] = []
    for named in _named_ids(args):
        if await _project_entity(session, project_id, named) is not None:
            kept.append(str(named))
    return kept


def outcome_decision(
    before: ConfirmationStatus | None, after: ConfirmationStatus | None
) -> OutcomeDecision | None:
    """What one decide request did to a card, or None when it decided nothing: the card was settled
    before it (a second click), or it is still pending (its tool is gone)."""
    if before is not ConfirmationStatus.PENDING or after is None:
        return None
    return _SETTLED.get(after)


def _shown_fingerprint(preview: Sequence[Any]) -> str | None:
    """The 64 hex digits of the card's `plan fingerprint` row, when it has a well-formed one."""
    for row in preview:
        if isinstance(row, Mapping) and row.get("label") == _FINGERPRINT_LABEL:
            shown = str(row.get("after") or "").replace(":", "")
            if _SHA256_HEX.fullmatch(shown):
                return shown
    return None


def proposal_digest(tool: str, args: Mapping[str, Any], preview: Sequence[Any] = ()) -> str:
    """For a code command (its card is the server's own `code.plan`), the plan fingerprint the card
    showed. Any other card's labels can come from model-proposed or ingested text, so a
    `plan fingerprint` row there is ignored (I2). Otherwise sha256 of the call's arguments after
    error filing's redaction (secret-named keys, then `redact_value`) as canonical JSON: sorted
    keys, no whitespace, so identical redacted arguments digest alike.

    ponytail: unkeyed — no server key is designated for it, so an argument the redaction keeps (a
    path, a file's text) stays confirmable by re-hashing, which is why only the decider is shown
    it; a dedicated `SOLUS_DIGEST_KEY` would make this HMAC-SHA256 (R147)."""
    shown = _shown_fingerprint(preview) if tool in PLAN_PREVIEW_TOOLS else None
    if shown is not None:
        return shown
    redacted = redact_value(_redact_args(dict(args)))
    canonical = json.dumps(redacted, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _machine_id(
    session: AsyncSession, ctx: ProjectContext, bridge: BridgeSessionRegistry | None
) -> uuid.UUID | None:
    """The person's own machine, when their companion is live in this project. A companion id is
    client-supplied, so one claiming a teammate's machine gives None."""
    live = bridge.get(ctx.user.id, ctx.team.id, ctx.project.id) if bridge is not None else None
    if live is None:
        return None
    machine = await find_machine(session, ctx.project.id, live.companion_instance_id)
    return machine.id if machine is not None and owns_machine(machine.attrs, ctx.user.id) else None


async def signals_at_click(
    session: AsyncSession, project_id: uuid.UUID, confirmation_id: uuid.UUID
) -> dict[str, str]:
    """The design signals when the person clicked (M5), read before the decision in a savepoint of
    their own: a failed read is one warning line naming the card and empty signals, never a failed
    decision (N2). The card names the decision; it has no turn yet."""
    try:
        async with session.begin_nested():
            return await snapshot_signals(session, project_id)
    except Exception as exc:  # noqa: BLE001 — data collection never fails the decision it records
        logger.warning(
            "design signals unread project=%s confirmation=%s (%s)",
            project_id,
            confirmation_id,
            type(exc).__name__,
        )
        return {}


async def record_outcome(
    session: AsyncSession,
    ctx: ProjectContext,
    *,
    tool: str,
    args: Mapping[str, Any],
    decision: OutcomeDecision,
    conversation_turn_id: uuid.UUID | None = None,
    preview: Sequence[Any] = (),
    bridge: BridgeSessionRegistry | None = None,
    design_signals: Mapping[str, str] | None = None,
    stale_reason: StaleReason | None = None,
) -> uuid.UUID | None:
    """One row and its event, in a savepoint of the caller's transaction (the caller commits).
    `design_signals` are the ones read at the decision; None reads them now. `stale_reason` is a
    stale card's (`stale_reason()`). Returns the row's id, or None when recording failed — logged,
    never raised."""
    project_id = ctx.project.id
    try:
        async with session.begin_nested():
            entity_ids = await _project_entity_ids(session, project_id, args)
            signals = (
                dict(design_signals)
                if design_signals is not None
                else await snapshot_signals(session, project_id)
            )
            row = ProposalOutcome(
                project_id=project_id,
                user_id=ctx.user.id,
                conversation_turn_id=conversation_turn_id,
                tool=tool[:TOOL_CHARS],
                proposal_digest=proposal_digest(tool, args, preview),
                decision=decision,
                entity_ids=entity_ids,
                design_signals=signals,
                machine_id=await _machine_id(session, ctx, bridge),
                stale_reason=stale_reason,
            )
            session.add(row)
            await session.flush()
            emit_event(
                session,
                user=ctx.user,
                event_type=OUTCOME_EVENT,
                team_id=ctx.team.id,
                project_id=project_id,
                payload={
                    "outcome_id": str(row.id),
                    "tool": row.tool,
                    "decision": decision,
                    "proposal_digest": row.proposal_digest,
                },
            )
    except Exception as exc:  # noqa: BLE001 — data collection never fails the decision it records
        logger.warning(
            "proposal outcome not recorded tool=%.64r decision=%s project=%s (%s)",
            tool,
            decision,
            project_id,
            type(exc).__name__,
        )
        return None
    return row.id
