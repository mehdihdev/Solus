"""Mates (SOLUSDEV-320 Phase 3 module 6): `mates_from_definition` on a recorded assembly
definition, `mates_with` emitted by the mechanical mapping, the Onshape sync reading mates ONLY
from the mirror (never a live request), and the `mounts` promotion in graph/inference/mates."""

from __future__ import annotations

import importlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fixtures.cad_sample import BRACKET
from solus_api.connectors.contracts import SyncError
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.mechanical import CadModel, CadNode, build_mechanical_graph
from solus_api.connectors.onshape import (
    ONSHAPE_API_BASE,
    OnshapeConnector,
    _Target,
    mirrored_payload_key,
)
from solus_api.connectors.onshape_assembly_read import (
    MateFrame,
    MateRecord,
    mates_from_definition,
)
from solus_api.connectors.onshape_read_cache import (
    ReadScope,
    TurnReadMemo,
    bind_read_scope,
    mirrored_get,
)
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.graph.inference import InferenceReport, mates
from solus_api.models import Domain, GraphEntity
from solus_contracts.relations import EdgeEvidence, EvidenceKind
from sqlalchemy.ext.asyncio import AsyncSession
from test_inference_firmware_edges import USER, inferred
from test_inference_power_nets import seed_project

# Untyped test module (mypy must not follow it): the pattern `test_edges.py` uses.
_onshape_tests = importlib.import_module("test_onshape_connector")
DID, EID, SCOPE = _onshape_tests.DID, _onshape_tests.EID, _onshape_tests.SCOPE
requires_occt: pytest.MarkDecorator = _onshape_tests.requires_occt

DEFINITION: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "inference" / "assembly_definition.json").read_text()
)
#: Authored from the public Onshape Assemblies API schema (`matedEntities[].matedCS`), not a
#: live capture — no Onshape call is made anywhere in this suite.
MATED_CS: dict[str, Any] = json.loads(
    (
        Path(__file__).parent / "fixtures" / "inference" / "assembly_definition_mated_cs.json"
    ).read_text()
)
MICROVERSION = "abc123def456"
MATE_PARAMS = {"includeMateFeatures": "true", "includeMateConnectors": "true"}


def test_mates_from_definition_reads_mate_features_only() -> None:
    assert mates_from_definition(DEFINITION) == [
        MateRecord("BasePlate", "PegPair/Peg", "FASTENED", "fastenA"),
        MateRecord("BasePlate", "PegPair/Peg[1]", "REVOLUTE", "revoluteB"),
    ]
    assert mates_from_definition({}) == []
    assert mates_from_definition({"rootAssembly": {"features": "nope"}}) == []
    suppressed = json.loads(json.dumps(DEFINITION))
    suppressed["rootAssembly"]["features"][0]["suppressed"] = True
    assert [m.feature_id for m in mates_from_definition(suppressed)] == ["revoluteB"]


def test_mechanical_mapping_emits_mates_with_between_resolved_occurrences() -> None:
    model = CadModel(
        nodes=(
            CadNode("Bracket", "Bracket", True),
            CadNode("Bracket/BasePlate", "BasePlate", False, "Bracket"),
            CadNode("Bracket/PegPair", "PegPair", True, "Bracket"),
            CadNode("Bracket/PegPair/Peg[0]", "Peg", False, "Bracket/PegPair"),
            CadNode("Bracket/PegPair/Peg[1]", "Peg", False, "Bracket/PegPair"),
        )
    )
    records = [
        *mates_from_definition(DEFINITION),
        MateRecord("BasePlate", "Ghost", "FASTENED", "ghost"),
    ]
    _, relations, errors = build_mechanical_graph(model, scope="s", mates=records)
    found = {(r.from_key, r.to_key): r.properties for r in relations if r.type == "mates_with"}
    assert found == {
        ("s:Bracket/BasePlate", "s:Bracket/PegPair/Peg[0]"): {
            "mate_type": "FASTENED",
            "feature_id": "fastenA",
            "evidence": [{"kind": "mate", "ref": "fastenA", "detail": None}],
            "matrix_cell": "mechanical->mechanical",
        },
        ("s:Bracket/BasePlate", "s:Bracket/PegPair/Peg[1]"): {
            "mate_type": "REVOLUTE",
            "feature_id": "revoluteB",
            "evidence": [{"kind": "mate", "ref": "revoluteB", "detail": None}],
            "matrix_cell": "mechanical->mechanical",
        },
    }
    assert errors == [SyncError(item="ghost", message="mate endpoint is not a node of this export")]
    assert not any(r.type == "mates_with" for r in build_mechanical_graph(model)[1])


def test_mated_cs_becomes_mate_frame_on_the_edge() -> None:
    records = mates_from_definition(MATED_CS)
    assert records == [
        MateRecord(
            "Base",
            "Arm",
            "REVOLUTE",
            "elbow",
            MateFrame((0.0, 0.0, 0.05), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        )
    ]
    model = CadModel(
        nodes=(
            CadNode("Robot", "Robot", True),
            CadNode("Robot/Base", "Base", False, "Robot"),
            CadNode("Robot/Arm", "Arm", False, "Robot"),
        )
    )
    _, relations, errors = build_mechanical_graph(model, scope="s", mates=records)
    (edge,) = [r for r in relations if r.type == "mates_with"]
    assert errors == []
    assert (edge.from_key, edge.to_key) == ("s:Robot/Base", "s:Robot/Arm")
    assert edge.properties["mate_frame"] == {
        "origin_m": [0.0, 0.0, 0.05],
        "x_axis": [1.0, 0.0, 0.0],
        "y_axis": [0.0, 1.0, 0.0],
        "z_axis": [0.0, 0.0, 1.0],
    }


def test_mate_without_cs_carries_no_frame() -> None:
    records = mates_from_definition(DEFINITION)
    assert all(record.frame is None for record in records)
    model = CadModel(
        nodes=(
            CadNode("Bracket", "Bracket", True),
            CadNode("Bracket/BasePlate", "BasePlate", False, "Bracket"),
            CadNode("Bracket/PegPair", "PegPair", True, "Bracket"),
            CadNode("Bracket/PegPair/Peg[0]", "Peg", False, "Bracket/PegPair"),
            CadNode("Bracket/PegPair/Peg[1]", "Peg", False, "Bracket/PegPair"),
        )
    )
    _, relations, _ = build_mechanical_graph(model, scope="s", mates=records)
    mated = [r for r in relations if r.type == "mates_with"]
    assert len(mated) == 2
    assert all("mate_frame" not in r.properties for r in mated)


def _mate_calls() -> list[Any]:
    return [
        call
        for call in respx.calls
        if "includeMateFeatures" in str(call.request.url) or "/features" in call.request.url.path
    ]


@requires_occt
@respx.mock
async def test_sync_reads_mates_from_the_mirror_and_never_live() -> None:
    _onshape_tests._mock_export()
    cache = IntegrationCache(InMemoryCacheStore())
    connector = OnshapeConnector(
        client_id="cid", client_secret="csecret", cache=cache, account_ref="acct"
    )
    key = mirrored_payload_key(
        "acct",
        DID,
        MICROVERSION,
        f"/api/v6/assemblies/d/{DID}/m/{MICROVERSION}/e/{EID}",
        MATE_PARAMS,
    )

    async def definition() -> dict[str, Any]:
        return DEFINITION

    # Stored the way `mirrored_get` stores it: through `fetch`, in the cache's own envelope.
    assert (await cache.fetch(key, ttl_seconds=60, fetch=definition)).value == DEFINITION

    result = await connector.sync(_onshape_tests._ctx())

    mated = {
        (r.from_key, r.to_key): r.properties["mate_type"]
        for r in result.relations
        if r.type == "mates_with"
    }
    assert mated == {
        (f"{SCOPE}:Bracket/BasePlate", f"{SCOPE}:Bracket/PegPair/Peg[0]"): "FASTENED",
        (f"{SCOPE}:Bracket/BasePlate", f"{SCOPE}:Bracket/PegPair/Peg[1]"): "REVOLUTE",
    }
    assert _mate_calls() == []


@requires_occt
@respx.mock
async def test_sync_without_a_mirrored_definition_skips_mates_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="solus.connectors.onshape")
    _onshape_tests._mock_export()
    connector = OnshapeConnector(
        client_id="cid",
        client_secret="csecret",
        cache=IntegrationCache(InMemoryCacheStore()),
        account_ref="acct",
    )
    result = await connector.sync(_onshape_tests._ctx())
    assert not any(r.type == "mates_with" for r in result.relations)
    assert "mates skipped: not mirrored" in caplog.text
    assert _mate_calls() == []
    # And a connector with no mirror at all (the ARQ worker's plain factory) is just as quiet.
    _onshape_tests._mock_export()  # the poll side effects were consumed by the first sync
    plain = await OnshapeConnector(client_id="cid", client_secret="csecret").sync(
        _onshape_tests._ctx()
    )
    assert not any(r.type == "mates_with" for r in plain.relations)
    assert _mate_calls() == []


@respx.mock
async def test_a_read_tools_mirror_lands_where_the_sync_looks() -> None:
    """`mirrored_get` (the read tools) and `mirrored_payload_key` (the sync) spell one key:
    a definition mirrored by a SOL read is the one the next sync's mates come from."""
    connector = OnshapeConnector(
        client_id="cid",
        client_secret="csecret",
        cache=IntegrationCache(InMemoryCacheStore()),
        account_ref="acct",
    )
    probe = respx.get(
        f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/w1/currentmicroversion"
    ).respond(200, json={"microversion": MICROVERSION})
    definition = respx.get(
        f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/{DID}/m/{MICROVERSION}/e/{EID}"
    ).respond(200, json=DEFINITION)
    scope = ReadScope(
        memo=TurnReadMemo(), account_ref="acct", workspaces={DID: "w1"}, is_write=False
    )
    async with httpx.AsyncClient(base_url=ONSHAPE_API_BASE) as client:
        with bind_read_scope(scope):
            await mirrored_get(
                connector,
                client,
                document_id=DID,
                workspace_id="w1",
                path_for=lambda sel, ident: f"/api/v6/assemblies/d/{DID}/{sel}/{ident}/e/{EID}",
                what="assembly definition",
                params=MATE_PARAMS,
            )
    assert probe.call_count == 1 and definition.call_count == 1

    records = await connector._mirrored_mates(_Target(DID, "w1", EID), MICROVERSION)

    assert [m.feature_id for m in records] == ["fastenA", "revoluteB"]
    assert definition.call_count == 1  # the sync's read never left the process


async def seed_part(
    db: AsyncSession, project_id: uuid.UUID, name: str, **attrs: Any
) -> GraphEntity:
    row = GraphEntity(
        project_id=project_id,
        kind=kinds.PART,
        domain=Domain.MECHANICAL,
        origin="connector",
        name=name,
        attrs=attrs,
    )
    db.add(row)
    await db.flush()
    return row


async def mate(
    db: AsyncSession,
    project_id: uuid.UUID,
    a: GraphEntity,
    b: GraphEntity,
    mate_type: str,
    feature_id: str,
) -> None:
    await write_edge(
        db,
        project_id=project_id,
        src_id=a.id,
        dst_id=b.id,
        relation_type="mates_with",
        origin="connector",
        confidence=1.0,
        evidence=[EdgeEvidence(kind=EvidenceKind.MATE, ref=feature_id)],
        created_by=None,
        attrs={"mate_type": mate_type, "feature_id": feature_id},
    )


async def test_mounts_from_a_fastened_mate_between_structure_and_device(db: AsyncSession) -> None:
    pid = await seed_project(db)
    plate = await seed_part(db, pid, "BasePlate", behaviour_class="structural")
    camera = await seed_part(db, pid, "Camera", behaviour_class="device")
    motor = await seed_part(db, pid, "Motor", behaviour_class="device")
    rail = await seed_part(db, pid, "Rail", behaviour_class="structural")
    battery = await seed_part(
        db, pid, "Battery", definition_id="lipo-4s"
    )  # library: power, not device
    await mate(db, pid, camera, plate, "FASTENED", "f1")  # either direction: structure → device
    await mate(db, pid, plate, motor, "fastened", "f2")
    await mate(db, pid, plate, rail, "FASTENED", "f3")  # structure ↔ structure: nothing
    await mate(db, pid, plate, battery, "FASTENED", "f4")  # not a device: nothing
    await mate(db, pid, rail, camera, "REVOLUTE", "f5")  # not fastened: nothing

    report = await mates.infer(db, pid)

    mounts = await inferred(db, pid, "mounts")
    assert {(e.src_id, e.dst_id, e.attrs["evidence"][0]["ref"]) for e in mounts} == {
        (plate.id, camera.id, "f1"),
        (plate.id, motor.id, "f2"),
    }
    assert all(e.confidence == 0.7 and e.attrs["evidence"][0]["kind"] == "mate" for e in mounts)
    assert all(e.attrs["matrix_cell"] == "mechanical->mechanical" for e in mounts)
    assert report == InferenceReport("mates", created=2, updated=0, skipped=0, candidates=2)
    assert await mates.infer(db, pid) == InferenceReport("mates", skipped=2, candidates=2)


async def test_manual_mounts_survives_a_rerun_without_its_mate(db: AsyncSession) -> None:
    pid = await seed_project(db)
    plate = await seed_part(db, pid, "BasePlate", behaviour_class="structural")
    camera = await seed_part(db, pid, "Camera", behaviour_class="device")
    manual = await write_edge(
        db,
        project_id=pid,
        src_id=plate.id,
        dst_id=camera.id,
        relation_type="mounts",
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=USER,
    )
    assert (await mates.infer(db, pid)).created == 0
    await db.refresh(manual)
    assert manual.origin == "manual" and manual.deleted_at is None
    assert BRACKET  # the shared CAD sample stays importable for the mechanical suite
