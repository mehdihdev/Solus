"""SOLUSDEV-326 — `ask_user`: SOL asks the person one question as a card.

Ungated: asking changes nothing a person must approve. Registered only for a turn bound to a person
(the user branch of `build_sol_registry`). The arguments are held to the contract's `Card` bounds
by the schema, and the texts are made one printable, masked line like every card's
(`cards.shown_card`); a title that opens like an approval card's ("Approv…", read after NFKC, or
a first word with a non-ASCII letter) or a title or button that opens with "[Solus]" is refused,
and the stored arguments are the masked texts. A
call writes exactly ONE row and nothing else: a PENDING
`tool_confirmations` row with `tool = "ask_user"` and the card built from its arguments, `resumes`
true, expiring like any parked call, in the conversation the ROUTE bound for the turn
(`turn_context.current_conversation_id`) — the caller's own live one, re-checked here. It answers
`{question_id}`. The person answers through `MessageCreate.answer`; the decide route never takes
the row (docs/contracts/action-gate.md §Cards 5).
"""

from __future__ import annotations

import unicodedata
import uuid
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.cards import shown_card
from solus_api.agent.confirmations import ASK_USER_TOOL, CONFIRMATION_TTL
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.agent.turn_context import current_conversation_id
from solus_api.models import Conversation, ToolConfirmation, utcnow

#: The `Card` bounds (contracts/action_gate.py), held by the schema before the tool runs.
PARAMS: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "kind": {"enum": ["offer", "problem"]},
        "title": {"type": "string", "minLength": 1, "maxLength": 80},
        "body": {"type": "string", "maxLength": 400},
        "primary": {"type": "string", "minLength": 1, "maxLength": 24},
        "secondary": {"type": "string", "minLength": 1, "maxLength": 24},
    },
    "required": ["kind", "title", "body", "primary"],
    "additionalProperties": False,
}


def _imitates_solus(card: dict[str, Any]) -> bool:
    """A question dressed as the gate's or as Solus's own words: a title that opens like an
    approval card's ("Approve:" is the gate's alone, so nothing may open "approv…"), or a title
    or button that opens with the "[Solus]" mark of Solus's own turns — the button's label
    becomes the person's answer turn. Read after NFKC (a fullwidth "Ａ" is an "A").
    ponytail: no confusables table — a title whose first word holds any non-ASCII letter (a
    Cyrillic "А") is refused whole; add a skeleton if non-English titles must open that way."""
    opens = [
        unicodedata.normalize("NFKC", str(card.get(key) or "")).strip().casefold()
        for key in ("title", "primary", "secondary")
    ]
    first = opens[0].split(maxsplit=1)[0] if opens[0] else ""
    lookalike = any(ch.isalpha() and not ch.isascii() for ch in first)
    return (
        opens[0].startswith("approv")
        or lookalike
        or any(text.startswith("[solus]") for text in opens)
    )


class AskUserTool:
    """`ask_user`, bound to one project and person (the module docstring)."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
    ) -> None:
        self._sessions, self._project_id, self._user_id = sessions, project_id, user_id
        self._descriptor = ToolDescriptor(
            name=ASK_USER_TOOL,
            description=(
                "Ask the person one short question as a card with one or two buttons: an offer, "
                "or a problem they must act on. Their answer arrives as their next message. Ask "
                "instead of guessing a choice that is theirs."
            ),
            params=PARAMS,
            returns={"type": "object", "properties": {"question_id": {"type": "string"}}},
        )

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        conversation_id = current_conversation_id()
        if conversation_id is None:
            raise ToolException(
                "ask_user can only ask inside a conversation.", code=ToolErrorCode.UNAVAILABLE
            )
        try:
            card = shown_card({**args, "receipt": ""}, resumes=True, guide=False)
        except ValidationError:
            raise ToolException(
                "The question does not fit its card: keep each text within its bound.",
                code=ToolErrorCode.INVALID_ARGS,
            ) from None
        if _imitates_solus(card):
            raise ToolException(
                'A question\'s title cannot begin with "Approve" or "Approval" (those are an '
                "approval card's), its first word must be plain ASCII letters, and neither it nor "
                'a button can begin with "[Solus]". Reword it.',
                code=ToolErrorCode.INVALID_ARGS,
            )
        async with self._sessions() as session:
            team_id = await session.scalar(
                select(Conversation.team_id).where(
                    Conversation.id == conversation_id,
                    Conversation.project_id == self._project_id,
                    Conversation.created_by == self._user_id,
                    Conversation.deleted_at.is_(None),
                )
            )
            if team_id is None:
                raise ToolException("Conversation not found.", code=ToolErrorCode.NOT_FOUND)
            row = ToolConfirmation(
                project_id=self._project_id,
                team_id=team_id,
                user_id=self._user_id,
                conversation_id=conversation_id,
                tool=ASK_USER_TOOL,
                # The texts as the card shows them, never the model's raw ones.
                args={key: card[key] for key in args},
                summary=card["title"],
                preview=[],
                card=card,
                expires_at=utcnow() + CONFIRMATION_TTL,
            )
            session.add(row)
            await session.commit()
            return {"question_id": str(row.id)}


def register_ask_user(
    registry: ToolRegistry,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
) -> None:
    registry.register(AskUserTool(sessions, project_id, user_id=user_id))
