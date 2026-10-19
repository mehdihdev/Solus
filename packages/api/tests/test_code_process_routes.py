"""SOLUSDEV-317 §6: the Running processes routes — list, output, the person's
own Stop. Scoped to the caller's OWN bridge session: a teammate never sees or
stops another member's processes; a non-member gets 404; offline is honest."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from conftest import BOB, add_member, create_project, create_team
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools.shapes import ToolDescriptor, ToolResult
from solus_api.bridge.allowlist import BridgeToolSpec
from solus_api.bridge.registry import BridgeSession
from solus_api.bridge.service import ingest_result
from solus_api.models import DataEvent, User
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

MACHINE = "c" * 32
_PROCESS = {
    "process_id": "p1",
    "name": "bringup",
    "argv": ["/opt/ros/jazzy/bin/ros2", "launch", "x"],
    "cwd": "ros_ws",
    "state": "running",
    "pid": 4242,
    "exit_code": None,
    "started_at": "2026-10-18T10:00:00Z",
    "ended_at": None,
    "sandbox": "landlock-abi3",
}
_OUTPUT = {
    "process_id": "p1",
    "chunks": [{"seq": 1, "stream": "stdout", "text": "ready\n"}],
    "cursor": 1,
    "truncated": False,
}


class _Companion:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.session: BridgeSession | None = None
        self.running = {"p1"}
        self.silent = False
        self.stop_failure: str | None = None

    async def _send(self, frame: str) -> None:
        data = json.loads(frame)["data"]
        self.sent.append(data)
        args = data["args"]
        if data["tool"] == "code.process_status":
            value: dict[str, Any] = {"processes": [_PROCESS]}
            if "process_id" in args:
                if args["process_id"] in self.running:
                    value["output"] = {**_OUTPUT, "process_id": args["process_id"]}
        elif data["tool"] == "code.process_stop" and self.silent:
            return
        elif data["tool"] == "code.process_stop" and self.stop_failure is not None:
            value = {"ok": False, "process_id": args["process_id"], "state": None}
            value |= {"exit_code": None, "reason": self.stop_failure}
        elif data["tool"] == "code.process_stop":
            known = args["process_id"] in self.running
            value = {
                "ok": known,
                "process_id": args["process_id"],
                "state": "stopped" if known else None,
                "exit_code": -15 if known else None,
                **({} if known else {"reason": "unknown process"}),
            }
        else:
            return
        assert self.session is not None
        asyncio.get_running_loop().call_soon(
            ingest_result, self.session, ToolResult.success(data["call_id"], value)
        )

    def bind(
        self, app: FastAPI, user_id: uuid.UUID, team_id: uuid.UUID, project_id: uuid.UUID
    ) -> None:
        async def _close(code: int) -> None:
            return None

        def spec(name: str) -> BridgeToolSpec:
            return BridgeToolSpec(
                server="code",
                remote_name=name.split(".")[1],
                descriptor=ToolDescriptor(
                    name=name,
                    description="d",
                    params={"type": "object"},
                    returns={"type": "object"},
                ),
            )

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
            inventory=(spec("code.process_status"), spec("code.process_stop")),
            send=self._send,
            close=_close,
            max_inflight=8,
            may_write=True,
        )
        app.state.bridge_sessions.bind(self.session)


async def _setup(
    client: AsyncClient, app: FastAPI, headers: dict[str, str]
) -> tuple[str, str, _Companion]:
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    me = (await client.get("/api/v1/users/me", headers=headers)).json()["data"]
    companion = _Companion()
    companion.bind(app, uuid.UUID(me["id"]), uuid.UUID(team["id"]), uuid.UUID(project["id"]))
    return team["id"], project["id"], companion


def _base(project: str) -> str:
    return f"/api/v1/projects/{project}/code/processes"


async def test_list_reads_the_callers_own_machine(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    _, project, companion = await _setup(client, app, alice_headers)
    resp = await client.get(_base(project), params={"machine_id": MACHINE}, headers=alice_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"bridge": {"connected": True}, "processes": [_PROCESS]}
    assert companion.sent[0]["tool"] == "code.process_status"
    assert companion.sent[0]["args"] == {}


async def test_offline_or_another_machine_is_an_honest_empty_answer(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    _, project, companion = await _setup(client, app, alice_headers)
    resp = await client.get(_base(project), params={"machine_id": "d" * 32}, headers=alice_headers)
    assert resp.json()["data"] == {"bridge": {"connected": False}, "processes": []}
    stop = await client.post(
        f"{_base(project)}/p1/stop", params={"machine_id": "d" * 32}, headers=alice_headers
    )
    assert stop.status_code == 409
    assert stop.json()["error"]["code"] == "bridge_offline"
    out = await client.get(
        f"{_base(project)}/p1/output", params={"machine_id": "d" * 32}, headers=alice_headers
    )
    assert out.status_code == 404
    assert companion.sent == []


async def test_output_reads_a_cursor_and_unknown_is_404(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    _, project, companion = await _setup(client, app, alice_headers)
    resp = await client.get(
        f"{_base(project)}/p1/output",
        params={"machine_id": MACHINE, "cursor": 0},
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"output": _OUTPUT}
    assert companion.sent[-1]["args"] == {"process_id": "p1", "cursor": 0}
    unknown = await client.get(
        f"{_base(project)}/zz/output", params={"machine_id": MACHINE}, headers=alice_headers
    )
    assert unknown.status_code == 404
    bad = await client.get(
        f"{_base(project)}/p1/output",
        params={"machine_id": MACHINE, "cursor": -1},
        headers=alice_headers,
    )
    assert bad.status_code == 422


async def test_stop_dispatches_directly_and_emits_via_ui(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    _, project, companion = await _setup(client, app, alice_headers)
    await db.execute(update(User).values(data_collection_consent=True))
    await db.commit()
    resp = await client.post(
        f"{_base(project)}/p1/stop", params={"machine_id": MACHINE}, headers=alice_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["state"] == "stopped"
    assert companion.sent[-1] == {**companion.sent[-1], "tool": "code.process_stop"}
    assert companion.sent[-1]["args"] == {"process_id": "p1"}
    events = (
        await db.scalars(select(DataEvent).where(DataEvent.event_type == "code.process.stopped"))
    ).all()
    assert [e.payload for e in events] == [{"via": "ui", "state": "stopped"}]
    unknown = await client.post(
        f"{_base(project)}/zz/stop", params={"machine_id": MACHINE}, headers=alice_headers
    )
    assert unknown.status_code == 404


async def test_a_teammate_never_sees_or_stops_another_members_processes(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team, project, companion = await _setup(client, app, alice_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team)
    params = {"machine_id": MACHINE}
    listing = await client.get(_base(project), params=params, headers=bob_headers)
    assert listing.json()["data"] == {"bridge": {"connected": False}, "processes": []}
    stop = await client.post(f"{_base(project)}/p1/stop", params=params, headers=bob_headers)
    assert stop.status_code == 409
    out = await client.get(f"{_base(project)}/p1/output", params=params, headers=bob_headers)
    assert out.status_code == 404
    assert companion.sent == []


async def test_non_member_and_unauthenticated(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    _, project, companion = await _setup(client, app, alice_headers)
    params = {"machine_id": MACHINE}
    assert (await client.get(_base(project), params=params, headers=bob_headers)).status_code == 404
    assert (
        await client.post(f"{_base(project)}/p1/stop", params=params, headers=bob_headers)
    ).status_code == 404
    assert (await client.get(_base(project), params=params)).status_code == 401
    assert (
        await client.get(_base(project), params={"machine_id": "nope"}, headers=alice_headers)
    ).status_code == 422
    assert (
        await client.post(f"{_base(project)}/{'x' * 65}/stop", params=params, headers=alice_headers)
    ).status_code == 422
    assert companion.sent == []


async def test_reads_are_rate_limited(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    from solus_api.routers.code_processes import READ_LIMIT

    _, project, _companion = await _setup(client, app, alice_headers)
    params = {"machine_id": MACHINE}
    statuses = [
        (await client.get(_base(project), params=params, headers=alice_headers)).status_code
        for _ in range(READ_LIMIT + 1)
    ]
    assert statuses[:-1] == [200] * READ_LIMIT
    assert statuses[-1] == 429


async def test_an_unanswered_stop_is_504_stop_unconfirmed(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    monkeypatch: Any,
) -> None:
    from solus_api.routers import code_processes

    monkeypatch.setattr(code_processes, "_TIMEOUT_SECONDS", 0.2)
    _, project, companion = await _setup(client, app, alice_headers)
    companion.silent = True
    resp = await client.post(
        f"{_base(project)}/p1/stop", params={"machine_id": MACHINE}, headers=alice_headers
    )
    assert resp.status_code == 504, resp.text
    assert resp.json()["error"]["code"] == "stop_unconfirmed"


async def test_a_failed_stop_that_is_not_unknown_is_unconfirmed_not_404(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    _, project, companion = await _setup(client, app, alice_headers)
    companion.stop_failure = "process_stop failed"
    resp = await client.post(
        f"{_base(project)}/p1/stop", params={"machine_id": MACHINE}, headers=alice_headers
    )
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "stop_unconfirmed"


async def test_stops_are_rate_limited(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    from solus_api.routers.code_processes import STOP_LIMIT

    _, project, _companion = await _setup(client, app, alice_headers)
    params = {"machine_id": MACHINE}
    statuses = [
        (
            await client.post(f"{_base(project)}/p1/stop", params=params, headers=alice_headers)
        ).status_code
        for _ in range(STOP_LIMIT + 1)
    ]
    assert statuses[:-1] == [200] * STOP_LIMIT
    assert statuses[-1] == 429


async def test_a_viewer_cannot_list_read_or_stop(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team, project, companion = await _setup(client, app, alice_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team, role="viewer")
    params = {"machine_id": MACHINE}
    assert (await client.get(_base(project), params=params, headers=bob_headers)).status_code == 403
    out = await client.get(f"{_base(project)}/p1/output", params=params, headers=bob_headers)
    assert out.status_code == 403
    stop = await client.post(f"{_base(project)}/p1/stop", params=params, headers=bob_headers)
    assert stop.status_code == 403
    assert companion.sent == []
