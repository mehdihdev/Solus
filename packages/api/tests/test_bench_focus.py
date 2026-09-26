"""Read-only focus narrowing follows accepted topology and never crosses projects."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
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
        params: dict[str, object] = {"device_id": list(targets)}
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
