"""graph/inference/config_requires: a hardware CONFIG's driver → `requires` package nodes,
hooked at the end of `hardware/store.py:put_entity_config` (SOLUSDEV-320 Phase 3 module 5)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.graph.inference import InferenceReport, config_requires
from solus_api.models import Domain, GraphEdge, GraphEntity
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_router import _hw_project, _hw_url, _robot, _saved_serial_arm
from test_inference_power_nets import USER, seed_project


async def requires_edges(db: AsyncSession, project: str) -> list[GraphEdge]:
    return list(
        await db.scalars(
            select(GraphEdge)
            .where(
                GraphEdge.project_id == uuid.UUID(project),
                GraphEdge.relation_type == "requires",
                GraphEdge.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
    )


async def test_saving_a_config_requires_the_drivers_packages(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, _ = await _hw_project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    config = await _saved_serial_arm(client, alice_headers, project, robot["id"])
    saved = await client.put(
        _hw_url(project, "robots", robot["id"], "config"),
        headers=alice_headers,
        json={"config": config},
    )
    assert saved.status_code == 200, saved.text

    edges = await requires_edges(db, project)
    assert len(edges) == 1
    edge = edges[0]
    package = await db.get(GraphEntity, edge.dst_id)
    node = await db.get(GraphEntity, edge.src_id)
    assert package is not None and node is not None
    assert node.kind == kinds.HARDWARE_CONFIG
    assert package.kind == kinds.PACKAGE_REQUIREMENT and package.name == "pyserial"
    assert package.canonical_key == "pkg:python:pyserial" and package.domain is Domain.CODE
    assert package.attrs == {
        "name": "pyserial",
        "ecosystem": "python",
        "source": "driver:feetech-sts",
    }
    assert edge.origin == "inferred" and edge.confidence == 0.8
    assert edge.attrs["evidence"] == [
        {"kind": "config", "ref": "protocol.driver_id", "detail": None}
    ]
    assert "matrix_cell" not in edge.attrs  # a project-domain config node sits outside the matrix

    # Saving again (version +1) lands on the same edge and the same package node.
    current = (
        await client.get(_hw_url(project, "robots", robot["id"], "config"), headers=alice_headers)
    ).json()["data"]
    again = await client.put(
        _hw_url(project, "robots", robot["id"], "config"),
        headers={**alice_headers, "If-Match": str(current["version"])},
        json={"config": current["config"]},
    )
    assert again.status_code == 200, again.text
    edge_id, package_id = edge.id, package.id
    edges = await requires_edges(db, project)
    assert [e.id for e in edges] == [edge_id] and edges[0].dst_id == package_id
    packages = await db.scalars(
        select(GraphEntity).where(
            GraphEntity.project_id == uuid.UUID(project),
            GraphEntity.kind == kinds.PACKAGE_REQUIREMENT,
        )
    )
    assert len(list(packages)) == 1


async def test_unknown_driver_or_missing_livebench_yields_no_edges(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = await seed_project(db)
    node = GraphEntity(
        project_id=pid,
        kind=kinds.HARDWARE_CONFIG,
        domain=Domain.PROJECT,
        name="config",
        origin="manual",
    )
    db.add(node)
    await db.flush()
    assert await config_requires.infer(
        db, pid, config_node_id=node.id, driver_id="no-such-driver"
    ) == InferenceReport("config_requires")
    assert await config_requires.infer(
        db, pid, config_node_id=node.id, driver_id=None
    ) == InferenceReport("config_requires")

    def unavailable(driver_id: str) -> tuple[str, ...]:
        raise ImportError("livebench is not installed here")

    monkeypatch.setattr(config_requires, "requires_packages_for", unavailable)
    assert await config_requires.infer(
        db, pid, config_node_id=node.id, driver_id="feetech-sts"
    ) == InferenceReport("config_requires")
    assert await requires_edges(db, str(pid)) == []


async def test_manual_requires_survives_and_rerun_is_a_no_op(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = await seed_project(db)
    node = GraphEntity(
        project_id=pid,
        kind=kinds.HARDWARE_CONFIG,
        domain=Domain.PROJECT,
        name="config",
        origin="manual",
    )
    package = GraphEntity(
        project_id=pid,
        kind=kinds.PACKAGE_REQUIREMENT,
        domain=Domain.CODE,
        name="numpy",
        origin="manual",
        canonical_key="pkg:python:numpy",
    )
    db.add_all([node, package])
    await db.flush()
    manual = await write_edge(
        db,
        project_id=pid,
        src_id=node.id,
        dst_id=package.id,
        relation_type="requires",
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=USER,
    )
    monkeypatch.setattr(
        config_requires, "requires_packages_for", lambda driver_id: ("pyserial", "numpy")
    )
    first = await config_requires.infer(db, pid, config_node_id=node.id, driver_id="demo")
    assert first == InferenceReport(
        "config_requires", created=1, updated=1, skipped=0, candidates=0
    )
    await db.refresh(manual)
    assert manual.origin == "manual" and manual.confidence == 1.0 and manual.deleted_at is None
    stamps = {e.id: e.updated_at for e in await requires_edges(db, str(pid))}
    second = await config_requires.infer(db, pid, config_node_id=node.id, driver_id="demo")
    assert second == InferenceReport(
        "config_requires", created=0, updated=0, skipped=2, candidates=0
    )
    db.expire_all()
    assert {e.id: e.updated_at for e in await requires_edges(db, str(pid))} == stamps
