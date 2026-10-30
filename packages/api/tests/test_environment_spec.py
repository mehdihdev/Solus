"""SOLUSDEV-320 P5-T3: the environment spec — what the project's graph says it needs,
computed from live `depends_on` / `requires` edges onto requirement entities and stored as
ONE `environment/spec` CONFIG bound to the project's `.solus` root. Nothing is guessed: a
requirement without a specifier yields `specifier: null`."""

from __future__ import annotations

import uuid

from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.models import Domain, GraphEntity, SolusEntry, SolusEntryKind
from solus_api.services.environment_spec import (
    build_environment_spec,
    recompute_environment_spec,
)
from solus_api.services.solus_graph import SolusGraph
from solus_api.services.solus_payloads import EnvironmentSpec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _spec_project(client: AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return uuid.UUID(project["id"])


def _requirement(project_id: uuid.UUID, kind: str, **attrs: object) -> GraphEntity:
    name = str(attrs["name"])
    return GraphEntity(
        project_id=project_id,
        kind=kind,
        domain=Domain.CODE,
        origin="connector",
        name=f"{name} {attrs.get('specifier', '')}".strip(),
        attrs=dict(attrs),
    )


async def _seed_requirements(db: AsyncSession, project_id: uuid.UUID) -> dict[str, GraphEntity]:
    repo = GraphEntity(
        project_id=project_id,
        kind=kinds.CODE_REPO,
        domain=Domain.CODE,
        origin="connector",
        name="rover-fw",
        attrs={},
    )
    config = GraphEntity(
        project_id=project_id,
        kind=kinds.HARDWARE_CONFIG,
        domain=Domain.PROJECT,
        origin="manual",
        name="arm config",
        attrs={},
    )
    torch = _requirement(
        project_id,
        kinds.PYTHON_REQUIREMENT,
        name="torch",
        specifier="==2.4.0",
        ecosystem="python",
        source_file="requirements.txt",
    )
    xacro = _requirement(
        project_id,
        kinds.PACKAGE_REQUIREMENT,
        name="xacro",
        specifier="",
        ecosystem="ros",
        source_file="package.xml",
    )
    pyserial = GraphEntity(
        project_id=project_id,
        kind=kinds.PACKAGE_REQUIREMENT,
        domain=Domain.CODE,
        origin="system",
        name="pyserial",
        canonical_key="pkg:python:pyserial",
        attrs={"name": "pyserial", "ecosystem": "python", "source": "driver:feetech-sts"},
    )
    nodes = {"repo": repo, "config": config, "torch": torch, "xacro": xacro, "pyserial": pyserial}
    db.add_all(nodes.values())
    await db.flush()
    for src, dst, relation, origin, confidence in (
        (repo, torch, "requires", "connector", 1.0),
        (repo, xacro, "requires", "connector", 1.0),
        (repo, torch, "depends_on", "inferred", 1.0),
        (config, pyserial, "requires", "inferred", 0.8),
    ):
        await write_edge(
            db,
            project_id=project_id,
            src_id=src.id,
            dst_id=dst.id,
            relation_type=relation,
            origin=origin,
            confidence=confidence,
            evidence=[],
            created_by=None,
        )
    await db.flush()
    return nodes


async def test_spec_groups_requirements_by_package(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _spec_project(client, alice_headers)
    nodes = await _seed_requirements(db, project_id)
    spec = await build_environment_spec(db, project_id)
    assert spec.schema_version == 1 and spec.tools == []
    by_name = {(p.ecosystem, p.name): p for p in spec.packages}
    assert set(by_name) == {("python", "torch"), ("ros", "xacro"), ("python", "pyserial")}
    torch = by_name[("python", "torch")]
    assert torch.specifier == "==2.4.0" and torch.source == "manifest"
    assert torch.required_by == [nodes["repo"].id]  # two edges, one requirer
    xacro = by_name[("ros", "xacro")]
    assert xacro.specifier is None and xacro.source == "manifest"
    pyserial = by_name[("python", "pyserial")]
    assert pyserial.specifier is None and pyserial.source == "config"
    assert pyserial.required_by == [nodes["config"].id]


async def test_spec_ignores_candidates_and_dead_edges(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _spec_project(client, alice_headers)
    nodes = await _seed_requirements(db, project_id)
    guess = _requirement(project_id, kinds.PYTHON_REQUIREMENT, name="numpy", ecosystem="python")
    db.add(guess)
    await db.flush()
    await write_edge(
        db,
        project_id=project_id,
        src_id=nodes["repo"].id,
        dst_id=guess.id,
        relation_type="requires",
        origin="inferred",
        confidence=0.5,
        evidence=[],
        created_by=None,
    )
    spec = await build_environment_spec(db, project_id)
    assert "numpy" not in {p.name for p in spec.packages}


async def test_spec_is_one_config_on_the_solus_root_recomputed_in_place(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _spec_project(client, alice_headers)
    await _seed_requirements(db, project_id)
    first = await recompute_environment_spec(db, project_id)
    root = (await SolusGraph.ensure(db, project_id)).root
    assert first.section == "environment" and first.subsection == "spec"
    assert first.kind == SolusEntryKind.CONFIG and first.configured_entity_id == root.id
    assert first.config_version == 1
    stored = EnvironmentSpec.model_validate(first.payload)
    assert {p.name for p in stored.packages} == {"torch", "xacro", "pyserial"}
    # Same graph → same row, same version (`computed_at` alone is not a change).
    again = await recompute_environment_spec(db, project_id)
    assert again.id == first.id and again.config_version == 1
    rows = list(
        await db.scalars(
            select(SolusEntry).where(
                SolusEntry.project_id == project_id, SolusEntry.subsection == "spec"
            )
        )
    )
    assert [r.id for r in rows] == [first.id]
    # The graph changed → the same row, one version up.
    extra = _requirement(
        project_id,
        kinds.PYTHON_REQUIREMENT,
        name="numpy",
        specifier=">=2",
        ecosystem="python",
        source_file="requirements.txt",
    )
    db.add(extra)
    await db.flush()
    repo = await db.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id, GraphEntity.kind == kinds.CODE_REPO
        )
    )
    assert repo is not None
    await write_edge(
        db,
        project_id=project_id,
        src_id=repo.id,
        dst_id=extra.id,
        relation_type="requires",
        origin="connector",
        confidence=1.0,
        evidence=[],
        created_by=None,
    )
    third = await recompute_environment_spec(db, project_id)
    assert third.id == first.id and third.config_version == 2


async def test_empty_project_has_an_empty_spec(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _spec_project(client, alice_headers)
    spec = await build_environment_spec(db, project_id)
    assert spec.packages == [] and spec.tools == []
