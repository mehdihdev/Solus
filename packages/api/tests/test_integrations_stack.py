"""LNK-08 integrations QA — the joint stack proof (SOLUSDEV-113).

Every EXISTING connector family lands a sample project through the ONE real
write path (`apply_sync_result`): KiCad and Altium via their REAL parsers on
committed exports; GitHub/GitLab as connector-output-shaped SyncResults (their
live HTTP flows are proven per-connector in test_github_connector /
test_gitlab_connector — re-faking OAuth here would prove nothing new). Then the
whole reasoning stack runs over the result: fingerprint scan → cross-domain
linking (the committed KiCad project's multi-instance parts — R1/R2 share one
MPN, C1/C2/C4 another — become same_as edges) → checkers firing on the seeded
known-bad sample (the MPU-6050 IMU's Nyquist floor vs. the GitHub reader's
loop rate) → the graph HTTP API returning the linked graph.

Scoped honestly per the Phase 0 audit (SOLUSDEV-113 comment): Onshape/ROS
connectors do not exist and are not asserted; no connector populates the
`checkers/attributes.py` keys yet, so the known-bad sample seeds them — the
sensor floor as manual enrichment on the KiCad part, the code loop rate via
connector `properties` — exactly the vocabulary the EDA attribute extraction
must later honour.

KNOWN GAP (filed for the LNK-09 gate, owner LANE G/EDA): the Altium/protel
parser leaves `modality_hints` EMPTY — the component comment lands only in
`properties.value` — so Altium observations can never fingerprint-match and
never link. This test asserts Altium ingests, and pins the gap so its fix
flips the assertion rather than silently changing behavior.
"""

import uuid
from typing import Any

from conftest import create_project, create_team, me
from fixtures.kicad_project import SOLUS_SAMPLE_NETLIST
from httpx import AsyncClient
from solus_api.connectors.altium import AltiumConnector
from solus_api.connectors.contracts import (
    Credentials,
    EntityOut,
    RelationOut,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.kicad import KicadConnector
from solus_api.connectors.runtime import apply_sync_result
from solus_api.contracts.action_gate import DiffRow
from solus_api.fingerprint.ingest import scan_project
from solus_api.impact import checker_provider, compute_impact
from solus_api.linking import link_from_fingerprint
from solus_api.linking.linker import LINK_ORIGIN, RELATION_SAME_AS
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    Source,
    SourceStatus,
    SourceType,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_altium_connector import PROTEL_EXPORT

SENSOR_FLOOR_HZ = 200.0
CODE_LOOP_HZ = 20.0


async def _source(
    db: AsyncSession,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    source_type: SourceType,
    name: str,
) -> Source:
    source = Source(
        project_id=project_id,
        team_id=team_id,
        type=source_type,
        name=name,
        status=SourceStatus.CONNECTED,
    )
    db.add(source)
    await db.flush()
    return source


def _code_host_result(repo_key: str, file_path: str, file_props: dict[str, Any]) -> SyncResult:
    """Connector-output-shaped code-host sample (repo + file + contains)."""
    return SyncResult(
        entities=[
            EntityOut(source_key=repo_key, type="code_repo", domain=Domain.CODE, name=repo_key),
            EntityOut(
                source_key=file_path,
                type="code_file",
                domain=Domain.CODE,
                name=file_path.rsplit("/", 1)[-1],
                properties=file_props,
            ),
        ],
        relations=[RelationOut(from_key=repo_key, to_key=file_path, type="contains")],
    )


async def _entity(
    db: AsyncSession, project_id: uuid.UUID, source_id: uuid.UUID, external_ref: str
) -> GraphEntity:
    return (
        await db.execute(
            select(GraphEntity).where(
                GraphEntity.project_id == project_id,
                GraphEntity.source_id == source_id,
                GraphEntity.external_ref == external_ref,
                GraphEntity.deleted_at.is_(None),
            )
        )
    ).scalar_one()


async def _by_mpn(
    db: AsyncSession, project_id: uuid.UUID, source_id: uuid.UUID, part_number: str
) -> list[GraphEntity]:
    """KiCad netlist source_keys are content-derived, so rows are located by
    their fingerprint channel rather than by designator."""
    rows = (
        (
            await db.execute(
                select(GraphEntity).where(
                    GraphEntity.project_id == project_id,
                    GraphEntity.source_id == source_id,
                    GraphEntity.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return [row for row in rows if row.modality_hints.get("part_number") == part_number]


async def test_full_stack_ingest_fingerprint_link_check_graph(
    db: AsyncSession, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    project_id, team_id = uuid.UUID(project["id"]), uuid.UUID(team["id"])

    # 1 — every existing connector family ingests its sample without error.
    kicad_source = await _source(db, project_id, team_id, SourceType.KICAD, "board")
    kicad_result = await KicadConnector().sync(
        SyncContext(
            credentials=Credentials(token="x"),
            config={"export": SOLUS_SAMPLE_NETLIST.read_text()},
        )
    )
    kicad_counts, kicad_errors = await apply_sync_result(db, kicad_source, kicad_result)

    altium_source = await _source(db, project_id, team_id, SourceType.ALTIUM, "board-alt")
    altium_result = await AltiumConnector().sync(
        SyncContext(credentials=Credentials(token="x"), config={"export": PROTEL_EXPORT})
    )
    altium_counts, altium_errors = await apply_sync_result(db, altium_source, altium_result)

    github_source = await _source(db, project_id, team_id, SourceType.GITHUB, "octo/fw")
    github_counts, github_errors = await apply_sync_result(
        db,
        github_source,
        _code_host_result(
            "repo:octo/fw", "firmware/imu_reader.cpp", {"loop_rate_hz": CODE_LOOP_HZ}
        ),
    )

    gitlab_source = await _source(db, project_id, team_id, SourceType.GITLAB, "grp/ctl")
    gitlab_counts, gitlab_errors = await apply_sync_result(
        db, gitlab_source, _code_host_result("repo:grp/ctl", "src/motor_ctl.cpp", {})
    )

    for counts, errors in [
        (kicad_counts, kicad_errors),
        (altium_counts, altium_errors),
        (github_counts, github_errors),
        (gitlab_counts, gitlab_errors),
    ]:
        assert counts.entities_created > 0
        assert errors == []

    # 2 — the seeded known-bad sample: the KiCad MPU-6050 IMU carries a Nyquist
    # floor (manual enrichment); the GitHub reader polls it too slowly
    # (connector properties); a manual reads_from edge spans code<->electrical.
    (sensor,) = await _by_mpn(db, project_id, kicad_source.id, "MPU-6050")
    sensor.attrs = {**sensor.attrs, "min_sample_rate_hz": SENSOR_FLOOR_HZ}
    reader = await _entity(db, project_id, github_source.id, "firmware/imu_reader.cpp")
    db.add(
        GraphEdge(
            project_id=project_id,
            src_id=reader.id,
            dst_id=sensor.id,
            relation_type="reads_from",
            domain_pair="code<->electrical",
            confidence=1.0,
            origin="manual",
            attrs={},
        )
    )
    await db.flush()

    # 3 — fingerprint: the sample's multi-instance parts form canonical parts.
    summary = await scan_project(db, project_id)
    assert summary.canonical_created >= 2  # the R pair's MPN + the C trio's MPN

    # 4 — linking: multi-instance identity becomes same_as edges (R1<->R2, and
    # the C trio pairwise). Altium ingested but cannot link — its parser emits
    # no modality_hints (the KNOWN GAP in the module docstring).
    link_result = await link_from_fingerprint(db, project_id=project_id)
    assert link_result.created >= 4  # 1 (R pair) + 3 (C trio)
    resistors = await _by_mpn(db, project_id, kicad_source.id, "RC0603FR-074K7L")
    assert len(resistors) == 2
    same_as = (
        (
            await db.execute(
                select(GraphEdge).where(
                    GraphEdge.project_id == project_id,
                    GraphEdge.origin == LINK_ORIGIN,
                    GraphEdge.relation_type == RELATION_SAME_AS,
                    GraphEdge.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    linked_pairs = {frozenset((edge.src_id, edge.dst_id)) for edge in same_as}
    assert frozenset((resistors[0].id, resistors[1].id)) in linked_pairs
    altium_ids = {
        row.id
        for row in (
            await db.execute(
                select(GraphEntity).where(
                    GraphEntity.source_id == altium_source.id,
                    GraphEntity.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    }
    assert not any(pair & altium_ids for pair in linked_pairs)  # the pinned gap

    # 5 — checkers fire on the seeded bug, through the real impact stack.
    result = await compute_impact(
        db,
        project_id,
        focus_id=sensor.id,
        change=[DiffRow(label="sample_rate_floor_hz", before="50", after="200")],
        provider=checker_provider(),
    )
    reader_nodes = [n for n in result.nodes if n.entity.entity_id == str(reader.id)]
    assert len(reader_nodes) == 1
    node = reader_nodes[0]
    assert node.domain is Domain.CODE
    assert node.distance == 1
    assert node.path[0].relation == "reads_from"
    assert any("alias" in c.headline for c in node.consequences)

    # 6 — the graph HTTP API returns the linked result.
    sensor_id, reader_id = sensor.id, reader.id
    r1_id, r2_id = resistors[0].id, resistors[1].id
    await db.commit()
    response = await client.get(
        f"/api/v1/projects/{project_id}/graph",
        params={"root": str(r1_id), "depth": 1},
        headers=alice_headers,
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    returned_ids = {entity["id"] for entity in payload["entities"]}
    assert str(r2_id) in returned_ids  # reached via the linker's same_as edge
    edge_types = {edge["type"] for edge in payload["edges"]}
    assert RELATION_SAME_AS in edge_types

    response = await client.get(
        f"/api/v1/projects/{project_id}/graph",
        params={"root": str(sensor_id), "depth": 1},
        headers=alice_headers,
    )
    assert response.status_code == 200
    reachable = {entity["id"] for entity in response.json()["data"]["entities"]}
    assert str(reader_id) in reachable  # the manual cross-domain reads_from
