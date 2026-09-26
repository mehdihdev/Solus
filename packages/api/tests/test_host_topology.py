"""Reviewed host topology binds live local authority without changing runtime config."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.models import Domain, GraphEntity, Source, SourceStatus, SourceType, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_router import _hw_project, _hw_url, _robot, _saved_serial_arm
from test_local_folder_routes import MACHINE, FakeCompanion, _scan


class Provider:
    machine_id: str | None = MACHINE
    device_ref = "usb:5B42134331"

    async def identity(self) -> str | None:
        return self.machine_id

    async def devices(self) -> list[dict[str, Any]]:
        return [{"device_ref": self.device_ref}]


async def setup_host(
    client: AsyncClient, app: FastAPI, headers: dict[str, str], db: AsyncSession
) -> tuple[str, str, dict[str, Any], Provider]:
    from solus_api.hardware.host_topology import host_provider

    project, team = await _hw_project(client, headers)
    robot = await _robot(client, headers, project)
    config = await _saved_serial_arm(client, headers, project, robot["id"])
    saved = await client.put(
        _hw_url(project, "robots", robot["id"], "config"), headers=headers, json={"config": config}
    )
    assert saved.status_code == 200, saved.text
    me = (await client.get("/api/v1/users/me", headers=headers)).json()["data"]
    user = await db.get(User, uuid.UUID(me["id"]))
    assert user
    companion = FakeCompanion(_scan())
    bridge = companion.bind(
        app, user_id=user.id, team_id=uuid.UUID(team), project_id=uuid.UUID(project)
    )
    bridge.token_exp += timedelta(hours=1)
    source = Source(
        project_id=uuid.UUID(project),
        team_id=uuid.UUID(team),
        type=SourceType.LOCAL,
        name="Fixture workstation",
        status=SourceStatus.CONNECTED,
        created_by=user.id,
        config={
            "machine_id": MACHINE,
            "user_id": str(user.id),
            "machine_name": "Fixture workstation",
        },
    )
    db.add(source)
    await db.flush()
    clone = GraphEntity(
        project_id=uuid.UUID(project),
        source_id=source.id,
        origin="connector",
        kind="local_clone",
        domain=Domain.CODE,
        name="Control repo",
        external_ref="clone:",
        attrs={"head": "abc"},
    )
    db.add(clone)
    await db.commit()
    data = (
        await client.get(_hw_url(project, "robots", robot["id"], "topology"), headers=headers)
    ).json()["data"]
    body = {
        "endpoint_id": next(n["id"] for n in data["nodes"] if n["role"] == "brain"),
        "machine_id": MACHINE,
        "local_source_id": str(source.id),
        "software_entity_id": str(clone.id),
    }
    provider = Provider()
    app.dependency_overrides[host_provider] = lambda: provider
    return project, robot["id"], body, provider


@pytest.mark.asyncio
async def test_proposal_is_readonly_confirm_replay_and_config_resync_preserve_host(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from solus_api.hardware.runtime import resolve_runtime_config
    from solus_api.hardware.topology import sync_topology

    project, robot, body, _ = await setup_host(client, app, alice_headers, db)
    url = _hw_url(project, "robots", robot, "topology", "host")
    original = await resolve_runtime_config(db, uuid.UUID(project), uuid.UUID(robot))
    count = await db.scalar(select(func.count()).select_from(GraphEntity))
    proposal = await client.post(url + "/propose", headers=alice_headers, json=body)
    assert proposal.status_code == 200, proposal.text
    data = proposal.json()["data"]
    assert any(n["brain_kind"] == "host" for n in data["topology"]["nodes"])
    assert await db.scalar(select(func.count()).select_from(GraphEntity)) == count
    headers = {**alice_headers, "Idempotency-Key": str(uuid.uuid4())}
    payload = {**body, "proposal_digest": data["proposal_digest"]}
    confirmed = await client.post(url + "/confirm", headers=headers, json=payload)
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()["data"]
    host = next(n for n in result["nodes"] if n["brain_kind"] == "host")
    assert host["software"] == "Control repo"
    assert host["presence"] is None
    assert next(n for n in result["nodes"] if n["id"] == body["endpoint_id"])["brain_kind"] is None
    replay = await client.post(url + "/confirm", headers=headers, json=payload)
    assert replay.json() == confirmed.json()
    await sync_topology(db, uuid.UUID(project), uuid.UUID(robot))
    await db.commit()
    assert await resolve_runtime_config(db, uuid.UUID(project), uuid.UUID(robot)) == original
    current = await client.get(_hw_url(project, "robots", robot, "topology"), headers=alice_headers)
    assert current.json()["data"] == result


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["machine", "source", "endpoint", "config"])
async def test_confirmation_rechecks_fresh_authority_and_evidence(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], db: AsyncSession, change: str
) -> None:
    from solus_api.models import SolusEntry

    project, robot, body, provider = await setup_host(client, app, alice_headers, db)
    url = _hw_url(project, "robots", robot, "topology", "host")
    proposal = await client.post(url + "/propose", headers=alice_headers, json=body)
    assert proposal.status_code == 200, proposal.text
    if change == "machine":
        provider.machine_id = "d" * 32
    elif change == "endpoint":
        provider.device_ref = "usb:elsewhere"
    elif change == "source":
        source = await db.get(Source, uuid.UUID(body["local_source_id"]))
        assert source
        source.config = {**source.config, "machine_name": "Changed"}
        await db.commit()
    else:
        entry = await db.scalar(
            select(SolusEntry).where(SolusEntry.configured_entity_id == uuid.UUID(robot))
        )
        assert entry
        entry.config_version += 1
        await db.commit()
    result = await client.post(
        url + "/confirm",
        headers={**alice_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={**body, "proposal_digest": proposal.json()["data"]["proposal_digest"]},
    )
    assert result.status_code in (404, 409, 503), result.text


@pytest.mark.asyncio
async def test_shared_host_keeps_software_per_robot_and_retires_changed_endpoint(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, first, body, provider = await setup_host(client, app, alice_headers, db)

    async def confirm(robot: str, requested: dict[str, Any]) -> dict[str, Any]:
        url = _hw_url(project, "robots", robot, "topology", "host")
        proposal = await client.post(url + "/propose", headers=alice_headers, json=requested)
        assert proposal.status_code == 200, proposal.text
        response = await client.post(
            url + "/confirm",
            headers={**alice_headers, "Idempotency-Key": str(uuid.uuid4())},
            json={**requested, "proposal_digest": proposal.json()["data"]["proposal_digest"]},
        )
        assert response.status_code == 200, response.text
        return dict(response.json()["data"])

    before = await confirm(first, body)
    second = await _robot(client, alice_headers, project)
    config = await _saved_serial_arm(client, alice_headers, project, second["id"])
    config["identity"]["binding"] = "other-usb"
    saved = await client.put(
        _hw_url(project, "robots", second["id"], "config"),
        headers=alice_headers,
        json={"config": config},
    )
    assert saved.status_code == 200, saved.text
    file = GraphEntity(
        project_id=uuid.UUID(project),
        source_id=uuid.UUID(body["local_source_id"]),
        origin="connector",
        kind="file",
        domain=Domain.CODE,
        name="controller.py",
        external_ref="file:controller.py",
    )
    db.add(file)
    await db.commit()
    topology = (
        await client.get(
            _hw_url(project, "robots", second["id"], "topology"), headers=alice_headers
        )
    ).json()["data"]
    provider.device_ref = "usb:other-usb"
    after = await confirm(
        second["id"],
        {
            **body,
            "endpoint_id": next(n["id"] for n in topology["nodes"] if n["role"] == "brain"),
            "software_entity_id": str(file.id),
            "endpoint_brain_kind": "mcu",
        },
    )
    host1 = next(n for n in before["nodes"] if n["brain_kind"] == "host")
    host2 = next(n for n in after["nodes"] if n["brain_kind"] == "host")
    assert host1["id"] == host2["id"]
    assert host1["software"] == "Control repo" and host2["software"] == "controller.py"
    assert any(n["brain_kind"] == "mcu" for n in after["nodes"])
    unchanged = (
        await client.get(_hw_url(project, "robots", first, "topology"), headers=alice_headers)
    ).json()["data"]
    assert unchanged == before
    config["identity"]["binding"] = "replacement-usb"
    saved = await client.put(
        _hw_url(project, "robots", second["id"], "config"),
        headers=alice_headers,
        json={"config": config},
    )
    assert saved.status_code == 200, saved.text
    changed = (
        await client.get(
            _hw_url(project, "robots", second["id"], "topology"), headers=alice_headers
        )
    ).json()["data"]
    assert not any(n["brain_kind"] == "host" for n in changed["nodes"])


@pytest.mark.asyncio
async def test_host_authorization_and_local_only_software(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project, robot, body, _ = await setup_host(client, app, alice_headers, db)
    url = _hw_url(project, "robots", robot, "topology", "host", "propose")
    assert (await client.post(url, json=body)).status_code == 401
    assert (await client.post(url, json=body, headers=bob_headers)).status_code == 404
    assert (
        await client.post(url, json={**body, "machine_id": "d" * 32}, headers=alice_headers)
    ).status_code == 404
    remote = GraphEntity(
        project_id=uuid.UUID(project),
        kind="repository",
        domain=Domain.CODE,
        name="Reference repository",
        origin="connector",
    )
    db.add(remote)
    await db.commit()
    assert (
        await client.post(
            url, json={**body, "software_entity_id": str(remote.id)}, headers=alice_headers
        )
    ).status_code == 404
    source = await db.get(Source, uuid.UUID(body["local_source_id"]))
    assert source
    source.config = {**source.config, "user_id": str(uuid.uuid4())}
    await db.commit()
    assert (await client.post(url, json=body, headers=alice_headers)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["source", "expiry"])
async def test_confirmation_rejects_authority_changes_during_usb_enumeration(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    from solus_api.models import GraphEdge, utcnow

    project, robot, body, provider = await setup_host(client, app, alice_headers, db)
    url = _hw_url(project, "robots", robot, "topology", "host")
    proposal = await client.post(url + "/propose", headers=alice_headers, json=body)
    assert proposal.status_code == 200, proposal.text
    before = await db.scalar(select(func.count()).select_from(GraphEdge))

    async def changed_devices() -> list[dict[str, Any]]:
        source = await db.get(Source, uuid.UUID(body["local_source_id"]))
        assert source and source.created_by
        if change == "source":
            source.config = {**source.config, "machine_name": "Relinked during scan"}
            await db.commit()
        else:
            bridge = app.state.bridge_sessions.get(
                source.created_by, source.team_id, source.project_id
            )
            assert bridge
            bridge.token_exp = utcnow() - timedelta(seconds=1)
        return [{"device_ref": provider.device_ref}]

    monkeypatch.setattr(provider, "devices", changed_devices)
    response = await client.post(
        url + "/confirm",
        headers={**alice_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={**body, "proposal_digest": proposal.json()["data"]["proposal_digest"]},
    )
    assert response.status_code == 409, response.text
    assert await db.scalar(select(func.count()).select_from(GraphEdge)) == before


@pytest.mark.asyncio
async def test_confirmation_rechecks_bridge_after_source_lock_wait(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.hardware.host_topology import HostAttachment, HostTopologyService

    project, robot, body, _ = await setup_host(client, app, alice_headers, db)
    url = _hw_url(project, "robots", robot, "topology", "host")
    proposal = await client.post(url + "/propose", headers=alice_headers, json=body)
    assert proposal.status_code == 200
    original = HostTopologyService._source

    async def after_lock(
        service: HostTopologyService, request: HostAttachment, *, lock: bool = False
    ) -> tuple[Source, GraphEntity, GraphEntity | None]:
        result = await original(service, request, lock=lock)
        if lock:
            bridge = service.sessions.get(service.user_id, service.team_id, service.project_id)
            assert bridge
            service.sessions.remove(bridge)
        return result

    monkeypatch.setattr(HostTopologyService, "_source", after_lock)
    response = await client.post(
        url + "/confirm",
        headers={**alice_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={**body, "proposal_digest": proposal.json()["data"]["proposal_digest"]},
    )
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("already_confirmed", [False, True])
async def test_host_confirm_and_replay_require_project_authorization(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    already_confirmed: bool,
) -> None:
    from solus_api.models import GraphEdge, HardwareOperation

    project, robot, body, _ = await setup_host(client, app, alice_headers, db)
    url = _hw_url(project, "robots", robot, "topology", "host")
    proposal = await client.post(url + "/propose", headers=alice_headers, json=body)
    assert proposal.status_code == 200, proposal.text
    payload = {**body, "proposal_digest": proposal.json()["data"]["proposal_digest"]}
    key = {"Idempotency-Key": str(uuid.uuid4())}
    if already_confirmed:
        accepted = await client.post(
            url + "/confirm", headers={**alice_headers, **key}, json=payload
        )
        assert accepted.status_code == 200, accepted.text

    async def row_counts() -> list[int | None]:
        return [
            await db.scalar(select(func.count()).select_from(model))
            for model in (GraphEntity, GraphEdge, HardwareOperation)
        ]

    before = await row_counts()
    for headers, status in ((key, 401), ({**bob_headers, **key}, 404)):
        denied = await client.post(url + "/confirm", headers=headers, json=payload)
        assert denied.status_code == status, denied.text
        assert await row_counts() == before


@pytest.mark.asyncio
async def test_robot_removal_retires_host_connectivity(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from solus_api.hardware.topology import HOST_MARKER
    from solus_api.models import GraphEdge

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
    removed = await client.delete(
        f"/api/v1/projects/{project}/entities/{robot}", headers={**alice_headers, "If-Match": "1"}
    )
    assert removed.status_code == 200, removed.text
    assert (
        await db.scalar(
            select(func.count())
            .select_from(GraphEdge)
            .where(
                GraphEdge.project_id == uuid.UUID(project),
                GraphEdge.attrs["managed_by"].astext == HOST_MARKER,
                GraphEdge.attrs["robot_id"].astext == robot,
                GraphEdge.deleted_at.is_(None),
            )
        )
        == 0
    )
