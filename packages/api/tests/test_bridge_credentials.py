"""Bridge credential capture (SOLUSDEV-153 MCP-05 Part B) — red-team suite.

The `credential_submit`/`credential_ack` frames: values land in the SecretStore
under the tenant-scoped ref and NOWHERE else — never in cloud logs (asserted at
DEBUG capture across success and failure paths), never in any outbound frame,
never partially written on a bad frame. The team scope comes from the
server-bound session, never from the frame. Plus the Part A↔B round-trip: the
gate reads the exact ref the handler writes, and `GET /bridge` surfaces the
three license states.
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import ALICE, BOB, TEST_DATABASE_URL, bearer
from fastapi import FastAPI
from solus_api.agent.runtime import build_sol_registry
from solus_api.agent.tools.mcp_servers import license_secret_ref
from solus_api.agent.tools.shapes import ToolCall, ToolDescriptor, ToolErrorCode
from solus_api.bridge.allowlist import BridgeToolSpec
from solus_api.bridge.frames import CredentialSubmitData
from solus_api.bridge.registry import BridgeSession
from solus_api.connectors.secrets import SecretNotFoundError
from solus_api.models import DataEvent, Project, User
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient, WebSocketTestSession

_TOOLS = {"altium": "list_units", "kicad": "list_footprints", "mock": "echo"}


def _hello_frame(*servers: str) -> str:
    return json.dumps(
        {
            "type": "hello",
            "data": {
                "protocol_version": 1,
                "companion_version": "0.1.0",
                "companion_instance_id": "instance-a",
                "servers": [
                    {
                        "server": s,
                        "tools": [
                            {
                                "name": _TOOLS[s],
                                "description": "d",
                                "input_schema": {"type": "object"},
                            }
                        ],
                    }
                    for s in servers
                ],
            },
        }
    )


def _credential_frame(server: str, secrets: dict[str, Any], **extra: Any) -> str:
    data: dict[str, Any] = {"server": server, "secrets": secrets}
    data.update(extra)
    return json.dumps({"type": "credential_submit", "data": data})


def _status_frame(*names: str) -> str:
    now = datetime.now(UTC).isoformat()
    return json.dumps(
        {
            "type": "status",
            "data": {"servers": [{"name": n, "state": "ready", "updated_at": now} for n in names]},
        }
    )


def _setup_project(client: TestClient, headers: dict[str, str]) -> tuple[str, str]:
    assert client.get("/api/v1/users/me", headers=headers).status_code == 200
    team = client.post("/api/v1/teams", json={"name": "T"}, headers=headers).json()["data"]
    project = client.post(
        f"/api/v1/teams/{team['id']}/projects", json={"name": "P"}, headers=headers
    ).json()["data"]
    return team["id"], project["id"]


def _connect(client: TestClient, project_id: str, headers: dict[str, str]) -> WebSocketTestSession:
    return client.websocket_connect(f"/api/v1/projects/{project_id}/bridge", headers=headers)


def _handshake(ws: WebSocketTestSession, *servers: str) -> None:
    ws.send_text(_hello_frame(*servers))
    assert json.loads(ws.receive_text())["type"] == "hello_ack"


def _run(coro: Callable[..., Any]) -> Any:
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


def _scope_of(project_id: str, sub: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async def _lookup(session: Any) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        user = (
            await session.execute(select(User).where(User.supabase_user_id == sub))
        ).scalar_one()
        project = await session.get(Project, uuid.UUID(project_id))
        return (user.id, project.team_id, project.id)

    result: tuple[uuid.UUID, uuid.UUID, uuid.UUID] = _run(_lookup)
    return result


def _stored(app: FastAPI, ref: str) -> str | None:
    async def _get() -> str | None:
        try:
            value: str = await app.state.secret_store.get(ref)
            return value
        except SecretNotFoundError:
            return None

    return asyncio.run(_get())


def _upgrade_to_pro(client: TestClient, headers: dict[str, str]) -> None:
    resp = client.patch("/api/v1/users/me/subscription", json={"plan": "pro"}, headers=headers)
    assert resp.status_code == 200, resp.text


# ------------------------------------------------------------------ happy path
def test_submit_stores_under_tenant_ref_acks_names_and_overwrites(
    bridge_app: FastAPI,
) -> None:
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
    _upgrade_to_pro(client, alice)  # submit is entitlement-gated (review M1)
    _, team_id, _ = _scope_of(project_id, ALICE["sub"])
    with _connect(client, project_id, alice) as ws:
        _handshake(ws, "altium")
        ws.send_text(_credential_frame("altium", {"altium_license": "fake-lic-1"}))
        ack = json.loads(ws.receive_text())
        assert ack == {
            "type": "credential_ack",
            "data": {"server": "altium", "ok": True, "stored": ["altium_license"], "error": None},
        }
        ref = license_secret_ref(team_id, "altium", "altium_license")
        assert _stored(bridge_app, ref) == "fake-lic-1"
        # idempotent: re-submit overwrites (put semantics)
        ws.send_text(_credential_frame("altium", {"altium_license": "fake-lic-9"}))
        assert json.loads(ws.receive_text())["data"]["ok"] is True
        assert _stored(bridge_app, ref) == "fake-lic-9"

    async def _event(session: Any) -> Any:
        return (
            (
                await session.execute(
                    select(DataEvent).where(
                        DataEvent.event_type == "bridge.license_credentials_submitted"
                    )
                )
            )
            .scalars()
            .first()
        )

    row = _run(_event)
    assert row is not None
    assert row.payload["server"] == "altium"
    assert row.payload["keys"] == ["altium_license"]  # key NAMES + scope only
    assert "fake-lic" not in json.dumps(row.payload)  # values never in the event


# --------------------------------------------------------- never in cloud logs
def test_values_never_in_logs_or_outbound_frames(
    bridge_app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    """The load-bearing MCP-05 guarantee: with DEBUG capture across the FULL
    submit flow — success, unknown-key rejection, and a validation failure —
    the sentinel credential values appear in NO log record and NO outbound
    frame. Key NAMES may appear; values never."""
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    _upgrade_to_pro(client, alice)
    received: list[str] = []
    with caplog.at_level("DEBUG"):
        with _connect(client, project_id, alice) as ws:
            ws.send_text(_hello_frame("altium"))
            received.append(ws.receive_text())
            ws.send_text(_credential_frame("altium", {"altium_license": "fake-lic-1"}))
            received.append(ws.receive_text())  # ok ack
            ws.send_text(_credential_frame("altium", {"evil_key": "fake-lic-2"}))
            received.append(ws.receive_text())  # unknown-key rejection ack
            # validation failure path: extra field → strict-model violation
            ws.send_text(_credential_frame("altium", {"altium_license": "fake-lic-3"}, extra="x"))
            ws.send_text(json.dumps({"type": "ping", "data": {}}))
            received.append(ws.receive_text())  # pong — socket survived
    for sentinel in ("fake-lic-1", "fake-lic-2", "fake-lic-3"):
        assert sentinel not in caplog.text  # NEVER in cloud logs
        for frame in received:
            assert sentinel not in frame  # NEVER echoed in any outbound frame


def test_model_repr_and_str_redact_values() -> None:
    """An accidental log interpolation of the payload model cannot leak a value:
    logging's `%s` renders via `str()`, so repr/str/f-string cover every path."""
    data = CredentialSubmitData(server="altium", secrets={"altium_license": "fake-lic-7"})
    for rendered in (repr(data), str(data), f"{data}"):
        assert "fake-lic-7" not in rendered
        assert "altium" in rendered  # server name (non-secret) stays debuggable


# ------------------------------------------------------------------ rejections
def _submit_and_ack(
    ws: WebSocketTestSession, server: str, secrets: dict[str, Any]
) -> dict[str, Any]:
    ws.send_text(_credential_frame(server, secrets))
    ack = json.loads(ws.receive_text())
    assert ack["type"] == "credential_ack"
    data: dict[str, Any] = ack["data"]
    return data


def test_unknown_server_rejected(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as ws:
        _handshake(ws, "altium")
        data = _submit_and_ack(ws, "ghost", {"ghost_license": "fake-lic-1"})
        assert data["ok"] is False and data["stored"] == []
        assert data["error"] == "unknown server"


def test_free_tier_server_rejected(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    _, team_id, _ = _scope_of(project_id, ALICE["sub"])
    with _connect(client, project_id, alice) as ws:
        _handshake(ws, "kicad")
        data = _submit_and_ack(ws, "kicad", {"kicad_license": "fake-lic-1"})
        assert data["ok"] is False
        assert data["error"] == "not a bring-your-own-license tool"
    assert _stored(bridge_app, license_secret_ref(team_id, "kicad", "kicad_license")) is None


def test_unknown_key_rejected_with_no_partial_write(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    _upgrade_to_pro(client, alice)
    _, team_id, _ = _scope_of(project_id, ALICE["sub"])
    with _connect(client, project_id, alice) as ws:
        _handshake(ws, "altium")
        data = _submit_and_ack(
            ws, "altium", {"altium_license": "fake-lic-1", "evil_key": "fake-lic-2"}
        )
        assert data["ok"] is False and data["stored"] == []
        assert "unknown keys" in data["error"]
    # the VALID key was rejected wholesale with the frame — no partial write
    assert _stored(bridge_app, license_secret_ref(team_id, "altium", "altium_license")) is None


def test_malformed_submit_is_dropped_but_socket_survives(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as ws:
        _handshake(ws, "altium")
        # missing fields / wrong types → protocol-violation path, no crash
        ws.send_text(json.dumps({"type": "credential_submit", "data": {"nope": True}}))
        ws.send_text(json.dumps({"type": "credential_submit", "data": {"server": 7}}))
        ws.send_text(
            json.dumps({"type": "credential_submit", "data": {"server": "altium", "secrets": 3}})
        )
        ws.send_text(json.dumps({"type": "ping", "data": {}}))
        assert json.loads(ws.receive_text())["type"] == "pong"


def test_oversized_submit_closes_4413_and_stores_nothing(bridge_app: FastAPI) -> None:
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    _, team_id, _ = _scope_of(project_id, ALICE["sub"])
    with _connect(client, project_id, alice) as ws:
        _handshake(ws, "altium")
        ws.send_text(_credential_frame("altium", {"altium_license": "v" * 20_000}))
        with pytest.raises(WebSocketDisconnect) as info:
            while True:
                ws.receive_text()
        assert info.value.code == 4413  # control-frame cap, existing oversize path
    assert _stored(bridge_app, license_secret_ref(team_id, "altium", "altium_license")) is None


# ----------------------------------------------------- cross-tenant isolation
def test_cross_tenant_isolation_refs_never_collide(bridge_app: FastAPI) -> None:
    """Two teams submit the same server/key: the values land under different
    team-scoped refs (scope from the SERVER-bound session, never the frame),
    and team A's gate ref never reads team B's value."""
    client = TestClient(bridge_app)
    alice, bob = bearer(**ALICE), bearer(**BOB)
    _, alice_project = _setup_project(client, alice)
    _, bob_project = _setup_project(client, bob)
    _upgrade_to_pro(client, alice)
    _upgrade_to_pro(client, bob)
    _, alice_team, _ = _scope_of(alice_project, ALICE["sub"])
    _, bob_team, _ = _scope_of(bob_project, BOB["sub"])
    assert alice_team != bob_team
    with _connect(client, alice_project, alice) as ws:
        _handshake(ws, "altium")
        assert _submit_and_ack(ws, "altium", {"altium_license": "fake-lic-a"})["ok"] is True
    with _connect(client, bob_project, bob) as ws:
        _handshake(ws, "altium")
        assert _submit_and_ack(ws, "altium", {"altium_license": "fake-lic-b"})["ok"] is True
    ref_a = license_secret_ref(alice_team, "altium", "altium_license")
    ref_b = license_secret_ref(bob_team, "altium", "altium_license")
    assert ref_a != ref_b
    assert _stored(bridge_app, ref_a) == "fake-lic-a"
    assert _stored(bridge_app, ref_b) == "fake-lic-b"


# ------------------------------------------------- GET /bridge license_state
def test_bridge_status_surfaces_all_three_license_states(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    url = f"/api/v1/projects/{project_id}/bridge"
    with _connect(client, project_id, alice) as ws:
        _handshake(ws, "altium", "kicad", "mock")
        ws.send_text(_status_frame("altium", "kicad", "mock"))
        ws.send_text(json.dumps({"type": "ping", "data": {}}))
        assert json.loads(ws.receive_text())["type"] == "pong"  # status ingested

        def states() -> dict[str, str]:
            servers = client.get(url, headers=alice).json()["data"]["servers"]
            return {s["name"]: s["license_state"] for s in servers}

        # BASIC: byo_paid blocked; free-tier and uncataloged servers are ready
        assert states() == {"altium": "upgrade_required", "kicad": "ready", "mock": "ready"}
        _upgrade_to_pro(client, alice)
        assert states()["altium"] == "bring_your_license"  # entitled, no license yet
        ws.send_text(_credential_frame("altium", {"altium_license": "fake-lic-1"}))
        assert json.loads(ws.receive_text())["data"]["ok"] is True
        assert states()["altium"] == "ready"


# --------------------------------------------------------- Part A↔B round-trip
def test_gate_round_trip_with_credentials_from_the_wire(bridge_app: FastAPI) -> None:
    """The three gate states against the REAL stored state: BASIC blocked with
    the upgrade message; PRO without a license told which key to bring; PRO with
    the license submitted over a real `credential_submit` frame passes the gate
    (the remaining failure is the offline transport, not authorization)."""
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    scope = _scope_of(project_id, ALICE["sub"])

    def invoke() -> Any:
        async def _go() -> Any:
            engine = create_async_engine(TEST_DATABASE_URL)
            try:
                sessions = bridge_app.state.bridge_sessions.__class__()
                session = BridgeSession(
                    session_id=uuid.uuid4().hex,
                    user_id=scope[0],
                    team_id=scope[1],
                    project_id=scope[2],
                    companion_instance_id="i-1",
                    companion_version="0.1.0",
                    protocol_version=1,
                    connected_at=datetime.now(UTC),
                    token_exp=datetime.now(UTC),
                    inventory=(
                        BridgeToolSpec(
                            server="altium",
                            remote_name="list_units",
                            descriptor=ToolDescriptor(
                                name="altium.list_units",
                                description="d",
                                params={"type": "object"},
                                returns={"type": "object"},
                            ),
                        ),
                    ),
                    send=_never_send,
                    close=_never_close,
                    max_inflight=8,
                )
                sessions.bind(session)
                registry = build_sol_registry(
                    async_sessionmaker(engine, expire_on_commit=False),
                    scope[2],
                    bridge=sessions,
                    user_id=scope[0],
                    team_id=scope[1],
                    secret_store=bridge_app.state.secret_store,
                )
                sessions.remove(session)  # transport offline; only the gate can block
                return await registry.invoke(ToolCall(tool="altium.list_units", args={}))
            finally:
                await engine.dispose()

        return asyncio.run(_go())

    result = invoke()  # BASIC plan
    assert result.error is not None and result.error.code is ToolErrorCode.UNAUTHORIZED
    assert "Pro plan" in result.error.message
    _upgrade_to_pro(client, alice)
    result = invoke()  # PRO, no license stored yet
    assert result.error is not None and result.error.code is ToolErrorCode.UNAUTHORIZED
    assert "Bring your license" in result.error.message
    assert "altium_license" in result.error.message
    with _connect(client, project_id, alice) as ws:
        _handshake(ws, "altium")
        assert _submit_and_ack(ws, "altium", {"altium_license": "fake-lic-1"})["ok"] is True
    result = invoke()  # PRO + license from the wire: the gate no longer blocks
    assert result.error is not None and result.error.code is ToolErrorCode.UNAVAILABLE
    assert "bridge offline" in result.error.message


async def _never_send(frame: str) -> None:
    return None


async def _never_close(code: int) -> None:
    return None


# ------------------------------------------- Phase-4 review hardening (M1/M2/L4)
def test_submit_requires_entitlement(bridge_app: FastAPI) -> None:
    """Review M1: a BASIC member cannot plant or clobber the team's license —
    the submit path is entitlement-gated like the invoke path."""
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)  # BASIC by default
    _, team_id, _ = _scope_of(project_id, ALICE["sub"])
    with _connect(client, project_id, alice) as ws:
        _handshake(ws, "altium")
        data = _submit_and_ack(ws, "altium", {"altium_license": "fake-lic-1"})
        assert data["ok"] is False and data["stored"] == []
        assert "upgraded plan" in data["error"]
    assert _stored(bridge_app, license_secret_ref(team_id, "altium", "altium_license")) is None


def test_submit_rate_limited_after_burst(bridge_app: FastAPI) -> None:
    """Review M2: each accepted submit is a quota-bearing Secrets Manager write —
    the per-connection bucket (burst 3 by default) rejects the excess."""
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    _upgrade_to_pro(client, alice)
    with _connect(client, project_id, alice) as ws:
        _handshake(ws, "altium")
        for n in range(3):
            assert _submit_and_ack(ws, "altium", {"altium_license": f"fake-lic-{n}"})["ok"] is True
        data = _submit_and_ack(ws, "altium", {"altium_license": "fake-lic-x"})
        assert data["ok"] is False
        assert "rate-limited" in data["error"]


def test_wrong_type_value_inside_secrets_never_leaks(
    bridge_app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    """Review L4: a validation failure that forces pydantic to reference the
    VALUE (wrong type inside `secrets`) still leaks nothing —
    `hide_input_in_errors` keeps the input out of the error text."""
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    _upgrade_to_pro(client, alice)
    with caplog.at_level("DEBUG"):
        with _connect(client, project_id, alice) as ws:
            _handshake(ws, "altium")
            ws.send_text(_credential_frame("altium", {"altium_license": ["fake-lic-lst"]}))
            ws.send_text(json.dumps({"type": "ping", "data": {}}))
            assert json.loads(ws.receive_text())["type"] == "pong"  # socket survived
    assert "fake-lic-lst" not in caplog.text


def test_scope_fields_in_frame_are_rejected(bridge_app: FastAPI) -> None:
    """A frame asserting its own scope (`team_id`) is a strict-model violation —
    the tenant ref can only ever come from the server-bound session."""
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    _upgrade_to_pro(client, alice)
    _, team_id, _ = _scope_of(project_id, ALICE["sub"])
    with _connect(client, project_id, alice) as ws:
        _handshake(ws, "altium")
        ws.send_text(
            _credential_frame("altium", {"altium_license": "fake-lic-1"}, team_id=str(uuid.uuid4()))
        )
        ws.send_text(json.dumps({"type": "ping", "data": {}}))
        assert json.loads(ws.receive_text())["type"] == "pong"
    assert _stored(bridge_app, license_secret_ref(team_id, "altium", "altium_license")) is None


def test_storage_failure_returns_error_ack_not_crash(
    bridge_app: FastAPI, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review L4: a secret-store failure becomes an error ack — the socket
    survives and no value reaches any log record."""
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    _upgrade_to_pro(client, alice)

    async def _broken_put(ref: str, value: str) -> None:
        raise RuntimeError("backend down")

    monkeypatch.setattr(bridge_app.state.secret_store, "put", _broken_put)
    with caplog.at_level("DEBUG"):
        with _connect(client, project_id, alice) as ws:
            _handshake(ws, "altium")
            data = _submit_and_ack(ws, "altium", {"altium_license": "fake-lic-1"})
            assert data["ok"] is False
            assert data["error"] == "credential storage failed; retry shortly"
            ws.send_text(json.dumps({"type": "ping", "data": {}}))
            assert json.loads(ws.receive_text())["type"] == "pong"
    assert "fake-lic-1" not in caplog.text


def test_unchanged_resubmit_skips_write_and_overwrite_is_flagged(
    bridge_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review M2/M1: re-submitting an UNCHANGED value does no quota-bearing
    re-write; replacing a configured value flags `overwrote` in the event —
    the tripwire for a member clobbering the team license."""
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    _upgrade_to_pro(client, alice)

    async def _consent(session: Any) -> None:
        await session.execute(
            update(User)
            .where(User.supabase_user_id == ALICE["sub"])
            .values(data_collection_consent=True)
        )

    _run(_consent)
    _, team_id, _ = _scope_of(project_id, ALICE["sub"])
    store = bridge_app.state.secret_store
    real_put = store.put
    puts = {"n": 0}

    async def _counted_put(ref: str, value: str) -> None:
        puts["n"] += 1
        await real_put(ref, value)

    monkeypatch.setattr(store, "put", _counted_put)
    with _connect(client, project_id, alice) as ws:
        _handshake(ws, "altium")
        assert _submit_and_ack(ws, "altium", {"altium_license": "fake-lic-1"})["ok"] is True
        assert puts["n"] == 1
        assert _submit_and_ack(ws, "altium", {"altium_license": "fake-lic-1"})["ok"] is True
        assert puts["n"] == 1  # unchanged — no re-write
        assert _submit_and_ack(ws, "altium", {"altium_license": "fake-lic-2"})["ok"] is True
        assert puts["n"] == 2

    async def _events(session: Any) -> list[dict[str, Any]]:
        rows = (
            (
                await session.execute(
                    select(DataEvent).where(
                        DataEvent.event_type == "bridge.license_credentials_submitted",
                        DataEvent.team_id == team_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        return [dict(row.payload) for row in rows]

    payloads = _run(_events)
    assert len(payloads) == 3
    assert [p["overwrote"] for p in payloads].count(True) == 1  # only the replacement


def test_license_state_is_isolated_between_teams(bridge_app: FastAPI) -> None:
    """Review M3 test-add: team A storing its license never makes team B's
    `GET /bridge` read `ready` — the status surface probes only the requesting
    team's refs."""
    client = TestClient(bridge_app)
    alice, bob = bearer(**ALICE), bearer(**BOB)
    _, alice_project = _setup_project(client, alice)
    _, bob_project = _setup_project(client, bob)
    _upgrade_to_pro(client, alice)
    _upgrade_to_pro(client, bob)
    with _connect(client, alice_project, alice) as ws:
        _handshake(ws, "altium")
        assert _submit_and_ack(ws, "altium", {"altium_license": "fake-lic-a"})["ok"] is True
    with _connect(client, bob_project, bob) as ws:
        _handshake(ws, "altium")
        ws.send_text(_status_frame("altium"))
        ws.send_text(json.dumps({"type": "ping", "data": {}}))
        assert json.loads(ws.receive_text())["type"] == "pong"
        servers = client.get(f"/api/v1/projects/{bob_project}/bridge", headers=bob).json()["data"][
            "servers"
        ]
        assert {s["name"]: s["license_state"] for s in servers} == {
            "altium": "bring_your_license"  # entitled, but ALICE's license is not Bob's
        }
