"""LB-05: bench telemetry routes — ingest, recent values, summaries, events.

The first production wiring of LNK-06 (`TelemetryPlumbing`) behind the central
auth/scoping middleware. Cross-tenant isolation is the highest-severity invariant
(CLAUDE.md §7): every case here runs both the member and the outsider path.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import create_project, create_team, me  # type: ignore[attr-defined]
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.interfaces import TelemetryWindow
from solus_api.connectors.live import BatchCallback, LiveStatus
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.graph.codec import to_wire
from solus_api.graph.packet import TelemetryPacket
from solus_api.livebench.sessions import AmbiguousDeviceError, DeviceNotFoundError

T0 = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _install_fake_github(app: FastAPI, fake_registry: ConnectorRegistry) -> None:
    app.state.connector_registry = fake_registry


async def _project_with_graph(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str, str]:
    """(project_id, entity_id, external_ref) for one synced entity."""
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    project_id: str = project["id"]
    source = (
        await client.post(
            f"/api/v1/projects/{project_id}/sources",
            json={"type": "github", "name": "fw", "config": {"repo": "o/r"}, "token": "tok"},
            headers=headers,
        )
    ).json()["data"]
    await client.post(f"/api/v1/projects/{project_id}/sources/{source['id']}/sync", headers=headers)
    entities = (
        await client.get(f"/api/v1/projects/{project_id}/entities", headers=headers)
    ).json()["data"]
    entity = entities[0]
    return project_id, entity["id"], entity["source_key"]


def wire_packet(device_id: str, sec: float, values: dict[str, float]) -> dict[str, Any]:
    from datetime import timedelta

    return to_wire(
        TelemetryPacket(device_id=device_id, timestamp=T0 + timedelta(seconds=sec), values=values)
    )


async def _ingest(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    packets: list[dict[str, Any]],
    events: list[dict[str, Any]] | None = None,
) -> Any:
    body: dict[str, Any] = {"packets": packets}
    if events is not None:
        body["events"] = events
    return await client.post(
        f"/api/v1/projects/{project_id}/bench/telemetry", json=body, headers=headers
    )


async def test_ingest_then_recent_round_trip(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, entity_id, ref = await _project_with_graph(client, alice_headers)

    resp = await _ingest(
        client,
        alice_headers,
        project_id,
        [wire_packet(ref, 0.0, {"rpm": 100.0}), wire_packet(ref, 1.0, {"rpm": 200.0})],
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"accepted": 2, "unresolved": 0, "rejected": 0}

    recent = (
        await client.get(
            f"/api/v1/projects/{project_id}/bench/recent/{entity_id}", headers=alice_headers
        )
    ).json()["data"]
    (series,) = recent["signals"]
    assert series["signal"] == "rpm"
    assert [point["value"] for point in series["points"]] == [100.0, 200.0]


async def test_summary_returns_w007_windows(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _entity_id, ref = await _project_with_graph(client, alice_headers)
    await _ingest(
        client,
        alice_headers,
        project_id,
        [wire_packet(ref, i * 0.5, {"rpm": 100.0 + i}) for i in range(6)],
    )

    resp = await client.get(
        f"/api/v1/projects/{project_id}/bench/summary",
        params={"duration_seconds": 10.0},
        headers=alice_headers,
    )

    assert resp.status_code == 200, resp.text
    windows = resp.json()["data"]["windows"]
    assert windows
    assert "rpm" in windows[-1]["signals"]


async def test_unresolved_devices_drop_never_500(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _entity_id, _ref = await _project_with_graph(client, alice_headers)

    resp = await _ingest(
        client, alice_headers, project_id, [wire_packet("ghost-device", 0.0, {"v": 1.0})]
    )

    assert resp.status_code == 200
    assert resp.json()["data"] == {"accepted": 0, "unresolved": 1, "rejected": 0}


async def test_hostile_packets_are_counted_rejected_stream_survives(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _entity_id, ref = await _project_with_graph(client, alice_headers)

    resp = await _ingest(
        client,
        alice_headers,
        project_id,
        [
            {"ts_us": "garbage"},
            {"nonsense": True},
            wire_packet(ref, 0.0, {"v": 1.0}),
        ],
    )

    assert resp.status_code == 200
    assert resp.json()["data"] == {"accepted": 1, "unresolved": 0, "rejected": 2}


async def test_batch_size_is_bounded(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    project_id, _entity_id, ref = await _project_with_graph(client, alice_headers)

    resp = await _ingest(
        client, alice_headers, project_id, [wire_packet(ref, i, {"v": 1.0}) for i in range(501)]
    )

    assert resp.status_code == 422


async def test_events_round_trip(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    project_id, _entity_id, ref = await _project_with_graph(client, alice_headers)
    event = {
        "kind": "threshold_breach",
        "device_id": ref,
        "signal": "temp",
        "at": T0.isoformat(),
        "value": 95.0,
        "detail": {"high": 80.0},
    }

    resp = await _ingest(
        client, alice_headers, project_id, [wire_packet(ref, 0.0, {"temp": 95.0})], [event]
    )
    assert resp.status_code == 200, resp.text

    events = (
        await client.get(f"/api/v1/projects/{project_id}/bench/events", headers=alice_headers)
    ).json()["data"]
    assert len(events) == 1
    assert events[0]["kind"] == "threshold_breach"
    assert events[0]["signal"] == "temp"


async def test_requires_authentication(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    project_id, entity_id, _ref = await _project_with_graph(client, alice_headers)

    assert (await client.get(f"/api/v1/projects/{project_id}/bench/events")).status_code == 401
    assert (
        await client.post(f"/api/v1/projects/{project_id}/bench/telemetry", json={"packets": []})
    ).status_code == 401
    assert (
        await client.get(f"/api/v1/projects/{project_id}/bench/recent/{entity_id}")
    ).status_code == 401


async def test_cross_team_isolation(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """Team B can neither read nor write team A's bench — the §7 invariant."""
    project_id, entity_id, ref = await _project_with_graph(client, alice_headers)
    await _ingest(client, alice_headers, project_id, [wire_packet(ref, 0.0, {"rpm": 1.0})])

    await me(client, bob_headers)
    bob_team = await create_team(client, bob_headers)
    bob_project = await create_project(client, bob_headers, bob_team["id"])

    # Bob cannot touch Alice's project at all.
    for method, url in [
        ("get", f"/api/v1/projects/{project_id}/bench/recent/{entity_id}"),
        ("get", f"/api/v1/projects/{project_id}/bench/events"),
        ("get", f"/api/v1/projects/{project_id}/bench/summary?duration_seconds=10"),
    ]:
        resp = await client.request(method, url, headers=bob_headers)
        assert resp.status_code == 404, url
    resp = await _ingest(client, bob_headers, project_id, [wire_packet(ref, 0.0, {"v": 2.0})])
    assert resp.status_code == 404

    # And Alice's data never bleeds into Bob's project, even with the same device_id.
    resp = await _ingest(
        client, bob_headers, bob_project["id"], [wire_packet(ref, 0.0, {"v": 3.0})]
    )
    assert resp.json()["data"]["accepted"] == 0  # no such entity in Bob's graph → unresolved
    bob_events = (
        await client.get(f"/api/v1/projects/{bob_project['id']}/bench/events", headers=bob_headers)
    ).json()["data"]
    assert bob_events == []


async def test_recent_for_foreign_entity_id_is_404(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    _a_project, a_entity, _ref = await _project_with_graph(client, alice_headers)
    await me(client, bob_headers)
    bob_team = await create_team(client, bob_headers)
    bob_project = await create_project(client, bob_headers, bob_team["id"])

    # Bob asks HIS project for ALICE's entity id: scoped read must come back empty/404.
    resp = await client.get(
        f"/api/v1/projects/{bob_project['id']}/bench/recent/{a_entity}", headers=bob_headers
    )
    assert resp.status_code == 404


async def test_unknown_project_is_404(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    await me(client, alice_headers)
    ghost = uuid.uuid4()
    resp = await client.get(f"/api/v1/projects/{ghost}/bench/events", headers=alice_headers)
    assert resp.status_code == 404


async def test_oversized_event_detail_is_rejected(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _entity_id, ref = await _project_with_graph(client, alice_headers)
    fat_event = {
        "kind": "threshold_breach",
        "device_id": ref,
        "signal": "temp",
        "at": T0.isoformat(),
        "detail": {"blob": "x" * 10_000},
    }

    resp = await _ingest(
        client, alice_headers, project_id, [wire_packet(ref, 0.0, {"temp": 1.0})], [fat_event]
    )

    assert resp.status_code == 422  # detail size bound (§7)


async def test_distinct_signal_flood_is_capped_not_blocking(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _entity_id, ref = await _project_with_graph(client, alice_headers)
    # One packet carrying far more distinct signals than a batch may create.
    flood = wire_packet(ref, 0.0, {f"s{i:04d}": float(i) for i in range(256)})
    packets = [
        wire_packet(ref, float(i), {f"s{i}_{j}": 1.0 for j in range(256)}) for i in range(20)
    ]

    resp = await _ingest(client, alice_headers, project_id, [flood, *packets])

    assert resp.status_code == 200
    data = resp.json()["data"]
    # Everything past the 4096 distinct-signal cap is rejected, not ingested.
    assert data["rejected"] > 0
    assert data["accepted"] + data["unresolved"] + data["rejected"] == len(packets) + 1


async def test_missing_content_length_is_refused(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    # httpx sets Content-Length for json bodies; a chunked body (no length) is refused.
    project_id, _entity_id, ref = await _project_with_graph(client, alice_headers)

    async def chunks() -> Any:
        yield b'{"packets":[]}'

    resp = await client.post(
        f"/api/v1/projects/{project_id}/bench/telemetry",
        content=chunks(),
        headers={**alice_headers, "content-type": "application/json"},
    )
    assert resp.status_code in (411, 422)  # 411 length_required (our gate) or 422 (empty batch)


# ═══════════════════════════════════════════════════════════════════════════════
# SOLUSDEV-72: local-connections surface — sources, sessions, device-recent
# ═══════════════════════════════════════════════════════════════════════════════


class TapConn:
    """Tappable LiveConnection double for route tests."""

    def __init__(self) -> None:
        self.tap: Any = None
        self.callback: BatchCallback | None = None
        self.closed = False
        self._status = LiveStatus.DISCONNECTED

    async def subscribe(self, window: TelemetryWindow) -> str:
        self._status = LiveStatus.CONNECTED
        return "h"

    def on_batch(self, handle: str, callback: BatchCallback) -> None:
        self.callback = callback

    def status(self) -> LiveStatus:
        return self._status

    async def aclose(self) -> None:
        self.closed = True
        self._status = LiveStatus.DISCONNECTED


def _fake_device(
    device: str = "/dev/ttyACM0", serial: str | None = "5B42135040", ambiguous: bool = False
) -> Any:
    return SimpleNamespace(
        identity=SimpleNamespace(
            device=device,
            vid=0x1A86,
            pid=0x55D3,
            serial=serial,
            board=SimpleNamespace(
                name="WCH CH343/CH9102 USB-serial bridge",
                kind=SimpleNamespace(value="usb_bridge"),
            ),
            mcu_known=False,
            evidence=SimpleNamespace(confidence=0.3, evidence={"note": "bridge chip only"}),
        ),
        by_id_path="/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B42135040-if00",
        ambiguous=ambiguous,
    )


class FakeLocal:
    """Duck-typed stand-in for livebench.local wired onto app.state.bench_local."""

    def __init__(self) -> None:
        self.conns: list[TapConn] = []
        self.opened: list[dict[str, Any]] = []
        self.serial_error: Exception | None = None
        self.gazebo_error: Exception | None = None

    def available_simulators(self) -> list[Any]:
        return [
            SimpleNamespace(kind="mujoco", available=True, reason=None),
            SimpleNamespace(
                kind="gazebo", available=False, reason="Gazebo is not installed (no `gz` CLI)"
            ),
            SimpleNamespace(kind="isaac", available=False, reason="Isaac Sim is not installed"),
        ]

    def list_devices(self) -> list[Any]:
        return [_fake_device()]

    async def _open(self, kind: str, **kwargs: Any) -> TapConn:
        self.opened.append({"kind": kind, **kwargs})
        conn = TapConn()
        self.conns.append(conn)
        return conn

    async def open_mujoco(self, **kwargs: Any) -> TapConn:
        return await self._open("mujoco", **kwargs)

    async def open_gazebo(self, topics: list[str], **kwargs: Any) -> TapConn:
        if self.gazebo_error is not None:
            raise self.gazebo_error
        return await self._open("gazebo", topics=topics, **kwargs)

    async def open_mcap(self, path: Any, **kwargs: Any) -> TapConn:
        return await self._open("mcap-replay", path=path, **kwargs)

    async def open_serial(self, serial_number: str | None, **kwargs: Any) -> TapConn:
        if self.serial_error is not None:
            raise self.serial_error
        return await self._open("serial", serial_number=serial_number, **kwargs)


@pytest.fixture
def fake_local(app: FastAPI) -> FakeLocal:
    fake = FakeLocal()
    app.state.bench_local = fake
    return fake


async def _member_project(client: AsyncClient, headers: dict[str, str]) -> str:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    project_id: str = project["id"]
    return project_id


async def test_sources_reports_honest_availability(
    client: AsyncClient, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    project_id = await _member_project(client, alice_headers)
    resp = await client.get(f"/api/v1/projects/{project_id}/bench/sources", headers=alice_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["runner"] == {"available": True, "reason": None}
    sims = {s["kind"]: s for s in data["simulators"]}
    assert sims["mujoco"]["available"] is True
    assert sims["gazebo"]["available"] is False and "not installed" in sims["gazebo"]["reason"]
    assert sims["mcap-replay"]["available"] is False  # bench_data_root unset
    (device,) = data["devices"]
    assert device["serial_number"] == "5B42135040"
    assert device["vid"] == "1a86" and device["pid"] == "55d3"
    assert device["board_class"] == "usb_bridge" and device["mcu_known"] is False
    assert device["by_id_path"].endswith("5B42135040-if00")
    assert device["ambiguous"] is False


async def test_sources_without_livebench_is_honestly_unavailable(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    app.state.bench_local = None
    project_id = await _member_project(client, alice_headers)
    data = (
        await client.get(f"/api/v1/projects/{project_id}/bench/sources", headers=alice_headers)
    ).json()["data"]
    assert data["runner"]["available"] is False
    assert "not installed" in data["runner"]["reason"]
    assert all(not s["available"] for s in data["simulators"])
    assert data["devices"] == []


async def test_session_lifecycle_start_list_detail_stop(
    client: AsyncClient, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    project_id = await _member_project(client, alice_headers)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions",
        json={"mode": "sim", "config": {"provider": "mujoco"}},
        headers=alice_headers,
    )
    assert resp.status_code == 201, resp.text
    record = resp.json()["data"]
    assert record["status"] == "active" and record["provider"] == "mujoco"
    assert record["mode"] == "sim"
    (opened,) = fake_local.opened
    assert str(opened["project_id"]) == project_id  # ctx-derived binding

    listed = (
        await client.get(f"/api/v1/projects/{project_id}/bench/sessions", headers=alice_headers)
    ).json()["data"]
    assert [s["id"] for s in listed] == [record["id"]]

    detail = (
        await client.get(
            f"/api/v1/projects/{project_id}/bench/sessions/{record['id']}", headers=alice_headers
        )
    ).json()["data"]
    assert detail["link"] == "connected"

    stopped = (
        await client.post(
            f"/api/v1/projects/{project_id}/bench/sessions/{record['id']}/stop",
            headers=alice_headers,
        )
    ).json()["data"]
    assert stopped["status"] == "ended"
    assert fake_local.conns[0].closed
    again = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions/{record['id']}/stop",
        headers=alice_headers,
    )
    assert again.status_code == 200  # idempotent
    active = (
        await client.get(
            f"/api/v1/projects/{project_id}/bench/sessions",
            params={"status": "active"},
            headers=alice_headers,
        )
    ).json()["data"]
    assert active == []


async def test_session_cap_returns_409(
    client: AsyncClient, alice_headers: dict[str, str], fake_local: FakeLocal, app: FastAPI
) -> None:
    from solus_api.livebench.sessions import SessionManager

    app.state.bench_sessions = SessionManager(
        app.state.telemetry_plumbing, max_active_per_project=1
    )
    project_id = await _member_project(client, alice_headers)
    body = {"mode": "sim", "config": {"provider": "mujoco"}}
    first = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions", json=body, headers=alice_headers
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions", json=body, headers=alice_headers
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "too_many_sessions"


async def test_serial_session_binds_by_serial_and_maps_device_errors(
    client: AsyncClient, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    project_id = await _member_project(client, alice_headers)
    body = {
        "mode": "real",
        "config": {"provider": "serial", "serial_number": "5B42135040", "baud": 115200},
    }
    resp = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions", json=body, headers=alice_headers
    )
    assert resp.status_code == 201, resp.text
    record = resp.json()["data"]
    assert record["device"]["serial_number"] == "5B42135040"
    assert "device_path" in record["device"]  # the desktop matches on this key
    assert "confirmed_device_path" not in record["device"]
    (opened,) = fake_local.opened
    assert opened["serial_number"] == "5B42135040"

    fake_local.serial_error = AmbiguousDeviceError([_fake_device(), _fake_device("/dev/ttyACM1")])
    ambiguous = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions", json=body, headers=alice_headers
    )
    assert ambiguous.status_code == 409
    err = ambiguous.json()["error"]
    assert err["code"] == "device_ambiguous"

    fake_local.serial_error = DeviceNotFoundError("no device with serial 'NOPE'")
    missing = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions", json=body, headers=alice_headers
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "device_not_found"


async def test_unavailable_simulator_cannot_be_started(
    client: AsyncClient, alice_headers: dict[str, str], fake_local: FakeLocal, app: FastAPI
) -> None:
    project_id = await _member_project(client, alice_headers)
    fake_local.gazebo_error = RuntimeError("gz CLI is not on PATH")
    resp = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions",
        json={"mode": "sim", "config": {"provider": "gazebo", "topics": ["/model/pose"]}},
        headers=alice_headers,
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "source_unavailable"

    app.state.bench_local = None
    resp = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions",
        json={"mode": "sim", "config": {"provider": "mujoco"}},
        headers=alice_headers,
    )
    assert resp.status_code == 503


async def test_session_config_validation(
    client: AsyncClient, alice_headers: dict[str, str], fake_local: FakeLocal
) -> None:
    project_id = await _member_project(client, alice_headers)
    url = f"/api/v1/projects/{project_id}/bench/sessions"
    cases = [
        {"mode": "real", "config": {"provider": "mujoco"}},  # mode/provider mismatch
        {"mode": "sim", "config": {"provider": "gazebo", "topics": []}},  # empty topics
        {"mode": "sim", "config": {"provider": "gazebo", "topics": ["-rf"]}},  # flag-shaped
        {"mode": "sim", "config": {"provider": "mujoco", "sample_hz": 0}},
        {"mode": "sim", "config": {"provider": "mujoco", "duration_seconds": 999999}},
        {"mode": "sim", "config": {"provider": "mujoco", "extra_field": 1}},
        {
            "mode": "sim",
            "config": {"provider": "mcap-replay", "mcap_path": "x.mcap", "topics": ["y" * 300]},
        },
    ]
    for body in cases:
        resp = await client.post(url, json=body, headers=alice_headers)
        assert resp.status_code == 422, body
    assert fake_local.opened == []


async def test_mcap_requires_configured_root_and_refuses_escapes(
    client: AsyncClient,
    alice_headers: dict[str, str],
    fake_local: FakeLocal,
    app: FastAPI,
    tmp_path: Any,
) -> None:
    project_id = await _member_project(client, alice_headers)
    url = f"/api/v1/projects/{project_id}/bench/sessions"

    def mcap_body(path: str) -> dict[str, Any]:
        return {"mode": "sim", "config": {"provider": "mcap-replay", "mcap_path": path}}

    resp = await client.post(url, json=mcap_body("run.mcap"), headers=alice_headers)
    assert resp.status_code == 503  # bench_data_root unset

    app.state.settings.bench_data_root = str(tmp_path)
    (tmp_path / "run.mcap").write_bytes(b"\x89MCAP0\r\n")
    escape = await client.post(url, json=mcap_body("../../etc/passwd"), headers=alice_headers)
    assert escape.status_code == 422
    missing = await client.post(url, json=mcap_body("ghost.mcap"), headers=alice_headers)
    assert missing.status_code == 422
    ok = await client.post(url, json=mcap_body("run.mcap"), headers=alice_headers)
    assert ok.status_code == 201, ok.text
    (opened,) = fake_local.opened
    assert str(opened["path"]).endswith("run.mcap")


async def test_device_recent_serves_unresolved_devices_batched(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _entity_id, _ref = await _project_with_graph(client, alice_headers)
    await _ingest(
        client,
        alice_headers,
        project_id,
        [
            wire_packet("serial:arm", 0.0, {"qvel": 1.5}),
            wire_packet("serial:arm2", 0.0, {"qpos": 0.25}),
        ],
    )
    # One request covers many devices — the desktop polls ALL visible panels in
    # a single batched call so N devices never multiply the request rate.
    resp = await client.get(
        f"/api/v1/projects/{project_id}/bench/device-recent",
        params={"device_id": ["serial:arm", "serial:arm2", "serial:ghost"]},
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text
    devices = resp.json()["data"]["devices"]
    assert [d["device_id"] for d in devices] == ["serial:arm", "serial:arm2", "serial:ghost"]
    (series,) = devices[0]["signals"]
    assert series["signal"] == "qvel"
    assert [p["value"] for p in series["points"]] == [1.5]
    assert devices[1]["signals"][0]["signal"] == "qpos"
    assert devices[2]["signals"] == []  # unknown device: honest empty, never invented

    too_many = await client.get(
        f"/api/v1/projects/{project_id}/bench/device-recent",
        params={"device_id": [f"d{i}" for i in range(17)]},
        headers=alice_headers,
    )
    assert too_many.status_code == 422


async def test_new_routes_are_cross_tenant_404(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    fake_local: FakeLocal,
) -> None:
    project_id = await _member_project(client, alice_headers)
    started = (
        await client.post(
            f"/api/v1/projects/{project_id}/bench/sessions",
            json={"mode": "sim", "config": {"provider": "mujoco"}},
            headers=alice_headers,
        )
    ).json()["data"]
    await me(client, bob_headers)

    for method, url in [
        ("get", f"/api/v1/projects/{project_id}/bench/sources"),
        ("get", f"/api/v1/projects/{project_id}/bench/sessions"),
        ("get", f"/api/v1/projects/{project_id}/bench/sessions/{started['id']}"),
        ("post", f"/api/v1/projects/{project_id}/bench/sessions/{started['id']}/stop"),
        ("get", f"/api/v1/projects/{project_id}/bench/device-recent?device_id=x"),
    ]:
        resp = await client.request(method, url, headers=bob_headers)
        assert resp.status_code == 404, url
    resp = await client.post(
        f"/api/v1/projects/{project_id}/bench/sessions",
        json={"mode": "sim", "config": {"provider": "mujoco"}},
        headers=bob_headers,
    )
    assert resp.status_code == 404

    # Foreign session id inside Bob's OWN project is also 404, never a leak.
    bob_team = await create_team(client, bob_headers)
    bob_project = await create_project(client, bob_headers, bob_team["id"])
    resp = await client.get(
        f"/api/v1/projects/{bob_project['id']}/bench/sessions/{started['id']}",
        headers=bob_headers,
    )
    assert resp.status_code == 404
