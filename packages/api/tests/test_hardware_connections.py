"""Committed connection attempts outlive requests, never deleted/config-changed robots."""

import asyncio
import uuid
from typing import Any

import pytest
from solus_api.models import GraphEntity, Membership, SolusEntry, utcnow
from sqlalchemy import select
from test_hardware_detect import DEVICE_REF, _confirm_body, _detect_project, _detect_url
from test_hardware_detect import detect_local as detect_local
from test_sessions import FakeConn


@pytest.mark.parametrize("status", ["connecting", "connected"])
async def test_delete_preserves_active_connection_owned_by_another_runtime(
    client: Any,
    alice_headers: dict[str, str],
    app: Any,
    detect_local: Any,
    status: str,
) -> None:
    from solus_api.hardware.connections import connection_state

    project, _ = await _detect_project(client, alice_headers)
    other_project, _ = await _detect_project(client, alice_headers)
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(),
    )
    assert response.status_code == 201, response.text
    robot = response.json()["data"]["robot"]
    metadata = connection_state(
        uuid.uuid4(), status, runtime_id=str(uuid.uuid4()), session_id=uuid.uuid4()
    )
    async with app.state.sessionmaker() as session:
        saved = await session.get(GraphEntity, uuid.UUID(robot["id"]))
        saved.attrs = {**saved.attrs, "connection": metadata}
        await session.commit()
    for target_project, expected in ((other_project, 404), (project, 409)):
        deleted = await client.delete(
            f"/api/v1/projects/{target_project}/entities/{robot['id']}",
            headers={**alice_headers, "If-Match": str(robot["version"])},
        )
        assert deleted.status_code == expected, deleted.text
        assert metadata["runtime_id"] not in deleted.text
    assert "owning local runtime" in deleted.json()["error"]["message"]
    async with app.state.sessionmaker() as session:
        saved = await session.get(GraphEntity, uuid.UUID(robot["id"]))
        assert saved.deleted_at is None and saved.attrs["connection"] == metadata


@pytest.mark.parametrize("local_available", [True, False])
@pytest.mark.parametrize("foreign_scope", ["legacy", "other_runtime", "other_manager"])
async def test_startup_reconciles_only_managed_state_without_touching_config(
    client: Any,
    alice_headers: dict[str, str],
    app: Any,
    detect_local: Any,
    local_available: bool,
    foreign_scope: str,
) -> None:
    from solus_api.hardware.connections import HardwareConnections, connection_state

    project, _ = await _detect_project(client, alice_headers)
    other_project, _ = await _detect_project(client, alice_headers)
    foreign_metadata = {
        "managed_by": "other" if foreign_scope == "other_manager" else "local_runtime",
        "attempt_id": str(uuid.uuid4()),
        "status": "connected",
        **({"runtime_id": str(uuid.uuid4())} if foreign_scope == "other_runtime" else {}),
    }
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(),
    )
    assert response.status_code == 201, response.text
    robot_id = uuid.UUID(response.json()["data"]["robot"]["id"])
    runtime_id = app.state.hardware_connections.owner.acquire()
    async with app.state.sessionmaker() as session:
        robot = await session.get(GraphEntity, robot_id)
        robot.attrs = {
            **robot.attrs,
            "connection": connection_state(
                uuid.uuid4(), "connected", session_id=uuid.uuid4(), runtime_id=runtime_id
            ),
        }
        foreign = GraphEntity(
            project_id=uuid.UUID(other_project),
            kind="physical_robot",
            domain=robot.domain,
            origin="manual",
            name="Other manager",
            attrs={"connection": foreign_metadata},
        )
        session.add(foreign)
        await session.commit()
        foreign_id = foreign.id
        before = [
            (entry.id, entry.config_version, entry.payload)
            for entry in await session.scalars(
                select(SolusEntry).where(SolusEntry.project_id == uuid.UUID(project))
            )
        ]
    coordinator = HardwareConnections(
        sessions=app.state.sessionmaker,
        manager=app.state.bench_sessions,
        local=detect_local if local_available else None,
        hub=app.state.graph_hub,
        owner=app.state.hardware_connections.owner,
    )
    await coordinator.startup()
    async with app.state.sessionmaker() as session:
        robot = await session.get(GraphEntity, robot_id)
        foreign = await session.get(GraphEntity, foreign_id)
        assert robot.attrs["connection"]["status"] == (
            "disconnected" if local_available else "connected"
        )
        assert foreign.attrs["connection"] == foreign_metadata
        after = [
            (entry.id, entry.config_version, entry.payload)
            for entry in await session.scalars(
                select(SolusEntry).where(SolusEntry.project_id == uuid.UUID(project))
            )
        ]
        assert before == after


async def test_confirm_returns_while_open_is_blocked(
    client: Any,
    alice_headers: dict[str, str],
    app: Any,
    detect_local: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.hardware.connections import HardwareConnections

    opened, release = asyncio.Event(), asyncio.Event()
    conn = FakeConn()

    async def open_robot(*args: Any, **kwargs: Any) -> FakeConn:
        opened.set()
        await release.wait()
        return conn

    monkeypatch.setattr(detect_local, "open_robot", open_robot)
    coordinator = HardwareConnections(
        sessions=app.state.sessionmaker,
        manager=app.state.bench_sessions,
        local=detect_local,
        hub=app.state.graph_hub,
        owner=app.state.hardware_connections.owner,
    )
    app.state.hardware_connections = coordinator
    project, _ = await _detect_project(client, alice_headers)
    try:
        response = await asyncio.wait_for(
            client.post(
                _detect_url(project, "detected", DEVICE_REF, "confirm"),
                headers=alice_headers,
                json=_confirm_body(start_session=True),
            ),
            5,
        )
        assert response.status_code == 201, response.text
        data = response.json()["data"]
        assert data["session_id"] is None and data["session_error"] is None
        state = data["robot"]["properties"]["connection"]
        assert state["status"] == "connecting" and state["managed_by"] == "local_runtime"
        await asyncio.wait_for(opened.wait(), 5)
        release.set()
        await coordinator.drain()
        robot = (
            await client.get(
                f"/api/v1/projects/{project}/entities/{data['robot']['id']}", headers=alice_headers
            )
        ).json()["data"]
        assert robot["properties"]["connection"]["status"] == "connected"
        assert robot["properties"]["connection"]["session_id"] is not None
    finally:
        release.set()
        await coordinator.aclose()
    assert conn.closed
    async with app.state.sessionmaker() as session:
        saved = await session.get(GraphEntity, uuid.UUID(data["robot"]["id"]))
        assert saved.attrs["connection"]["status"] == "disconnected"


@pytest.mark.parametrize("change", ["delete", "config", "child_config", "membership", "shutdown"])
async def test_stale_connection_completion_is_closed(
    client: Any,
    alice_headers: dict[str, str],
    app: Any,
    detect_local: Any,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    from solus_api.hardware.connections import HardwareConnections

    opened, release = asyncio.Event(), asyncio.Event()
    conn = FakeConn()

    async def late_open(*args: Any, **kwargs: Any) -> FakeConn:
        opened.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            pass  # A local driver can finish acquiring after cancellation.
        return conn

    monkeypatch.setattr(detect_local, "open_robot", late_open)
    coordinator = HardwareConnections(
        sessions=app.state.sessionmaker,
        manager=app.state.bench_sessions,
        local=detect_local,
        hub=app.state.graph_hub,
        owner=app.state.hardware_connections.owner,
    )
    app.state.hardware_connections = coordinator
    project, team = await _detect_project(client, alice_headers)
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(start_session=True),
    )
    assert response.status_code == 201, response.text
    robot = response.json()["data"]["robot"]
    try:
        await asyncio.wait_for(opened.wait(), 5)
        if change == "delete":
            deletion = asyncio.create_task(
                client.delete(
                    f"/api/v1/projects/{project}/entities/{robot['id']}",
                    headers={**alice_headers, "If-Match": str(robot["version"])},
                )
            )
            # Opening owns the native acquisition until its result can be closed.
            await asyncio.sleep(0)
            release.set()
            deleted = await deletion
            assert deleted.status_code == 200, deleted.text
        elif change in {"config", "child_config", "membership"}:
            async with app.state.sessionmaker() as session:
                if change in {"config", "child_config"}:
                    entry = await session.scalar(
                        select(SolusEntry).where(
                            SolusEntry.project_id == uuid.UUID(project),
                            (SolusEntry.configured_entity_id == uuid.UUID(robot["id"]))
                            if change == "config"
                            else (SolusEntry.configured_entity_id != uuid.UUID(robot["id"])),
                        )
                    )
                    assert entry is not None
                    entry.config_version += 1
                else:
                    member = await session.scalar(
                        select(Membership).where(
                            Membership.team_id == uuid.UUID(team), Membership.deleted_at.is_(None)
                        )
                    )
                    assert member is not None
                    member.deleted_at = utcnow()
                await session.commit()
            release.set()
            await coordinator.drain()
        else:
            closing = asyncio.create_task(coordinator.aclose())
            await asyncio.sleep(0)
            release.set()
            await closing
        assert conn.closed
        assert app.state.bench_sessions.list(uuid.UUID(project), status="active") == []
        async with app.state.sessionmaker() as session:
            saved = await session.get(GraphEntity, uuid.UUID(robot["id"]))
            assert saved is not None
            assert saved.attrs["connection"]["status"] != "connected"
            assert saved.attrs["connection"]["status"] != "connecting"
    finally:
        release.set()
        await coordinator.aclose()


async def test_concurrent_deletes_wait_for_hardware_close(
    client: Any,
    alice_headers: dict[str, str],
    app: Any,
    detect_local: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closing, release = asyncio.Event(), asyncio.Event()

    class DeferredClose(FakeConn):
        async def aclose(self) -> None:
            closing.set()
            await release.wait()
            await super().aclose()

    conn = DeferredClose()

    async def open_robot(*args: Any, **kwargs: Any) -> FakeConn:
        return conn

    monkeypatch.setattr(detect_local, "open_robot", open_robot)
    project, _ = await _detect_project(client, alice_headers)
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(start_session=True),
    )
    assert response.status_code == 201, response.text
    robot = response.json()["data"]["robot"]
    await app.state.hardware_connections.drain()

    async def delete() -> Any:
        return await client.delete(
            f"/api/v1/projects/{project}/entities/{robot['id']}",
            headers={**alice_headers, "If-Match": str(robot["version"])},
        )

    first = asyncio.create_task(delete())
    await closing.wait()
    second = asyncio.create_task(delete())
    try:
        done, _ = await asyncio.wait({first, second}, timeout=0.2)
        assert not done
    finally:
        release.set()
        results = await asyncio.gather(first, second)
    assert conn.closed
    assert sorted(result.status_code for result in results) == [200, 404]


@pytest.mark.parametrize("ending", ["stop", "sweep", "stop_during_commit", "closing_during_commit"])
async def test_bench_session_end_updates_owned_robot(
    client: Any,
    alice_headers: dict[str, str],
    app: Any,
    detect_local: Any,
    monkeypatch: pytest.MonkeyPatch,
    ending: str,
) -> None:
    from solus_api.connectors.live import LiveStatus

    closing, close_release = asyncio.Event(), asyncio.Event()

    class Deferred(FakeConn):
        async def aclose(self) -> None:
            closing.set()
            await close_release.wait()
            await super().aclose()

    conn = Deferred() if ending == "closing_during_commit" else FakeConn()

    async def open_robot(*args: Any, **kwargs: Any) -> FakeConn:
        return conn

    coordinator = app.state.hardware_connections
    committed, release = asyncio.Event(), asyncio.Event()
    original_finish = coordinator._finish

    async def delayed_finish(*args: Any, **kwargs: Any) -> bool:
        result = await original_finish(*args, **kwargs)
        if args[1] == "connected":
            committed.set()
            await release.wait()
        return bool(result)

    if ending in {"stop_during_commit", "closing_during_commit"}:
        monkeypatch.setattr(coordinator, "_finish", delayed_finish)
    monkeypatch.setattr(detect_local, "open_robot", open_robot)
    project, _ = await _detect_project(client, alice_headers)
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(start_session=True),
    )
    assert response.status_code == 201, response.text
    robot_id = uuid.UUID(response.json()["data"]["robot"]["id"])
    if ending in {"stop_during_commit", "closing_during_commit"}:
        await committed.wait()
    else:
        await coordinator.drain()
    async with app.state.sessionmaker() as session:
        robot = await session.get(GraphEntity, robot_id)
        session_id = uuid.UUID(robot.attrs["connection"]["session_id"])
    manager = app.state.bench_sessions
    if ending == "closing_during_commit":
        stopping = asyncio.create_task(manager.stop(uuid.UUID(project), session_id))
        await closing.wait()
        release.set()
        draining = asyncio.create_task(coordinator.drain())
        try:
            done, _ = await asyncio.wait({draining}, timeout=0.2)
            assert not done
        finally:
            close_release.set()
            await asyncio.gather(stopping, draining)
    elif ending in {"stop", "stop_during_commit"}:
        stopped = await client.post(
            f"/api/v1/projects/{project}/bench/sessions/{session_id}/stop",
            headers=alice_headers,
        )
        assert stopped.status_code == 200, stopped.text
        release.set()
        await coordinator.drain()
    else:
        conn._status = LiveStatus.DISCONNECTED
        await manager._sweep_dead(uuid.UUID(project))
    async with app.state.sessionmaker() as session:
        robot = await session.get(GraphEntity, robot_id)
        assert robot.attrs["connection"]["status"] == "disconnected"
        assert robot.attrs["connection"]["session_id"] is None
    assert conn.closed
