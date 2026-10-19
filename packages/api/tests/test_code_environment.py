"""SOLUSDEV-250 / INTEGRATIONS I3 — the Code environment: the resolve tool over the
graph, the failure filing into Error logging, and the machine route."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from conftest import add_member, bearer, create_project, create_team
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.errors_filing import run_failure
from solus_api.agent.tools.environment import resolve_environment
from solus_api.agent.tools.shapes import ToolDescriptor, ToolResult
from solus_api.bridge.allowlist import BridgeToolSpec
from solus_api.bridge.registry import BridgeSession
from solus_api.bridge.service import ingest_result
from solus_api.models import GraphEntity, Project, SolusEntry, SolusSection
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MACHINE = "e" * 32
LINK = {"machine_id": MACHINE, "machine_name": "mbp", "folder_name": "rover-fw"}
PROBE = {
    "python": {"path": "/usr/bin/python3", "version": "3.12.4"},
    "interpreters": [{"path": "/usr/bin/python3", "version": "3.12.4"}],
    "venv": {"path": ".venv", "python_version": "3.12.4", "packages": [], "truncated": False},
    "conda": None,
    "uv": None,
}


def _spec(name: str) -> BridgeToolSpec:
    server, _, tool = name.partition(".")
    return BridgeToolSpec(
        server=server,
        remote_name=tool,
        descriptor=ToolDescriptor(
            name=name, description="d", params={"type": "object"}, returns={"type": "object"}
        ),
    )


def _scan_with_pins() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "root_name": "rover-fw",
        "git": None,
        "files": [{"parts": ["policy.py"], "size": 1, "hash": None, "tool": "python"}],
        "digest": "ab" * 16,
        "truncated": False,
        "tools_installed": {"kicad": False, "altium": False, "vscode": True},
        "dependencies": [
            {"parts": ["requirements.txt"], "name": "torch", "specifier": "==2.3.0", "line": 1},
            {"parts": ["requirements.txt"], "name": "gymnasium", "specifier": ">=0.29", "line": 2},
            {
                "parts": ["isaac", "requirements.txt"],
                "name": "torch",
                "specifier": "==2.1.0",
                "line": 1,
            },
            {"parts": ["isaac", "requirements.txt"], "name": "numpy", "specifier": "", "line": 2},
        ],
        "truncated_dependencies": False,
    }


class FakeCompanion:
    def __init__(self, scan: dict[str, Any]) -> None:
        self.scan = scan
        self.sent: list[dict[str, Any]] = []
        self.session: BridgeSession | None = None

    async def _send(self, frame: str) -> None:
        data = json.loads(frame)["data"]
        self.sent.append(data)
        tool = data["tool"]
        if tool == "local.scan_folder":
            value: dict[str, Any] = self.scan
        elif tool == "local.folder_digest":
            value = {"digest": self.scan["digest"], "truncated": False}
        elif tool == "code.probe_environment":
            value = PROBE
        else:
            return
        assert self.session is not None
        asyncio.get_running_loop().call_soon(
            ingest_result, self.session, ToolResult.success(data["call_id"], value)
        )

    def bind(
        self, app: FastAPI, *, user_id: uuid.UUID, team_id: uuid.UUID, project_id: uuid.UUID
    ) -> None:
        async def _close(code: int) -> None:
            return None

        self.session = BridgeSession(
            session_id=uuid.uuid4().hex,
            user_id=user_id,
            team_id=team_id,
            project_id=project_id,
            companion_instance_id=MACHINE,
            companion_version="0.1.0",
            protocol_version=1,
            connected_at=datetime.now(UTC),
            token_exp=datetime.now(UTC),
            inventory=tuple(
                _spec(t)
                for t in (
                    "local.scan_folder",
                    "local.folder_digest",
                    "code.probe_environment",
                    "code.plan",
                )
            ),
            send=self._send,
            close=_close,
            max_inflight=8,
            may_write=True,
        )
        app.state.bridge_sessions.bind(self.session)


async def _linked_project(client: AsyncClient, app: FastAPI, headers: dict[str, str]) -> str:
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    me = await client.get("/api/v1/users/me", headers=headers)
    companion = FakeCompanion(_scan_with_pins())
    companion.bind(
        app,
        user_id=uuid.UUID(me.json()["data"]["id"]),
        team_id=uuid.UUID(team["id"]),
        project_id=uuid.UUID(project["id"]),
    )
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/local-folder", json=LINK, headers=headers
    )
    assert resp.status_code == 201, resp.text
    for _ in range(100):
        view = (
            await client.get(
                f"/api/v1/projects/{project['id']}/local-folder",
                params={"machine_id": MACHINE},
                headers=headers,
            )
        ).json()["data"]
        if view["source"] and view["source"]["status"] == "connected":
            break
        await asyncio.sleep(0.02)
    project_id: str = project["id"]
    return project_id


async def test_scan_lands_requirements_and_the_route_answers_conflicts_and_a_split(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    project_id = await _linked_project(client, app, alice_headers)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/code-environment",
        params={"machine_id": MACHINE},
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["source"]["type"] == "local"
    assert data["bridge"] == {"connected": True, "code_server": True}
    assert data["probe"] == PROBE
    assert data["requirements"] == {
        "count": 4,
        "files": ["isaac/requirements.txt", "requirements.txt"],
    }
    (conflict,) = data["conflicts"]
    assert conflict["checker_id"] == "python_pin_conflict" and conflict["severity"] == "critical"
    assert data["proposal"]["split"] is True
    envs = {e["name"]: e for e in data["proposal"]["environments"]}
    assert len(envs) == 2
    # The graph itself carries the nodes under the clone.
    async with app.state.sessionmaker() as db:
        kinds = (
            await db.scalars(
                select(GraphEntity.kind).where(
                    GraphEntity.project_id == uuid.UUID(project_id),
                    GraphEntity.deleted_at.is_(None),
                )
            )
        ).all()
    assert kinds.count("python_requirement") == 4


async def test_route_is_honest_offline_and_isolated(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id = await _linked_project(client, app, alice_headers)
    # Bob (another team) gets 404; unauthenticated 401.
    assert (
        await client.get(
            f"/api/v1/projects/{project_id}/code-environment",
            params={"machine_id": MACHINE},
            headers=bob_headers,
        )
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/projects/{project_id}/code-environment", params={"machine_id": MACHINE}
        )
    ).status_code == 401
    # Companion gone: probe null, bridge offline, graph facts still served.
    for session in (
        list(app.state.bridge_sessions._sessions.values())
        if hasattr(app.state.bridge_sessions, "_sessions")
        else []
    ):
        app.state.bridge_sessions.remove(session)
    data = (
        await client.get(
            f"/api/v1/projects/{project_id}/code-environment",
            params={"machine_id": MACHINE},
            headers=alice_headers,
        )
    ).json()["data"]
    assert data["probe"] is None
    assert data["requirements"]["count"] == 4
    # No local source on this machine: an empty, honest answer.
    other = (
        await client.get(
            f"/api/v1/projects/{project_id}/code-environment",
            params={"machine_id": "f" * 32},
            headers=alice_headers,
        )
    ).json()["data"]
    assert other == {
        "source": None,
        "bridge": {"connected": False, "code_server": False},
        "probe": None,
        "requirements": {"count": 0, "files": []},
        "conflicts": [],
        "proposal": None,
    }


async def test_resolve_tool_reads_only_this_project(db: AsyncSession) -> None:
    from solus_api.models import Membership, Role, Team, User

    user = User(supabase_user_id=f"sub-{uuid.uuid4().hex[:8]}", email="env@example.com")
    team = Team(name="Env")
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    mine = Project(team_id=team.id, name="Mine", created_by=user.id)
    theirs = Project(team_id=team.id, name="Theirs", created_by=user.id)
    db.add_all([mine, theirs])
    await db.flush()
    for project, spec in ((mine, "==2.1.0"), (theirs, "==9.9.9")):
        db.add(
            GraphEntity(
                project_id=project.id,
                kind="python_requirement",
                domain="code",
                name=f"torch {spec}",
                origin="connector",
                attrs={"name": "torch", "specifier": spec, "source_file": "requirements.txt"},
                modality_hints={},
            )
        )
    await db.commit()
    out = await resolve_environment(db, mine.id)
    assert out["requirement_count"] == 1 and out["split"] is False
    assert out["environments"][0]["requirements"][0]["specifier"] == "==2.1.0"


def test_failure_entry_text_only_for_real_failures() -> None:
    from solus_api.agent.errors_filing import format_error_entry
    from solus_api.agent.tools.shapes import ToolCall, ToolResult

    assert run_failure(ToolResult.success("fixture", {"exit_code": 0})) is None
    assert (
        run_failure(
            ToolResult.success("fixture", {"ok": False, "exit_code": None, "reason": "refused"})
        )
        is None
    )
    value = {
        "exit_code": 1,
        "argv": [".venv/bin/python", "-m", "pytest", "-q"],
        "stdout_tail": "FAILED tests/test_policy.py::test_reward_is_positive",
        "stderr_tail": "warning: x",
    }
    text = format_error_entry(
        ToolCall(tool="code.test", args={}), ToolResult.success("fixture", value)
    )
    assert "exit 1" in text
    assert "test_reward_is_positive" in text and "warning: x" in text
    assert text.index("test_reward_is_positive") < text.index("warning: x")
    assert (
        len(
            format_error_entry(
                ToolCall(tool="code.run", args={}),
                ToolResult.success("fixture", {"exit_code": 2, "stderr_tail": "x" * 10000}),
            )
        )
        <= 4000
    )


async def test_failed_confirmed_test_is_filed_into_error_logging(
    db: AsyncSession, engine: Any
) -> None:
    from solus_api.agent.confirmations import decide_confirmation, request_confirmation
    from solus_api.agent.tools.registry import ToolRegistry
    from solus_api.agent.tools.shapes import ToolCall
    from solus_api.agent.tools.tool import InProcessTool
    from solus_api.models import Membership, Role, Team, User
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        user = User(supabase_user_id=f"sub-{uuid.uuid4().hex[:8]}", email="s5@example.com")
        team = Team(name="S5")
        session.add_all([user, team])
        await session.flush()
        session.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
        project = Project(team_id=team.id, name="P", created_by=user.id)
        session.add(project)
        await session.commit()
        project_id, team_id, user_id = project.id, team.id, user.id

    async def _test_plan_rows(args: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"label": "command", "before": None, "after": ".venv/bin/python -m pytest -q"}]

    async def failing_test(args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "exit_code": 1,
            "argv": [".venv/bin/python", "-m", "pytest", "-q", "--", "tests"],
            "stdout_tail": "",
            "stderr_tail": "FAILED tests/test_policy.py::test_reward - AssertionError",
            "duration_ms": 120,
        }

    registry = ToolRegistry()
    registry.register(
        InProcessTool(
            ToolDescriptor(
                name="code.test",
                description="run tests",
                params={"type": "object", "properties": {"target": {"type": "string"}}},
                returns={"type": "object"},
                requires_confirmation=True,
                files_errors=True,
            ),
            failing_test,
            preview=_test_plan_rows,
        )
    )
    async with maker() as session:
        parked = await request_confirmation(
            session,
            registry,
            ToolCall(tool="code.test", args={"target": "tests"}),
            project_id=project_id,
            team_id=team_id,
            user_id=user_id,
        )
        await session.commit()
        assert parked is not None and parked.confirmation_id is not None
    async with maker() as session:
        result = await decide_confirmation(
            session,
            registry,
            parked.confirmation_id,
            approve=True,
            project_id=project_id,
            user_id=user_id,
        )
        await session.commit()
    assert result.ok is True and result.value is not None
    assert result.value["exit_code"] == 1
    async with maker() as session:
        entries = (
            await session.scalars(
                select(SolusEntry).where(
                    SolusEntry.project_id == project_id, SolusEntry.section == SolusSection.ERRORS
                )
            )
        ).all()
    assert len(entries) == 1
    assert entries[0].text is not None
    assert entries[0].text.startswith("Tool failure: code.test")
    assert '[".venv/bin/python", "-m", "pytest", "-q", "--", "tests"]' in entries[0].text
    assert "exit 1" in entries[0].text
    assert "test_reward" in entries[0].text
    assert entries[0].author == "sol"


async def test_a_teammate_never_sees_another_users_machine(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    """Security review L9: the local source is bound to (creator, machine).
    Carol — same team, same project — asking with Alice's machine id gets the
    empty, honest answer, never Alice's probe or requirements."""
    project_id = await _linked_project(client, app, alice_headers)
    team_id = (await client.get(f"/api/v1/projects/{project_id}", headers=alice_headers)).json()[
        "data"
    ]["team_id"]
    carol = {"sub": f"carol-{uuid.uuid4().hex[:8]}", "email": "carol@example.com"}
    carol_headers = bearer(carol["sub"], carol["email"])
    await add_member(client, alice_headers, carol_headers, carol, team_id)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/code-environment",
        params={"machine_id": MACHINE},
        headers=carol_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == {
        "source": None,
        "bridge": {"connected": False, "code_server": False},
        "probe": None,
        "requirements": {"count": 0, "files": []},
        "conflicts": [],
        "proposal": None,
    }


async def test_the_live_probe_is_reused_across_polls(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    """Security review M6: the desktop polls every 30 s; two reads inside the
    cache window dispatch ONE probe to the customer machine."""
    project_id = await _linked_project(client, app, alice_headers)
    companions = (
        [s for s in app.state.bridge_sessions._sessions.values()]
        if hasattr(app.state.bridge_sessions, "_sessions")
        else []
    )
    assert companions
    sent_before = _probe_calls(companions[0])
    for _ in range(3):
        data = (
            await client.get(
                f"/api/v1/projects/{project_id}/code-environment",
                params={"machine_id": MACHINE},
                headers=alice_headers,
            )
        ).json()["data"]
        assert data["probe"] == PROBE
    assert _probe_calls(companions[0]) - sent_before == 1


def _probe_calls(session: Any) -> int:
    sender = session.send  # the FakeCompanion's bound `_send`
    companion = getattr(sender, "__self__", None)
    sent = getattr(companion, "sent", [])
    return sum(1 for frame in sent if frame.get("tool") == "code.probe_environment")


def test_the_code_allowlist_bounds_exceed_the_servers_own_cap() -> None:
    """Security review M5: the cloud dispatch bound for the gated commands
    must exceed the fork's 600 s cap, or the cloud reports TIMEOUT while the
    child keeps running on the customer machine."""
    from pathlib import Path

    import yaml
    from solus_api.bridge.allowlist import ServerAllowlist

    root = Path(__file__).resolve().parents[3]
    parsed = ServerAllowlist.model_validate(
        yaml.safe_load((root / "integrations" / "mcp" / "code" / "allowlist.yaml").read_text())
    )
    bounds = {tool.name: tool.timeout_seconds for tool in parsed.tools}
    for name in ("create_environment", "install", "run", "test"):
        timeout = bounds[name]
        assert timeout is not None and timeout > 600, name
    assert bounds["probe_environment"] is None and bounds["plan"] is None
