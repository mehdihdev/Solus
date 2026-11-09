"""SOLUSDEV-321 P6 — `agent/expertise.py`: a member's level per domain from their own repos and
the kinds of questions they ask. Only the four levels are stored, on the member node, because a
teammate can read `member.attrs`; the person's own preference wins per domain; and the levels set
the one Solus-authored register line the prompt carries."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from solus_api.agent import expertise
from solus_api.agent.expertise import (
    EXPERTISE_HOUR_UTC,
    Expertise,
    compute_expertise,
    recompute_after_sync,
    recompute_due_expertise,
    register_line,
    store_expertise,
    turn_expertise,
)
from solus_api.agent.preferences import ExpertiseOverride
from solus_api.graph import kinds
from solus_api.models import (
    Conversation,
    ConversationTurn,
    Domain,
    GraphEdge,
    GraphEntity,
    Membership,
    MembershipStatus,
    Project,
    SolusEntry,
    Source,
    SourceStatus,
    SourceType,
    Team,
    TurnRole,
    User,
)
from solus_api.services.machines import ensure_member
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


class _Member:
    def __init__(self, team_id: uuid.UUID, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.team_id, self.project_id, self.user_id = team_id, project_id, user_id


async def _member(
    db: AsyncSession, team_id: uuid.UUID | None = None, *, registered: bool = True
) -> _Member:
    """A team member; `registered` means they registered a machine, so their member node exists
    (R168: only that route creates one — a sync writes onto it, never makes it)."""
    if team_id is None:
        team = Team(name="expertise")
        db.add(team)
        await db.flush()
        team_id = team.id
    project = (await db.scalar(select(Project).where(Project.team_id == team_id))) or Project(
        team_id=team_id, name="expertise"
    )
    user = User(supabase_user_id=f"ex-{uuid.uuid4()}", email=f"{uuid.uuid4().hex[:8]}@ex.com")
    db.add_all([project, user])
    await db.flush()
    db.add(Membership(team_id=team_id, user_id=user.id))
    await db.flush()
    if registered:
        await ensure_member(db, project.id, user.id)
    return _Member(team_id, project.id, user.id)


async def _repo(
    db: AsyncSession, who: _Member, files: dict[str, str], kind: SourceType = SourceType.GITHUB
) -> Source:
    source = Source(
        project_id=who.project_id,
        team_id=who.team_id,
        type=kind,
        name="repo",
        status=SourceStatus.CONNECTED,
        config={},
        created_by=who.user_id,
    )
    db.add(source)
    await db.flush()
    db.add_all(
        GraphEntity(
            project_id=who.project_id,
            source_id=source.id,
            kind=entity_kind,
            domain=Domain.CODE,
            origin="manual",
            name=path,
            attrs={"path": path},
        )
        for path, entity_kind in files.items()
    )
    await db.flush()
    return source


async def _asked(db: AsyncSession, who: _Member, *questions: str) -> None:
    conversation = Conversation(
        project_id=who.project_id, team_id=who.team_id, created_by=who.user_id
    )
    db.add(conversation)
    await db.flush()
    db.add_all(
        ConversationTurn(
            conversation_id=conversation.id,
            project_id=who.project_id,
            role=TurnRole.USER,
            content=question,
        )
        for question in questions
    )
    await db.flush()


BASIC_ELECTRONICS = (
    "what is a schematic net?",
    "explain what a capacitor does in this circuit",
    "how do I read the pcb layers?",
)


async def test_levels_from_repos_and_questions_and_override(db: AsyncSession) -> None:
    me = await _member(db)
    teammate = await _member(db, me.team_id)
    await _repo(db, me, {f"src/node_{n}.py": kinds.CODE_FILE for n in range(12)})
    await _asked(db, me, *BASIC_ELECTRONICS, "refactor the python timer in the node")
    # a teammate's repos and questions never count for this member
    await _repo(db, teammate, {f"cad/part_{n}.step": kinds.CODE_FILE for n in range(12)})
    await _asked(
        db,
        teammate,
        "route the i2c bus on the pcb",
        "check the regulator schematic",
        "the uart circuit needs a resistor",
        "the gear mount bracket is tight",
    )

    found = await compute_expertise(db, me.project_id, me.user_id)

    assert found == Expertise(software="expert", electronics="novice")
    assert await compute_expertise(db, me.project_id, teammate.user_id) == Expertise(
        mechanical="expert"
    )
    stored = await store_expertise(db, me.project_id, me.user_id)
    stated = ExpertiseOverride(electronics="expert", control="novice")
    assert await turn_expertise(db, me.project_id, me.user_id, stated) == Expertise(
        software="expert", electronics="expert", control="novice"
    )
    assert await turn_expertise(db, me.project_id, me.user_id, None) == stored
    nobody = await _member(db, me.team_id)
    assert await turn_expertise(db, me.project_id, nobody.user_id, None) is None
    assert await turn_expertise(db, me.project_id, nobody.user_id, stated) == Expertise(
        electronics="expert", control="novice"
    )


def test_the_register_line_is_built_from_the_levels_alone() -> None:
    assert register_line(Expertise(control="novice", electronics="expert")) == (
        "By domain: explain fundamentals and define terms in control (novice); "
        "be terse and skip basics in electronics (expert)."
    )
    assert register_line(Expertise()) is None and register_line(None) is None


async def test_no_evidence_stored_on_member(db: AsyncSession) -> None:
    """`member.attrs` is readable by every teammate: it holds the display name and the four
    levels, and no question, count or path, anywhere."""
    me = await _member(db)
    token = f"zebra{uuid.uuid4().hex}"
    await _repo(db, me, {f"fw/{token}_{n}.ino": kinds.CODE_FILE for n in range(3)})
    await _asked(db, me, f"what is the {token} circuit?", f"explain {token} in the schematic")

    await store_expertise(db, me.project_id, me.user_id)
    await db.commit()

    (member,) = await db.scalars(
        select(GraphEntity).where(
            GraphEntity.project_id == me.project_id, GraphEntity.kind == kinds.MEMBER
        )
    )
    assert set(member.attrs) == {"display_name", "expertise"}
    assert set(member.attrs["expertise"]) == {"control", "electronics", "mechanical", "software"}
    assert set(member.attrs["expertise"].values()) <= {"novice", "working", "expert"}
    held = [
        *(
            json.dumps([e.name, e.attrs])
            for e in await db.scalars(select(GraphEntity))
            if e.kind != kinds.CODE_FILE
        ),
        *(json.dumps(e.attrs) for e in await db.scalars(select(GraphEdge))),
        *(json.dumps([s.text, s.payload]) for s in await db.scalars(select(SolusEntry))),
    ]
    assert held and not any(token in row for row in held)


async def test_a_code_sync_and_the_daily_sweep_recompute(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    me = await _member(db)
    source = await _repo(db, me, {f"src/m_{n}.py": kinds.CODE_FILE for n in range(12)})
    cad = await _repo(db, me, {}, kind=SourceType.ONSHAPE)
    await db.commit()
    maker = async_sessionmaker(engine, expire_on_commit=False)

    await recompute_after_sync(maker, cad.id)  # not a code source: nothing
    assert await turn_expertise(db, me.project_id, me.user_id, None) is None
    await recompute_after_sync(maker, source.id)
    db.expire_all()
    # P6 fix 1 (m6, a moved pin): repos alone reach `working`; `expert` needs the member's own
    # questions about the domain, so whoever connected a big team repo is not `expert` in it all
    assert await turn_expertise(db, me.project_id, me.user_id, None) == Expertise()
    await _asked(db, me, "refactor the python timer in the node")
    await db.commit()

    off_hour = datetime(2026, 10, 29, (EXPERTISE_HOUR_UTC + 1) % 24, tzinfo=UTC)
    on_hour = datetime(2026, 10, 29, EXPERTISE_HOUR_UTC, tzinfo=UTC)
    assert await recompute_due_expertise(maker, now=off_hour) == 0
    assert await recompute_due_expertise(maker, now=on_hour) == 1
    db.expire_all()
    assert await turn_expertise(db, me.project_id, me.user_id, None) == Expertise(software="expert")


async def test_a_code_sync_by_an_unregistered_member_lands_nothing(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """R168: a sync lands only what the connector produced. The levels go onto an existing member
    node — the one registering a machine creates — so a code-source sync by a person without one
    adds no entity and stores nothing; the levels are still computed and returned."""
    me = await _member(db, registered=False)
    source = await _repo(db, me, {f"src/m_{n}.py": kinds.CODE_FILE for n in range(12)})
    await db.commit()
    count = select(func.count()).select_from(GraphEntity)
    before = await db.scalar(count)

    assert await store_expertise(db, me.project_id, me.user_id) == Expertise()
    await db.commit()
    await recompute_after_sync(async_sessionmaker(engine, expire_on_commit=False), source.id)

    db.expire_all()
    assert await db.scalar(count) == before
    assert await turn_expertise(db, me.project_id, me.user_id, None) is None


async def test_the_sweep_writes_only_active_members(db: AsyncSession, engine: AsyncEngine) -> None:
    """R139: the daily sweep lists only ACTIVE, live memberships and checks again before it
    writes, as the post-sync recompute does. A member who left or was suspended keeps the value
    last computed, untouched: the sweep never writes a non-member's node."""
    me = await _member(db)
    gone, suspended = await _member(db, me.team_id), await _member(db, me.team_id)
    stale = Expertise(software="novice").model_dump()
    for who in (me, gone, suspended):
        await _repo(db, who, {f"src/{who.user_id}_{n}.py": kinds.CODE_FILE for n in range(12)})
        await store_expertise(db, who.project_id, who.user_id)
    for member in await db.scalars(select(GraphEntity).where(GraphEntity.kind == kinds.MEMBER)):
        member.attrs = {**member.attrs, "expertise": stale}
    for membership in await db.scalars(select(Membership)):
        if membership.user_id == gone.user_id:
            membership.deleted_at = datetime(2026, 10, 1, tzinfo=UTC)
        if membership.user_id == suspended.user_id:
            membership.status = MembershipStatus.SUSPENDED
    await db.commit()
    maker = async_sessionmaker(engine, expire_on_commit=False)

    swept = await recompute_due_expertise(
        maker, now=datetime(2026, 10, 29, EXPERTISE_HOUR_UTC, tzinfo=UTC)
    )

    db.expire_all()
    levels = {
        member.canonical_key: member.attrs["expertise"]["software"]
        for member in await db.scalars(select(GraphEntity).where(GraphEntity.kind == kinds.MEMBER))
    }
    assert swept == 1 and levels == {
        f"member:{me.user_id}": "working",  # repos alone (m6); the others keep the stale level
        f"member:{gone.user_id}": "novice",
        f"member:{suspended.user_id}": "novice",
    }


async def test_a_member_past_its_time_is_skipped_and_the_sweep_goes_on(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P6 fix 1 (m5): the sweep runs after change detection, inside the cron job's 300 s ARQ
    timeout, so each member is cut off at MEMBER_TIMEOUT_SECONDS: one that cannot finish (its
    project locked by a sync, say) is skipped, stays the oldest for the next day, and the sweep
    goes on to the others."""
    me, slow = await _member(db), await _member(db)
    stale = Expertise(software="novice")
    for who in (me, slow):
        await _repo(db, who, {f"src/{who.user_id}_{n}.py": kinds.CODE_FILE for n in range(12)})
        await store_expertise(db, who.project_id, who.user_id)
    for member in await db.scalars(select(GraphEntity).where(GraphEntity.kind == kinds.MEMBER)):
        member.attrs = {**member.attrs, "expertise": stale.model_dump()}
    await db.commit()
    stored = expertise.store_expertise

    async def store(session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> Any:
        if user_id == slow.user_id:
            await asyncio.sleep(5)
        return await stored(session, project_id, user_id)

    monkeypatch.setattr(expertise, "store_expertise", store)
    monkeypatch.setattr(expertise, "MEMBER_TIMEOUT_SECONDS", 0.2)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    swept = await recompute_due_expertise(
        maker, now=datetime(2026, 10, 29, EXPERTISE_HOUR_UTC, tzinfo=UTC)
    )

    db.expire_all()
    assert swept == 1
    assert await turn_expertise(db, slow.project_id, slow.user_id, None) == stale
    assert await turn_expertise(db, me.project_id, me.user_id, None) != stale
