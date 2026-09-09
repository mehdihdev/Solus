"""End-to-end proofs for the full SOLUSDEV-100 KiCad ingest surface (T5):
the real committed T3 fixture landing in the graph through the actual
connect/sync HTTP flow, re-sync idempotency, invariant-2 (content-derived
identity) equality across all three acquisition paths, and the large
(1001-component) fixture. Mirrors `test_sources.py`'s HTTP flow and
`test_sync_live_acquisition.py` / `test_mcp_acquire_artifact.py`'s fakes for
the live-acquisition/artifact-ref paths (docs/contracts/metadata-extraction.md
§2.1).

SOLUSDEV-252 adds the natural-ingestion flows through the SAME route: the
real KiCad-10 S-expression export of the fixture lands the same component/net
counts and identity hints as its XML twin (the cross-format invariant, W0-08
§5.2), and a board-only source (`config.board`, §5.2a) lands board-only parts
as components with no edges.

`serialize_entity` (schemas.py) does not surface `modality_hints` on the
public `/entities` read (only `attrs`/`properties`) — see the T5 completion
report. So graph-row assertions here read the DB directly via a dedicated
sessionmaker, the same idiom `test_sync_live_acquisition.py` already uses for
its own end-to-end checks (`_landed_external_refs`).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import create_project, create_team, me
from fixtures.kicad_project import (
    SOLUS_SAMPLE_DIR,
    SOLUS_SAMPLE_LARGE_NETLIST,
    SOLUS_SAMPLE_NETLIST,
)
from fixtures.kicad_sample import KICAD_PCB
from httpx import AsyncClient
from solus_api.agent.tools.shapes import ArtifactRef, ToolDescriptor, ToolResult
from solus_api.bridge.allowlist import BridgeToolSpec
from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry
from solus_api.bridge.service import ingest_result
from solus_api.connectors.contracts import Credentials, SyncContext
from solus_api.connectors.eda import CONNECTED_TO
from solus_api.connectors.kicad import KicadConnector
from solus_api.connectors.mcp_acquire import BridgeExportAcquirer
from solus_api.models import ArtifactStorage, Domain, GraphEdge, GraphEntity
from solus_api.services.artifacts import create_artifact
from solus_api.storage import LocalArtifactStore
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

NETLIST_TEXT = SOLUS_SAMPLE_NETLIST.read_text()
LARGE_NETLIST_TEXT = SOLUS_SAMPLE_LARGE_NETLIST.read_text()
#: The real `kicad-cli sch export netlist` (10.0.1, default S-expression format)
#: of the SAME committed fixture schematic — the XML export's twin.
SEXPR_NETLIST_TEXT = (Path(__file__).parent / "fixtures" / "solus_sample.net").read_text()
LARGE_COMPONENT_COUNT = 1001
TOOL_NAME = "kicad.export_netlist"

#: T3's committed roster (solus_sample.net.xml): designator -> MPN, the
#: `modality_hints.part_number` the KiCad parser must emit for each.
EXPECTED_COMPONENT_ROSTER = {
    "U1": "STM32F030F4P6",
    "U2": "MPU-6050",
    "R1": "RC0603FR-074K7L",
    "R2": "RC0603FR-074K7L",
    "R3": "RC0603FR-0710KL",
    "C1": "CL10B104KB8NNNC",
    "C2": "CL10B104KB8NNNC",
    "C3": "CL10B222KB8NNNC",
    "C4": "CL10B104KB8NNNC",
}


# ---------------------------------------------------------------- HTTP helpers


async def _project_and_user(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """`(project_id, user_id, team_id)` — the REAL team the project belongs
    to (Phase 4: `consume_tool_artifact`'s anti-forgery condition 2 checks
    the project's ACTUAL team_id, so callers must scope any acquirer to that
    same team rather than an arbitrary uuid)."""
    user = await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return uuid.UUID(project["id"]), uuid.UUID(user["id"]), uuid.UUID(team["id"])


async def _project(client: AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    project_id, _user_id, _team_id = await _project_and_user(client, headers)
    return project_id


async def _connect_kicad(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: uuid.UUID,
    *,
    export: str | None = None,
    board: str | None = None,
) -> dict[str, Any]:
    # Exactly what the desktop sends: present keys only (SOLUSDEV-252).
    config = {key: text for key, text in (("export", export), ("board", board)) if text}
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "kicad", "name": "solus-sample", "config": config},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def _sync(
    client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID, source_id: str
) -> None:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources/{source_id}/sync", headers=headers
    )
    assert resp.status_code == 202, resp.text


# ---------------------------------------------------------------- DB read helpers
#
# The public `/entities` read does not surface `modality_hints` (module
# docstring) — graph-row assertions read the DB directly, mirroring
# `test_sync_live_acquisition.py`'s own `_landed_external_refs` idiom.


async def _entity_snapshot(
    maker: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> dict[str, dict[str, Any]]:
    """`external_ref` -> a plain-dict snapshot of the fields this suite checks."""
    async with maker() as session:
        rows = (
            await session.scalars(
                select(GraphEntity).where(
                    GraphEntity.project_id == project_id, GraphEntity.deleted_at.is_(None)
                )
            )
        ).all()
        return {
            row.external_ref: {
                "id": row.id,
                "kind": row.kind,
                "domain": row.domain,
                "modality_hints": dict(row.modality_hints),
            }
            for row in rows
            if row.external_ref
        }


async def _relation_snapshot(
    maker: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    entities: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """`(from_key, to_key)` -> a plain-dict snapshot of relation_type/attrs."""
    id_to_key = {snapshot["id"]: key for key, snapshot in entities.items()}
    async with maker() as session:
        rows = (
            await session.scalars(
                select(GraphEdge).where(
                    GraphEdge.project_id == project_id, GraphEdge.deleted_at.is_(None)
                )
            )
        ).all()
        return {
            (id_to_key[row.src_id], id_to_key[row.dst_id]): {
                "type": row.relation_type,
                "attrs": dict(row.attrs),
            }
            for row in rows
            if row.src_id in id_to_key and row.dst_id in id_to_key
        }


async def _component_count(maker: async_sessionmaker[AsyncSession], project_id: uuid.UUID) -> int:
    async with maker() as session:
        total = await session.scalar(
            select(func.count())
            .select_from(GraphEntity)
            .where(
                GraphEntity.project_id == project_id,
                GraphEntity.deleted_at.is_(None),
                GraphEntity.kind == "component",
            )
        )
        return int(total or 0)


@pytest.fixture
def sessionmaker_fixture(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# -------------------------------------------------------- 1: real fixture e2e


async def test_real_fixture_lands_expected_component_and_net_entities(
    client: AsyncClient,
    alice_headers: dict[str, str],
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _connect_kicad(client, alice_headers, project_id, export=NETLIST_TEXT)
    await _sync(client, alice_headers, project_id, source["id"])

    entities = await _entity_snapshot(sessionmaker_fixture, project_id)

    components = {key: row for key, row in entities.items() if row["kind"] == "component"}
    assert set(components) == set(EXPECTED_COMPONENT_ROSTER)
    for designator, expected_mpn in EXPECTED_COMPONENT_ROSTER.items():
        row = components[designator]
        assert row["domain"] is Domain.ELECTRICAL
        assert row["modality_hints"].get("part_number") == expected_mpn

    # First-class net entities, not pairwise component-component edges.
    assert entities["net:SDA"]["kind"] == "net"
    assert entities["net:SDA"]["domain"] is Domain.ELECTRICAL
    assert entities["net:SCL"]["kind"] == "net"
    assert entities["net:SCL"]["domain"] is Domain.ELECTRICAL

    relations = await _relation_snapshot(sessionmaker_fixture, project_id, entities)

    def _edge(net: str, pins: list[str]) -> dict[str, Any]:
        return {"type": CONNECTED_TO, "attrs": {"net": net, "pins": pins}}

    # SDA: R1 pin 2, U1 pin 18, U2 pin 24 (solus_sample.net.xml net code="8").
    assert relations[("R1", "net:SDA")] == _edge("SDA", ["2"])
    assert relations[("U1", "net:SDA")] == _edge("SDA", ["18"])
    assert relations[("U2", "net:SDA")] == _edge("SDA", ["24"])
    # SCL: R2 pin 2, U1 pin 17, U2 pin 23 (net code="7").
    assert relations[("R2", "net:SCL")] == _edge("SCL", ["2"])
    assert relations[("U1", "net:SCL")] == _edge("SCL", ["17"])
    assert relations[("U2", "net:SCL")] == _edge("SCL", ["23"])


# -------------------------------------- 1b: cross-format invariant (SOLUSDEV-252)


async def test_sexpr_export_lands_the_same_graph_shape_as_the_xml_twin(
    client: AsyncClient,
    alice_headers: dict[str, str],
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """W0-08 §5.2: the default S-expression `.net` is a first-class equal of the
    XML export. Through the real connect/sync route, the KiCad-10 export of the
    fixture lands the same component roster (with the same MPN hints) and the
    same number of net entities and edges as the XML flow. Net NAMES are not
    compared: KiCad 10 writes local labels as `/SDA` where the XML twin (KiCad 9)
    wrote `SDA` — a producer quirk the graph keeps verbatim."""
    xml_project = await _project(client, alice_headers)
    xml_source = await _connect_kicad(client, alice_headers, xml_project, export=NETLIST_TEXT)
    await _sync(client, alice_headers, xml_project, xml_source["id"])

    sexpr_project = await _project(client, alice_headers)
    sexpr_source = await _connect_kicad(
        client, alice_headers, sexpr_project, export=SEXPR_NETLIST_TEXT
    )
    await _sync(client, alice_headers, sexpr_project, sexpr_source["id"])

    xml_entities = await _entity_snapshot(sessionmaker_fixture, xml_project)
    sexpr_entities = await _entity_snapshot(sessionmaker_fixture, sexpr_project)

    def _components(rows: dict[str, dict[str, Any]]) -> dict[str, str | None]:
        return {
            key: row["modality_hints"].get("part_number")
            for key, row in rows.items()
            if row["kind"] == "component"
        }

    assert _components(sexpr_entities) == _components(xml_entities) == EXPECTED_COMPONENT_ROSTER
    for rows in (xml_entities, sexpr_entities):
        for designator in EXPECTED_COMPONENT_ROSTER:
            assert rows[designator]["modality_hints"].get("schematic_symbol_name")
    xml_nets = {k for k, row in xml_entities.items() if row["kind"] == "net"}
    sexpr_nets = {k for k, row in sexpr_entities.items() if row["kind"] == "net"}
    assert len(sexpr_nets) == len(xml_nets)
    # KiCad 10's `/` sheet-path prefix aside, the two exports name the same nets.
    assert {n.removeprefix("net:").removeprefix("/") for n in sexpr_nets} == {
        n.removeprefix("net:") for n in xml_nets
    }

    xml_relations = await _relation_snapshot(sessionmaker_fixture, xml_project, xml_entities)
    sexpr_relations = await _relation_snapshot(sessionmaker_fixture, sexpr_project, sexpr_entities)
    assert len(sexpr_relations) == len(xml_relations)
    # Same pins on the same edge; the edge carries its producer's net name verbatim.
    assert xml_relations[("R1", "net:SDA")] == {
        "type": CONNECTED_TO,
        "attrs": {"net": "SDA", "pins": ["2"]},
    }
    assert sexpr_relations[("R1", "net:/SDA")] == {
        "type": CONNECTED_TO,
        "attrs": {"net": "/SDA", "pins": ["2"]},
    }


# ------------------------------------------------ 1c: board-only source (§5.2a)


async def test_board_only_source_lands_board_only_parts_without_edges(
    client: AsyncClient,
    alice_headers: dict[str, str],
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _connect_kicad(client, alice_headers, project_id, board=KICAD_PCB)
    await _sync(client, alice_headers, project_id, source["id"])

    syncs_resp = await client.get(
        f"/api/v1/projects/{project_id}/sources/{source['id']}/syncs", headers=alice_headers
    )
    assert syncs_resp.status_code == 200, syncs_resp.text
    assert syncs_resp.json()["data"][0]["status"] == "succeeded"

    entities = await _entity_snapshot(sessionmaker_fixture, project_id)
    components = {key: row for key, row in entities.items() if row["kind"] == "component"}
    assert set(components) == {"U1", "R1", "C1", "H1", "FID1"}
    assert components["H1"]["domain"] is Domain.ELECTRICAL
    # A board carries no libsource: no schematic_symbol_name hint anywhere.
    assert all("schematic_symbol_name" not in row["modality_hints"] for row in components.values())
    assert components["U1"]["modality_hints"]["part_number"] == "LM358DR"
    assert {k for k, row in entities.items() if row["kind"] == "net"} == {
        "net:VCC",
        "net:GND",
        "net:SIGNAL",
    }

    relations = await _relation_snapshot(sessionmaker_fixture, project_id, entities)
    assert not any(src in {"H1", "FID1"} for src, _dst in relations)
    assert relations[("U1", "net:VCC")] == {
        "type": CONNECTED_TO,
        "attrs": {"net": "VCC", "pins": ["8"]},
    }


# ------------------------------------------------------------ 2: idempotency


async def test_resync_identical_content_is_idempotent(
    client: AsyncClient,
    alice_headers: dict[str, str],
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _connect_kicad(client, alice_headers, project_id, export=NETLIST_TEXT)

    await _sync(client, alice_headers, project_id, source["id"])
    entities_first = await _entity_snapshot(sessionmaker_fixture, project_id)
    relations_first = await _relation_snapshot(sessionmaker_fixture, project_id, entities_first)

    await _sync(client, alice_headers, project_id, source["id"])

    syncs_resp = await client.get(
        f"/api/v1/projects/{project_id}/sources/{source['id']}/syncs", headers=alice_headers
    )
    assert syncs_resp.status_code == 200, syncs_resp.text
    sync_rows = syncs_resp.json()["data"]
    assert len(sync_rows) == 2
    second_sync = sync_rows[0]  # newest first (created_at desc)
    assert second_sync["status"] == "succeeded"
    # Upsert by source_key: an identical re-sync creates/updates/deletes nothing.
    assert second_sync["entities_created"] == 0
    assert second_sync["entities_updated"] == 0
    assert second_sync["relations_created"] == 0
    assert second_sync["relations_deleted"] == 0

    entities_second = await _entity_snapshot(sessionmaker_fixture, project_id)
    relations_second = await _relation_snapshot(sessionmaker_fixture, project_id, entities_second)
    assert set(entities_second) == set(entities_first)
    assert len(entities_second) == len(entities_first)
    assert set(relations_second) == set(relations_first)
    assert len(relations_second) == len(relations_first)


# ------------------------------------------------ 3: invariant-2 identity equality


class _FakeAcquirer:
    """A minimal T4a-seam `ExportAcquirer` — no bridge/artifact machinery,
    just a fixed export text handed straight back."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def acquire(self, ctx: SyncContext) -> str | None:
        return self._text


def _export_tool_spec() -> BridgeToolSpec:
    return BridgeToolSpec(
        server="kicad",
        remote_name="export_netlist",
        descriptor=ToolDescriptor(
            name=TOOL_NAME,
            description="export",
            params={"type": "object"},
            returns={"type": "object"},
        ),
    )


def _live_session(
    sent: list[str], *, user_id: uuid.UUID, team_id: uuid.UUID, project_id: uuid.UUID
) -> BridgeSession:
    async def _send(frame: str) -> None:
        sent.append(frame)

    async def _close(code: int) -> None:
        return None

    return BridgeSession(
        session_id=uuid.uuid4().hex,
        user_id=user_id,
        team_id=team_id,
        project_id=project_id,
        companion_instance_id="i-1",
        companion_version="0.1.0",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=(_export_tool_spec(),),
        send=_send,
        close=_close,
        max_inflight=8,
    )


async def _wait_for_call_id(sent: list[str]) -> str:
    while not sent:
        await asyncio.sleep(0.005)
    call_id: str = json.loads(sent[0])["data"]["call_id"]
    return call_id


async def test_identity_invariant_equal_across_inline_fake_and_artifact_paths(
    client: AsyncClient,
    alice_headers: dict[str, str],
    tmp_path: Path,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """docs/contracts/metadata-extraction.md §2.1 invariant 2: identity is
    content-derived, never transport-derived. The SAME netlist text acquired
    (a) inline via `config.export`, (b) via a fake `ExportAcquirer`, and
    (c) via a live tool result carrying an `ArtifactRef` (T4c's artifact
    service + T4b's `BridgeExportAcquirer`) must yield byte-identical
    `SyncResult`s — same entities, same relations."""
    text = NETLIST_TEXT

    via_inline = await KicadConnector().sync(
        SyncContext(credentials=Credentials(token=""), config={"export": text})
    )

    via_fake = await KicadConnector(acquirer=_FakeAcquirer(text)).sync(
        SyncContext(credentials=Credentials(token=""), config={"export": "irrelevant placeholder"})
    )
    assert via_fake == via_inline

    project_id, user_id, team_id = await _project_and_user(client, alice_headers)
    sessions = InMemoryBridgeSessionRegistry()
    sent: list[str] = []
    session = _live_session(sent, user_id=user_id, team_id=team_id, project_id=project_id)
    sessions.bind(session)
    store = LocalArtifactStore(str(tmp_path / "artifacts"))

    async def _answer_with_artifact() -> None:
        call_id = await _wait_for_call_id(sent)
        data = text.encode("utf-8")
        async with sessionmaker_fixture() as session_db:
            artifact = await create_artifact(
                session_db,
                store,
                project_id=project_id,
                created_by=user_id,
                data=data,
                media_type="application/xml",
                source_tool=TOOL_NAME,
                tool_call_id=call_id,
            )
            await session_db.commit()
            ref = ArtifactRef(
                artifact_id=artifact.id,
                uri=artifact.uri,
                media_type="application/xml",
                storage=ArtifactStorage.LOCAL,
                size_bytes=len(data),
            )
        ingest_result(
            session,
            ToolResult.success(call_id, {"artifact_ref": json.loads(ref.model_dump_json())}),
        )

    acquirer = BridgeExportAcquirer(
        sessions=sessions,
        sessionmaker=sessionmaker_fixture,
        store=store,
        project_id=project_id,
        team_id=team_id,
        acting_user_id=user_id,
        tool_name=TOOL_NAME,
        call_cap_bytes=1_048_576,
        artifact_ttl_seconds=3600,
        inline_max_bytes=1,  # irrelevant to the artifact_ref path; forces it if ever inline
    )
    task = asyncio.create_task(_answer_with_artifact())
    via_artifact = await KicadConnector(acquirer=acquirer).sync(
        SyncContext(
            credentials=Credentials(token=""),
            config={"export": "irrelevant placeholder", "project_path": "/p"},
        )
    )
    await task

    assert via_artifact == via_inline
    assert via_artifact.entities == via_inline.entities
    assert via_artifact.relations == via_inline.relations


# ----------------------------------------------------------- 4: large fixture


async def test_large_fixture_lands_all_components(
    client: AsyncClient,
    alice_headers: dict[str, str],
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await _project(client, alice_headers)
    source = await _connect_kicad(client, alice_headers, project_id, export=LARGE_NETLIST_TEXT)
    await _sync(client, alice_headers, project_id, source["id"])

    assert await _component_count(sessionmaker_fixture, project_id) == LARGE_COMPONENT_COUNT


# --------------------------------------------------- 5: hostile fixture (M6)

#: FIX-B's adversarial fixture (Phase 4 M6): a `solus_sample`-topology netlist
#: with adversarial instructions embedded in component values/net names.
#: Written under the SAME committed-fixture directory as the benign T3
#: fixture; not yet merged when this suite was authored — the test below
#: skips cleanly until it lands (the orchestrator unskips at integration by
#: simply re-running once the fixture file exists).
HOSTILE_NETLIST_PATH = SOLUS_SAMPLE_DIR / "solus_sample_hostile.net.xml"


@pytest.mark.skipif(
    not HOSTILE_NETLIST_PATH.exists(),
    reason=(
        "M6 hostile fixture not yet merged by FIX-B "
        "(integrations/mcp/kicad/tests/fixtures/solus_sample/solus_sample_hostile.net.xml) "
        "— unskip once it lands"
    ),
)
async def test_hostile_fixture_ingests_cleanly_with_verbatim_inert_strings(
    client: AsyncClient,
    alice_headers: dict[str, str],
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """Phase 4 M6: adversarial instructions embedded in component values/net
    names (CLAUDE.md §7 — everything ingested by connectors is untrusted
    input to the model layer) must ingest EXACTLY like a benign netlist —
    same topology, no parser divergence — and the hostile strings must land
    VERBATIM as INERT data (modality_hints values), never altered, never
    executed, never able to change ingestion's control flow."""
    hostile_text = HOSTILE_NETLIST_PATH.read_text()
    project_id = await _project(client, alice_headers)
    source = await _connect_kicad(client, alice_headers, project_id, export=hostile_text)
    await _sync(client, alice_headers, project_id, source["id"])

    syncs_resp = await client.get(
        f"/api/v1/projects/{project_id}/sources/{source['id']}/syncs", headers=alice_headers
    )
    assert syncs_resp.status_code == 200, syncs_resp.text
    latest_sync = syncs_resp.json()["data"][0]
    assert latest_sync["status"] == "succeeded"  # ingests cleanly, no crash / no divergence

    entities = await _entity_snapshot(sessionmaker_fixture, project_id)
    components = {key: row for key, row in entities.items() if row["kind"] == "component"}

    # Same designator roster as the benign fixture (no parse divergence). The
    # fixture deliberately renames the SDA net to CARRY the injection string, so
    # the topology check is: SCL untouched, and the hostile net name landed
    # VERBATIM as an inert `net:` entity key (never parsed as markup, never
    # truncated at the embedded `"></export>`).
    assert set(components) == set(EXPECTED_COMPONENT_ROSTER)
    assert "net:SCL" in entities
    hostile_net_keys = [
        key
        for key in entities
        if key.startswith("net:SDA") and "IGNORE ALL PREVIOUS INSTRUCTIONS" in key
    ]
    assert len(hostile_net_keys) == 1, sorted(k for k in entities if k.startswith("net:"))

    # The hostile strings land VERBATIM as inert data — never escaped, never
    # dropped, never able to alter parsing — and never anywhere but a plain
    # modality_hints value; at least one component's part_number must differ
    # from the benign roster (proving the hostile text actually rode in).
    part_numbers = [
        components[designator]["modality_hints"].get("part_number")
        for designator in EXPECTED_COMPONENT_ROSTER
    ]
    assert any(
        actual != expected
        for actual, expected in zip(part_numbers, EXPECTED_COMPONENT_ROSTER.values(), strict=True)
    ), "expected at least one hostile value to differ from the benign roster"
