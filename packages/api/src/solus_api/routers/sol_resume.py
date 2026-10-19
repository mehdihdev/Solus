"""Continuing a SOL turn after an approved command (SOLUSDEV-317 §5.5).

`MessageCreate.resume_confirmation_id` lets the desktop start the next turn
once an approved command card finishes, so SOL can read the outcome and carry
on without the person retyping "continue". Admission is strict:

* the confirmation belongs to the caller, this project/team and THIS
  conversation (anything else is the same 404 — no existence oracle);
* it is decided and is one of the command tools;
* each confirmation resumes once — claimed ATOMICALLY on the decision's TOOL
  turn (`attrs.resumed`), so two concurrent requests cannot both start a turn;
  the assistant turn then records `{resume_of: <id>}`;
* at most `MAX_CONSECUTIVE_RESUMES` resume turns since the last message the
  person wrote — then SOL waits for them.

Budget pre-flight, the frequency cap and turn limits are applied by the route
exactly as for a typed message. No user turn is stored.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import ColumnElement, func, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.command_gate import COMMAND_TOOLS
from solus_api.core.errors import APIError
from solus_api.models import (
    ConfirmationStatus,
    Conversation,
    ConversationTurn,
    ToolConfirmation,
    TurnRole,
)

MAX_CONSECUTIVE_RESUMES: Final = 6
#: Solus-authored; it rides the turn's fenced user-message slot.
RESUME_PROMPT: Final = (
    "[Solus] The command you proposed was decided by the person and its outcome is the "
    "latest tool result in this conversation. Continue the task from that outcome. Report "
    "exactly what the result says; if it failed, explain why and propose the next step. "
    "If nothing remains to do, summarise the outcome briefly."
)


@dataclass(frozen=True)
class ResumeTicket:
    confirmation_id: uuid.UUID
    tool: str
    chain: int  # this resume's position since the person's last message (1-based)


def _decision_turn(
    conversation_id: uuid.UUID, project_id: uuid.UUID, confirmation_id: uuid.UUID
) -> tuple[ColumnElement[bool], ...]:
    return (
        ConversationTurn.conversation_id == conversation_id,
        ConversationTurn.project_id == project_id,
        ConversationTurn.role == TurnRole.TOOL,
        ConversationTurn.attrs["confirmation_id"].astext == str(confirmation_id),
    )


async def _chain_length(
    session: AsyncSession, conversation_id: uuid.UUID, project_id: uuid.UUID
) -> int:
    """Resumes since the person's last message: answered ones (assistant turns
    with `resume_of`) plus CLAIMED ones whose turn is still streaming (decision
    turns marked `resumed`), counted once per confirmation."""
    scope = (
        ConversationTurn.conversation_id == conversation_id,
        ConversationTurn.project_id == project_id,
    )
    last_user = await session.scalar(
        select(func.max(ConversationTurn.created_at)).where(
            *scope, ConversationTurn.role == TurnRole.USER
        )
    )
    since = () if last_user is None else (ConversationTurn.created_at > last_user,)
    answered = await session.scalars(
        select(ConversationTurn.attrs["resume_of"].astext).where(
            *scope,
            *since,
            ConversationTurn.role == TurnRole.ASSISTANT,
            ConversationTurn.attrs.has_key("resume_of"),
        )
    )
    claimed = await session.scalars(
        select(ConversationTurn.attrs["confirmation_id"].astext).where(
            *scope,
            *since,
            ConversationTurn.role == TurnRole.TOOL,
            ConversationTurn.attrs.has_key("resumed"),
        )
    )
    return len(set(answered) | set(claimed))


async def check_resume(
    session: AsyncSession,
    *,
    confirmation_id: uuid.UUID,
    conversation_id: uuid.UUID,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ResumeTicket:
    """Validate a resume request (no writes). Raises APIError.

    Locks the conversation row (§9 item 9) until the caller commits its claim,
    so two concurrent resumes cannot both pass the chain cap."""
    await session.scalar(
        select(Conversation.id)
        .where(Conversation.id == conversation_id, Conversation.project_id == project_id)
        .with_for_update()
    )
    row = await session.scalar(
        select(ToolConfirmation).where(
            ToolConfirmation.id == confirmation_id,
            ToolConfirmation.project_id == project_id,
            ToolConfirmation.team_id == team_id,
            ToolConfirmation.user_id == user_id,
            ToolConfirmation.conversation_id == conversation_id,
        )
    )
    if row is None:
        raise APIError(404, "not_found", "No such action.")
    if row.status is ConfirmationStatus.PENDING or row.tool not in COMMAND_TOOLS:
        raise APIError(
            422, "validation_error", "Only a decided command action can continue the turn."
        )
    decision = await session.scalar(
        select(ConversationTurn).where(
            *_decision_turn(conversation_id, project_id, confirmation_id)
        )
    )
    if decision is None:
        raise APIError(422, "validation_error", "This action's outcome is not recorded yet.")
    if decision.attrs.get("resumed") is True:
        raise APIError(409, "already_resumed", "This action already continued the turn.")
    chain = await _chain_length(session, conversation_id, project_id)
    if chain >= MAX_CONSECUTIVE_RESUMES:
        raise APIError(
            409, "resume_limit", "SOL has continued on its own enough times; send a message."
        )
    return ResumeTicket(confirmation_id=confirmation_id, tool=row.tool, chain=chain + 1)


async def claim_resume(
    session: AsyncSession,
    ticket: ResumeTicket,
    *,
    conversation_id: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """Atomically mark the decision turn resumed; 409 if another request won.
    The caller commits with the rest of its admission writes."""
    claimed = await session.scalar(
        update(ConversationTurn)
        .where(
            *_decision_turn(conversation_id, project_id, ticket.confirmation_id),
            ~ConversationTurn.attrs.has_key("resumed"),
        )
        .values(attrs=ConversationTurn.attrs.op("||")(literal({"resumed": True}, JSONB)))
        .returning(ConversationTurn.id)
        .execution_options(synchronize_session=False)
    )
    if claimed is None:
        raise APIError(409, "already_resumed", "This action already continued the turn.")
