"""Read-only focus narrowing follows accepted topology and never crosses projects."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import BOB, add_member, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.models import Domain, GraphEdge, GraphEntity, utcnow
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_router import _hw_project, _robot


@pytest.mark.asyncio
async def test_focus_narrows_only_confirmed_projection(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _ = await _hw_project(client, alice_headers)
    first = await _robot(client, alice_headers, project)
    second = await _robot(client, alice_headers, project)
    unmapped = await _robot(client, alice_headers, project)
    host, motor_a, motor_b, unrelated = [uuid.uuid4() for _ in range(4)]
    for identity in (host, motor_a, motor_b, unrelated):
        db.add(
            GraphEntity(
                id=identity,
                project_id=uuid.UUID(project),
                kind="part",
                domain=Domain.ELECTRICAL,
                origin="manual",
                name="Observed part",
            )
        )
    await db.flush()
    for robot, target in [(first, motor_a), (second, motor_b)]:
        for source, destination, kind in [
            (uuid.UUID(robot["id"]), host, "hardware_topology_member"),
            (host, target, "hardware_connected_to"),
        ]:
            db.add(
                GraphEdge(
                    project_id=uuid.UUID(project),
                    src_id=source,
                    dst_id=destination,
                    relation_type=kind,
                    domain_pair="electrical<->electrical",
                    origin="manual",
                    attrs={"managed_by": "hardware_topology_v1", "robot_id": robot["id"]},
                )
            )
    db.add(
        GraphEdge(
            project_id=uuid.UUID(project),
            src_id=host,
            dst_id=unrelated,
            relation_type="connected_to",
            domain_pair="electrical<->electrical",
            origin="manual",
        )
    )
    await db.commit()
    targets = {"a": motor_a, "b": motor_b, "unrelated": unrelated, "unknown": None}

    async def recent(_project: uuid.UUID, device: str, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            device_id=device,
            resolved_entity_id=targets[device],
            model_dump=lambda **_: {
                "device_id": device,
                "resolved_entity_id": str(targets[device]) if targets[device] else None,
                "signals": [],
            },
        )

    monkeypatch.setattr(
        app.state.telemetry_plumbing, "get_device_recent", AsyncMock(side_effect=recent)
    )
    url = f"/api/v1/projects/{project}/bench/device-recent"

    async def devices(focus: str | None) -> list[str]:
        params: dict[str, str | list[str]] = {"device_id": list(targets)}
        if focus:
            params["focus_entity_id"] = focus
        result = await client.get(url, headers=alice_headers, params=params)
        assert result.status_code == 200, result.text
        return [row["device_id"] for row in result.json()["data"]["devices"]]

    assert await devices(unmapped["id"]) == []
    assert await devices(None) == list(targets)
    assert await devices(first["id"]) == ["a"]
    assert await devices(second["id"]) == ["b"]
    assert await devices(str(host)) == ["a", "b"]
    assert await devices(str(motor_a)) == ["a"]
    assert await devices(str(uuid.UUID(first["id"]))) == ["a"]


@pytest.mark.asyncio
async def test_focus_refuses_foreign_deleted_and_unauthenticated(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project, _ = await _hw_project(client, alice_headers)
    other, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    params = {"device_id": "unknown", "focus_entity_id": robot["id"]}
    assert (
        await client.get(
            f"/api/v1/projects/{other}/bench/device-recent", headers=alice_headers, params=params
        )
    ).status_code == 404
    url = f"/api/v1/projects/{project}/bench/device-recent"
    assert (await client.get(url, params=params)).status_code == 401
    assert (await client.get(url, headers=bob_headers, params=params)).status_code == 404
    assert (
        await client.get(
            url,
            headers=alice_headers,
            params={"device_id": "unknown", "focus_entity_id": "invalid"},
        )
    ).status_code == 422
    entity = await db.get(GraphEntity, uuid.UUID(robot["id"]))
    assert entity is not None
    entity.deleted_at = utcnow()
    await db.commit()
    assert (await client.get(url, headers=alice_headers, params=params)).status_code == 404


@pytest.mark.asyncio
async def test_reachable_query_bounds_leaf_cycle_and_foreign_edges(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.livebench.focus_scope import focus_entity_ids

    project, _ = await _hw_project(client, alice_headers)
    other, _ = await _hw_project(client, alice_headers)
    ids = [uuid.uuid4() for _ in range(6)]
    for index, identity in enumerate(ids):
        db.add(
            GraphEntity(
                id=identity,
                project_id=uuid.UUID(other if index == 5 else project),
                kind="part",
                domain=Domain.ELECTRICAL,
                origin="manual",
                name="Part",
            )
        )
    await db.flush()
    for source, target in [(ids[0], ids[1]), (ids[1], ids[0]), (ids[2], ids[3]), (ids[0], ids[5])]:
        db.add(
            GraphEdge(
                project_id=uuid.UUID(project),
                src_id=source,
                dst_id=target,
                relation_type="hardware_connected_to",
                domain_pair="electrical<->electrical",
                origin="manual",
                attrs={"managed_by": "hardware_topology_v1"},
            )
        )
    await db.flush()
    execute = AsyncMock(wraps=db.execute)
    monkeypatch.setattr(db, "execute", execute)
    assert await focus_entity_ids(db, uuid.UUID(project), ids[4]) == {ids[4]}
    statement = execute.call_args.args[0]
    sql = str(statement).lower()
    assert "with recursive" in sql
    assert "union all" not in sql  # UUID-only UNION removes cycles in the database.
    assert len(statement.selected_columns) == 1
    assert await focus_entity_ids(db, uuid.UUID(project), ids[0]) == {ids[0], ids[1]}


@pytest.mark.asyncio
async def test_focus_reaches_devices_through_accepted_host(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    from solus_api.livebench.focus_scope import focus_entity_ids
    from test_hardware_router import _hw_url
    from test_host_topology import setup_host

    project, robot, body, _ = await setup_host(client, app, alice_headers, db)
    url = _hw_url(project, "robots", robot, "topology", "host")
    proposal = await client.post(url + "/propose", headers=alice_headers, json=body)
    assert proposal.status_code == 200, proposal.text
    confirmed = await client.post(
        url + "/confirm",
        headers={**alice_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={**body, "proposal_digest": proposal.json()["data"]["proposal_digest"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    topology = confirmed.json()["data"]
    host = next(node["id"] for node in topology["nodes"] if node["brain_kind"] == "host")
    allowed = await focus_entity_ids(db, uuid.UUID(project), uuid.UUID(host))
    assert uuid.UUID(body["endpoint_id"]) in allowed
    parts = {uuid.UUID(node["id"]) for node in topology["nodes"] if node["role"] == "part"}
    assert parts and parts <= allowed


@pytest.mark.asyncio
async def test_focus_and_descendants_honor_selected_source_revision(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    from solus_api.core.errors import APIError
    from solus_api.graph.read_scope import GraphReadScope, bind_scope
    from solus_api.livebench.focus_scope import focus_entity_ids
    from solus_api.models import Source, SourceType

    project, team = await _hw_project(client, alice_headers)
    pid = uuid.UUID(project)
    base = Source(project_id=pid, team_id=uuid.UUID(team), type=SourceType.GITHUB, name="base")
    db.add(base)
    await db.flush()
    snapshot = Source(
        project_id=pid,
        team_id=uuid.UUID(team),
        type=SourceType.GITHUB,
        name="snapshot",
        revision_base_source_id=base.id,
    )
    db.add(snapshot)
    await db.flush()
    nodes = [
        GraphEntity(
            project_id=pid,
            source_id=source,
            kind="part",
            domain=Domain.ELECTRICAL,
            origin="connector" if source else "manual",
            name="Part",
        )
        for source in (None, base.id, snapshot.id)
    ]
    db.add_all(nodes)
    await db.flush()
    for target in nodes[1:]:
        db.add(
            GraphEdge(
                project_id=pid,
                src_id=nodes[0].id,
                dst_id=target.id,
                relation_type="hardware_connected_to",
                domain_pair="electrical<->electrical",
                origin="manual",
                attrs={"managed_by": "hardware_topology_v1"},
            )
        )
    await db.flush()
    with pytest.raises(APIError):
        await focus_entity_ids(db, pid, nodes[2].id)
    assert await focus_entity_ids(db, pid, nodes[0].id) == {nodes[0].id, nodes[1].id}
    with bind_scope(GraphReadScope(pid, ((base.id, snapshot.id),))):
        with pytest.raises(APIError):
            await focus_entity_ids(db, pid, nodes[1].id)
        assert await focus_entity_ids(db, pid, nodes[0].id) == {nodes[0].id, nodes[2].id}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "untrusted", ["missing_marker", "wrong_marker", "connector", "source", "deleted"]
)
async def test_focus_rejects_untrusted_or_deleted_hardware_edges(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    untrusted: str,
) -> None:
    from solus_api.livebench.focus_scope import focus_entity_ids
    from solus_api.models import Source, SourceType

    project, team = await _hw_project(client, alice_headers)
    pid = uuid.UUID(project)
    source = Source(project_id=pid, team_id=uuid.UUID(team), type=SourceType.GITHUB, name="import")
    db.add(source)
    nodes = [
        GraphEntity(
            project_id=pid, kind="part", domain=Domain.ELECTRICAL, origin="manual", name="Part"
        )
        for _ in range(2)
    ]
    db.add_all(nodes)
    await db.flush()
    marker = (
        {}
        if untrusted == "missing_marker"
        else {"managed_by": "untrusted" if untrusted == "wrong_marker" else "hardware_topology_v1"}
    )
    db.add(
        GraphEdge(
            project_id=pid,
            src_id=nodes[0].id,
            dst_id=nodes[1].id,
            relation_type="hardware_connected_to",
            domain_pair="electrical<->electrical",
            origin="connector" if untrusted == "connector" else "manual",
            source_id=source.id if untrusted == "source" else None,
            deleted_at=utcnow() if untrusted == "deleted" else None,
            attrs=marker,
        )
    )
    await db.flush()
    assert await focus_entity_ids(db, pid, nodes[0].id) == {nodes[0].id}


@pytest.mark.asyncio
async def test_focus_on_hardware_out_of_the_graph_is_its_onboarders_alone(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    """SOLUSDEV-326: a teammate's focus on a robot its onboarder has not added to the graph is the
    same 404 as an unknown one; once it is added, the teammate focuses it too."""
    project, team = await _hw_project(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team)
    robot = await _robot(client, alice_headers, project)
    row = await db.get(GraphEntity, uuid.UUID(robot["id"]))
    assert row is not None
    row.attrs = {**row.attrs, "onboarded_by": (await me(client, alice_headers))["id"]}  # P2's tools
    await db.commit()
    graph = f"/api/v1/projects/{project}/hardware/entities/{robot['id']}/graph"

    async def recent(_project: uuid.UUID, device: str, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            device_id=device,
            resolved_entity_id=None,
            model_dump=lambda **_: {"device_id": device, "resolved_entity_id": None, "signals": []},
        )

    monkeypatch.setattr(
        app.state.telemetry_plumbing, "get_device_recent", AsyncMock(side_effect=recent)
    )
    url = f"/api/v1/projects/{project}/bench/device-recent"
    params = {"device_id": "unknown", "focus_entity_id": robot["id"]}

    async def focus(headers: dict[str, str]) -> int:
        return (await client.get(url, headers=headers, params=params)).status_code

    removed = await client.put(graph, headers=alice_headers, json={"in_graph": False})
    assert removed.status_code == 200, removed.text
    assert (await focus(alice_headers), await focus(bob_headers)) == (200, 404)
    added = await client.put(graph, headers=alice_headers, json={"in_graph": True})
    assert added.status_code == 200, added.text
    assert (await focus(alice_headers), await focus(bob_headers)) == (200, 200)


@pytest.mark.asyncio
async def test_live_bench_reads_leave_out_a_teammates_hidden_hardware(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SOLUSDEV-326: the project-wide Live Bench reads are per viewer too. A running session of a
    robot its onboarder keeps out of the graph, with its devices, values, summary and observer
    events, reaches her alone; a teammate can neither read nor stop it (the 404 of an unknown
    session) until she adds the robot to the graph."""
    from datetime import UTC, datetime
    from typing import Any

    from solus_api.graph.packet import TelemetryPacket
    from solus_api.livebench.bench_router import ObserverEventIn
    from solus_api.livebench.sessions import SessionManager
    from sqlalchemy import select
    from test_bench_router import TapConn
    from test_hardware_detect import DEVICE_REF
    from test_in_graph import _onboard, _team

    team = await _team(client, alice_headers, bob_headers)
    result = await _onboard(db, team)
    manager = SessionManager(app.state.telemetry_plumbing)  # no evaluator: the reads are tested
    monkeypatch.setattr(app.state, "bench_sessions", manager)
    conn = TapConn()

    async def open_conn() -> TapConn:
        return conn

    record = await manager.start(
        team.project_id,
        mode="real",
        provider="robot",
        label="Robot Private arm",
        open_conn=open_conn,
        device={"device_ref": DEVICE_REF},
        robot_entity_id=result.robot.id,
        owner_user_id=team.alice_id,
    )
    device, signal, now = f"{DEVICE_REF}/1", "Private arm-Motor-1.position", datetime.now(UTC)
    await conn.tap(TelemetryPacket(device_id=device, timestamp=now, values={signal: 1.0}))
    app.state.bench_events.append(
        team.project_id,
        ObserverEventIn(kind="threshold_breach", device_id=device, signal=signal, at=now),
    )
    part = await db.scalar(
        select(GraphEntity.id).where(
            GraphEntity.project_id == team.project_id, GraphEntity.external_ref == device
        )
    )
    bench = team.url("bench")

    async def view(headers: dict[str, str]) -> dict[str, Any]:
        async def data(path: str, **params: Any) -> Any:
            response = await client.get(f"{bench}/{path}", headers=headers, params=params)
            assert response.status_code == 200, (path, response.text)
            return response.json()["data"]

        async def status(path: str) -> int:
            return (await client.get(f"{bench}/{path}", headers=headers)).status_code

        windows = (await data("summary", duration_seconds=60))["windows"]
        recent = (await data("device-recent", device_id=device))["devices"]
        return {
            "sessions": [row["id"] for row in await data("sessions")],
            "summary": sorted({name for found in windows for name in found["signals"]}),
            "devices": (await data("telemetry-devices"))["device_ids"],
            "device_recent": [row["device_id"] for row in recent],
            "events": [row["device_id"] for row in await data("events")],
            "values": await status(f"recent/{part}"),
            "detail": await status(f"sessions/{record.id}"),
        }

    seen = {
        "sessions": [str(record.id)],
        "summary": [signal],
        "devices": [device],
        "device_recent": [device],
        "events": [device],
        "values": 200,
        "detail": 200,
    }
    assert await view(alice_headers) == seen
    assert await view(bob_headers) == {
        "sessions": [],
        "summary": [],
        "devices": [],
        "device_recent": [],
        "events": [],
        "values": 404,
        "detail": 404,
    }
    stop = f"{bench}/sessions/{record.id}/stop"
    assert (await client.post(stop, headers=bob_headers)).status_code == 404
    assert manager.get(team.project_id, record.id).status == "active"
    assert (await client.get(f"{bench}/sessions/{record.id}")).status_code == 401

    added = await client.put(
        team.url("hardware", "entities", str(result.robot.id), "graph"),
        headers=alice_headers,
        json={"in_graph": True},
    )
    assert added.status_code == 200, added.text
    assert await view(bob_headers) == seen
    assert (await client.post(stop, headers=bob_headers)).status_code == 200


async def test_an_event_keeps_the_hardware_its_session_resolved_it_to(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """SOLUSDEV-326: an observer event is attributed by the session that emits it, the way that
    session resolved its packet. A sim session names a device by a sim alias only its provider
    resolves; on a robot out of the graph its events reach the onboarder alone, even after a
    packet without that provider names the same device. An event on a device bound to nothing
    is every member's, like the device list."""
    from datetime import UTC, datetime
    from typing import Any

    from solus_api.graph.packet import TelemetryPacket
    from solus_api.livebench.bench_router import ObserverEventIn
    from solus_api.livebench.sessions import SessionManager
    from test_bench_router import TapConn
    from test_in_graph import _onboard, _team

    team = await _team(client, alice_headers, bob_headers)
    result = await _onboard(db, team)  # out of the graph: Alice's alone
    alias, loose, now = "mujoco/arm/shoulder", "usb:UNBOUND/1", datetime.now(UTC)
    part = await db.get(GraphEntity, result.part_ids[0])
    assert part is not None
    part.attrs = {**part.attrs, "sim_aliases": [{"provider": "mujoco", "device_id": alias}]}
    await db.commit()

    class Observer:
        def add(self, packet: TelemetryPacket) -> list[dict[str, Any]]:
            at = packet.timestamp.isoformat()
            return [
                {"kind": "change_point", "device_id": packet.device_id, "signal": "s", "at": at}
            ]

    plumbing = app.state.telemetry_plumbing
    manager = SessionManager(
        plumbing, observer_factory=Observer, event_sink=app.state.bench_events.record
    )
    conn = TapConn()

    async def open_conn() -> TapConn:
        return conn

    await manager.start(
        team.project_id,
        mode="sim",
        provider="mujoco",
        label="Sim arm",
        open_conn=open_conn,
        robot_entity_id=result.robot.id,
        owner_user_id=team.alice_id,
        evaluate=False,
    )
    packet = TelemetryPacket(device_id=alias, timestamp=now, values={"shoulder.position": 1.0})
    await conn.tap(packet)
    await plumbing.ingest(team.project_id, packet)  # no provider: the alias resolves to nothing
    await conn.tap(packet)
    event = ObserverEventIn(kind="change_point", device_id=loose, signal="s", at=now)
    app.state.bench_events.append(team.project_id, event)

    async def events(headers: dict[str, str]) -> list[str]:
        response = await client.get(team.url("bench", "events"), headers=headers)
        assert response.status_code == 200, response.text
        assert "owner" not in response.text
        return [row["device_id"] for row in response.json()["data"]]

    assert await events(alice_headers) == [alias, alias, loose]
    assert await events(bob_headers) == [loose]
    await manager.aclose_all()
