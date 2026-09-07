"""`/projects/{id}/local-folder` routes (SOLUSDEV-249; `docs/api/local-folder.md` §3/§6).

End to end against the real app: link → inline sync → the fake companion answers
`local.scan_folder` over an injected bridge session → the graph chain lands →
GET reports the detected projects → open dispatches `local.open_in_tool`.
Plus every refusal: auth, cross-team, wrong machine, bridge offline, bad tool.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from conftest import add_member, create_project, create_team
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools.shapes import ToolDescriptor, ToolResult
from solus_api.bridge.allowlist import BridgeToolSpec
from solus_api.bridge.registry import BridgeSession
from solus_api.bridge.service import ingest_result
from solus_api.connectors.local_folder import DIGEST_TOOL, OPEN_TOOL, SCAN_TOOL
from solus_api.models import GraphEdge, GraphEntity, User
from sqlalchemy import select

MACHINE = "c" * 32
LINK = {"machine_id": MACHINE, "machine_name": "mbp", "folder_name": "rover-fw"}


def _spec(name: str) -> BridgeToolSpec:
    server, _, tool = name.partition(".")
    return BridgeToolSpec(
        server=server,
        remote_name=tool,
        descriptor=ToolDescriptor(
            name=name, description="d", params={"type": "object"}, returns={"type": "object"}
        ),
    )


class FakeCompanion:
    """Answers tool_calls on a bound session the way the `local` server would."""

    def __init__(self, scan: dict[str, Any]) -> None:
        self.scan = scan
        self.sent: list[dict[str, Any]] = []
        self.session: BridgeSession | None = None
        self.open_answer: dict[str, Any] = {"launched": True, "tool": "kicad", "reason": None}

    async def _send(self, frame: str) -> None:
        data = json.loads(frame)["data"]
        self.sent.append(data)
        tool = data["tool"]
        if tool == SCAN_TOOL:
            value: dict[str, Any] = self.scan
        elif tool == DIGEST_TOOL:
            value = {"digest": self.scan["digest"], "truncated": False}
        elif tool == OPEN_TOOL:
            value = {**self.open_answer, "tool": data["args"]["tool"]}
        else:
            return
        assert self.session is not None
        asyncio.get_running_loop().call_soon(
            ingest_result, self.session, ToolResult.success(data["call_id"], value)
        )

    def bind(
        self,
        app: FastAPI,
        *,
        user_id: uuid.UUID,
        team_id: uuid.UUID,
        project_id: uuid.UUID,
        machine: str = MACHINE,
    ) -> BridgeSession:
        async def _close(code: int) -> None:
            return None

        session = BridgeSession(
            session_id=uuid.uuid4().hex,
            user_id=user_id,
            team_id=team_id,
            project_id=project_id,
            companion_instance_id=machine,
            companion_version="0.1.0",
            protocol_version=1,
            connected_at=datetime.now(UTC),
            token_exp=datetime.now(UTC),
            inventory=tuple(_spec(t) for t in (SCAN_TOOL, DIGEST_TOOL, OPEN_TOOL)),
            send=self._send,
            close=_close,
            max_inflight=8,
            may_write=True,
        )
        self.session = session
        app.state.bridge_sessions.bind(session)
        return session


def _scan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "root_name": "rover-fw",
        "git": {"remote_url": "git@github.com:org/rover-fw.git", "branch": "main", "head": "abc"},
        "files": [
            {
                "parts": ["hw", "main", "main.kicad_pro"],
                "size": 1,
                "hash": "1" * 32,
                "tool": "kicad",
            },
            {
                "parts": ["hw", "main", "main.kicad_sch"],
                "size": 1,
                "hash": "2" * 32,
                "tool": "kicad",
            },
            {"parts": ["fw", "blink", "blink.ino"], "size": 1, "hash": "3" * 32, "tool": "arduino"},
        ],
        "digest": "ab" * 16,
        "truncated": False,
        "tools_installed": {"kicad": True, "altium": False, "vscode": True},
    }


async def _project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str, uuid.UUID]:
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    me = await client.get("/api/v1/users/me", headers=headers)
    return project["id"], team["id"], uuid.UUID(me.json()["data"]["id"])


async def _bound(
    client: AsyncClient, app: FastAPI, headers: dict[str, str], scan: dict[str, Any]
) -> tuple[str, FakeCompanion]:
    project_id, team_id, user_id = await _project(client, headers)
    companion = FakeCompanion(scan)
    companion.bind(
        app, user_id=user_id, team_id=uuid.UUID(team_id), project_id=uuid.UUID(project_id)
    )
    return project_id, companion


async def _wait_synced(client: AsyncClient, headers: dict[str, str], project_id: str) -> Any:
    for _ in range(100):
        resp = await client.get(
            f"/api/v1/projects/{project_id}/local-folder",
            params={"machine_id": MACHINE},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        view = resp.json()["data"]
        if view["source"] and view["source"]["status"] != "syncing":
            return view
        await asyncio.sleep(0.02)
    raise AssertionError("local source never left syncing")


# ------------------------------------------------------------------- happy path


async def test_link_scans_and_lands_the_chain(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    project_id, companion = await _bound(client, app, alice_headers, _scan())

    resp = await client.post(
        f"/api/v1/projects/{project_id}/local-folder", json=LINK, headers=alice_headers
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["source"]["type"] == "local"
    assert data["source"]["name"] == "mbp"
    assert data["source"]["config"] == {**LINK, "user_id": data["source"]["config"]["user_id"]}
    assert data["source"]["config"]["user_id"]
    assert data["job_id"]

    view = await _wait_synced(client, alice_headers, project_id)
    assert view["source"]["status"] == "connected"
    assert view["bridge"] == {
        "connected": True,
        "tools_installed": {"kicad": True, "altium": False, "vscode": True},
    }
    detected = {d["entity_key"]: d for d in view["detected"]}
    assert set(detected) == {"clone:", "kicad:hw/main", "arduino:fw/blink"}
    assert detected["kicad:hw/main"]["tool"] == "kicad"
    assert detected["kicad:hw/main"]["path"] == "hw/main/main.kicad_pro"
    assert detected["kicad:hw/main"]["open_targets"] == ["kicad", "vscode", "system"]
    assert detected["arduino:fw/blink"]["open_targets"] == ["vscode", "system"]
    assert detected["clone:"]["open_targets"] == ["vscode", "system"]
    assert all(d["entity_id"] for d in view["detected"])
    assert [c["tool"] for c in companion.sent] == [SCAN_TOOL]

    # The graph carries the chain: clone —contains→ kicad project.
    async with app.state.sessionmaker() as db:
        kinds = set(
            (
                await db.scalars(
                    select(GraphEntity.kind).where(
                        GraphEntity.project_id == uuid.UUID(project_id),
                        GraphEntity.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        assert {"local_clone", "kicad_project", "arduino_sketch"} <= kinds
        rels = set(
            (
                await db.scalars(
                    select(GraphEdge.relation_type).where(
                        GraphEdge.project_id == uuid.UUID(project_id)
                    )
                )
            ).all()
        )
        assert "contains" in rels


async def test_relink_reuses_the_machine_source(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _bound(client, app, alice_headers, _scan())
    first = await client.post(
        f"/api/v1/projects/{project_id}/local-folder", json=LINK, headers=alice_headers
    )
    await _wait_synced(client, alice_headers, project_id)
    second = await client.post(
        f"/api/v1/projects/{project_id}/local-folder",
        json={**LINK, "folder_name": "other"},
        headers=alice_headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"]["source"]["id"] == first.json()["data"]["source"]["id"]
    assert second.json()["data"]["source"]["config"]["folder_name"] == "other"
    listing = await client.get(f"/api/v1/projects/{project_id}/sources", headers=alice_headers)
    assert [s["type"] for s in listing.json()["data"]] == ["local"]


async def test_second_sync_with_unchanged_digest_is_skipped(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    project_id, companion = await _bound(client, app, alice_headers, _scan())
    await client.post(
        f"/api/v1/projects/{project_id}/local-folder", json=LINK, headers=alice_headers
    )
    view = await _wait_synced(client, alice_headers, project_id)
    source_id = view["source"]["id"]
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources/{source_id}/sync", headers=alice_headers
    )
    assert resp.status_code == 202, resp.text
    await _wait_synced(client, alice_headers, project_id)
    # The cheap digest probe answered "unchanged": no second scan was paid for.
    assert [c["tool"] for c in companion.sent] == [SCAN_TOOL, DIGEST_TOOL]


async def test_open_dispatches_to_the_companion(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    project_id, companion = await _bound(client, app, alice_headers, _scan())
    await client.post(
        f"/api/v1/projects/{project_id}/local-folder", json=LINK, headers=alice_headers
    )
    view = await _wait_synced(client, alice_headers, project_id)
    kicad = next(d for d in view["detected"] if d["tool"] == "kicad")
    source_id = view["source"]["id"]

    resp = await client.post(
        f"/api/v1/projects/{project_id}/local-folder/{source_id}/open",
        json={"entity_id": kicad["entity_id"], "tool": "kicad"},
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"launched": True, "tool": "kicad", "reason": None}
    call = companion.sent[-1]
    assert call["tool"] == OPEN_TOOL
    assert call["args"] == {"path": "hw/main/main.kicad_pro", "tool": "kicad"}

    companion.open_answer = {"launched": False, "reason": "KiCad is not installed"}
    resp = await client.post(
        f"/api/v1/projects/{project_id}/local-folder/{source_id}/open",
        json={"entity_id": kicad["entity_id"], "tool": "kicad"},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["launched"] is False
    assert resp.json()["data"]["reason"] == "KiCad is not installed"

    bad = await client.post(
        f"/api/v1/projects/{project_id}/local-folder/{source_id}/open",
        json={"entity_id": kicad["entity_id"], "tool": "altium"},
        headers=alice_headers,
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "unsupported_tool"


# ---------------------------------------------------------------------- refusals


async def test_generic_sources_route_refuses_local(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _, _ = await _project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "local", "name": "x", "config": LINK},
        headers=alice_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "use_local_folder_route"


async def test_link_validates_machine_id_and_rejects_unknown_fields(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _, _ = await _project(client, alice_headers)
    for body in (
        {**LINK, "machine_id": "short"},
        {**LINK, "machine_name": "  "},
        {**LINK, "path": "/Users/alice/rover"},
    ):
        resp = await client.post(
            f"/api/v1/projects/{project_id}/local-folder", json=body, headers=alice_headers
        )
        assert resp.status_code == 422, body


async def test_link_without_bridge_keeps_source_and_reports_no_signal(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _, _ = await _project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/local-folder", json=LINK, headers=alice_headers
    )
    assert resp.status_code == 201, resp.text
    view = await _wait_synced(client, alice_headers, project_id)
    assert view["bridge"]["connected"] is False
    assert view["detected"] == []
    # The sync could not ask the machine — recorded, never faked as empty.
    assert view["source"]["last_error"]["code"] == "api_unreachable"


async def test_open_refuses_when_bridge_offline_or_another_machine(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    project_id, companion = await _bound(client, app, alice_headers, _scan())
    await client.post(
        f"/api/v1/projects/{project_id}/local-folder", json=LINK, headers=alice_headers
    )
    view = await _wait_synced(client, alice_headers, project_id)
    kicad = next(d for d in view["detected"] if d["tool"] == "kicad")
    source_id = view["source"]["id"]
    assert companion.session is not None
    app.state.bridge_sessions.remove(companion.session)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/local-folder/{source_id}/open",
        json={"entity_id": kicad["entity_id"], "tool": "kicad"},
        headers=alice_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "bridge_offline"

    other = FakeCompanion(_scan())
    other.bind(
        app,
        user_id=companion.session.user_id,
        team_id=companion.session.team_id,
        project_id=companion.session.project_id,
        machine="d" * 32,
    )
    resp = await client.post(
        f"/api/v1/projects/{project_id}/local-folder/{source_id}/open",
        json={"entity_id": kicad["entity_id"], "tool": "kicad"},
        headers=alice_headers,
    )
    assert resp.status_code == 409
    assert other.sent == []


async def test_cross_team_isolation(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    project_id, _ = await _bound(client, app, alice_headers, _scan())
    await client.post(
        f"/api/v1/projects/{project_id}/local-folder", json=LINK, headers=alice_headers
    )
    view = await _wait_synced(client, alice_headers, project_id)
    source_id = view["source"]["id"]
    kicad = next(d for d in view["detected"] if d["tool"] == "kicad")

    assert (
        await client.get(
            f"/api/v1/projects/{project_id}/local-folder",
            params={"machine_id": MACHINE},
            headers=bob_headers,
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/projects/{project_id}/local-folder", json=LINK, headers=bob_headers
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/projects/{project_id}/local-folder/{source_id}/open",
            json={"entity_id": kicad["entity_id"], "tool": "kicad"},
            headers=bob_headers,
        )
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/projects/{project_id}/local-folder", params={"machine_id": MACHINE}
        )
    ).status_code == 401


async def test_open_refuses_foreign_entity(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _bound(client, app, alice_headers, _scan())
    await client.post(
        f"/api/v1/projects/{project_id}/local-folder", json=LINK, headers=alice_headers
    )
    view = await _wait_synced(client, alice_headers, project_id)
    source_id = view["source"]["id"]
    # An entity that is not one of this source's detected projects.
    async with app.state.sessionmaker() as db:
        user = await db.scalar(select(User))
        assert user is not None
        entity = GraphEntity(
            project_id=uuid.UUID(project_id),
            kind="component",
            domain="electrical",
            name="U1",
            origin="manual",
        )
        db.add(entity)
        await db.commit()
        foreign = str(entity.id)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/local-folder/{source_id}/open",
        json={"entity_id": foreign, "tool": "system"},
        headers=alice_headers,
    )
    assert resp.status_code == 404


async def test_get_without_a_source_is_empty_not_invented(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _, _ = await _project(client, alice_headers)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/local-folder",
        params={"machine_id": MACHINE},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == {
        "source": None,
        "bridge": {"connected": False, "tools_installed": {}},
        "detected": [],
    }


# --------------------------------------------------------- resync on connect


async def test_resync_filters_local_sources_by_machine(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], monkeypatch: Any
) -> None:
    """The bridge's re-sync only touches `local` sources of THIS machine, and
    `only_local` (the on-connect scan) leaves KiCad/Altium exports alone."""
    from solus_api.routers import bridge as bridge_router

    project_id, companion = await _bound(client, app, alice_headers, _scan())
    assert companion.session is not None
    await client.post(
        f"/api/v1/projects/{project_id}/local-folder", json=LINK, headers=alice_headers
    )
    await _wait_synced(client, alice_headers, project_id)
    other = await client.post(
        f"/api/v1/projects/{project_id}/local-folder",
        json={**LINK, "machine_id": "e" * 32},
        headers=alice_headers,
    )
    assert other.status_code == 201
    kicad = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "kicad", "name": "k", "config": {"export": "<export/>"}},
        headers=alice_headers,
    )
    assert kicad.status_code == 201, kicad.text

    synced: list[tuple[uuid.UUID, str]] = []

    async def _record(**kwargs: Any) -> None:
        synced.append((kwargs["source_id"], "x"))

    monkeypatch.setattr(bridge_router, "execute_source_sync", _record, raising=False)
    # `execute_source_sync` is imported inside the function; patch at its origin.
    import solus_api.connectors.worker as worker

    monkeypatch.setattr(worker, "execute_source_sync", _record)

    await bridge_router._resync_local_sources(app.state, companion.session, only_local=True)
    listing = await client.get(f"/api/v1/projects/{project_id}/sources", headers=alice_headers)
    by_type = {s["type"]: s for s in listing.json()["data"] if s["type"] != "local"}
    local_ids = {
        s["id"] for s in listing.json()["data"] if s["config"].get("machine_id") == MACHINE
    }
    assert {str(sid) for sid, _ in synced} == local_ids  # this machine's local source only

    synced.clear()
    await bridge_router._resync_local_sources(app.state, companion.session, only_local=False)
    assert {str(sid) for sid, _ in synced} == local_ids | {by_type["kicad"]["id"]}


# ------------------------------------------------ security review (C1, H1, M3)


async def test_read_only_session_never_triggers_a_resync(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], monkeypatch: Any
) -> None:
    """C1: a viewer/share-only companion connect must not write the graph."""
    from solus_api.routers import bridge as bridge_router

    project_id, companion = await _bound(client, app, alice_headers, _scan())
    assert companion.session is not None
    ran: list[str] = []

    async def _record(state: Any, sess: Any, **_: Any) -> None:
        ran.append(sess.session_id)

    monkeypatch.setattr(bridge_router, "_resync_local_sources", _record)
    from dataclasses import replace

    read_only = replace(companion.session, may_write=False)
    bridge_router._schedule_local_resync(app.state, read_only, only_local=True)
    bridge_router._schedule_local_resync(app.state, read_only)
    await asyncio.sleep(0.05)
    assert ran == []
    bridge_router._schedule_local_resync(app.state, companion.session, only_local=True)
    await asyncio.sleep(0.05)
    assert ran == [companion.session.session_id]


async def test_another_members_session_cannot_resync_or_open_my_source(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    monkeypatch: Any,
) -> None:
    """H1: a teammate whose companion DECLARES my machine id reaches nothing of mine."""
    from solus_api.routers import bridge as bridge_router

    project_id, companion = await _bound(client, app, alice_headers, _scan())
    assert companion.session is not None
    team_id = str(companion.session.team_id)
    bob = (await client.get("/api/v1/users/me", headers=bob_headers)).json()["data"]
    bob_id = uuid.UUID(bob["id"])
    await add_member(client, alice_headers, bob_headers, bob, team_id)
    await client.post(
        f"/api/v1/projects/{project_id}/local-folder", json=LINK, headers=alice_headers
    )
    view = await _wait_synced(client, alice_headers, project_id)
    kicad = next(d for d in view["detected"] if d["tool"] == "kicad")
    source_id = view["source"]["id"]

    spoof = FakeCompanion(_scan())
    spoof.bind(app, user_id=bob_id, team_id=uuid.UUID(team_id), project_id=uuid.UUID(project_id))
    synced: list[uuid.UUID] = []

    async def _record(**kwargs: Any) -> None:
        synced.append(kwargs["source_id"])

    import solus_api.connectors.worker as worker

    monkeypatch.setattr(worker, "execute_source_sync", _record)
    assert spoof.session is not None
    await bridge_router._resync_local_sources(app.state, spoof.session, only_local=True)
    assert synced == []

    # Bob's own view of the project shows HIS (absent) folder, not Alice's.
    mine = await client.get(
        f"/api/v1/projects/{project_id}/local-folder",
        params={"machine_id": MACHINE},
        headers=bob_headers,
    )
    assert mine.status_code == 200 and mine.json()["data"]["source"] is None
    # And Bob cannot open Alice's project through his own (spoofed) session.
    resp = await client.post(
        f"/api/v1/projects/{project_id}/local-folder/{source_id}/open",
        json={"entity_id": kicad["entity_id"], "tool": "kicad"},
        headers=bob_headers,
    )
    assert resp.status_code == 404
    assert spoof.sent == []


async def test_patch_cannot_rebind_a_local_source(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    """M3: the machine/user binding is written only by /local-folder."""
    project_id, _ = await _bound(client, app, alice_headers, _scan())
    await client.post(
        f"/api/v1/projects/{project_id}/local-folder", json=LINK, headers=alice_headers
    )
    view = await _wait_synced(client, alice_headers, project_id)
    resp = await client.patch(
        f"/api/v1/projects/{project_id}/sources/{view['source']['id']}",
        json={"config": {"machine_id": "e" * 32}},
        headers=alice_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "use_local_folder_route"
    renamed = await client.patch(
        f"/api/v1/projects/{project_id}/sources/{view['source']['id']}",
        json={"name": "my laptop"},
        headers=alice_headers,
    )
    assert renamed.status_code == 200
