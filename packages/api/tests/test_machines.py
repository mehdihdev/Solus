"""SOLUSDEV-320 T3 + P5: `PUT /projects/{id}/members/me/machines/{companion_id}` → member +
machine nodes joined by `contains`; P5-T1 populates `tool_versions` and the machine's
`environment/software` CONFIG over the caller's live bridge; P5-T2 stores member
preferences under `members/<uid.hex>`."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from conftest import add_member, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools.shapes import ToolResult
from solus_api.bridge.registry import BridgeSession
from solus_api.bridge.service import ingest_result
from solus_api.graph import kinds
from solus_api.models import Domain, GraphEdge, GraphEntity, SolusEntry, SolusEntryKind
from solus_api.routers.machines import _versions_of
from solus_api.services.machines import MachineIn, upsert_machine
from solus_api.services.solus_payloads import MAX_PREFERENCES_BYTES
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_code_environment import PROBE, _spec

COMPANION = "0123456789abcdef0123456789abcdef"
BODY = {"hostname": "bench-01", "os": "linux", "arch": "arm64"}
VERSIONS = {"python3": "Python 3.12.3", "git": "git version 2.45.0"}
PREFS = {"schema_version": 1, "shared": {"codeStyle": "black, 100 cols", "mechanical": "mm"}}


class _MachineBridge:
    """A live bridge session for COMPANION answering the two population tools."""

    def __init__(
        self, tools: tuple[str, ...], *, fail_send: bool = False, probe: Any = PROBE
    ) -> None:
        self.tools, self.fail_send, self.probe = tools, fail_send, probe
        self.calls: list[str] = []
        self.session: BridgeSession | None = None

    async def _send(self, frame: str) -> None:
        data = json.loads(frame)["data"]
        self.calls.append(data["tool"])
        if self.fail_send:
            raise RuntimeError("socket closed")
        value = (
            {"tool_versions": VERSIONS} if data["tool"] == "machine.tool_versions" else self.probe
        )
        assert self.session is not None
        asyncio.get_running_loop().call_soon(
            ingest_result, self.session, ToolResult.success(data["call_id"], value)
        )

    def bind(self, app: FastAPI, *, user_id: str, team_id: str, project_id: str) -> None:
        async def _close(code: int) -> None:
            return None

        self.session = BridgeSession(
            session_id=uuid.uuid4().hex,
            user_id=uuid.UUID(user_id),
            team_id=uuid.UUID(team_id),
            project_id=uuid.UUID(project_id),
            companion_instance_id=COMPANION,
            companion_version="0.1.0",
            protocol_version=1,
            connected_at=datetime.now(UTC),
            token_exp=datetime.now(UTC),
            inventory=tuple(_spec(t) for t in self.tools),
            send=self._send,
            close=_close,
            max_inflight=8,
            may_write=True,
        )
        app.state.bridge_sessions.bind(self.session)


async def _machine_configs(db: AsyncSession, project_id: str) -> list[SolusEntry]:
    return list(
        await db.scalars(
            select(SolusEntry).where(
                SolusEntry.project_id == uuid.UUID(project_id),
                SolusEntry.kind == SolusEntryKind.CONFIG,
                SolusEntry.subsection == "software",
                SolusEntry.deleted_at.is_(None),
            )
        )
    )


async def _machine_project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str, str]:
    user = await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return str(project["id"]), str(team["id"]), str(user["id"])


async def _put_machine(
    client: AsyncClient, headers: dict[str, str], project_id: str, cid: str = COMPANION, **over: str
) -> tuple[int, dict[str, object]]:
    resp = await client.put(
        f"/api/v1/projects/{project_id}/members/me/machines/{cid}",
        json={**BODY, **over},
        headers=headers,
    )
    body = resp.json()
    return resp.status_code, body.get("data", body)


async def _machine_rows(
    db: AsyncSession, project_id: str
) -> tuple[list[GraphEntity], list[GraphEdge]]:
    pid = uuid.UUID(project_id)
    nodes = list(
        await db.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == pid,
                GraphEntity.kind.in_((kinds.MEMBER, kinds.MACHINE)),
                GraphEntity.deleted_at.is_(None),
            )
        )
    )
    edges = list(
        await db.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == pid,
                GraphEdge.relation_type == "contains",
                GraphEdge.src_id.in_([n.id for n in nodes if n.kind == kinds.MEMBER]),
                GraphEdge.deleted_at.is_(None),
            )
        )
    )
    return nodes, edges


async def test_put_creates_member_machine_and_contains_edge(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _, user_id = await _machine_project(client, alice_headers)
    status, data = await _put_machine(client, alice_headers, project_id)
    assert status == 200, data
    assert data["type"] == kinds.MACHINE and data["domain"] == "runtime"
    assert data["origin"] == "system" and data["name"] == "bench-01"
    props = data["properties"]
    assert isinstance(props, dict)
    assert props == {
        "hostname": "bench-01",
        "os": "linux",
        "arch": "arm64",
        "owner_user_id": user_id,
        "tool_versions": {},
        "devices": [],
        "flash_history": [],
        "recent_commands": [],
    }

    nodes, edges = await _machine_rows(db, project_id)
    member = next(n for n in nodes if n.kind == kinds.MEMBER)
    machine = next(n for n in nodes if n.kind == kinds.MACHINE)
    assert len(nodes) == 2 and str(machine.id) == data["id"]
    assert member.canonical_key == f"member:{user_id}" and member.domain == Domain.PROJECT
    assert member.origin == "system" and member.attrs["display_name"] == "alice"
    assert machine.canonical_key == f"machine:{COMPANION}" and machine.domain == Domain.RUNTIME
    assert [(e.src_id, e.dst_id, e.origin) for e in edges] == [(member.id, machine.id, "system")]
    # The member hangs off `.solus` → Members, so the canvas shows it inside the tree.
    members_section = await db.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == uuid.UUID(project_id),
            GraphEntity.kind == kinds.SOLUS_SECTION,
            GraphEntity.attrs["section"].astext == "members",
            GraphEntity.deleted_at.is_(None),
        )
    )
    assert members_section is not None
    parent = await db.scalar(
        select(GraphEdge).where(
            GraphEdge.src_id == members_section.id,
            GraphEdge.dst_id == member.id,
            GraphEdge.relation_type == "contains",
            GraphEdge.deleted_at.is_(None),
        )
    )
    assert parent is not None and parent.origin == "system"


async def test_second_put_updates_in_place_without_duplicates(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _, _ = await _machine_project(client, alice_headers)
    _, first = await _put_machine(client, alice_headers, project_id)
    status, second = await _put_machine(
        client, alice_headers, project_id, arch="x86_64", hostname="bench-02"
    )
    assert status == 200 and second["id"] == first["id"]
    assert second["version"] == 2 and second["name"] == "bench-02"
    props = second["properties"]
    assert isinstance(props, dict) and props["arch"] == "x86_64"
    nodes, edges = await _machine_rows(db, project_id)
    assert len(nodes) == 2 and len(edges) == 1


async def test_put_validation_membership_and_role(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_id, team_id, _ = await _machine_project(client, alice_headers)
    for bad in ("short", "0123456789ABCDEF0123456789ABCDEF", "g" * 32):
        status, _ = await _put_machine(client, alice_headers, project_id, cid=bad)
        assert status == 422, bad
    resp = await client.put(
        f"/api/v1/projects/{project_id}/members/me/machines/{COMPANION}",
        json={**BODY, "extra": 1},
        headers=alice_headers,
    )
    assert resp.status_code == 422
    resp = await client.put(
        f"/api/v1/projects/{project_id}/members/me/machines/{COMPANION}",
        json={**BODY, "hostname": "h" * 129},
        headers=alice_headers,
    )
    assert resp.status_code == 422

    bob = await me(client, bob_headers)
    status, _ = await _put_machine(client, bob_headers, project_id)
    assert status == 404
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="viewer")
    status, _ = await _put_machine(client, bob_headers, project_id)
    assert status == 403
    nodes, _ = await _machine_rows(db, project_id)
    assert nodes == []


async def test_alice_and_bob_machines_are_isolated_per_project(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_a, _, alice_id = await _machine_project(client, alice_headers)
    project_b, _, bob_id = await _machine_project(client, bob_headers)
    _, a = await _put_machine(client, alice_headers, project_a)
    _, b = await _put_machine(client, bob_headers, project_b)  # same companion id, other project
    assert a["id"] != b["id"]
    nodes_a, _ = await _machine_rows(db, project_a)
    nodes_b, _ = await _machine_rows(db, project_b)
    assert {n.canonical_key for n in nodes_a} == {f"member:{alice_id}", f"machine:{COMPANION}"}
    assert {n.canonical_key for n in nodes_b} == {f"member:{bob_id}", f"machine:{COMPANION}"}


async def test_member_cannot_take_over_another_members_machine(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_id, team_id, alice_id = await _machine_project(client, alice_headers)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob, team_id)
    _, a = await _put_machine(client, alice_headers, project_id)
    status, body = await _put_machine(client, bob_headers, project_id, hostname="hijacked")
    assert status == 404, body
    nodes, edges = await _machine_rows(db, project_id)
    machine = next(n for n in nodes if n.kind == kinds.MACHINE)
    assert str(machine.id) == a["id"] and machine.name == "bench-01" and machine.version == 1
    assert machine.attrs["owner_user_id"] == alice_id
    assert len(edges) == 1 and len([n for n in nodes if n.kind == kinds.MEMBER]) == 1


async def test_service_replaces_tool_versions_and_never_touches_recent_commands(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _, user_id = await _machine_project(client, alice_headers)
    pid, uid = uuid.UUID(project_id), uuid.UUID(user_id)
    machine = await upsert_machine(
        db, pid, uid, COMPANION, MachineIn(**BODY), tool_versions={"python": "3.12.1"}
    )
    machine.attrs = {**machine.attrs, "recent_commands": [{"cmd": "flash"}]}
    await db.flush()
    again = await upsert_machine(
        db, pid, uid, COMPANION, MachineIn(**BODY), tool_versions={"arduino-cli": "1.1.0"}
    )
    assert again.id == machine.id
    # A reported dict REPLACES the stored one (an uninstalled tool must disappear);
    # None (tool unavailable) keeps what was last reported.
    assert again.attrs["tool_versions"] == {"arduino-cli": "1.1.0"}
    assert again.attrs["recent_commands"] == [{"cmd": "flash"}]
    assert again.version == 2
    plain = await upsert_machine(db, pid, uid, COMPANION, MachineIn(**BODY))
    assert plain.attrs["tool_versions"] == {"arduino-cli": "1.1.0"}
    assert plain.version == 2  # nothing changed → no bump
    same = await upsert_machine(
        db, pid, uid, COMPANION, MachineIn(**BODY), tool_versions={"arduino-cli": "1.1.0"}
    )
    assert same.version == 2


# ------------------------------------------------------------------ P5-T1 population


async def test_put_populates_tool_versions_and_one_machine_config(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    project_id, team_id, user_id = await _machine_project(client, alice_headers)
    bridge = _MachineBridge(("machine.tool_versions", "code.probe_environment", "code.plan"))
    bridge.bind(app, user_id=user_id, team_id=team_id, project_id=project_id)
    status, data = await _put_machine(client, alice_headers, project_id)
    assert status == 200, data
    props = data["properties"]
    assert isinstance(props, dict) and props["tool_versions"] == VERSIONS
    assert sorted(bridge.calls) == ["code.probe_environment", "machine.tool_versions"]
    configs = await _machine_configs(db, project_id)
    assert len(configs) == 1
    entry = configs[0]
    assert str(entry.configured_entity_id) == data["id"] and entry.config_version == 1
    assert entry.payload is not None
    assert entry.payload["type"] == "venv" and entry.payload["path"] == ".venv"
    assert entry.payload["detected_on"] == {"os": "linux", "arch": "arm64"}
    assert entry.payload["provenance"] == "detected"

    # The same probe again: same row, same version, nothing new.
    status, again = await _put_machine(client, alice_headers, project_id)
    assert status == 200 and again["id"] == data["id"] and again["version"] == 1
    db.expire_all()
    configs = await _machine_configs(db, project_id)
    assert [c.id for c in configs] == [entry.id]
    assert configs[0].config_version == 1


async def test_put_without_the_tools_is_body_only(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    project_id, team_id, user_id = await _machine_project(client, alice_headers)
    bridge = _MachineBridge(("code.plan",))
    bridge.bind(app, user_id=user_id, team_id=team_id, project_id=project_id)
    status, data = await _put_machine(client, alice_headers, project_id)
    assert status == 200, data
    props = data["properties"]
    assert isinstance(props, dict) and props["tool_versions"] == {}
    assert bridge.calls == []
    assert await _machine_configs(db, project_id) == []


async def test_put_survives_a_dead_bridge_and_a_malformed_probe(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    project_id, team_id, user_id = await _machine_project(client, alice_headers)
    dead = _MachineBridge(("machine.tool_versions", "code.probe_environment"), fail_send=True)
    dead.bind(app, user_id=user_id, team_id=team_id, project_id=project_id)
    status, data = await _put_machine(client, alice_headers, project_id)
    assert status == 200, data
    props = data["properties"]
    assert isinstance(props, dict) and props["tool_versions"] == {}
    assert await _machine_configs(db, project_id) == []

    # A second project: the probe answers garbage → no CONFIG is invented from it.
    project_b, team_b, _ = await _machine_project(client, alice_headers)
    odd = _MachineBridge(
        ("machine.tool_versions", "code.probe_environment"), probe={"venv": "invented"}
    )
    odd.bind(app, user_id=user_id, team_id=team_b, project_id=project_b)
    status, data = await _put_machine(client, alice_headers, project_b)
    assert status == 200, data
    props = data["properties"]
    assert isinstance(props, dict) and props["tool_versions"] == VERSIONS
    assert await _machine_configs(db, project_b) == []


def test_versions_of_redacts_paths_and_keeps_only_the_fixed_binaries() -> None:
    answer = {
        "tool_versions": {
            "pip": "pip 24.0 from /home/alice/.venv/lib/python3.12/site-packages/pip (python 3.12)",
            "uv": "uv 0.4.0 (C:\\Users\\bob\\uv)\x07",
            "python3": "Python 3.12.3",
            "rm": "not a probed binary",
            "node": 42,
        }
    }
    assert _versions_of(answer) == {
        "pip": "pip 24.0",
        "uv": "uv 0.4.0 (<path>)",
        "python3": "Python 3.12.3",
    }
    assert _versions_of(None) is None and _versions_of({"tool_versions": "x"}) is None


# ------------------------------------------------------------------ P5-T2 preferences


async def _put_prefs(
    client: AsyncClient, headers: dict[str, str], project_id: str, body: Any = None
) -> tuple[int, Any]:
    resp = await client.put(
        f"/api/v1/projects/{project_id}/members/me/preferences",
        json=PREFS if body is None else body,
        headers=headers,
    )
    parsed = resp.json()
    return resp.status_code, parsed.get("data", parsed)


async def _member_entries(db: AsyncSession, project_id: str) -> list[SolusEntry]:
    return list(
        await db.scalars(
            select(SolusEntry).where(
                SolusEntry.project_id == uuid.UUID(project_id),
                SolusEntry.section == "members",
                SolusEntry.deleted_at.is_(None),
            )
        )
    )


async def test_preferences_are_one_config_under_the_member_hex(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _, user_id = await _machine_project(client, alice_headers)
    status, data = await _put_prefs(client, alice_headers, project_id)
    assert status == 200, data
    assert data["section"] == "members" and data["subsection"] == uuid.UUID(user_id).hex
    assert data["kind"] == "config" and data["payload"] == PREFS
    entries = await _member_entries(db, project_id)
    assert len(entries) == 1 and entries[0].config_version == 1
    member = await db.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == uuid.UUID(project_id), GraphEntity.kind == kinds.MEMBER
        )
    )
    assert member is not None and entries[0].configured_entity_id == member.id
    assert entries[0].entity_id is not None
    node = await db.get(GraphEntity, entries[0].entity_id)
    assert node is not None and node.attrs["subsection"] == uuid.UUID(user_id).hex

    status, second = await _put_prefs(
        client, alice_headers, project_id, {"schema_version": 1, "shared": {"electrical": "3V3"}}
    )
    assert status == 200 and second["id"] == data["id"]
    assert second["payload"] == {"schema_version": 1, "shared": {"electrical": "3V3"}}
    db.expire_all()
    entries = await _member_entries(db, project_id)
    assert len(entries) == 1 and entries[0].config_version == 2


async def test_preferences_validation_membership_and_role(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project_id, team_id, _ = await _machine_project(client, alice_headers)
    for bad in (
        {**PREFS, "freeText": "x"},
        {"schema_version": 2, "shared": {}},
        {"schema_version": 1, "shared": {"passwords": "hunter2"}},
        {"schema_version": 1, "shared": {"codeStyle": 1}},
        {"schema_version": 1, "shared": {"codeStyle": "x" * (MAX_PREFERENCES_BYTES + 1)}},
    ):
        status, body = await _put_prefs(client, alice_headers, project_id, bad)
        assert status == 422, (bad, body)
    bob = await me(client, bob_headers)
    status, _ = await _put_prefs(client, bob_headers, project_id)
    assert status == 404
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="viewer")
    status, _ = await _put_prefs(client, bob_headers, project_id)
    assert status == 403
