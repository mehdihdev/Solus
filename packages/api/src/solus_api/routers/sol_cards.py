"""SOLUSDEV-326 — the open-card slot, and the answer to a question card.

`GET /sol/cards/open` is what the Hardware page's one slot shows (docs/contracts/action-gate.md
§Cards 3): the caller's oldest PENDING, unexpired row with a card in this project, across their live
conversations, and how many more wait behind it. A row with no card (an Onshape edit, `code.exec`,
a drive step) never reaches the slot, and another member's never does either: only the person a
call was parked for may see or decide it.

`MessageCreate.answer` answers an open `ask_user` card the caller owns (§Cards 5). The route reads
the question when it admits the turn (`answer_prompt`; anything else is 404) and closes it in the
same transaction as the person's turn, after the budget gates (`close_question`): 0 → approved,
1 → rejected, no new status. A question is answered only in the conversation it was asked in. The
turn's words are written by the server: `Chose "<label>"` (the stored button label, JSON-quoted
as data) plus what the person typed. The decide route never takes a question (`confirmations`).

It also answers an open card whose stored `card.field` is set: an edit. `text` is the new value
(choice 0, else 422), the turn reads `<field.label>: "<text>"`, and the card expires without being
decided, so editing a device card is never the "Not now" a reject of it is.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Final

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import ColumnElement, select, update

from solus_api.agent.cards import oldest_showable_card
from solus_api.agent.confirmations import ASK_USER_TOOL
from solus_api.contracts.action_gate import OpenCard, OpenCards, QuestionAnswer
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import ProjectCtx, SessionDep, require_role
from solus_api.models import ConfirmationStatus, Role, ToolConfirmation, utcnow
from solus_api.services.events import emit_event

router = APIRouter(prefix="/api/v1/projects/{project_id}/sol")
logger = logging.getLogger("solus.routers.sol_cards")

#: What a declined question with no second button answers: the slot's dismiss.
NOT_NOW: Final = "Not now"
_NO_QUESTION: Final = "No such open question."


class OpenCardsEnvelope(BaseModel):
    data: OpenCards


@router.get("/cards/open", response_model=OpenCardsEnvelope)
async def open_cards(ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    """The slot's card: the caller's oldest open card here, and how many more wait (`queued`)."""
    require_role(ctx, Role.MEMBER)
    found = await oldest_showable_card(
        session, ctx.project.id, ctx.user.id, ToolConfirmation.team_id == ctx.team.id
    )
    if found is None:
        return envelope(OpenCards(card=None, queued=0).model_dump(mode="json"))
    row, shown, total = found
    card = OpenCard(
        confirmation_id=str(row.id),
        conversation_id=str(row.conversation_id),
        tool=row.tool,
        card=shown,
        expires_at=row.expires_at.isoformat(),
    )
    return envelope(OpenCards(card=card, queued=total - 1).model_dump(mode="json"))


def _question_id(answer: QuestionAnswer) -> uuid.UUID:
    try:
        return uuid.UUID(answer.question_id)
    except ValueError:
        raise APIError(404, "not_found", _NO_QUESTION) from None


def _open_card(
    ctx: ProjectCtx, conversation_id: uuid.UUID, card_id: uuid.UUID
) -> tuple[ColumnElement[bool], ...]:
    """One of the caller's open cards in this conversation."""
    return (
        ToolConfirmation.id == card_id,
        ToolConfirmation.conversation_id == conversation_id,
        ToolConfirmation.project_id == ctx.project.id,
        ToolConfirmation.team_id == ctx.team.id,
        ToolConfirmation.user_id == ctx.user.id,
        ToolConfirmation.status == ConfirmationStatus.PENDING,
        ToolConfirmation.expires_at > utcnow(),
        ToolConfirmation.card.is_not(None),
    )


def _edit_prompt(field: dict[str, Any], answer: QuestionAnswer) -> str:
    """An edit in words: `<field.label>: "<text>"`. The label is the stored card's, which Solus
    wrote; what the person typed goes in JSON-quoted as data. 422 unless it is the first choice
    with something typed."""
    typed = (answer.text or "").strip()
    if answer.choice != 0 or not typed:
        raise APIError(422, "validation_error", "An edit is choice 0 with the new value as text")
    return f"{field['label']}: {json.dumps(typed, ensure_ascii=False)}"


async def answer_prompt(
    session: SessionDep, ctx: ProjectCtx, conversation_id: uuid.UUID, answer: QuestionAnswer
) -> str:
    """The person's answer in words. A question: `Chose "<label>"`, then what they typed. An
    edit: `<field.label>: "<text>"`. 404 unless it names one of the caller's open cards in this
    conversation that is an `ask_user` question or shows a field. Reads only.

    A question's label is the STORED, masked card's, but a model wrote it and this turn rides the
    slot Solus's own "[Solus] …" resume and wake prompts use: it goes in JSON-quoted as data,
    after Solus's word, so it never opens the turn or reads as Solus's framing."""
    found = (
        await session.execute(
            select(ToolConfirmation.tool, ToolConfirmation.card).where(
                *_open_card(ctx, conversation_id, _question_id(answer))
            )
        )
    ).first()
    if found is None:
        raise APIError(404, "not_found", _NO_QUESTION)
    card: dict[str, Any] = found.card
    if found.tool != ASK_USER_TOOL:
        if not card.get("field"):
            raise APIError(404, "not_found", _NO_QUESTION)
        return _edit_prompt(card["field"], answer)
    label = card["primary"] if answer.choice == 0 else card.get("secondary") or NOT_NOW
    chose = f"Chose {json.dumps(str(label), ensure_ascii=False)}"
    typed = (answer.text or "").strip()
    return f"{chose} — {typed}" if typed else chose


async def _close_edited(
    session: SessionDep, ctx: ProjectCtx, conversation_id: uuid.UUID, card_id: uuid.UUID
) -> dict[str, Any]:
    """Expire an edited card without deciding it: no status, no `decided_at`, no decline hook, no
    event, so an edit is never the "Not now" a reject of a device card is. Returns what the turn
    is marked with."""
    card: dict[str, Any] | None = await session.scalar(
        update(ToolConfirmation)
        .where(
            *_open_card(ctx, conversation_id, card_id),
            ToolConfirmation.tool != ASK_USER_TOOL,
            ToolConfirmation.card["field"].astext.is_not(None),
        )
        .values(expires_at=utcnow())
        .returning(ToolConfirmation.card)
        .execution_options(synchronize_session=False)
    )
    if card is None:
        raise APIError(404, "not_found", _NO_QUESTION)
    return {"edit": True, "label": card["field"]["label"]}


async def close_question(
    session: SessionDep, ctx: ProjectCtx, conversation_id: uuid.UUID, answer: QuestionAnswer
) -> dict[str, Any]:
    """Settle the card with the turn that answers it, in the caller's transaction, and return the
    turn's `attrs.answer`. A question: 0 → approved, 1 → rejected. An edit: the card expires
    undecided. 404 when it was answered, or ran out, since it was read: the update re-checks it
    under the row lock, so two answers cannot both close it."""
    question_id = _question_id(answer)
    said = {"question_id": str(question_id), "choice": answer.choice}
    closed = await session.scalar(
        update(ToolConfirmation)
        .where(
            *_open_card(ctx, conversation_id, question_id),
            ToolConfirmation.tool == ASK_USER_TOOL,
        )
        .values(
            status=ConfirmationStatus.APPROVED
            if answer.choice == 0
            else ConfirmationStatus.REJECTED,
            decided_at=utcnow(),
        )
        .returning(ToolConfirmation.id)
        .execution_options(synchronize_session=False)
    )
    if closed is None:
        return {**said, **await _close_edited(session, ctx, conversation_id, question_id)}
    emit_event(
        session,
        user=ctx.user,
        event_type="sol.tool_confirmation_decided",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={
            "decision": "approve" if answer.choice == 0 else "reject",
            "ok": True,
            "confirmation_id": str(question_id),
            "tool": ASK_USER_TOOL,
        },
    )
    return said
