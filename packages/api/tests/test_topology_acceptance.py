"""Explicit extraction acceptance is scoped, replayable and nonoperational."""

import uuid
from pathlib import Path
from typing import Any

import pytest
from conftest import me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.core.errors import APIError
from solus_api.hardware.local_sources import LocalHardwareSources
from solus_api.models import GraphEdge, GraphEntity, SolusEntry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_topology_proposals import setup, url


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["create", "retain", "stale", "foreign", "index", "replay"])
async def test_acceptance_boundary(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    from solus_api.hardware.topology_acceptance import ExtractionConfirm, TopologyAcceptanceService

    project, _, robot, body, _, _ = await setup(client, alice_headers, app, tmp_path, monkeypatch)
    proposal = (await client.post(url(project, robot), headers=alice_headers, json=body)).json()[
        "data"
    ]
    user = (await me(client, alice_headers))["id"]
    service = TopologyAcceptanceService(
        db,
        uuid.UUID(project),
        uuid.UUID(user),
        LocalHardwareSources.for_local_runner(app.state.bench_local),
    )
    configs = list(
        (
            await db.execute(select(SolusEntry.id, SolusEntry.payload, SolusEntry.config_version))
        ).all()
    )
    selection: dict[str, Any] = {"row_index": 0, "name": "Reviewed elbow"}
    if case == "retain":
        selection["entity_id"] = body["brain_id"]
    if case == "foreign":
        selection["entity_id"] = str(uuid.uuid4())
    if case == "index":
        selection["row_index"] = 255
    payload = {
        **body,
        "proposal_digest": "0" * 64 if case == "stale" else proposal["proposal_digest"],
        "operation_id": str(uuid.uuid4()),
        "selections": [selection],
    }
    request = ExtractionConfirm.model_validate(payload)
    if case in ("stale", "foreign", "index"):
        with pytest.raises(APIError):
            await service.confirm(uuid.UUID(robot), request)
        return
    result, replayed = await service.confirm(uuid.UUID(robot), request)
    await db.commit()
    assert not replayed
    assert result.created == (0 if case == "retain" else 1)
    assert len(result.entity_ids) == 1
    from solus_api.hardware.topology import read_topology, sync_topology

    await sync_topology(db, uuid.UUID(project), uuid.UUID(robot))
    await db.commit()
    projected = await read_topology(db, uuid.UUID(project), uuid.UUID(robot))
    assert result.entity_ids[0] in {node.id for node in projected.nodes}
    if case == "retain":
        assert not any(edge.source == edge.target for edge in projected.edges)
    else:
        assert any(
            edge.target == result.entity_ids[0] and edge.source == uuid.UUID(body["brain_id"])
            for edge in projected.edges
        )
    edge = await db.scalar(
        select(GraphEdge).where(GraphEdge.relation_type == "hardware_evidence_for")
    )
    assert edge is not None and edge.attrs["nonoperational"] is True
    assert "/private" not in str(edge.attrs)
    entity = await db.get(GraphEntity, result.entity_ids[0])
    assert entity is not None
    if case != "retain":
        assert entity.kind == "hardware_evidence" and entity.attrs["nonoperational"] is True
    assert (
        list(
            (
                await db.execute(
                    select(SolusEntry.id, SolusEntry.payload, SolusEntry.config_version)
                )
            ).all()
        )
        == configs
    )
    if case == "replay":
        repeated, replayed = await service.confirm(uuid.UUID(robot), request)
        assert replayed and repeated == result
        await db.commit()
        with pytest.raises(APIError):
            await service.confirm(
                uuid.UUID(robot),
                ExtractionConfirm.model_validate(
                    {**payload, "selections": [{"row_index": 0, "name": "Changed"}]}
                ),
            )


def test_strict_selections() -> None:
    from solus_api.hardware.topology_acceptance import ExtractionConfirm

    base = {
        "brain_id": str(uuid.uuid4()),
        "source_ref": f"source:{uuid.uuid4()}",
        "source_kind": "firmware",
        "proposal_digest": "a" * 64,
        "operation_id": str(uuid.uuid4()),
    }
    for selections in (
        [],
        [{"row_index": -1, "name": "x"}],
        [{"row_index": 0, "name": " "}],
        [{"row_index": 0, "name": "x"}] * 2,
        [{"row_index": 0, "name": "/home/private/file"}],
        [{"row_index": True, "name": "x"}],
    ):
        with pytest.raises((ValueError, APIError)):
            ExtractionConfirm.model_validate({**base, "selections": selections})


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "viewer"])
async def test_confirm_route_authorization_and_portable_errors(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    from conftest import ALICE, BOB, add_member, bearer

    project, team, robot, body, _, _ = await setup(
        client, alice_headers, app, tmp_path, monkeypatch
    )
    proposal = (await client.post(url(project, robot), headers=alice_headers, json=body)).json()[
        "data"
    ]
    route = url(project, robot).removesuffix("propose") + "confirm"
    payload = {
        **body,
        "proposal_digest": proposal["proposal_digest"],
        "operation_id": str(uuid.uuid4()),
        "selections": [{"row_index": 0, "name": "Reviewed elbow"}],
    }
    assert (await client.post(route, json=payload)).status_code == 401
    assert (
        await client.post(route, headers=bearer(**ALICE, email_verified=False), json=payload)
    ).status_code == 403
    assert (await client.post(route, headers=bob_headers, json=payload)).status_code == 404
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team, role=role)
    assert (await client.post(route, headers=bob_headers, json=payload)).status_code == (
        403 if role == "viewer" else 404
    )
    for invalid in (
        {**payload, "path": "/home/private/file"},
        {**payload, "proposal_digest": "/home/private/file"},
        {**payload, "selections": [{"row_index": "/home/private/file", "name": "x"}]},
        {
            **payload,
            "selections": [{"row_index": 0, "name": "x", "entity_id": "/home/private/file"}],
        },
    ):
        response = await client.post(route, headers=alice_headers, json=invalid)
        assert response.status_code == 422
        assert "/home/private" not in response.text
    accepted = await client.post(route, headers=alice_headers, json=payload)
    assert accepted.status_code == 200, accepted.text
    assert (await client.post(route, headers=alice_headers, json=payload)).json() == accepted.json()
