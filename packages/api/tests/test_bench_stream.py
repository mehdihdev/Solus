"""Authenticated read-only live snapshots; no hardware acquisition."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from conftest import ALICE, BOB, bearer
from fastapi import FastAPI
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.packet import TelemetryPacket
from solus_api.graph.resolver import DictEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.livebench.stream import snapshot
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_bridge import _setup_project


async def test_snapshot_preserves_six_channels_and_never_resolves_on_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, session = uuid.uuid4(), uuid.uuid4()
    resolver = DictEntityResolver({})
    plumbing = TelemetryPlumbing(InMemoryTelemetryBuffer(), resolver)
    for index in range(6):
        await plumbing.ingest(
            project,
            TelemetryPacket(
                device_id="arm",
                timestamp=datetime.now(UTC),
                values={f"j{index}": float(index)},
                units={},
            ),
        )
    resolve = MagicMock(side_effect=AssertionError("snapshot performed resolver lookup"))
    monkeypatch.setattr(resolver, "resolve", resolve)
    manager = MagicMock()
    manager.get.return_value = SimpleNamespace(device_ids=["arm"], status="active")
    manager.channel_roles.return_value = {}
    frame = await snapshot(plumbing, manager, project, session, set())
    assert len(frame["devices"][0]["signals"]) == 6
    assert frame["devices"][0]["resolved_entity_id"] is None
    resolve.assert_not_called()


def test_socket_auth_and_full_snapshot(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    headers = bearer(**ALICE)
    _, project = _setup_project(client, headers)
    manager = MagicMock()
    manager.get.return_value = SimpleNamespace(device_ids=[], status="active")
    bridge_app.state.bench_sessions = manager
    identity = str(uuid.uuid4())
    with client.websocket_connect(f"/ws/v1/bench/sessions/{identity}") as ws:
        ws.send_json(
            {"type": "authenticate", "project_id": project, "token": headers["Authorization"][7:]}
        )
        assert ws.receive_json() == {
            "type": "telemetry",
            "project_id": project,
            "session_id": identity,
            "devices": [],
        }
        ws.send_json({"type": "start"})
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
        assert caught.value.code == 4400


@pytest.mark.parametrize("foreign", [False, True])
def test_socket_rejects_invalid_token_and_foreign_project(
    bridge_app: FastAPI, foreign: bool
) -> None:
    client = TestClient(bridge_app)
    _, project = _setup_project(client, bearer(**ALICE))
    bob = bearer(**BOB)
    client.get("/api/v1/users/me", headers=bob)
    manager = MagicMock()
    bridge_app.state.bench_sessions = manager
    with client.websocket_connect(f"/ws/v1/bench/sessions/{uuid.uuid4()}") as ws:
        ws.send_json(
            {
                "type": "authenticate",
                "project_id": project,
                "token": bob["Authorization"][7:] if foreign else "invalid",
            }
        )
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
        assert caught.value.code == (4404 if foreign else 4401)
    manager.get.assert_not_called()


@pytest.mark.parametrize("kind", ["binary", "malformed", "timeout", "oversize"])
def test_first_frame_bounds(
    bridge_app: FastAPI, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    from solus_api.livebench import stream

    monkeypatch.setattr(stream, "AUTH_TIMEOUT", 0.02)
    with TestClient(bridge_app).websocket_connect(f"/ws/v1/bench/sessions/{uuid.uuid4()}") as ws:
        if kind == "binary":
            ws.send_bytes(b"no")
        elif kind == "malformed":
            ws.send_text("{")
        elif kind == "oversize":
            ws.send_text("x" * 10000)
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
        assert caught.value.code == (4413 if kind == "oversize" else 4400)
    assert bridge_app.state.bench_stream_count == 0


@pytest.mark.parametrize("expiry", [None, float("nan"), float("inf"), -1])
def test_invalid_expiry_claim_is_bounded(bridge_app: FastAPI, expiry: float | None) -> None:
    import jwt
    from conftest import TEST_JWT_SECRET

    client = TestClient(bridge_app)
    _, project = _setup_project(client, bearer(**ALICE))
    claims = {**ALICE, "aud": "authenticated"}
    if expiry is not None:
        claims["exp"] = expiry
    token = jwt.encode(claims, TEST_JWT_SECRET, algorithm="HS256")
    bridge_app.state.bench_sessions = MagicMock()
    bridge_app.state.bench_sessions.get.return_value = SimpleNamespace(
        device_ids=[], status="active"
    )
    with client.websocket_connect(f"/ws/v1/bench/sessions/{uuid.uuid4()}") as ws:
        ws.send_json({"type": "authenticate", "project_id": project, "token": token})
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
        assert caught.value.code == 4401


def test_membership_revocation_closes_and_releases_slot(
    bridge_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typing import Any

    from solus_api.livebench import stream
    from solus_api.models import Membership, ProjectMembership, utcnow
    from sqlalchemy import update
    from test_bridge import _run

    monkeypatch.setattr(stream, "REAUTHORIZE_SECONDS", 0.03)
    client = TestClient(bridge_app)
    headers = bearer(**ALICE)
    _, project = _setup_project(client, headers)
    manager = MagicMock()
    manager.get.return_value = SimpleNamespace(device_ids=[], status="active")
    bridge_app.state.bench_sessions = manager
    with client.websocket_connect(f"/ws/v1/bench/sessions/{uuid.uuid4()}") as ws:
        ws.send_json(
            {"type": "authenticate", "project_id": project, "token": headers["Authorization"][7:]}
        )
        assert ws.receive_json()["type"] == "telemetry"

        async def revoke(db: Any) -> None:
            await db.execute(update(Membership).values(deleted_at=utcnow()))
            await db.execute(update(ProjectMembership).values(deleted_at=utcnow()))

        _run(revoke)
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
        assert caught.value.code == 4403
    assert bridge_app.state.bench_stream_users == {}
    assert bridge_app.state.bench_stream_count == 0


async def test_resolved_snapshot_bounds_channel_reads_and_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    project, entity = uuid.uuid4(), uuid.uuid4()
    buffer = InMemoryTelemetryBuffer()
    plumbing = TelemetryPlumbing(buffer, DictEntityResolver({(project, "arm"): entity}))
    await plumbing.ingest(
        project,
        TelemetryPacket(device_id="arm", timestamp=datetime.now(UTC), values={"j": 1.0}, units={}),
    )
    names = AsyncMock(return_value=[f"j{i}" for i in range(1000)])
    recent = AsyncMock(return_value=[])
    monkeypatch.setattr(buffer, "signal_names", names)
    monkeypatch.setattr(buffer, "recent", recent)
    view = await plumbing.snapshot_device(project, "arm")
    assert len(view.signals) == 64 and recent.await_count == 64
    manager = MagicMock()
    manager.get.return_value = SimpleNamespace(device_ids=["arm"], status="active")
    manager.channel_roles.return_value = {}
    assert (await snapshot(plumbing, manager, project, uuid.uuid4(), set()))["devices"] == []
    assert plumbing.observed_entity_ids(uuid.uuid4(), ["arm"]) == set()


async def test_slow_consumer_is_closed_without_backlog(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import time
    from unittest.mock import AsyncMock

    from solus_api.livebench import stream

    plumbing = TelemetryPlumbing(InMemoryTelemetryBuffer(), DictEntityResolver({}))
    manager = MagicMock()
    manager.get.return_value = SimpleNamespace(device_ids=[], status="active")

    async def blocked(data: str) -> None:
        await asyncio.Event().wait()

    socket = MagicMock()
    socket.app.state.telemetry_plumbing = plumbing
    socket.app.state.bench_sessions = manager
    socket.send_text = AsyncMock(side_effect=blocked)
    monkeypatch.setattr(stream, "SEND_TIMEOUT", 0.01)
    auth = stream.Authenticate(type="authenticate", token="unused", project_id=uuid.uuid4())
    with pytest.raises(stream.StreamClosedError) as caught:
        await stream.send_snapshots(socket, auth, uuid.uuid4(), set(), time.time() + 60)
    assert caught.value.code == 1013
    assert socket.send_text.await_count == 1


@pytest.mark.parametrize("ended", [False, True])
def test_real_session_manager_scope_and_ended_session(bridge_app: FastAPI, ended: bool) -> None:
    from solus_api.livebench.sessions import _Session

    client = TestClient(bridge_app)
    headers = bearer(**ALICE)
    _, project = _setup_project(client, headers)
    identity = uuid.uuid4()
    owner = uuid.UUID(project) if ended else uuid.uuid4()
    record = _Session(
        id=identity,
        project_id=owner,
        mode="real",
        provider="fixture",
        label="fixture",
        created_at=datetime.now(UTC),
        ended_at=datetime.now(UTC) if ended else None,
    )
    bridge_app.state.bench_sessions._active[owner] = {identity: record}
    with client.websocket_connect(f"/ws/v1/bench/sessions/{identity}") as ws:
        ws.send_json(
            {"type": "authenticate", "project_id": project, "token": headers["Authorization"][7:]}
        )
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
        assert caught.value.code == (1000 if ended else 4404)
    assert bridge_app.state.bench_stream_users == {}


def test_stream_caps_and_cleanup(bridge_app: FastAPI) -> None:
    from test_bridge import _scope_of

    client = TestClient(bridge_app)
    headers = bearer(**ALICE)
    _, project = _setup_project(client, headers)
    user, _, _ = _scope_of(bridge_app, project)
    bridge_app.state.bench_stream_count = 64
    bridge_app.state.bench_stream_users = {}
    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect(f"/ws/v1/bench/sessions/{uuid.uuid4()}"):
            pass
    assert caught.value.code == 4429
    assert bridge_app.state.bench_stream_count == 64
    bridge_app.state.bench_stream_count = 0
    bridge_app.state.bench_stream_users = {user: 8}
    manager = MagicMock()
    manager.get.return_value = SimpleNamespace(device_ids=[], status="active")
    bridge_app.state.bench_sessions = manager
    with client.websocket_connect(f"/ws/v1/bench/sessions/{uuid.uuid4()}") as ws:
        ws.send_json(
            {"type": "authenticate", "project_id": project, "token": headers["Authorization"][7:]}
        )
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
        assert caught.value.code == 4429
    assert bridge_app.state.bench_stream_count == 0
    assert bridge_app.state.bench_stream_users == {user: 8}
    bridge_app.state.bench_stream_users = {}
    with client.websocket_connect(f"/ws/v1/bench/sessions/{uuid.uuid4()}") as ws:
        ws.send_json(
            {"type": "authenticate", "project_id": project, "token": headers["Authorization"][7:]}
        )
        ws.receive_json()
    assert bridge_app.state.bench_stream_users == {}
    assert bridge_app.state.bench_stream_count == 0


async def test_new_mapping_streams_without_waiting_for_periodic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import time
    from unittest.mock import AsyncMock

    from solus_api.livebench import stream

    project, entity, identity = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    plumbing = TelemetryPlumbing(
        InMemoryTelemetryBuffer(), DictEntityResolver({(project, "arm"): entity})
    )
    manager = MagicMock()
    session = SimpleNamespace(device_ids=[], status="active")
    manager.get.return_value = session
    manager.channel_roles.return_value = {}
    socket = MagicMock()
    socket.app.state.telemetry_plumbing = plumbing
    socket.app.state.bench_sessions = manager
    frames = []

    async def receive_frame(raw: str) -> None:
        import json

        frames.append(json.loads(raw))
        if len(frames) == 1:
            session.device_ids = ["arm"]
            await plumbing.ingest(
                project,
                TelemetryPacket(
                    device_id="arm",
                    timestamp=datetime.now(UTC),
                    values={f"j{i}": float(i) for i in range(6)},
                    units={},
                ),
            )
        else:
            raise stream.StreamClosedError(1000)

    socket.send_text = AsyncMock(side_effect=receive_frame)
    authorize = AsyncMock(return_value=(uuid.uuid4(), {entity}, time.time() + 60))
    monkeypatch.setattr(stream, "authorize", authorize)
    auth = stream.Authenticate(type="authenticate", token="unused", project_id=project)
    with pytest.raises(stream.StreamClosedError):
        await asyncio.wait_for(
            stream.send_snapshots(socket, auth, identity, set(), time.time() + 60), 1
        )
    assert authorize.await_count == 1
    assert len(frames[1]["devices"][0]["signals"]) == 6


def test_idle_stream_heartbeat_preserves_transport_liveness(
    bridge_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus_api.livebench import stream

    monkeypatch.setattr(stream, "HEARTBEAT_SECONDS", 0.01)
    client = TestClient(bridge_app)
    headers = bearer(**ALICE)
    _, project = _setup_project(client, headers)
    manager = MagicMock()
    manager.get.return_value = SimpleNamespace(device_ids=[], status="active")
    bridge_app.state.bench_sessions = manager
    identity = str(uuid.uuid4())
    with client.websocket_connect(f"/ws/v1/bench/sessions/{identity}") as ws:
        ws.send_json(
            {"type": "authenticate", "project_id": project, "token": headers["Authorization"][7:]}
        )
        assert ws.receive_json()["type"] == "telemetry"
        assert ws.receive_json() == {
            "type": "heartbeat",
            "project_id": project,
            "session_id": identity,
        }


def test_frame_downsampling_retains_channel_identity_and_latest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from solus_api.livebench import stream

    monkeypatch.setattr(stream, "MAX_FRAME_BYTES", 1500)
    frame = {
        "devices": [
            {"signals": [{"signal": f"j{i}", "points": list(range(128))} for i in range(6)]}
        ]
    }
    encoded = stream.encode_snapshot(frame)
    result = json.loads(encoded)
    assert len(encoded.encode()) <= 1500
    assert len(result["devices"][0]["signals"]) == 6
    assert all(series["points"][-1] == 127 for series in result["devices"][0]["signals"])


def test_pre_auth_rate_limit_is_separate_from_bridge(bridge_app: FastAPI) -> None:
    limiter = MagicMock()
    limiter.allow.return_value = False
    bridge_app.state.bench_stream_ip_limiter = limiter
    with pytest.raises(WebSocketDisconnect) as caught:
        with TestClient(bridge_app).websocket_connect(f"/ws/v1/bench/sessions/{uuid.uuid4()}"):
            pass
    assert caught.value.code == 4429
    limiter.allow.assert_called_once()
    assert bridge_app.state.bench_stream_count == 0


async def test_connected_token_expiry_stops_before_another_frame() -> None:
    import time
    from unittest.mock import AsyncMock

    from solus_api.livebench import stream

    socket = MagicMock()
    socket.app.state.telemetry_plumbing = TelemetryPlumbing(
        InMemoryTelemetryBuffer(), DictEntityResolver({})
    )
    socket.app.state.bench_sessions.get.return_value = SimpleNamespace(
        device_ids=[], status="active"
    )
    socket.send_text = AsyncMock()
    auth = stream.Authenticate(type="authenticate", token="unused", project_id=uuid.uuid4())
    with pytest.raises(stream.StreamClosedError) as caught:
        await stream.send_snapshots(socket, auth, uuid.uuid4(), set(), time.time() + 0.05)
    assert caught.value.code == 4401
    assert socket.send_text.await_count == 1
