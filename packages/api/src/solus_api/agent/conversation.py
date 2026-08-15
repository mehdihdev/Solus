"""The conversation/session service (SOLUS-SYS-01).

Persists SOL chat sessions and their append-only turns, and is the ONE place that
enforces the ownership+tenant scope for a conversation: a row is reachable only
through `(project_id, created_by)`, so neither another tenant nor another teammate
in the same project can read or append to it. Routers call these methods; they never
hand-roll the scoping predicate (CLAUDE.md §7 — tenant isolation is centralized).

Stateless by design — every method takes the `AsyncSession` to act within, so the
same service serves both a request-scoped session and the fresh session the SSE
generator opens after the response has started streaming.
"""

import uuid
from typing import Any, Final

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import Conversation, ConversationTurn, TurnRole

#: How many past turns reach the runner's context. Bounded because every one of
#: them is billed on every turn and is attacker-influenceable text that would
#: otherwise replay forever (CLAUDE.md §7).
HISTORY_TURN_LIMIT: Final = 20


class ConversationService:
    """Create/read conversations and append turns, always within the owner+project
    scope. No hidden state; safe to share as a module-level singleton."""

    async def create(
        self,
        session: AsyncSession,
        *,
        project_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
        title: str | None = None,
    ) -> Conversation:
        conversation = Conversation(
            project_id=project_id, team_id=team_id, created_by=user_id, title=title
        )
        session.add(conversation)
        await session.flush()
        return conversation

    def owned_query(
        self, *, project_id: uuid.UUID, user_id: uuid.UUID
    ) -> Select[tuple[Conversation]]:
        """The base scoped SELECT for a user's live conversations in a project —
        reused by list and get so the scope predicate is written exactly once."""
        return select(Conversation).where(
            Conversation.project_id == project_id,
            Conversation.created_by == user_id,
            Conversation.deleted_at.is_(None),
        )

    async def get_owned(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Conversation | None:
        """The conversation IF it is live, in this project, and owned by this user —
        else None. Out-of-scope ids return None (no cross-tenant/cross-user oracle)."""
        found: Conversation | None = await session.scalar(
            self.owned_query(project_id=project_id, user_id=user_id).where(
                Conversation.id == conversation_id
            )
        )
        return found

    async def append_turn(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        project_id: uuid.UUID,
        role: TurnRole,
        content: str,
        attrs: dict[str, Any] | None = None,
    ) -> ConversationTurn:
        """Append one turn (the log is append-only). `project_id` is stored denormalized
        so a turn stays team-scopable without joining back through the conversation."""
        turn = ConversationTurn(
            conversation_id=conversation_id,
            project_id=project_id,
            role=role,
            content=content,
            attrs=attrs or {},
        )
        session.add(turn)
        await session.flush()
        return turn

    def turns_query(
        self, *, conversation_id: uuid.UUID, project_id: uuid.UUID, newest_first: bool = False
    ) -> Select[tuple[ConversationTurn]]:
        """Turns of a conversation. Callers prove conversation ownership via `get_owned`
        first; `project_id` is pinned here too so the tenant scope is INTRINSIC to the
        query (defense in depth — the column is denormalized and indexed for exactly this).

        `newest_first` picks the order: DESC for the paginated list endpoint (so the
        `(created_at, id)` DESC cursor from `core.pagination` advances correctly, matching
        every other list in the API); ASC (chronological) for building the runner's live
        context, which reads the whole history unpaginated."""
        order = (
            (ConversationTurn.created_at.desc(), ConversationTurn.id.desc())
            if newest_first
            else (ConversationTurn.created_at.asc(), ConversationTurn.id.asc())
        )
        return (
            select(ConversationTurn)
            .where(
                ConversationTurn.conversation_id == conversation_id,
                ConversationTurn.project_id == project_id,
            )
            .order_by(*order)
        )

    async def history(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        project_id: uuid.UUID,
        limit: int = HISTORY_TURN_LIMIT,
    ) -> list[ConversationTurn]:
        """The recent ordered turn history, for the runner's live context.

        BOUNDED, deliberately. A model-backed runner puts every one of these
        turns into a paid prompt, so reading the whole log would be both a cost
        bomb on a long thread and a permanent injection foothold — one poisoned
        turn replaying into every future prompt forever.

        The newest `limit` turns are taken (DESC + limit, then re-sorted into
        chronological order), because dropping the OLDEST is what keeps the live
        thread coherent. The paginated `/turns` endpoint is unaffected: it reads
        `turns_query` directly and still serves the full transcript.
        """
        rows = (
            await session.scalars(
                self.turns_query(
                    conversation_id=conversation_id, project_id=project_id, newest_first=True
                ).limit(limit)
            )
        ).all()
        return sorted(rows, key=lambda turn: (turn.created_at, turn.id))


def serialize_conversation(conversation: Conversation) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "project_id": conversation.project_id,
        "title": conversation.title,
        "created_by": conversation.created_by,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def serialize_turn(turn: ConversationTurn) -> dict[str, Any]:
    return {
        "id": turn.id,
        "conversation_id": turn.conversation_id,
        "role": turn.role.value,
        "content": turn.content,
        "attrs": turn.attrs,
        "created_at": turn.created_at,
    }
