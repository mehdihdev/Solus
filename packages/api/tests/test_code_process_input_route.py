"""SOLUSDEV-317 §11.2: the person's own input route.

`POST /api/v1/projects/{project_id}/code/processes/{process_id}/input?machine_id=…`
with `{text, enter}` dispatches `code.process_input` over the caller's OWN bridge
session (a user action, no card). 404 unknown, 409 bridge_offline, 409
not_waiting, 422 bounds; 60/min; `code.process.input {via: "ui"}` without text.
A teammate can never send input to another member's process.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
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

MACHINE = "e" * 32
TAIL = "Place the robot on a flat surface.\nPress Enter to continue:"


def waiting_entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "process_id": "p1",
        "name": "calibrate",
        "argv": ["/usr/bin/python3", "tools/calibrate.py"],
        "cwd": ".",
        "state": "running",
        "pid": 99,
        "exit_code": None,
        "started_at": "2026-10-19T10:00:00Z",
        "ended_at": None,
        "sandbox": "sandbox-exec",
        "interactive": True,
        "awaiting_input": True,
        "prompt_seq": 2,
        "prompt_tail": TAIL,
        "git_metadata_changed": False,
    }
    entry.update(overrides)
    return entry


class ProcessCompanion:
    """A bound bridge session whose `code` server knows one interactive process."""

    def __init__(self, entry: dict[str, Any] | None = None) -> None:
        self.entry = entry if entry is not None else waiting_entry()
        self.sent: list[dict[str, Any]] = []
        self.session: BridgeSession | None = None
        self.silent = False
        self.input_failure: str | None = None

    def _answer(self, tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
        if tool == "code.process_status":
            return {"processes": [self.entry] if self.entry else []}
        if tool != "code.process_input" or self.silent:
            return None
        known = self.entry is not None and args["process_id"] == self.entry["process_id"]
        reason = self.input_failure or (None if known else "unknown process")
        sent = len(args.get("text", "")) + (1 if args.get("enter", True) else 0)
        return {
            "ok": reason is None,
            "process_id": args["process_id"],
            "sent_chars": sent if reason is None else 0,
            "reason": reason,
        }

    async def _send(self, frame: str) -> None:
        data = json.loads(frame)["data"]
        self.sent.append(data)
        value = self._answer(data["tool"], data["args"])
        if value is None:
            return
        assert self.session is not None
        asyncio.get_running_loop().call_soon(
            ingest_result, self.session, ToolResult.success(data["call_id"], value)
        )

    def bind(
        self,
        app: FastAPI,
        user_id: uuid.UUID,
        team_id: uuid.UUID,
        project_id: uuid.UUID,
        tools: tuple[str, ...] = ("code.process_status", "code.process_input"),
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
                    requires_confirmation=name == "code.process_input",
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
            inventory=tuple(spec(name) for name in tools),
            send=self._send,
            close=_close,
            max_inflight=8,
            may_write=True,
        )
        app.state.bridge_sessions.bind(self.session)


async def _setup(
    client: AsyncClient, app: FastAPI, headers: dict[str, str]
) -> tuple[str, str, ProcessCompanion]:
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    me = (await client.get("/api/v1/users/me", headers=headers)).json()["data"]
    companion = ProcessCompanion()
    companion.bind(app, uuid.UUID(me["id"]), uuid.UUID(team["id"]), uuid.UUID(project["id"]))
    return team["id"], project["id"], companion


def _url(project: str, process: str = "p1") -> str:
    return f"/api/v1/projects/{project}/code/processes/{process}/input"


_PARAMS = {"machine_id": MACHINE}


async def test_the_list_carries_the_interactive_fields(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    _, project, _companion = await _setup(client, app, alice_headers)
    resp = await client.get(
        f"/api/v1/projects/{project}/code/processes", params=_PARAMS, headers=alice_headers
    )
    row = resp.json()["data"]["processes"][0]
    assert row["interactive"] is True and row["awaiting_input"] is True
    assert row["prompt_seq"] == 2 and row["prompt_tail"] == TAIL


async def test_input_dispatches_over_the_callers_bridge_and_emits_via_ui(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    _, project, companion = await _setup(client, app, alice_headers)
    await db.execute(update(User).values(data_collection_consent=True))
    await db.commit()
    resp = await client.post(
        _url(project), params=_PARAMS, json={"text": "y", "enter": True}, headers=alice_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"ok": True, "process_id": "p1", "sent_chars": 2}
    assert [s["tool"] for s in companion.sent] == ["code.process_status", "code.process_input"]
    assert companion.sent[-1]["args"] == {"process_id": "p1", "text": "y", "enter": True}
    events = (
        await db.scalars(select(DataEvent).where(DataEvent.event_type == "code.process.input"))
    ).all()
    assert [e.payload for e in events] == [{"via": "ui", "auto": False, "chars": 2}]


async def test_a_bare_enter_is_the_default_body(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    _, project, companion = await _setup(client, app, alice_headers)
    resp = await client.post(_url(project), params=_PARAMS, json={}, headers=alice_headers)
    assert resp.status_code == 200, resp.text
    assert companion.sent[-1]["args"] == {"process_id": "p1", "text": "", "enter": True}


@pytest.mark.parametrize(
    "body",
    [
        {"text": "y\n"},
        {"text": "\x1b[A"},
        {"text": "a" * 1025},
        {"text": "", "enter": False},
        {"text": 5},
        {"enter": "yes"},
        {"text": "y", "extra": 1},
    ],
)
async def test_out_of_bounds_bodies_are_422(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], body: dict[str, Any]
) -> None:
    _, project, companion = await _setup(client, app, alice_headers)
    resp = await client.post(_url(project), params=_PARAMS, json=body, headers=alice_headers)
    assert resp.status_code == 422, resp.text
    assert companion.sent == []


async def test_offline_or_another_machine_is_409_bridge_offline(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    _, project, companion = await _setup(client, app, alice_headers)
    resp = await client.post(
        _url(project), params={"machine_id": "d" * 32}, json={}, headers=alice_headers
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "bridge_offline"
    assert companion.sent == []


async def test_a_server_without_process_input_is_offline(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    me = (await client.get("/api/v1/users/me", headers=alice_headers)).json()["data"]
    companion = ProcessCompanion()
    companion.bind(
        app,
        uuid.UUID(me["id"]),
        uuid.UUID(team["id"]),
        uuid.UUID(project["id"]),
        tools=("code.process_status",),
    )
    resp = await client.post(_url(project["id"]), params=_PARAMS, json={}, headers=alice_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "bridge_offline"


async def test_unknown_process_is_404(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    _, project, companion = await _setup(client, app, alice_headers)
    resp = await client.post(_url(project, "zz"), params=_PARAMS, json={}, headers=alice_headers)
    assert resp.status_code == 404
    assert [s["tool"] for s in companion.sent] == ["code.process_status"]


@pytest.mark.parametrize(
    "entry",
    [
        waiting_entry(awaiting_input=False),
        waiting_entry(interactive=False),
        waiting_entry(state="exited"),
    ],
)
async def test_a_process_that_is_not_waiting_is_409_not_waiting(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], entry: dict[str, Any]
) -> None:
    _, project, companion = await _setup(client, app, alice_headers)
    companion.entry = entry
    resp = await client.post(_url(project), params=_PARAMS, json={}, headers=alice_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "not_waiting"
    assert [s["tool"] for s in companion.sent] == ["code.process_status"]


async def test_a_server_refusal_after_the_check_is_409_not_waiting(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    _, project, companion = await _setup(client, app, alice_headers)
    companion.input_failure = "process is not running"
    resp = await client.post(_url(project), params=_PARAMS, json={}, headers=alice_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "not_waiting"


async def test_an_unanswered_input_is_504_input_unconfirmed(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], monkeypatch: Any
) -> None:
    from solus_api.routers import code_processes

    monkeypatch.setattr(code_processes, "_TIMEOUT_SECONDS", 0.2)
    _, project, companion = await _setup(client, app, alice_headers)
    companion.silent = True
    resp = await client.post(_url(project), params=_PARAMS, json={}, headers=alice_headers)
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "input_unconfirmed"


async def test_a_teammate_cannot_send_input_to_another_members_process(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team, project, companion = await _setup(client, app, alice_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team)
    resp = await client.post(_url(project), params=_PARAMS, json={"text": "y"}, headers=bob_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "bridge_offline"
    assert companion.sent == []


async def test_non_member_viewer_and_unauthenticated(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    team, project, companion = await _setup(client, app, alice_headers)
    outsider = await client.post(_url(project), params=_PARAMS, json={}, headers=bob_headers)
    assert outsider.status_code == 404
    assert (await client.post(_url(project), params=_PARAMS, json={})).status_code == 401
    await add_member(client, alice_headers, bob_headers, BOB, team, role="viewer")
    viewer = await client.post(_url(project), params=_PARAMS, json={}, headers=bob_headers)
    assert viewer.status_code == 403
    bad_id = await client.post(
        _url(project, "x" * 65), params=_PARAMS, json={}, headers=alice_headers
    )
    assert bad_id.status_code == 422
    assert companion.sent == []


async def test_input_is_rate_limited_at_sixty_a_minute(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str]
) -> None:
    from solus_api.routers.code_processes import INPUT_LIMIT

    assert INPUT_LIMIT == 60
    _, project, _companion = await _setup(client, app, alice_headers)
    statuses = [
        (
            await client.post(_url(project), params=_PARAMS, json={}, headers=alice_headers)
        ).status_code
        for _ in range(INPUT_LIMIT + 1)
    ]
    assert statuses[:-1] == [200] * INPUT_LIMIT
    assert statuses[-1] == 429
