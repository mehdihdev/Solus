"""Tenant isolation for driving (CLAUDE.md §7, ADR-041): user A's `drive.step`
exists only from A's own companion for this team and project, every helper call
and capture pull goes to that session alone, and nobody else can approve it."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from solus_api.agent.confirmations import decide_confirmation, request_confirmation
from solus_api.agent.drive.executor import Budget, StepOutcome
from solus_api.agent.drive.port import DriveRefusal
from solus_api.agent.drive.tool import DriveStepTool
from solus_api.agent.drive.wiring import DRIVE_TOOLS, bridge_drive_port
from solus_api.agent.runtime import build_sol_registry
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolErrorCode
from solus_api.bridge.allowlist import load_allowlist, validate_inventory
from solus_api.bridge.frames import HelloData
from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import Project, Team, User
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

Scope = tuple[uuid.UUID, uuid.UUID, uuid.UUID]
ROOT = Path(__file__).resolve().parents[3] / "integrations" / "mcp"


def _drive_session(scope: Scope, sent: list[str]) -> BridgeSession:
    hello = HelloData.model_validate(
        {
            "protocol_version": 1,
            "companion_version": "0.1.0",
            "companion_instance_id": f"i-{scope[0]}",
            "servers": [
                {
                    "server": "drive",
                    "tools": [
                        {"name": n, "description": "d", "input_schema": {"type": "object"}}
                        for n in ("identify", "capture", "act")
                    ],
                }
            ],
        }
    )

    async def send(frame: str) -> None:
        sent.append(frame)

    async def close(_code: int) -> None:
        return None

    return BridgeSession(
        session_id=uuid.uuid4().hex,
        user_id=scope[0],
        team_id=scope[1],
        project_id=scope[2],
        companion_instance_id=f"i-{scope[0]}",
        companion_version="0.1.0",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=validate_inventory(hello, load_allowlist(ROOT)),
        send=send,
        close=close,
        max_inflight=8,
    )


def _drive_names(sessions: InMemoryBridgeSessionRegistry, scope: Scope) -> set[str]:
    registry = build_sol_registry(
        async_sessionmaker(),
        scope[2],
        bridge=sessions,
        user_id=scope[0],
        team_id=scope[1],
        secret_store=InMemorySecretStore(),
    )
    return {d.name for d in registry.list() if d.name.startswith("drive.")}


def test_a_teammates_or_another_teams_companion_never_offers_drive_to_me() -> None:
    me: Scope = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    teammate: Scope = (uuid.uuid4(), me[1], me[2])  # same team and project
    other_team: Scope = (me[0], uuid.uuid4(), uuid.uuid4())  # me, in another team
    sessions = InMemoryBridgeSessionRegistry()
    for scope in (teammate, other_team):
        sessions.bind(_drive_session(scope, []))
    assert _drive_names(sessions, me) == set()
    sessions.bind(_drive_session(me, []))
    assert _drive_names(sessions, me) == {"drive.step"}


async def test_my_port_only_ever_reaches_my_own_session() -> None:
    me: Scope = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    teammate: Scope = (uuid.uuid4(), me[1], me[2])
    mine: list[str] = []
    theirs: list[str] = []
    sessions = InMemoryBridgeSessionRegistry()
    sessions.bind(_drive_session(me, mine))
    sessions.bind(_drive_session(teammate, theirs))
    my_session = sessions.get(*me)
    assert my_session is not None
    descriptors = {s.descriptor.name: s.descriptor for s in my_session.inventory}
    port = bridge_drive_port(
        sessions,
        {n: descriptors[n] for n in DRIVE_TOOLS},
        user_id=me[0],
        team_id=me[1],
        project_id=me[2],
        call_cap_bytes=262_144,
    )

    import asyncio

    pending = asyncio.create_task(port.identify())
    for _ in range(200):
        if mine:
            break
        await asyncio.sleep(0.005)
    pending.cancel()
    assert [json.loads(f)["data"]["tool"] for f in mine] == ["drive.identify"]
    assert theirs == []

    # My session gone: a pull fails closed — it never falls back to a teammate's.
    sessions.remove(my_session)
    with pytest.raises(DriveRefusal) as caught:
        await port.identify()
    assert caught.value.code == "bridge"
    assert theirs == []


# --- approval is the requester's alone -------------------------------------------------


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _scope(maker: async_sessionmaker[AsyncSession]) -> tuple[Scope, uuid.UUID]:
    async with maker() as db:
        owner = User(supabase_user_id=f"sub-{uuid.uuid4()}", email=f"{uuid.uuid4()}@e.test")
        mate = User(supabase_user_id=f"sub-{uuid.uuid4()}", email=f"{uuid.uuid4()}@e.test")
        team = Team(name="T")
        db.add_all([owner, mate, team])
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.commit()
        return (owner.id, team.id, project.id), mate.id


async def test_a_teammate_cannot_approve_my_drive_step(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    runs: list[str] = []

    async def run_step(intent: str, *_a: Any) -> StepOutcome:
        runs.append(intent)
        return StepOutcome(outcome="done", code=None, actions=0, seconds=0.0, summary="")

    async def record(*_a: Any) -> None:
        return None

    registry = ToolRegistry()
    registry.register(DriveStepTool(run_step=run_step, record=record, budget=Budget()))
    (owner, team, project), mate = await _scope(maker)
    async with maker() as db:
        parked = await request_confirmation(
            db,
            registry,
            ToolCall(tool="drive.step", args={"app": "kicad", "intent": "Place R1"}),
            project_id=project,
            team_id=team,
            user_id=owner,
        )
        await db.commit()
    assert parked is not None and parked.confirmation_id is not None

    async with maker() as db:
        result = await decide_confirmation(
            db, registry, parked.confirmation_id, approve=True, project_id=project, user_id=mate
        )
    assert result.ok is False
    assert result.error is not None and result.error.code is ToolErrorCode.NOT_FOUND
    assert runs == []

    async with maker() as db:
        result = await decide_confirmation(
            db, registry, parked.confirmation_id, approve=True, project_id=project, user_id=owner
        )
        await db.commit()
    assert result.ok is True and runs == ["Place R1"]
