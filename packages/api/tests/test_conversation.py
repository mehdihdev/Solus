"""Conversation/session service (SOLUS-SYS-01) — persistence + scope.

DB-backed unit tests. Proves create/append/history and, most importantly, that the
ownership+tenant scope is enforced in the service: a conversation is reachable only
through its `(project_id, created_by)` — a different project OR a different user in
the same project gets None (no cross-tenant / cross-user oracle, CLAUDE.md §7).
"""

import uuid

from solus_api.agent.conversation import (
    ConversationService,
    serialize_conversation,
    serialize_turn,
)
from solus_api.models import (
    Project,
    Team,
    TeamKind,
    TurnRole,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession

SERVICE = ConversationService()


async def _seed_project(
    session: AsyncSession, *, owner_email: str = "o@x.io"
) -> tuple[User, Team, Project]:
    user = User(supabase_user_id=uuid.uuid4().hex, email=owner_email)
    team = Team(name="T", kind=TeamKind.COLLABORATIVE)
    session.add_all([user, team])
    await session.flush()
    project = Project(team_id=team.id, name="Rover", created_by=user.id)
    session.add(project)
    await session.flush()
    return user, team, project


async def test_create_and_get_owned_roundtrip(db: AsyncSession) -> None:
    user, team, project = await _seed_project(db)
    convo = await SERVICE.create(
        db, project_id=project.id, team_id=team.id, user_id=user.id, title="Debug I2C"
    )
    found = await SERVICE.get_owned(
        db, conversation_id=convo.id, project_id=project.id, user_id=user.id
    )
    assert found is not None
    assert found.id == convo.id
    assert found.title == "Debug I2C"


async def test_append_turns_are_ordered_history(db: AsyncSession) -> None:
    user, team, project = await _seed_project(db)
    convo = await SERVICE.create(db, project_id=project.id, team_id=team.id, user_id=user.id)
    await SERVICE.append_turn(
        db, conversation_id=convo.id, project_id=project.id, role=TurnRole.USER, content="hi"
    )
    await SERVICE.append_turn(
        db,
        conversation_id=convo.id,
        project_id=project.id,
        role=TurnRole.ASSISTANT,
        content="hello",
        attrs={"sol_mode": "guide"},
    )
    history = await SERVICE.history(db, conversation_id=convo.id, project_id=project.id)
    assert [t.role for t in history] == [TurnRole.USER, TurnRole.ASSISTANT]
    assert history[1].attrs == {"sol_mode": "guide"}


async def test_get_owned_is_scoped_to_project(db: AsyncSession) -> None:
    user, team, project = await _seed_project(db)
    convo = await SERVICE.create(db, project_id=project.id, team_id=team.id, user_id=user.id)
    # A different project id must not resolve the conversation.
    other = await SERVICE.get_owned(
        db, conversation_id=convo.id, project_id=uuid.uuid4(), user_id=user.id
    )
    assert other is None


async def test_get_owned_is_scoped_to_owner(db: AsyncSession) -> None:
    user, team, project = await _seed_project(db)
    convo = await SERVICE.create(db, project_id=project.id, team_id=team.id, user_id=user.id)
    # A different user in the SAME project cannot reach another user's conversation.
    intruder = await SERVICE.get_owned(
        db, conversation_id=convo.id, project_id=project.id, user_id=uuid.uuid4()
    )
    assert intruder is None


async def test_serializers_shape(db: AsyncSession) -> None:
    user, team, project = await _seed_project(db)
    convo = await SERVICE.create(
        db, project_id=project.id, team_id=team.id, user_id=user.id, title="X"
    )
    turn = await SERVICE.append_turn(
        db, conversation_id=convo.id, project_id=project.id, role=TurnRole.TOOL, content="{}"
    )
    cs = serialize_conversation(convo)
    assert cs["id"] == convo.id and cs["title"] == "X" and cs["created_by"] == user.id
    ts = serialize_turn(turn)
    assert ts["role"] == "tool" and ts["conversation_id"] == convo.id
