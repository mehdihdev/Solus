"""SOLUSDEV-261: companion change signal -> persisted KiCad graph topology.

Proves, through the real app assembly (real registry, real BridgeExportAcquirer,
real ``_handle_notification``), that a ``change`` frame from a companion re-syncs
the project's bound KiCad source from the LIVE export and that the persisted
graph topology (entities + relations) follows. Team B's source is never touched
by team A's signal.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
from typing import Any

from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools.shapes import ToolResult
from solus_api.bridge.frames import parse_frame
from solus_api.bridge.service import ingest_result
from solus_api.models import GraphEntity, GraphEdge
from solus_api.routers import bridge as bridge_mod
from sqlalchemy import func, select
from test_sync_live_acquisition import _live_session


def _netlist(*, connected: bool) -> str:
    nets = (
        '<net code="1" name="SENSE_A0"><node ref="R1" pin="1"/><node ref="RFSR1" pin="1"/></net>'
        if connected
        else ""
    )
    return (
        '<?xml version="1.0"?><export version="E"><components>'
        '<comp ref="R1"><value>10k</value></comp>'
        '<comp ref="RFSR1"><value>FSR402</value></comp>'
        f"</components><nets>{nets}</nets></export>"
    )


async def _connect(
    client: AsyncClient, headers: dict[str, str], name: str, export: str
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    user = await me(client, headers)
    team = await create_team(client, headers, name)
    project = await create_project(client, headers, team["id"])
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/sources",
        json={"type": "kicad", "name": "k", "config": {"export": export, "project_path": "/p"}},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return user, team, project["id"], resp.json()["data"]


async def _counts(app: FastAPI, project_id: str) -> tuple[int, int]:
    async with app.state.sessionmaker() as db:
        pid = uuid.UUID(project_id)
        ents = await db.scalar(
            select(func.count()).select_from(GraphEntity).where(GraphEntity.project_id == pid)
        )
        rels = await db.scalar(
            select(func.count()).select_from(GraphEdge).where(GraphEdge.project_id == pid)
        )
        return int(ents or 0), int(rels or 0)


async def _answer_once(sent: list[str], session: Any, content: str) -> None:
    while not sent:
        await asyncio.sleep(0.005)
    call_id = json.loads(sent[0])["data"]["call_id"]
    ingest_result(session, ToolResult.success(call_id, {"content": content}))


async def test_change_frame_updates_graph_topology_and_isolates_teams(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    a_user, a_team, a_project, _ = await _connect(
        client, alice_headers, "A", _netlist(connected=False)
    )
    b_user, b_team, b_project, _ = await _connect(
        client, bob_headers, "B", _netlist(connected=False)
    )
    a_before = await _counts(app, a_project)
    b_before = await _counts(app, b_project)
    assert a_before[0] >= 2

    a_sent: list[str] = []
    b_sent: list[str] = []
    a_session = _live_session(
        a_sent,
        user_id=uuid.UUID(a_user["id"]),
        team_id=uuid.UUID(a_team["id"]),
        project_id=uuid.UUID(a_project),
    )
    b_session = _live_session(
        b_sent,
        user_id=uuid.UUID(b_user["id"]),
        team_id=uuid.UUID(b_team["id"]),
        project_id=uuid.UUID(b_project),
    )
    a_session = dataclasses.replace(a_session, may_write=True)
    app.state.bridge_sessions.bind(a_session)
    app.state.bridge_sessions.bind(b_session)

    frame = parse_frame('{"type":"change","data":{}}', control_cap=16 * 1024, tool_result_cap=1024)
    answer = asyncio.create_task(_answer_once(a_sent, a_session, _netlist(connected=True)))
    violation = bridge_mod._handle_notification(app.state, a_session, frame, frozenset(), None)
    assert violation is False
    await asyncio.wait_for(bridge_mod._INFLIGHT_RESYNC[a_session.session_id], timeout=15)
    await answer

    a_after = await _counts(app, a_project)
    assert a_after[1] > a_before[1], "the companion's change did not reach graph topology"
    assert await _counts(app, b_project) == b_before
    assert b_sent == [], "team A's signal dispatched to team B's companion"
