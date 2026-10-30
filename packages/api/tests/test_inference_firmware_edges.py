"""graph/inference/firmware_edges: accepted extraction evidence + the robot's bus map →
`commands` / `reads` code → part, hooked into `TopologyAcceptanceService.confirm`
(SOLUSDEV-320 Phase 3 module 2)."""

from __future__ import annotations

import importlib
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.graph.inference import InferenceReport, firmware_edges
from solus_api.hardware.local_sources import LocalHardwareSources
from solus_api.hardware.topology import EVIDENCE_MARKER, EVIDENCE_RELATION
from solus_api.hardware.topology_evidence import TopologyEvidence, TopologyProvenance
from solus_api.models import Domain, GraphEdge, GraphEntity
from solus_contracts.relations import matrix_cell
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_router import _hw_project, _hw_url, _robot, _saved_serial_arm

# Untyped test module (mypy must not follow it): the pattern `test_edges.py` uses.
_proposals = importlib.import_module("test_topology_proposals")
proposal_setup = _proposals.setup
propose_url = _proposals.url

SKETCH = Path(__file__).parent / "fixtures" / "inference" / "bus_sketch.ino"
SKETCH_PATH = "fw/bus_sketch.ino"
USER = uuid.uuid4()


def sketch_line(needle: str) -> int:
    """The 1-based line of the live (uncommented) `needle` in the fixture sketch."""
    for number, text in enumerate(SKETCH.read_text().splitlines(), 1):
        if needle in text and not text.strip().startswith("//"):
            return number
    raise AssertionError(needle)


async def seed_robot(
    client: AsyncClient, headers: dict[str, str], db: AsyncSession
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, dict[str, uuid.UUID]]:
    """`(project_id, robot_id, brain_id, {address: part_entity_id})` from the saved serial arm."""
    project, _ = await _hw_project(client, headers)
    robot = await _robot(client, headers, project)
    config = await _saved_serial_arm(client, headers, project, robot["id"])
    saved = await client.put(
        _hw_url(project, "robots", robot["id"], "config"), headers=headers, json={"config": config}
    )
    assert saved.status_code == 200, saved.text
    topology = (
        await client.get(_hw_url(project, "robots", robot["id"], "topology"), headers=headers)
    ).json()["data"]
    brain = next(uuid.UUID(n["id"]) for n in topology["nodes"] if n["role"] == "brain")
    parts = {item["address"]: uuid.UUID(item["part_entity_id"]) for item in config["bus_map"]}
    return uuid.UUID(project), uuid.UUID(robot["id"]), brain, parts


async def seed_code_file(db: AsyncSession, project_id: uuid.UUID, path: str) -> GraphEntity:
    row = GraphEntity(
        project_id=project_id,
        kind=kinds.CODE_FILE,
        domain=Domain.CODE,
        origin="connector",
        name=path.rsplit("/", 1)[-1],
        attrs={"path": path},
    )
    db.add(row)
    await db.flush()
    return row


async def seed_evidence(
    db: AsyncSession,
    project_id: uuid.UUID,
    robot_id: uuid.UUID,
    brain_id: uuid.UUID,
    *,
    source_ref: str,
    source_kind: str = "firmware",
    **row: Any,
) -> GraphEdge:
    """An accepted extraction row, shaped as `TopologyAcceptanceService.confirm` writes it."""
    evidence = GraphEntity(
        project_id=project_id,
        kind=kinds.HARDWARE_EVIDENCE,
        domain=Domain.ELECTRICAL,
        origin="manual",
        name="Reviewed row",
        attrs={"managed_by": EVIDENCE_MARKER, "nonoperational": True, "robot_id": str(robot_id)},
    )
    db.add(evidence)
    await db.flush()
    provenance = TopologyProvenance(source_ref=source_ref, **row.pop("provenance", {}))
    dump = TopologyEvidence(
        source_namespace="extraction:test",
        source_ref="source:test",
        provenance=(provenance,),
        confidence=0.55,
        **row,
    ).model_dump(mode="json")
    return await write_edge(
        db,
        project_id=project_id,
        src_id=brain_id,
        dst_id=evidence.id,
        relation_type=EVIDENCE_RELATION,
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=USER,
        attrs={
            "managed_by": EVIDENCE_MARKER,
            "nonoperational": True,
            "robot_id": str(robot_id),
            "source_kind": source_kind,
            "row": dump,
        },
        edge_id=uuid.uuid4(),
        managed_by=EVIDENCE_MARKER,
    )


async def inferred(db: AsyncSession, project_id: uuid.UUID, relation_type: str) -> list[GraphEdge]:
    return list(
        await db.scalars(
            select(GraphEdge)
            .where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type == relation_type,
                GraphEdge.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
    )


async def test_commands_from_a_bus_address_that_matches_one_part(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    pid, robot, brain, parts = await seed_robot(client, alice_headers, db)
    sketch = await seed_code_file(db, pid, SKETCH_PATH)
    line = sketch_line("Wire.beginTransmission(0x03)")
    await seed_evidence(
        db, pid, robot, brain, source_ref=f"{SKETCH_PATH}:{line}", protocol="i2c", address="0x03"
    )
    await seed_evidence(
        db, pid, robot, brain, source_ref=f"{SKETCH_PATH}:9", protocol="i2c", address="9"
    )
    await seed_evidence(
        db, pid, robot, brain, source_ref="source:elsewhere", protocol="i2c", address="4"
    )

    report = await firmware_edges.infer(db, pid)

    edges = await inferred(db, pid, "commands")
    assert [(e.src_id, e.dst_id, e.confidence) for e in edges] == [(sketch.id, parts["3"], 0.8)]
    assert edges[0].attrs["evidence"] == [
        {"kind": "firmware_symbol", "ref": f"{SKETCH_PATH}:{line}", "detail": None}
    ]
    part = await db.get(GraphEntity, parts["3"])
    assert part is not None
    cell = matrix_cell("code", part.domain.value)
    assert edges[0].attrs.get("matrix_cell") == (cell.value if cell else None)
    assert edges[0].attrs["address"] == "0x03"
    assert report == InferenceReport(
        "firmware_edges", created=1, updated=0, skipped=0, candidates=0
    )

    again = await firmware_edges.infer(db, pid)
    assert again == InferenceReport("firmware_edges", created=0, updated=0, skipped=1, candidates=0)
    assert [e.id for e in await inferred(db, pid, "commands")] == [edges[0].id]


async def test_repo_config_literal_is_a_candidate_and_a_manual_edge_survives(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    pid, robot, brain, parts = await seed_robot(client, alice_headers, db)
    sketch = await seed_code_file(db, pid, SKETCH_PATH)
    config = await seed_code_file(db, pid, "config/robot.json")
    await seed_evidence(
        db,
        pid,
        robot,
        brain,
        source_ref="config/robot.json:4",
        source_kind="host_config",
        address="06",
    )
    manual = await write_edge(
        db,
        project_id=pid,
        src_id=sketch.id,
        dst_id=parts["1"],
        relation_type="commands",
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=USER,
    )

    report = await firmware_edges.infer(db, pid)

    edges = await inferred(db, pid, "commands")
    assert {(e.src_id, e.dst_id, e.confidence, e.origin) for e in edges} == {
        (config.id, parts["6"], 0.55, "inferred"),
        (sketch.id, parts["1"], 1.0, "manual"),
    }
    assert report.candidates == 1
    await db.refresh(manual)
    assert manual.origin == "manual" and manual.deleted_at is None


async def test_reads_from_an_analog_pin_wired_through_the_brain(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    pid, robot, brain, parts = await seed_robot(client, alice_headers, db)
    sketch = await seed_code_file(db, pid, SKETCH_PATH)
    line = sketch_line("analogRead(A0)")
    brain_row = await db.get(GraphEntity, brain)
    assert brain_row is not None
    await write_edge(
        db,
        project_id=pid,
        src_id=brain,
        dst_id=parts["2"],
        relation_type="wires",
        origin="inferred",
        confidence=1.0,
        evidence=[],
        created_by=None,
        attrs={"nets": ["/SENSE"], "pins": {str(brain): ["A0"], str(parts["2"]): ["1"]}},
    )
    await seed_evidence(
        db,
        pid,
        robot,
        brain,
        source_ref=f"{SKETCH_PATH}:{line}",
        protocol="analog",
        provenance={"pin_ref": "A0"},
    )
    await seed_evidence(
        db,
        pid,
        robot,
        brain,
        source_ref=f"{SKETCH_PATH}:{line}",
        protocol="analog",
        provenance={"pin_ref": "A7"},
    )

    await firmware_edges.infer(db, pid)

    reads = await inferred(db, pid, "reads")
    assert [(e.src_id, e.dst_id, e.confidence) for e in reads] == [(sketch.id, parts["2"], 0.55)]
    assert reads[0].attrs["pin"] == "A0"
    assert reads[0].attrs["evidence"][0]["ref"] == f"{SKETCH_PATH}:{line}"


@pytest.mark.asyncio
async def test_confirm_runs_inference_once_and_never_on_replay(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.hardware import topology_acceptance
    from solus_api.hardware.topology_acceptance import ExtractionConfirm, TopologyAcceptanceService

    project, _, robot, body, _, _ = await proposal_setup(
        client, alice_headers, app, tmp_path, monkeypatch
    )
    proposal = (
        await client.post(propose_url(project, robot), headers=alice_headers, json=body)
    ).json()["data"]
    me = (await client.get("/api/v1/users/me", headers=alice_headers)).json()["data"]
    service = TopologyAcceptanceService(
        db,
        uuid.UUID(project),
        uuid.UUID(me["id"]),
        LocalHardwareSources.for_local_runner(app.state.bench_local),
    )
    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def record(
        session: AsyncSession, project_id: uuid.UUID, *, robot_id: uuid.UUID
    ) -> list[Any]:
        calls.append((project_id, robot_id))
        return []

    monkeypatch.setattr(topology_acceptance, "infer_after_acceptance", record)
    request = ExtractionConfirm.model_validate(
        {
            **body,
            "proposal_digest": proposal["proposal_digest"],
            "operation_id": str(uuid.uuid4()),
            "selections": [{"row_index": 0, "name": "Reviewed elbow"}],
        }
    )
    _, replayed = await service.confirm(uuid.UUID(robot), request)
    await db.commit()
    assert not replayed and calls == [(uuid.UUID(project), uuid.UUID(robot))]
    _, replayed = await service.confirm(uuid.UUID(robot), request)
    assert replayed and len(calls) == 1
    edge = await db.scalar(select(GraphEdge).where(GraphEdge.relation_type == EVIDENCE_RELATION))
    assert edge is not None and edge.attrs["source_kind"] == "host_config"
