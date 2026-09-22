"""Persisted approval restoration and cross-turn reuse never invoke a tool."""

import asyncio
import uuid
from datetime import timedelta

from conftest import BOB, add_member, me
from solus_api.agent.confirmations import request_confirmation
from solus_api.agent.tools.shapes import ToolCall
from solus_api.models import ConfirmationStatus, Conversation, ToolConfirmation, utcnow
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_confirmations import _registry, _scope
from test_sol import _create_conversation, _project


async def test_restore_scoped_pending_without_arguments(client, alice_headers, bob_headers, db):
    team, project = await _project(client, alice_headers)
    conversation = await _create_conversation(client, alice_headers, project["id"])
    owner = (await me(client, alice_headers))["id"]
    common = dict(
        project_id=uuid.UUID(project["id"]),
        team_id=uuid.UUID(team["id"]),
        user_id=uuid.UUID(owner),
        conversation_id=uuid.UUID(conversation["id"]),
        tool="code.run",
        args={"private": "not returned"},
        summary="Run build",
        preview=[{"label": "Command", "before": None, "after": "python build.py"}],
    )
    active = ToolConfirmation(**common, expires_at=utcnow() + timedelta(minutes=5))
    expired = ToolConfirmation(**common, expires_at=utcnow() - timedelta(seconds=1))
    decided = ToolConfirmation(
        **common, status=ConfirmationStatus.APPROVED, expires_at=utcnow() + timedelta(minutes=5)
    )
    db.add_all([active, expired, decided])
    await db.commit()
    url = f"/api/v1/projects/{project['id']}/sol/conversations/{conversation['id']}/confirmations"
    response = await client.get(url, headers=alice_headers)
    assert response.status_code == 200
    rows = response.json()["data"]
    assert [row["confirmation_id"] for row in rows] == [str(active.id)]
    assert rows[0]["preview"] == active.preview
    assert "args" not in rows[0]
    assert (await client.get(url)).status_code == 401
    await me(client, bob_headers)
    assert (await client.get(url, headers=bob_headers)).status_code == 404
    await add_member(client, alice_headers, bob_headers, BOB, team["id"])
    assert (await client.get(url, headers=bob_headers)).status_code == 404


async def test_cross_turn_concurrent_identical_pending_reuses_original(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project, team, user = await _scope(maker)
    async with maker() as db:
        conversation = Conversation(project_id=project, team_id=team, created_by=user)
        db.add(conversation)
        await db.commit()
    record = []
    registry = _registry(record)

    async def park():
        async with maker() as db:
            result = await request_confirmation(
                db,
                registry,
                ToolCall(tool="onshape.set_variable", args={"name": "width"}),
                project_id=project,
                team_id=team,
                user_id=user,
                conversation_id=conversation.id,
            )
            await db.commit()
            return result

    first, second = await asyncio.gather(park(), park())
    assert first.confirmation_id == second.confirmation_id
    assert first.preview == second.preview
    assert record == []
    async with maker() as db:
        row = await db.get(ToolConfirmation, first.confirmation_id)
        row.expires_at = utcnow() - timedelta(seconds=1)
        await db.commit()
    third = await park()
    assert third.confirmation_id != first.confirmation_id
    async with maker() as db:
        row = await db.get(ToolConfirmation, third.confirmation_id)
        row.status = ConfirmationStatus.APPROVED
        await db.commit()
    fourth = await park()
    assert fourth.confirmation_id not in {first.confirmation_id, third.confirmation_id}
    async with maker() as db:
        other = Conversation(project_id=project, team_id=team, created_by=user)
        db.add(other)
        await db.flush()
        separate = await request_confirmation(
            db,
            registry,
            ToolCall(tool="onshape.set_variable", args={"name": "width"}),
            project_id=project,
            team_id=team,
            user_id=user,
            conversation_id=other.id,
        )
        different = await request_confirmation(
            db,
            registry,
            ToolCall(tool="onshape.set_variable", args={"name": "height"}),
            project_id=project,
            team_id=team,
            user_id=user,
            conversation_id=conversation.id,
        )
        await db.commit()
    assert separate.confirmation_id != fourth.confirmation_id
    assert different.confirmation_id != fourth.confirmation_id
    assert record == []
