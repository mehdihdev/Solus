"""SOLUSDEV-321 P6 — how expert a project member is, per domain, and the register SOL speaks in.

`compute_expertise(session, project_id, user_id)` reads two signals. Both are transient: they are
never stored and never logged.

- **The member's repos.** The live entities the member's own code sources landed
  (`Source.created_by`; GitHub, GitLab and local folders), counted per domain up to EXPERT_SIGNAL:
  electronics (schematic and board projects, their exports and files), mechanical (CAD folders
  and documents, STEP and mesh files), software (code files and modules, sketches, requirements,
  ROS nodes) and control (ROS nodes, files whose path names a controller, a policy, PID, MPC or
  kinematics, and the files the software reader found a module interface in).
- **The questions.** The member's own USER turns in conversations they own in this project, the
  last MAX_QUESTIONS. Per domain they split into basic questions ("what is", "what does … mean",
  "explain", "how do I", "new to") and other mentions of the domain.

The level: `expert` when the repo signal reaches EXPERT_SIGNAL and the member has asked about the
domain, the basic questions at most half the others; `novice` when there is no repo signal and
the basic questions outnumber the others; otherwise `working`, the neutral register. Repos alone
reach `working` at most (P6 fix 1, m6): whoever connected a large team repo is not `expert` in
every domain it holds, a terse register their teammates can read.

Only the four levels are stored, on the member node (`attrs.expertise`, the JSONB reassigned),
because `member.attrs` is readable by every teammate: no count, no question and no path ever
lands there. The node itself is made only when the person registers a machine
(`services/machines.ensure_member`): a sync lands only what the connector produced, so without
one nothing is stored and the register stays unchanged (R168). The person's own `expertise`
preference wins per domain (`turn_expertise`), and `register_line` turns the levels into the one
Solus-authored line the system prompt carries. Recomputed after a code source's sync
(`recompute_after_sync`) and once a day by the hourly sweep (`recompute_due_expertise`). No model
is called.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import ColumnElement, String, and_, cast, func, or_, select

from solus_api.agent.preferences import ExpertiseLevel, ExpertiseOverride
from solus_api.graph import kinds
from solus_api.models import (
    Conversation,
    ConversationTurn,
    GraphEntity,
    Membership,
    MembershipStatus,
    Project,
    Source,
    SourceType,
    TurnRole,
)
from solus_api.services.solus_graph import lock_project

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("solus.agent.expertise")

EXPERTISE_KEY: Final = "expertise"
#: Repo entities that make a domain's signal enough for `expert` (counted no further).
EXPERT_SIGNAL: Final = 10
MAX_QUESTIONS: Final = 200
MAX_QUESTION_CHARS: Final = 2_000
#: The sweep at this UTC hour recomputes, once a day. It runs after change detection, inside that
#: cron job's 300 s ARQ timeout (arq's default `job_timeout`): at most MAX_DAILY_MEMBERS members a
#: run, each cut off at MEMBER_TIMEOUT_SECONDS, so it adds at most 100 × 1 s = 100 s to the job.
#: A member cut off (its project locked by a sync, say) is still among the oldest the next day.
EXPERTISE_HOUR_UTC: Final = 3
MAX_DAILY_MEMBERS: Final = 100
MEMBER_TIMEOUT_SECONDS: Final = 1.0
CODE_SOURCES: Final = frozenset({SourceType.GITHUB, SourceType.GITLAB, SourceType.LOCAL})

_ELECTRONICS_KINDS: Final = ("kicad_project", "altium_project", kinds.DESIGN_EXPORT)
_ELECTRONICS_SUFFIXES: Final = (
    ".kicad_sch",
    ".kicad_pcb",
    ".kicad_pro",
    ".schdoc",
    ".pcbdoc",
    ".sch",
    ".brd",
    ".net",
    ".cir",
    ".gbr",
)
_MECHANICAL_KINDS: Final = ("cad_folder", kinds.CAD_DOCUMENT)
_MECHANICAL_SUFFIXES: Final = (".step", ".stp", ".stl", ".iges", ".igs", ".f3d", ".scad")
_SOFTWARE_KINDS: Final = (
    kinds.CODE_MODULE,
    kinds.ARDUINO_SKETCH,
    "python_code",
    kinds.PYTHON_REQUIREMENT,
    kinds.PACKAGE_REQUIREMENT,
    kinds.ROS_NODE,
)
_SOFTWARE_SUFFIXES: Final = (
    ".py",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".ino",
    ".rs",
    ".go",
    ".java",
    ".js",
    ".ts",
)
_CONTROL_WORDS: Final = ("controller", "policy", "pid", "mpc", "kinematic")
#: A question's words that name each domain (word-bounded, any case).
DOMAIN_WORDS: Final = {
    "control": r"control\w*|pid|mpc|polic(?:y|ies)|kinematics?|trajector(?:y|ies)|setpoints?",
    "electronics": (
        r"circuits?|schematics?|pcbs?|voltages?|resistors?|capacitors?|i2c|spi|uart|netlists?"
        r"|transistors?|mosfets?|regulators?"
    ),
    "mechanical": r"cad|brackets?|mounts?|torques?|gears?|bearings?|tolerances?|assembl(?:y|ies)",
    "software": r"code|functions?|compil\w*|python|librar(?:y|ies)|packages?|ros|firmware|bugs?",
}
_BASIC: Final = (
    r"\b(?:what\s+is|what's|what\s+are|what\s+does\b.{0,60}\bmean|explain|how\s+do\s+i|new\s+to)\b"
)
#: Solus-authored register for a level; `working` says nothing.
_REGISTER: Final = {
    "novice": "explain fundamentals and define terms",
    "expert": "be terse and skip basics",
}


class Expertise(BaseModel):
    """A member's level per domain; `working` is the neutral default, the register unchanged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    control: ExpertiseLevel = "working"
    electronics: ExpertiseLevel = "working"
    mechanical: ExpertiseLevel = "working"
    software: ExpertiseLevel = "working"


DOMAINS: Final = tuple(Expertise.model_fields)


def level_of(signal: int, basic: int, other: int) -> ExpertiseLevel:
    if signal >= EXPERT_SIGNAL and other > 0 and basic * 2 <= other:
        return "expert"
    if signal == 0 and basic > other:
        return "novice"
    return "working"


async def compute_expertise(
    session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> Expertise:
    """The member's levels from their repos and their questions (the module docstring)."""
    signal = await _repo_signal(session, project_id, user_id)
    basic, other = _question_counts(await _questions(session, project_id, user_id))
    return Expertise(
        **{domain: level_of(signal[domain], basic[domain], other[domain]) for domain in DOMAINS}
    )


async def store_expertise(
    session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> Expertise:
    """Compute the four levels and keep them on the member node, and nothing else; with no member
    node (the person registered no machine) nothing is stored, the levels only returned (R168).
    Flushes."""
    found = await compute_expertise(session, project_id, user_id)
    await lock_project(session, project_id)
    member = await _member_node(session, project_id, user_id)
    if member is not None:
        member.attrs = {**member.attrs, EXPERTISE_KEY: found.model_dump()}
        await session.flush()
    return found


async def turn_expertise(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    override: ExpertiseOverride | None,
) -> Expertise | None:
    """The levels a turn speaks to: the stored ones, each domain the person stated replaced by
    theirs. None when nothing is stored and nothing stated (the register stays as it is)."""
    stored = await _stored(session, project_id, user_id)
    stated = override.model_dump(exclude_none=True) if override is not None else {}
    if stored is None and not stated:
        return None
    return (stored or Expertise()).model_copy(update=stated)


def register_line(expertise: Expertise | None) -> str | None:
    """The one Solus-authored line the prompt carries for the levels; None when every domain is
    `working`. Built from the validated literals alone."""
    if expertise is None:
        return None
    said = [
        f"{_REGISTER[level]} in {domain} ({level})"
        for domain, level in expertise.model_dump().items()
        if level in _REGISTER
    ]
    return f"By domain: {'; '.join(said)}." if said else None


async def recompute_after_sync(
    sessionmaker: async_sessionmaker[AsyncSession], source_id: uuid.UUID
) -> None:
    """After a code source's sync, its creator's levels, when they are still a member. Never
    raises: a sync never fails for this."""
    try:
        async with sessionmaker() as session:
            source = await session.get(Source, source_id)
            if source is None or source.type not in CODE_SOURCES or source.created_by is None:
                return
            if not await _is_member(session, source.team_id, source.created_by):
                return
            await store_expertise(session, source.project_id, source.created_by)
            await session.commit()
    except Exception:  # noqa: BLE001 — expertise is best-effort; the sync stands
        logger.warning("expertise recompute failed source=%s", source_id, exc_info=True)


async def recompute_due_expertise(
    sessionmaker: async_sessionmaker[AsyncSession], *, now: datetime
) -> int:
    """The hourly sweep's daily due check: at EXPERTISE_HOUR_UTC, the levels of at most
    MAX_DAILY_MEMBERS member nodes, those updated longest ago first, each in its own
    transaction cut off at MEMBER_TIMEOUT_SECONDS. Only a live project's ACTIVE, undeleted
    memberships are listed, and each is checked again before it is written (R139), as
    `recompute_after_sync` checks: a person who left keeps the value last computed, untouched.
    Returns how many were stored; never raises."""
    if now.hour != EXPERTISE_HOUR_UTC:
        return 0
    try:
        async with sessionmaker() as session:
            rows = (await session.execute(_members_due())).all()
    except Exception:  # noqa: BLE001 — the sweep goes on without it
        logger.warning("expertise sweep could not list members", exc_info=True)
        return 0
    stored = 0
    for project_id, team_id, user_id in rows:
        stored += await _recompute_one(sessionmaker, project_id, team_id, user_id)
    logger.info("expertise sweep stored=%d of %d", stored, len(rows))
    return stored


def _members_due() -> Select[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
    """`(project, team, user)` of each member node whose person holds an ACTIVE membership of the
    project's team, the nodes updated longest ago first."""
    held = and_(
        Membership.team_id == Project.team_id,
        GraphEntity.canonical_key == func.concat("member:", cast(Membership.user_id, String)),
        Membership.deleted_at.is_(None),
        Membership.status == MembershipStatus.ACTIVE,
    )
    return (
        select(GraphEntity.project_id, Project.team_id, Membership.user_id)
        .join(Project, Project.id == GraphEntity.project_id)
        .join(Membership, held)
        .where(
            GraphEntity.kind == kinds.MEMBER,
            GraphEntity.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
        .order_by(GraphEntity.updated_at, GraphEntity.id)
        .limit(MAX_DAILY_MEMBERS)
    )


async def _recompute_one(
    sessionmaker: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    try:
        async with asyncio.timeout(MEMBER_TIMEOUT_SECONDS), sessionmaker() as session:
            if not await _is_member(session, team_id, user_id):
                return 0  # removed between the listing and this write
            await store_expertise(session, project_id, user_id)
            await session.commit()
    except Exception:  # noqa: BLE001 — one member's failure, or its time, never stops the sweep
        logger.warning("expertise recompute failed project=%s", project_id, exc_info=True)
        return 0
    return 1


# ------------------------------------------------------------------------------ signals


async def _repo_signal(
    session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> dict[str, int]:
    """Per domain, the member's live repo entities, counted up to EXPERT_SIGNAL."""
    sources = select(Source.id).where(
        Source.project_id == project_id,
        Source.created_by == user_id,
        Source.type.in_(CODE_SOURCES),
    )
    path = func.lower(GraphEntity.attrs["path"].astext)
    code = GraphEntity.kind == kinds.CODE_FILE
    predicates = {
        "electronics": _kind_or_path(_ELECTRONICS_KINDS, code, path, _ELECTRONICS_SUFFIXES),
        "mechanical": _kind_or_path(_MECHANICAL_KINDS, code, path, _MECHANICAL_SUFFIXES),
        "software": _kind_or_path(_SOFTWARE_KINDS, code, path, _SOFTWARE_SUFFIXES),
        "control": or_(
            GraphEntity.kind == kinds.ROS_NODE,
            GraphEntity.attrs.has_key("module_interfaces"),
            and_(code, or_(*(path.like(f"%{word}%") for word in _CONTROL_WORDS))),
        ),
    }
    counts: dict[str, int] = {}
    for domain, predicate in predicates.items():
        held = (
            select(GraphEntity.id)
            .where(
                GraphEntity.project_id == project_id,
                GraphEntity.source_id.in_(sources),
                GraphEntity.deleted_at.is_(None),
                predicate,
            )
            .limit(EXPERT_SIGNAL)
            .subquery()
        )
        counts[domain] = int(await session.scalar(select(func.count()).select_from(held)) or 0)
    return counts


def _kind_or_path(
    entity_kinds: tuple[str, ...],
    code: ColumnElement[bool],
    path: ColumnElement[str],
    suffixes: tuple[str, ...],
) -> ColumnElement[bool]:
    """An entity of one of `entity_kinds`, or a code file whose path ends in one of `suffixes`."""
    return or_(
        GraphEntity.kind.in_(entity_kinds),
        and_(code, or_(*(path.like(f"%{suffix}") for suffix in suffixes))),
    )


async def _questions(session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> list[str]:
    """The member's own last MAX_QUESTIONS USER turns in conversations they own here."""
    rows = await session.scalars(
        select(ConversationTurn.content)
        .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
        .where(
            Conversation.project_id == project_id,
            Conversation.created_by == user_id,
            Conversation.deleted_at.is_(None),
            ConversationTurn.project_id == project_id,
            ConversationTurn.role == TurnRole.USER,
        )
        .order_by(ConversationTurn.created_at.desc())
        .limit(MAX_QUESTIONS)
    )
    return [text[:MAX_QUESTION_CHARS] for text in rows]


def _question_counts(questions: list[str]) -> tuple[Counter[str], Counter[str]]:
    """Per domain, the basic questions and the other mentions."""
    basic: Counter[str] = Counter()
    other: Counter[str] = Counter()
    for question in questions:
        asked = basic if re.search(_BASIC, question, re.IGNORECASE) else other
        for domain, words in DOMAIN_WORDS.items():
            if re.search(rf"\b(?:{words})\b", question, re.IGNORECASE):
                asked[domain] += 1
    return basic, other


async def _member_node(
    session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> GraphEntity | None:
    member: GraphEntity | None = await session.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kinds.MEMBER,
            GraphEntity.canonical_key == f"member:{user_id}",
            GraphEntity.deleted_at.is_(None),
        )
    )
    return member


async def _stored(
    session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> Expertise | None:
    member = await _member_node(session, project_id, user_id)
    raw = member.attrs.get(EXPERTISE_KEY) if member is not None else None
    if raw is None:
        return None
    try:
        return Expertise.model_validate(raw)
    except ValidationError:
        logger.warning("stored expertise left out project=%s", project_id)
        return None


async def _is_member(session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    membership = await session.scalar(
        select(Membership.id).where(
            Membership.team_id == team_id,
            Membership.user_id == user_id,
            Membership.deleted_at.is_(None),
            Membership.status == MembershipStatus.ACTIVE,
        )
    )
    return membership is not None
