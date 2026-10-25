"""graph/inference/overlay_edges: `drives` bus → device from the topology overlay and `hosts`
machine → robot from a confirmed host brain (SOLUSDEV-320 Phase 3 module 3)."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.graph.inference import InferenceReport, overlay_edges
from solus_api.hardware.topology import read_topology
from solus_api.models import GraphEdge, GraphEntity
from solus_api.services.machines import MachineIn, upsert_machine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_router import _hw_url
from test_host_topology import setup_host
from test_inference_firmware_edges import USER, inferred, seed_robot
from test_local_folder_routes import MACHINE


async def test_drives_bus_to_device_from_the_overlay(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    pid, robot, brain, parts = await seed_robot(client, alice_headers, db)
    before = await read_topology(db, pid, robot)

    report = await overlay_edges.infer(db, pid, robot_id=robot)

    drives = await inferred(db, pid, "drives")
    buses = {e.src_id for e in drives}
    assert len(buses) == 1
    bus = await db.get(GraphEntity, buses.pop())
    assert bus is not None and bus.kind == kinds.HARDWARE_BUS
    assert {e.dst_id: e.attrs["evidence"][0]["ref"] for e in drives} == {
        part_id: address for address, part_id in parts.items()
    }
    assert all(
        e.confidence == 0.9 and e.attrs["evidence"][0]["kind"] == "bus_enumeration" for e in drives
    )
    assert brain not in {e.dst_id for e in drives}  # brain → bus is not a drives edge
    assert report == InferenceReport("overlay_edges", created=6, updated=0, skipped=0, candidates=0)
    assert await read_topology(db, pid, robot) == before  # the overlay tree still validates
    again = await overlay_edges.infer(db, pid, robot_id=robot)
    assert again == InferenceReport("overlay_edges", created=0, updated=0, skipped=6, candidates=0)


async def test_manual_drives_survives_a_rerun_undowngraded(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    pid, robot, _, parts = await seed_robot(client, alice_headers, db)
    await overlay_edges.infer(db, pid, robot_id=robot)
    bus_id = {e.src_id for e in await inferred(db, pid, "drives")}.pop()
    part_id = next(iter(parts.values()))
    manual = await write_edge(
        db,
        project_id=pid,
        src_id=bus_id,
        dst_id=part_id,
        relation_type="drives",
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=USER,
    )
    assert manual.origin == "manual" and manual.confidence == 1.0

    report = await overlay_edges.infer(db, pid, robot_id=robot)

    assert report.created == 0
    await db.refresh(manual)
    assert manual.origin == "manual" and manual.confidence == 1.0 and manual.deleted_at is None
    drives = await inferred(db, pid, "drives")
    assert len(drives) == len(parts) and manual.id in {e.id for e in drives}


@pytest.mark.asyncio
async def test_host_confirm_writes_hosts_and_binds_the_robot_to_the_machine(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, robot, body, _ = await setup_host(client, app, alice_headers, db)
    me = (await client.get("/api/v1/users/me", headers=alice_headers)).json()["data"]
    machine = await upsert_machine(
        db,
        uuid.UUID(project),
        uuid.UUID(me["id"]),
        MACHINE,
        MachineIn(hostname="bench", os="linux", arch="arm64"),
    )
    await db.commit()
    robot_row = await db.get(GraphEntity, uuid.UUID(robot))
    assert robot_row is not None
    version_before = robot_row.version

    url = _hw_url(project, "robots", robot, "topology", "host")
    proposal = await client.post(url + "/propose", headers=alice_headers, json=body)
    assert proposal.status_code == 200, proposal.text
    headers = {**alice_headers, "Idempotency-Key": str(uuid.uuid4())}
    payload = {**body, "proposal_digest": proposal.json()["data"]["proposal_digest"]}
    confirmed = await client.post(url + "/confirm", headers=headers, json=payload)
    assert confirmed.status_code == 200, confirmed.text

    hosts = await inferred(db, uuid.UUID(project), "hosts")
    assert [(e.src_id, e.dst_id, e.confidence) for e in hosts] == [
        (machine.id, uuid.UUID(robot), 1.0)
    ]
    assert hosts[0].attrs["evidence"] == [
        {"kind": "config", "ref": f"host:{MACHINE}", "detail": None}
    ]
    await db.refresh(robot_row)
    assert robot_row.attrs["host_machine_id"] == MACHINE and robot_row.version == version_before + 1
    # The USB bus drives the MCU endpoint and the arm's parts; the tree still reads.
    drives = await inferred(db, uuid.UUID(project), "drives")
    assert uuid.UUID(body["endpoint_id"]) in {e.dst_id for e in drives}
    topology = await read_topology(db, uuid.UUID(project), uuid.UUID(robot))
    assert topology.model_dump(mode="json") == confirmed.json()["data"]

    replay = await client.post(url + "/confirm", headers=headers, json=payload)
    assert replay.json() == confirmed.json()
    await db.refresh(robot_row)
    assert robot_row.version == version_before + 1
    assert [e.id for e in await inferred(db, uuid.UUID(project), "hosts")] == [hosts[0].id]


@pytest.mark.asyncio
async def test_without_a_machine_node_only_the_attr_is_set(
    client: AsyncClient, app: FastAPI, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, robot, body, _ = await setup_host(client, app, alice_headers, db)
    url = _hw_url(project, "robots", robot, "topology", "host")
    proposal = (await client.post(url + "/propose", headers=alice_headers, json=body)).json()[
        "data"
    ]
    headers = {**alice_headers, "Idempotency-Key": str(uuid.uuid4())}
    confirmed = await client.post(
        url + "/confirm",
        headers=headers,
        json={**body, "proposal_digest": proposal["proposal_digest"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert await inferred(db, uuid.UUID(project), "hosts") == []
    robot_row = await db.get(GraphEntity, uuid.UUID(robot))
    assert robot_row is not None and robot_row.attrs["host_machine_id"] == MACHINE
    # A machine that reports later picks the edge up on the next run.
    me = (await client.get("/api/v1/users/me", headers=alice_headers)).json()["data"]
    machine = await upsert_machine(
        db,
        uuid.UUID(project),
        uuid.UUID(me["id"]),
        MACHINE,
        MachineIn(hostname="bench", os="linux", arch="arm64"),
    )
    await overlay_edges.infer(db, uuid.UUID(project), robot_id=uuid.UUID(robot), machine_id=MACHINE)
    assert [e.src_id for e in await inferred(db, uuid.UUID(project), "hosts")] == [machine.id]
    total = await db.scalar(
        select(GraphEdge.id).where(
            GraphEdge.relation_type == "hosts", GraphEdge.deleted_at.is_(None)
        )
    )
    assert total is not None
