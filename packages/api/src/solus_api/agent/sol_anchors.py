"""Turn anchors that need the database or the transcript (SOLUSDEV-321 P0-T3).

`turn_scope.plan_scope` is pure: it ranks the anchors it is handed. What needs a session — is this
id visible, what are this finding's subjects — and what needs the transcript — which entities
did the last tool calls name — is decided here, by Solus code, from the ids a client sent and
the arguments of calls Solus recorded. Nothing a model wrote or a connector ingested decides
which entity becomes an anchor, or whether one may.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Collection, Iterable, Iterator
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.reason import UUID_RE, FocusIn
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.findings import load_finding, subject_rows
from solus_api.graph.read_scope import current_scope
from solus_api.models import ConversationTurn, GraphEntity, TurnRole

logger = logging.getLogger("solus.agent.anchors")

#: How many recently used entities a turn carries to the planner.
MAX_HISTORY_ENTITY_IDS: Final = 8


async def visible_entity_ids(
    session: AsyncSession,
    project_id: uuid.UUID,
    ids: Collection[uuid.UUID],
    *,
    kind: str | None = None,
) -> set[uuid.UUID]:
    """The ones among `ids` that are live entities (of `kind`, when given) in the caller's
    current view of this project. Foreign, deleted, hidden and absent ids are all simply
    missing from the answer — nothing tells them apart."""
    if not ids:
        return set()
    stmt = select(GraphEntity.id).where(
        GraphEntity.id.in_(list(ids)),
        GraphEntity.deleted_at.is_(None),
        current_scope(project_id).entity_predicate(),
    )
    if kind is not None:
        stmt = stmt.where(GraphEntity.kind == kind)
    return set((await session.scalars(stmt)).all())


async def require_turn_targets(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    finding_id: uuid.UUID | None,
    robot_id: uuid.UUID | None,
) -> None:
    """404 `not_found` unless the finding and the robot a turn names are this project's own
    live ones. A foreign id, an absent one, a deleted one and one of the wrong kind answer
    alike, so the refusal is no existence oracle."""
    if finding_id is not None:
        await load_finding(session, project_id, finding_id)
    if robot_id is not None:
        robots = await visible_entity_ids(
            session, project_id, [robot_id], kind=kinds.PHYSICAL_ROBOT
        )
        if robot_id not in robots:
            raise APIError(404, "not_found", "Robot not found")


def _one_level(value: object) -> Iterable[object]:
    if isinstance(value, dict):
        return value.values()
    return value if isinstance(value, list) else (value,)


def _arg_uuids(call: object) -> Iterator[uuid.UUID]:
    """UUID-shaped strings among a recorded call's arguments: the values themselves and, one
    level down, a list's items or a dict's values. Deeper than that is out of reach."""
    args = call.get("args") if isinstance(call, dict) else None
    if not isinstance(args, dict):
        return
    for value in args.values():
        for leaf in _one_level(value):
            if isinstance(leaf, str) and UUID_RE.fullmatch(leaf):
                yield uuid.UUID(leaf)


def prior_tool_entity_ids(turns: Iterable[ConversationTurn]) -> tuple[uuid.UUID, ...]:
    """Entities the conversation's recent tool calls named, newest call first — each id once,
    at most `MAX_HISTORY_ENTITY_IDS`. Only the arguments Solus recorded for each call are read
    (`attrs.call.args`); a user's prose and a call's result are not. The ids are unchecked
    hints for the planner, never anchors, and nothing here reaches a prompt."""
    found: dict[uuid.UUID, None] = {}
    for turn in reversed(list(turns)):
        # `attrs` is JSONB: a row whose attrs is not an object (old or hand-edited data) is
        # skipped, never a 500 on the conversation (cf. `history_evidence._evidence`).
        attrs: object = turn.attrs
        if turn.role is not TurnRole.TOOL or not isinstance(attrs, dict):
            continue
        for entity_id in _arg_uuids(attrs.get("call")):
            found.setdefault(entity_id)
            if len(found) == MAX_HISTORY_ENTITY_IDS:
                return tuple(found)
    return tuple(found)


@dataclass(frozen=True)
class ResolvedAnchors:
    """What the database added to the ids a turn arrived with."""

    #: The finding's live subjects, in blame order.
    finding_subjects: tuple[uuid.UUID, ...] = ()
    #: Ids among the auto-sent ones (the focus and its trail, the finding's subjects) that the
    #: caller's view of the project cannot see — dropped by the planner, never raised.
    not_visible: frozenset[uuid.UUID] = frozenset()


async def _finding_subject_ids(
    session: AsyncSession, project_id: uuid.UUID, finding_id: uuid.UUID | None
) -> tuple[uuid.UUID, ...]:
    if finding_id is None:
        return ()
    try:
        finding = await load_finding(session, project_id, finding_id)
    except APIError:
        # The route refused a finding it could not see at admission; one that has vanished
        # since carries on without its subjects — empty beats a failed turn.
        logger.info("finding gone before the run project=%s finding=%s", project_id, finding_id)
        return ()
    return tuple(row.id for row in await subject_rows(session, finding))


async def resolve_anchor_inputs(
    sessionmaker: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    focus: FocusIn | None,
    finding_id: uuid.UUID | None,
) -> ResolvedAnchors:
    """Resolve the anchors a turn names rather than lists: a finding's subjects, and which of
    the ids that were sent without a person choosing them are not visible. One read-only
    session, and none at all when the turn names neither."""
    if focus is None and finding_id is None:
        return ResolvedAnchors()
    async with sessionmaker() as session:
        subjects = await _finding_subject_ids(session, project_id, finding_id)
        wanted = {*(focus.ids() if focus else ()), *subjects}
        visible = await visible_entity_ids(session, project_id, wanted)
    not_visible = frozenset(wanted - visible)
    if not_visible:
        # A count, never the ids: they may be another team's.
        logger.info(
            "anchors not visible, dropped project=%s count=%d", project_id, len(not_visible)
        )
    return ResolvedAnchors(finding_subjects=subjects, not_visible=not_visible)
