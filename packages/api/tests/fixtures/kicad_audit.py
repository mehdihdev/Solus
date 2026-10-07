"""Shared HTTP/DB helpers for the KiCad acceptance-audit suites (SOLUSDEV-312).

Mirrors the idioms in `test_kicad_ingest_e2e.py` (connect/sync through the real
routes, read graph rows straight from the DB because `/entities` does not surface
`modality_hints`) so the audit suites stay small and consistent.
"""

from __future__ import annotations

import uuid
from typing import Any

from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.models import GraphEdge, GraphEntity
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]

#: The pin-level connectivity KICAD_XML / KICAD_SEXPR / KICAD_PCB all describe for
#: U1, R1 and C1: `(refdes, net) -> pins`.
SAMPLE_CONNECTIVITY: dict[tuple[str, str], list[str]] = {
    ("U1", "VCC"): ["8"],
    ("U1", "GND"): ["4"],
    ("U1", "SIGNAL"): ["1"],
    ("C1", "VCC"): ["1"],
    ("C1", "GND"): ["2"],
    ("R1", "SIGNAL"): ["2"],
}


async def new_project(client: AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    """A fresh team + project for the caller; returns the project id."""
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return uuid.UUID(project["id"])


async def connect_kicad_config(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: uuid.UUID,
    config: dict[str, str],
) -> dict[str, Any]:
    """POST a kicad source carrying exactly `config` (what the desktop sends: present keys only)."""
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "kicad", "name": "audit", "config": config},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def connect_kicad(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: uuid.UUID,
    *,
    export: str | None = None,
    board: str | None = None,
) -> dict[str, Any]:
    config = {key: text for key, text in (("export", export), ("board", board)) if text is not None}
    return await connect_kicad_config(client, headers, project_id, config)


async def sync(
    client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID, source_id: str
) -> dict[str, Any]:
    """Trigger a sync (runs inline in tests) and return its newest Sync record."""
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources/{source_id}/sync", headers=headers
    )
    assert resp.status_code == 202, resp.text
    return await latest_sync(client, headers, project_id, source_id)


async def latest_sync(
    client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID, source_id: str
) -> dict[str, Any]:
    resp = await client.get(
        f"/api/v1/projects/{project_id}/sources/{source_id}/syncs", headers=headers
    )
    assert resp.status_code == 200, resp.text
    row: dict[str, Any] = resp.json()["data"][0]
    return row


async def get_source(
    client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID, source_id: str
) -> dict[str, Any]:
    resp = await client.get(f"/api/v1/projects/{project_id}/sources/{source_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    row: dict[str, Any] = resp.json()["data"]
    return row


async def patch_config(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: uuid.UUID,
    source_id: str,
    config: dict[str, str],
) -> None:
    resp = await client.patch(
        f"/api/v1/projects/{project_id}/sources/{source_id}",
        json={"config": config},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def entities_by_ref(
    maker: Maker, project_id: uuid.UUID, *, include_deleted: bool = False
) -> dict[str, GraphEntity]:
    """`external_ref` -> row (detached; `expire_on_commit=False` sessionmaker)."""
    async with maker() as session:
        stmt = select(GraphEntity).where(GraphEntity.project_id == project_id)
        if not include_deleted:
            stmt = stmt.where(GraphEntity.deleted_at.is_(None))
        rows = (await session.scalars(stmt)).all()
    return {row.external_ref: row for row in rows if row.external_ref}


async def connectivity(
    maker: Maker, project_id: uuid.UUID, *, kinds: tuple[str, ...] = ("component",)
) -> dict[tuple[str, str], list[str]]:
    """Live `(component refdes, net name) -> pins` taken from the `connected_to` edges."""
    async with maker() as session:
        ents = {
            e.id: e
            for e in (
                await session.scalars(
                    select(GraphEntity).where(
                        GraphEntity.project_id == project_id, GraphEntity.deleted_at.is_(None)
                    )
                )
            ).all()
        }
        edges = (
            await session.scalars(
                select(GraphEdge).where(
                    GraphEdge.project_id == project_id, GraphEdge.deleted_at.is_(None)
                )
            )
        ).all()
    out: dict[tuple[str, str], list[str]] = {}
    for edge in edges:
        src, dst = ents.get(edge.src_id), ents.get(edge.dst_id)
        if src is None or dst is None or src.kind not in kinds or dst.kind != "net":
            continue
        out[(str(src.external_ref), str(edge.attrs["net"]))] = list(edge.attrs["pins"])
    return out
