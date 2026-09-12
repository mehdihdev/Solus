"""Reviewed hardware creations are atomic, authorization-scoped and bounded."""

import asyncio
import uuid

import pytest
from conftest import BOB, add_member, create_project, create_team, me
from httpx import AsyncClient
from solus_api.models import GraphEntity
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _setup(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    return str((await create_project(client, headers, team["id"]))["id"]), str(team["id"])


async def test_concurrent_retry_materializes_only_one_entity(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, _ = await _setup(client, alice_headers)
    headers = {**alice_headers, "Idempotency-Key": str(uuid.uuid4())}
    url = f"/api/v1/projects/{project}/hardware/entities"
    responses = await asyncio.gather(
        *(
            client.post(url, headers=headers, json={"kind": "part", "name": "Joint"})
            for _ in range(4)
        )
    )
    assert [response.status_code for response in responses] == [201] * 4
    assert len({response.json()["data"]["entity"]["id"] for response in responses}) == 1
    assert (
        await db.scalar(
            select(func.count())
            .select_from(GraphEntity)
            .where(GraphEntity.project_id == uuid.UUID(project), GraphEntity.kind == "part")
        )
        == 1
    )


async def test_creation_with_unknown_bus_part_rolls_back_entity_and_config(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, _ = await _setup(client, alice_headers)
    before = await db.scalar(
        select(func.count())
        .select_from(GraphEntity)
        .where(GraphEntity.project_id == uuid.UUID(project))
    )
    response = await client.post(
        f"/api/v1/projects/{project}/hardware/entities",
        headers={**alice_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "kind": "part",
            "name": "Controller",
            "config": {
                "schema_version": 2,
                "bus_map": [
                    {"protocol": "generic", "address": "1", "part_entity_id": str(uuid.uuid4())}
                ],
                "provenance": {"bus_map": {"by": "user"}},
            },
        },
    )
    assert response.status_code == 404, response.text
    assert (
        await db.scalar(
            select(func.count())
            .select_from(GraphEntity)
            .where(GraphEntity.project_id == uuid.UUID(project))
        )
        == before
    )


async def test_viewer_cannot_create_configure_or_assign(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    project, team = await _setup(client, alice_headers)
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team, "viewer")
    headers = {**alice_headers, "Idempotency-Key": str(uuid.uuid4())}
    base = f"/api/v1/projects/{project}/hardware"
    created = await client.post(
        f"{base}/entities", headers=headers, json={"kind": "part", "name": "Joint"}
    )
    assert created.status_code == 201, created.text
    entity = created.json()["data"]["entity"]
    assert (
        await client.post(
            f"{base}/entities",
            headers={**bob_headers, "Idempotency-Key": str(uuid.uuid4())},
            json={"kind": "part", "name": "Other"},
        )
    ).status_code == 403
    assert (
        await client.put(
            f"{base}/entities/{entity['id']}/config",
            headers={**bob_headers, "If-Match": "0"},
            json={"config": {"schema_version": 2, "entity_id": entity["id"]}},
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"{base}/parts/{entity['id']}/parent",
            headers=bob_headers,
            json={"parent_id": None, "expected_parent_id": None, "version": entity["version"]},
        )
    ).status_code == 403


@pytest.mark.parametrize("header", [None, "not-a-uuid"])
async def test_creation_requires_a_valid_reviewed_operation_key(
    client: AsyncClient, alice_headers: dict[str, str], header: str | None
) -> None:
    project, _ = await _setup(client, alice_headers)
    headers = dict(alice_headers)
    if header is not None:
        headers["Idempotency-Key"] = header
    response = await client.post(
        f"/api/v1/projects/{project}/hardware/entities",
        headers=headers,
        json={"kind": "part", "name": "Joint"},
    )
    assert response.status_code == 422
