"""WS-protocol tests for the bridge route (BRG-02-impl, contract §2/§4/§9).

Protocol-level via starlette's TestClient (httpx ASGITransport cannot open
WebSockets). Live dispatch through a real socket is covered by the uvicorn E2E
(test_bridge_e2e.py); service/tool unit suites cover redaction, correlation,
and cross-scope routing.
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from conftest import ALICE, BOB, TEST_DATABASE_URL, bearer, make_token
from fastapi import FastAPI
from solus_api.models import DataEvent, Membership, User
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient, WebSocketTestSession


def _hello_frame(**overrides: Any) -> str:
    data: dict[str, Any] = {
        "protocol_version": 1,
        "companion_version": "0.1.0",
        "companion_instance_id": "instance-a",
        "servers": [
            {
                "server": "mock",
                "tools": [
                    {"name": "echo", "description": "echo", "input_schema": {"type": "object"}}
                ],
            }
        ],
    }
    data.update(overrides)
    return json.dumps({"type": "hello", "data": data})


def _setup_project(client: TestClient, headers: dict[str, str]) -> tuple[str, str]:
    """Provision the user, one team, one project; returns (team_id, project_id)."""
    assert client.get("/api/v1/users/me", headers=headers).status_code == 200
    team = client.post("/api/v1/teams", json={"name": "T"}, headers=headers).json()["data"]
    project = client.post(
        f"/api/v1/teams/{team['id']}/projects", json={"name": "P"}, headers=headers
    ).json()["data"]
    return team["id"], project["id"]


def _connect(client: TestClient, project_id: str, headers: dict[str, str]) -> WebSocketTestSession:
    return client.websocket_connect(f"/api/v1/projects/{project_id}/bridge", headers=headers)


def _expect_close(ws: WebSocketTestSession, code: int) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as info:
        while True:
            ws.receive_text()
    assert info.value.code == code


def _run(coro: Any) -> Any:
    """Run a DB coroutine on a private loop/engine (the WS tests are sync)."""

    async def _with_engine() -> Any:
        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as session:
                result = await coro(session)
                await session.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(_with_engine())


def test_happy_connect_binds_validated_inventory_and_answers_ping(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _team_id, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_hello_frame())
        ack = json.loads(ws.receive_text())
        assert ack == {"type": "hello_ack", "data": {"protocol_version": 1}}
        session = bridge_app.state.bridge_sessions.get(*_scope_of(bridge_app, project_id))
        assert session is not None
        assert [spec.descriptor.name for spec in session.inventory] == ["mock.echo"]
        assert session.companion_instance_id == "instance-a"
        ws.send_text(json.dumps({"type": "ping", "data": {}}))
        assert json.loads(ws.receive_text()) == {"type": "pong", "data": {}}
        # status + unknown types are tolerated; the socket stays healthy
        ws.send_text(json.dumps({"type": "status", "data": {"servers": []}}))
        ws.send_text(json.dumps({"type": "future_thing", "data": {}}))
        ws.send_text(json.dumps({"type": "ping", "data": {}}))
        assert json.loads(ws.receive_text())["type"] == "pong"
    # context exit disconnects; the session must be unregistered
    assert bridge_app.state.bridge_sessions.get(*_scope_of(bridge_app, project_id)) is None


def _scope_of(app: FastAPI, project_id: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async def _lookup(session: Any) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        user = (
            await session.execute(select(User).where(User.supabase_user_id == ALICE["sub"]))
        ).scalar_one()
        from solus_api.models import Project

        project = await session.get(Project, uuid.UUID(project_id))
        return (user.id, project.team_id, project.id)

    result: tuple[uuid.UUID, uuid.UUID, uuid.UUID] = _run(_lookup)
    return result


def test_garbage_and_expired_jwt_close_4401(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, {"Authorization": "Bearer garbage"}) as ws:
        _expect_close(ws, 4401)
    expired = {
        "Authorization": f"Bearer {make_token(ALICE['sub'], ALICE['email'], expires_in=-10)}"
    }
    with _connect(client, project_id, expired) as ws:
        _expect_close(ws, 4401)
    with _connect(client, project_id, {}) as ws:  # no header at all
        _expect_close(ws, 4401)


def test_query_token_never_accepted_and_never_logged(
    bridge_app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    token = make_token(ALICE["sub"], ALICE["email"])
    with caplog.at_level("DEBUG"):
        with client.websocket_connect(f"/api/v1/projects/{project_id}/bridge?token={token}") as ws:
            _expect_close(ws, 4401)
    assert token not in caplog.text  # §6 log hygiene (app logs; infra logs untestable)


def test_non_member_project_closes_4404_no_existence_leak(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice, bob = bearer(**ALICE), bearer(**BOB)
    _, project_id = _setup_project(client, alice)
    assert client.get("/api/v1/users/me", headers=bob).status_code == 200
    with _connect(client, project_id, bob) as ws:
        _expect_close(ws, 4404)
    with _connect(client, str(uuid.uuid4()), alice) as ws:  # unknown project: same code
        _expect_close(ws, 4404)


def test_client_asserted_scope_or_confirmation_is_rejected(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_hello_frame(team_id="someone-elses-team"))
        err = json.loads(ws.receive_text())
        assert err["type"] == "error" and err["data"]["code"] == "expected_hello"
        _expect_close(ws, 4400)


def test_unsupported_protocol_version_gets_error_then_4400(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_hello_frame(protocol_version=99))
        err = json.loads(ws.receive_text())
        assert err["data"]["code"] == "unsupported_protocol_version"
        _expect_close(ws, 4400)


def test_frame_before_hello_closes_4400(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as ws:
        ws.send_text(json.dumps({"type": "ping", "data": {}}))
        err = json.loads(ws.receive_text())
        assert err["data"]["code"] == "expected_hello"
        _expect_close(ws, 4400)


def _fat_hello(payload_bytes: int) -> str:
    """A hello whose inventory is `payload_bytes` of tool descriptions — the
    shape a real companion sends: every fork's every tool, JSON schema and all.
    Two vendored forks put the live frame at 22 KB (SOLUSDEV-252, measured)."""
    filler = "d" * payload_bytes
    return _hello_frame(
        servers=[
            {
                "server": "mock",
                "tools": [
                    {"name": "echo", "description": filler, "input_schema": {"type": "object"}}
                ],
            }
        ]
    )


def test_realistic_multi_fork_hello_is_accepted(bridge_app: FastAPI) -> None:
    """A hello bigger than the CONTROL cap still connects. The inventory grows
    with the number of vendored forks, so sizing it like a ping is how the
    bridge came to refuse every real companion (live, SOLUSDEV-252)."""
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _team_id, project_id = _setup_project(client, alice)
    settings = bridge_app.state.settings
    assert settings.bridge_hello_frame_max_bytes > settings.bridge_control_frame_max_bytes
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_fat_hello(settings.bridge_control_frame_max_bytes * 2))
        assert json.loads(ws.receive_text())["type"] == "hello_ack"


def test_oversize_hello_closes_4413_with_an_honest_code(bridge_app: FastAPI) -> None:
    """Past the hello cap it is still refused — but as oversize, not as
    "expected_hello / update required", which sends the operator hunting a
    protocol mismatch that does not exist."""
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _team_id, project_id = _setup_project(client, alice)
    cap = bridge_app.state.settings.bridge_hello_frame_max_bytes
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_fat_hello(cap + 1024))
        err = json.loads(ws.receive_text())
        assert err["data"]["code"] == "oversize_hello"
        _expect_close(ws, 4413)


def test_supersede_closes_old_socket_4409_and_emits_event(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)

    async def _consent(session: Any) -> None:
        await session.execute(
            update(User)
            .where(User.supabase_user_id == ALICE["sub"])
            .values(data_collection_consent=True)
        )

    _run(_consent)
    with _connect(client, project_id, alice) as first:
        first.send_text(_hello_frame())
        assert json.loads(first.receive_text())["type"] == "hello_ack"
        with _connect(client, project_id, alice) as second:
            second.send_text(_hello_frame(companion_instance_id="instance-b"))
            assert json.loads(second.receive_text())["type"] == "hello_ack"
            _expect_close(first, 4409)

    async def _event(session: Any) -> Any:
        return (
            await session.execute(
                select(DataEvent).where(DataEvent.event_type == "bridge.session_superseded")
            )
        ).scalar_one()

    row = _run(_event)
    assert row.payload["old_companion_instance_id"] == "instance-a"
    assert row.payload["new_companion_instance_id"] == "instance-b"


def test_bad_results_and_dup_hello_are_dropped_but_socket_survives(
    bridge_app: FastAPI,
) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_hello_frame())
        assert json.loads(ws.receive_text())["type"] == "hello_ack"
        # unknown call_id, invariant-violating result, second hello: all dropped
        ws.send_text(
            json.dumps(
                {"type": "tool_result", "data": {"call_id": "nope", "ok": True, "value": {}}}
            )
        )
        ws.send_text(
            json.dumps(
                {
                    "type": "tool_result",
                    "data": {
                        "call_id": "x",
                        "ok": True,
                        "value": {},
                        "error": {"code": "tool_error", "message": "m"},
                    },
                }
            )
        )
        ws.send_text(_hello_frame())
        ws.send_text(json.dumps({"type": "ping", "data": {}}))
        assert json.loads(ws.receive_text())["type"] == "pong"  # still alive


def test_oversize_frame_closes_4413(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(bridge_tool_result_max_bytes=1024)
    client = TestClient(app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_hello_frame())
        assert json.loads(ws.receive_text())["type"] == "hello_ack"
        ws.send_text(json.dumps({"type": "status", "data": {"blob": "x" * 2048}}))
        _expect_close(ws, 4413)


def test_hello_timeout_closes_4400(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(bridge_hello_timeout_seconds=0.2)
    client = TestClient(app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as ws:
        _expect_close(ws, 4400)


def test_idle_timeout_closes_and_frees_the_slot(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(bridge_idle_timeout_seconds=0.3)
    client = TestClient(app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_hello_frame())
        assert json.loads(ws.receive_text())["type"] == "hello_ack"
        _expect_close(ws, 1000)


def test_message_flood_closes_4429(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(bridge_msg_rate_per_second=1.0, bridge_msg_burst=2)
    client = TestClient(app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_hello_frame())
        assert json.loads(ws.receive_text())["type"] == "hello_ack"
        for _ in range(40):  # blast past burst + MAX_VIOLATIONS
            ws.send_text(json.dumps({"type": "ping", "data": {}}))
        _expect_close(ws, 4429)


def test_connect_rate_limit_closes_4429(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(bridge_connect_rate_per_minute=1)
    client = TestClient(app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as first:
        first.send_text(_hello_frame())
        assert json.loads(first.receive_text())["type"] == "hello_ack"
        with _connect(client, project_id, alice) as second:
            _expect_close(second, 4429)


def test_team_session_cap_closes_4429(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(bridge_max_team_sessions=1)
    client = TestClient(app)
    alice = bearer(**ALICE)
    team_id, project_id = _setup_project(client, alice)
    other = client.post(
        f"/api/v1/teams/{team_id}/projects", json={"name": "P2"}, headers=alice
    ).json()["data"]
    with _connect(client, project_id, alice) as first:
        first.send_text(_hello_frame())
        assert json.loads(first.receive_text())["type"] == "hello_ack"
        with _connect(client, other["id"], alice) as second:
            _expect_close(second, 4429)


def test_membership_revoked_mid_session_closes_4403(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(bridge_revocation_poll_seconds=0.2)
    client = TestClient(app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_hello_frame())
        assert json.loads(ws.receive_text())["type"] == "hello_ack"

        async def _revoke(session: Any) -> None:
            from solus_api.models import ProjectMembership, utcnow

            # Dual-source access (ADR-025): both the team membership AND the
            # creator's direct project share must go for revocation to bite.
            await session.execute(update(Membership).values(deleted_at=utcnow()))
            await session.execute(update(ProjectMembership).values(deleted_at=utcnow()))

        _run(_revoke)
        _expect_close(ws, 4403)


def test_live_companion_tools_appear_in_sol_tools(bridge_app: FastAPI) -> None:
    """The SOL turn's tool set reflects the live session's validated inventory
    (runtime threading): bridge tools appear while connected, vanish after."""
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    tools_url = f"/api/v1/projects/{project_id}/sol/tools"
    before = [t["name"] for t in client.get(tools_url, headers=alice).json()["data"]]
    assert "mock.echo" not in before  # bridge offline → no bridge tools
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_hello_frame())
        assert json.loads(ws.receive_text())["type"] == "hello_ack"
        during = {t["name"]: t for t in client.get(tools_url, headers=alice).json()["data"]}
        assert "get_entity" in during and "mock.echo" in during
        assert during["mock.echo"]["requires_confirmation"] is False
    after = [t["name"] for t in client.get(tools_url, headers=alice).json()["data"]]
    assert "mock.echo" not in after  # disconnect → gone


def test_preauth_ip_connect_flood_throttled(make_app: Callable[..., FastAPI]) -> None:
    """SEC-M1: unauthenticated connects from one IP are throttled BEFORE any
    signature verification — the N+1th garbage-token connect gets 4429, not
    4401."""
    app = make_app(bridge_connect_rate_per_minute=2)
    client = TestClient(app)
    garbage = {"Authorization": "Bearer garbage"}
    project = str(uuid.uuid4())
    with _connect(client, project, garbage) as ws:
        _expect_close(ws, 4401)
    with _connect(client, project, garbage) as ws:
        _expect_close(ws, 4401)
    with _connect(client, project, garbage) as ws:  # limit exhausted pre-auth
        _expect_close(ws, 4429)
