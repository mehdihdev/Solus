"""SOLUSDEV-319 slice 4 (A4a) — tenant isolation for the turn's `front_app` (CLAUDE.md §7): it
binds only to the turn that carried it — the requesting user's own companion for THIS team and
project — is never stored, never reaches another turn, and never conjures `drive.step` from a
teammate's or another team's companion."""

from __future__ import annotations

import uuid
from typing import Any

from conftest import me
from httpx import AsyncClient
from solus_api.agent.drive.binding import FrontAppBinding
from solus_api.agent.drive.executor import Budget
from solus_api.agent.runtime import build_sol_registry, with_front_app
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.bridge.registry import InMemoryBridgeSessionRegistry
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import ConversationTurn
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_drive_isolation import Scope, _drive_session
from test_sol import _create_conversation, _project, _RecordingRunner
from test_sol_front_app import TITLE, WINDOW, _app_enum, _url

FRONT = FrontAppBinding.model_validate(WINDOW)


def _fronted(sessions: InMemoryBridgeSessionRegistry, scope: Scope) -> ToolRegistry:
    base = build_sol_registry(
        async_sessionmaker(),
        scope[2],
        bridge=sessions,
        user_id=scope[0],
        team_id=scope[1],
        secret_store=InMemorySecretStore(),
    )
    return with_front_app(
        base,
        FRONT,
        async_sessionmaker(),
        scope[2],
        bridge=sessions,
        user_id=scope[0],
        team_id=scope[1],
        call_cap_bytes=262_144,
        secret_store=InMemorySecretStore(),
        redis=None,
        enqueue=None,
        budget=Budget(),
    )


def test_front_app_never_conjures_drive_from_someone_elses_companion() -> None:
    me_scope: Scope = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    teammate: Scope = (uuid.uuid4(), me_scope[1], me_scope[2])
    other_team: Scope = (me_scope[0], uuid.uuid4(), uuid.uuid4())
    sessions = InMemoryBridgeSessionRegistry()
    for scope in (teammate, other_team):
        sessions.bind(_drive_session(scope, []))
    assert _app_enum(_fronted(sessions, me_scope).list()) is None
    sessions.bind(_drive_session(me_scope, []))
    assert _app_enum(_fronted(sessions, me_scope).list()) == ["front", "kicad"]


def test_with_front_app_keeps_every_other_tool_and_is_a_no_op_without_a_window() -> None:
    scope: Scope = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    sessions = InMemoryBridgeSessionRegistry()
    sessions.bind(_drive_session(scope, []))
    base = build_sol_registry(
        async_sessionmaker(),
        scope[2],
        bridge=sessions,
        user_id=scope[0],
        team_id=scope[1],
        secret_store=InMemorySecretStore(),
    )
    fronted = _fronted(sessions, scope)
    assert [d.name for d in fronted.list()] == [d.name for d in base.list()]
    denied = FrontAppBinding.model_validate(
        {
            **WINDOW,
            "title": None,
            "pid": None,
            "window_id": None,
            "drivable": False,
            "binding": None,
        }
    )
    same = with_front_app(
        base,
        denied,
        async_sessionmaker(),
        scope[2],
        bridge=sessions,
        user_id=scope[0],
        team_id=scope[1],
        call_cap_bytes=262_144,
        secret_store=InMemorySecretStore(),
        redis=None,
        enqueue=None,
        budget=Budget(),
    )
    assert same is base


async def test_a_team_b_turn_cannot_reach_team_as_companion_or_project(
    app: Any,
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team_a, project_a = await _project(client, alice_headers)
    alice = await me(client, alice_headers)
    sessions: InMemoryBridgeSessionRegistry = app.state.bridge_sessions
    sessions.bind(
        _drive_session(
            (uuid.UUID(alice["id"]), uuid.UUID(team_a["id"]), uuid.UUID(project_a["id"])), []
        )
    )
    _, project_b = await _project(client, bob_headers)
    convo_b = await _create_conversation(client, bob_headers, project_b["id"])
    runner = _RecordingRunner()
    app.state.agent_runner = runner

    body = {"content": "go", "action_mode": "do", "front_app": WINDOW}
    resp = await client.post(_url(project_b, convo_b), json=body, headers=bob_headers)
    assert resp.status_code == 200, resp.text
    assert runner.ctx.project_id == uuid.UUID(project_b["id"])
    assert _app_enum(runner.ctx.tools) is None  # Alice's companion is not Bob's

    # Bob cannot aim a front_app turn at Alice's project at all.
    convo_a = await _create_conversation(client, alice_headers, project_a["id"])
    runner.ctx = None
    denied = await client.post(_url(project_a, convo_a), json=body, headers=bob_headers)
    assert denied.status_code in (403, 404)
    assert runner.ctx is None


async def test_front_app_binds_only_the_turn_that_carried_it(
    app: Any, client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    team, project = await _project(client, alice_headers)
    alice = await me(client, alice_headers)
    sessions: InMemoryBridgeSessionRegistry = app.state.bridge_sessions
    sessions.bind(
        _drive_session(
            (uuid.UUID(alice["id"]), uuid.UUID(team["id"]), uuid.UUID(project["id"])), []
        )
    )
    convo = await _create_conversation(client, alice_headers, project["id"])
    runner = _RecordingRunner()
    app.state.agent_runner = runner

    body = {"content": "go", "action_mode": "do", "front_app": WINDOW}
    assert (await client.post(_url(project, convo), json=body, headers=alice_headers)).is_success
    assert runner.ctx.front_app == FRONT
    later = {"content": "and again", "action_mode": "do"}
    assert (await client.post(_url(project, convo), json=later, headers=alice_headers)).is_success
    assert runner.ctx.front_app is None
    assert _app_enum(runner.ctx.tools) == ["kicad"]
    assert all(TITLE not in t.content for t in runner.ctx.history)
    stored = (await db.scalars(select(ConversationTurn))).all()
    assert not any("benchy" in f"{t.content}{t.attrs}" for t in stored)
