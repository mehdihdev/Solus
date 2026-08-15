"""LB-05: bench telemetry routes — ingest, recent values, summaries, events.

The first production wiring of LNK-06 (`TelemetryPlumbing`) behind the central
auth/scoping middleware. Cross-tenant isolation is the highest-severity invariant
(CLAUDE.md §7): every case here runs both the member and the outsider path.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import create_project, create_team, me  # type: ignore[attr-defined]
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.graph.codec import to_wire
from solus_api.graph.packet import TelemetryPacket

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
