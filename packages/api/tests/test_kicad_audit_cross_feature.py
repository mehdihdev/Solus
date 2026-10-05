"""KiCad acceptance criterion 10 (SOLUSDEV-312 audit): cross-feature interactions.

Everything here starts from the REAL connect/sync route, then follows the KiCad
entities into the neighbouring features:

* Fingerprint: KiCad `modality_hints` become canonical parts and `same_as` links,
  both within the design (R1/R2 share an MPN) and across tools (a CAD part carrying
  the MCU's MPN links to the KiCad U1). The pre-existing stack test seeds through
  `apply_sync_result`; this one goes through HTTP.
* BOM: the BOM view aggregates the KiCad parts by MPN with quantities and keeps a
  cross-domain pair as ONE row only once the fingerprint has linked it.
* Sources / Connected accounts: status, entity count, last_error and the catalog
  entry reflect what the sync did, including failure and recovery.
* Data collection (ADR-011): consented users get `source.connected` and
  `source.sync_started` events with no design content in the payload;
  non-consenting users get none; the activity feed records the lifecycle.
  KNOWN GAP (strict xfail): no event is emitted when a sync FINISHES.
"""

from __future__ import annotations

import re
import uuid

import pytest
from fixtures.kicad_audit import (
    Maker,
    connect_kicad,
    entities_by_ref,
    get_source,
    new_project,
    patch_config,
    sync,
)
from fixtures.kicad_project import SOLUS_SAMPLE_NETLIST
from fixtures.kicad_sample import KICAD_PCB, KICAD_XML
from httpx import AsyncClient
from solus_api.fingerprint.ingest import scan_project
from solus_api.linking import link_from_fingerprint
from solus_api.linking.linker import RELATION_SAME_AS
from solus_api.models import DataEvent, Domain, GraphEdge, GraphEntity, User
from solus_api.widgets.bom.service import load_inputs
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

NETLIST = SOLUS_SAMPLE_NETLIST.read_text()
MCU_MPN = "STM32F030F4P6"


@pytest.fixture
def maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _cad_part(maker: Maker, project_id: uuid.UUID, mpn: str) -> uuid.UUID:
    """A mechanical part from another tool carrying `mpn` (what an Onshape BOM would give)."""
    async with maker() as session:
        part = GraphEntity(
            project_id=project_id,
            kind="part",
            domain=Domain.MECHANICAL,
            name="MCU body",
            external_ref="doc:mcu",
            source_connector="onshape",
            modality_hints={"part_number": mpn},
            attrs={},
        )
        session.add(part)
        await session.commit()
        return part.id


async def _same_as_pairs(maker: Maker, project_id: uuid.UUID) -> set[frozenset[uuid.UUID]]:
    async with maker() as session:
        edges = (
            await session.scalars(
                select(GraphEdge).where(
                    GraphEdge.project_id == project_id,
                    GraphEdge.relation_type == RELATION_SAME_AS,
                    GraphEdge.deleted_at.is_(None),
                )
            )
        ).all()
    return {frozenset((e.src_id, e.dst_id)) for e in edges}


# ------------------------------------------------------------------ fingerprint


async def test_kicad_parts_synced_over_http_become_canonical_parts_and_same_as_links(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=NETLIST)
    await sync(client, alice_headers, project_id, source["id"])
    entities = await entities_by_ref(maker, project_id)

    async with maker() as session:
        summary = await scan_project(session, project_id)
        linked = await link_from_fingerprint(session, project_id=project_id)
        await session.commit()
    # 9 components share 6 distinct MPNs; each component is an observation, none dropped.
    assert summary.observations == 9
    assert summary.canonical_created == 6
    assert (summary.unmatched, summary.ambiguous, summary.low_confidence) == (0, 0, 0)
    # R1<->R2 (one MPN) and the C1/C2/C4 trio pairwise => 1 + 3 same_as edges, at minimum.
    assert linked.created >= 4
    pairs = await _same_as_pairs(maker, project_id)
    assert frozenset((entities["R1"].id, entities["R2"].id)) in pairs
    assert frozenset((entities["C1"].id, entities["C2"].id)) in pairs
    assert frozenset((entities["R1"].id, entities["C1"].id)) not in pairs  # zero false merges

    async with maker() as session:
        refreshed = await session.get(GraphEntity, entities["U1"].id)
    assert refreshed is not None and refreshed.canonical_part_id is not None


async def test_a_cad_part_with_the_mcus_mpn_links_to_the_kicad_component_across_tools(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=NETLIST)
    await sync(client, alice_headers, project_id, source["id"])
    entities = await entities_by_ref(maker, project_id)
    cad_id = await _cad_part(maker, project_id, MCU_MPN)

    async with maker() as session:
        await scan_project(session, project_id)
        await link_from_fingerprint(session, project_id=project_id)
        await session.commit()
    assert frozenset((entities["U1"].id, cad_id)) in await _same_as_pairs(maker, project_id)


async def test_a_board_only_source_feeds_the_fingerprint_with_its_mpn_hints(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, board=KICAD_PCB)
    await sync(client, alice_headers, project_id, source["id"])
    entities = await entities_by_ref(maker, project_id)
    assert entities["U1"].modality_hints["part_number"] == "LM358DR"
    assert "schematic_symbol_name" not in entities["U1"].modality_hints  # board has no libsource
    cad_id = await _cad_part(maker, project_id, "LM358DR")

    async with maker() as session:
        summary = await scan_project(session, project_id)
        await link_from_fingerprint(session, project_id=project_id)
        await session.commit()
    assert summary.observations >= 2
    assert frozenset((entities["U1"].id, cad_id)) in await _same_as_pairs(maker, project_id)


async def test_a_resync_that_drops_a_part_retracts_its_fingerprint_link(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=NETLIST)
    await sync(client, alice_headers, project_id, source["id"])
    async with maker() as session:
        await scan_project(session, project_id)
        await link_from_fingerprint(session, project_id=project_id)
        await session.commit()
    before = await entities_by_ref(maker, project_id)
    assert frozenset((before["R1"].id, before["R2"].id)) in await _same_as_pairs(maker, project_id)

    # R2 disappears from the design (drop its comp, pins and the link target).
    start = NETLIST.index('<comp ref="R2">')
    end = NETLIST.index("</comp>", start) + len("</comp>")
    trimmed = NETLIST[:start] + NETLIST[end:]
    trimmed = re.sub(r'\s*<node ref="R2"[^>]*/>', "", trimmed)
    await patch_config(client, alice_headers, project_id, source["id"], {"export": trimmed})
    assert (await sync(client, alice_headers, project_id, source["id"]))["status"] == "succeeded"
    async with maker() as session:
        await scan_project(session, project_id)
        await link_from_fingerprint(session, project_id=project_id)
        await session.commit()
    assert "R2" not in await entities_by_ref(maker, project_id)
    live = await _same_as_pairs(maker, project_id)
    assert not any(before["R2"].id in pair for pair in live)


# -------------------------------------------------------------------------- BOM


async def test_bom_aggregates_kicad_parts_by_mpn_with_quantities(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=NETLIST)
    await sync(client, alice_headers, project_id, source["id"])
    async with maker() as session:
        await scan_project(session, project_id)
        await link_from_fingerprint(session, project_id=project_id)
        await session.commit()
        rows = (await load_inputs(session, project_id)).rows()

    by_mpn = {row.part_number: row for row in rows}
    assert {r: row.quantity for r, row in by_mpn.items()} == {
        "CL10B104KB8NNNC": 3,  # C1, C2, C4
        "CL10B222KB8NNNC": 1,
        "MPU-6050": 1,
        "RC0603FR-0710KL": 1,
        "RC0603FR-074K7L": 2,  # R1, R2
        MCU_MPN: 1,
    }
    assert sum(row.quantity for row in rows) == 9  # every component is on the BOM exactly once
    assert all(row.kind == "design" and row.state == "installed" for row in rows)
    assert all({s.domain for s in row.sources} == {"electrical"} for row in rows)


async def test_bom_keeps_a_cad_part_and_its_kicad_twin_as_one_row_only_after_linking(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=NETLIST)
    await sync(client, alice_headers, project_id, source["id"])
    await _cad_part(maker, project_id, MCU_MPN)

    async with maker() as session:
        unlinked = [
            r for r in (await load_inputs(session, project_id)).rows() if r.part_number == MCU_MPN
        ]
    assert len(unlinked) == 2  # same MPN string across domains is NOT merged on its own

    async with maker() as session:
        await scan_project(session, project_id)
        await link_from_fingerprint(session, project_id=project_id)
        await session.commit()
        linked = [
            r for r in (await load_inputs(session, project_id)).rows() if r.part_number == MCU_MPN
        ]
    assert len(linked) == 1
    assert {s.domain for s in linked[0].sources} == {"electrical", "mechanical"}


# ------------------------------------------------ sources / connected accounts


async def test_sources_list_and_catalog_reflect_the_kicad_sync_lifecycle(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=KICAD_XML)

    fresh = await get_source(client, alice_headers, project_id, source["id"])
    assert (fresh["type"], fresh["status"], fresh["account_login"]) == (
        "kicad",
        "connected",
        "kicad-export",
    )
    assert fresh["last_synced_at"] is None and fresh["last_error"] is None

    await sync(client, alice_headers, project_id, source["id"])
    listed = (
        await client.get(f"/api/v1/projects/{project_id}/sources", headers=alice_headers)
    ).json()["data"]
    (row,) = listed
    assert row["status"] == "connected" and row["last_synced_at"] is not None
    assert row["entity_count"] == 6  # 3 components + 3 nets
    assert "export" not in row["config"] and "board" not in row["config"]

    await patch_config(client, alice_headers, project_id, source["id"], {"export": "garbage"})
    await sync(client, alice_headers, project_id, source["id"])
    failed = await get_source(client, alice_headers, project_id, source["id"])
    assert failed["status"] == "error"
    assert set(failed["last_error"]) == {"code", "message"}  # an object, never a bare string
    assert failed["entity_count"] == 6  # the last good graph is kept visible

    await patch_config(client, alice_headers, project_id, source["id"], {"export": KICAD_XML})
    await sync(client, alice_headers, project_id, source["id"])
    healed = await get_source(client, alice_headers, project_id, source["id"])
    assert healed["status"] == "connected" and healed["last_error"] is None


async def test_the_integration_catalog_offers_kicad_with_its_two_design_inputs(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await new_project(client, alice_headers)
    resp = await client.get("/api/v1/integrations", headers=alice_headers)
    (entry,) = [c for c in resp.json()["data"] if c["type"] == "kicad"]
    assert entry["auth_kind"] == "none"  # no credential, so no Connected-accounts grant
    assert {"export", "board"} <= set(entry["config_fields"])


async def test_disconnecting_the_kicad_source_removes_its_graph_and_records_activity(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    project_id = await new_project(client, alice_headers)
    team_id = (await client.get(f"/api/v1/projects/{project_id}", headers=alice_headers)).json()[
        "data"
    ]["team_id"]
    source = await connect_kicad(client, alice_headers, project_id, export=KICAD_XML)
    await sync(client, alice_headers, project_id, source["id"])
    assert any(r.kind == "component" for r in (await entities_by_ref(maker, project_id)).values())

    resp = await client.delete(
        f"/api/v1/projects/{project_id}/sources/{source['id']}", headers=alice_headers
    )
    assert resp.status_code == 200, resp.text
    live = await entities_by_ref(maker, project_id)
    assert not [r for r in live.values() if r.kind in {"component", "net"}]

    feed = await client.get(f"/api/v1/teams/{team_id}/activity", headers=alice_headers)
    types = [a["type"] for a in feed.json()["data"]]
    for expected in ("source.connected", "source.sync_started", "source.disconnected"):
        assert expected in types
    assert types.index("source.disconnected") < types.index("source.connected")  # newest first


# ------------------------------------------------------------ data collection


async def _consent(db: AsyncSession, user_id: str, value: bool = True) -> None:
    await db.execute(
        update(User).where(User.id == uuid.UUID(user_id)).values(data_collection_consent=value)
    )
    await db.commit()


async def _events(db: AsyncSession, project_id: uuid.UUID) -> list[DataEvent]:
    rows = await db.scalars(
        select(DataEvent)
        .where(DataEvent.project_id == project_id)
        .order_by(DataEvent.created_at, DataEvent.id)
    )
    return list(rows.all())


async def test_consented_kicad_actions_emit_scoped_events_without_design_content(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from conftest import me

    user = await me(client, alice_headers)
    await _consent(db, user["id"])
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=NETLIST, board=KICAD_PCB)
    await sync(client, alice_headers, project_id, source["id"])

    events = [e for e in await _events(db, project_id) if e.event_type.startswith("source.")]
    assert [e.event_type for e in events] == ["source.connected", "source.sync_started"]
    connected, started = events
    assert connected.payload == {"type": "kicad"}
    assert started.payload == {"source_id": source["id"]}
    for event in events:
        assert str(event.user_id) == user["id"]
        assert event.project_id == project_id and event.team_id is not None
        blob = str(event.payload)
        assert "STM32" not in blob and "(export" not in blob and "<export" not in blob


async def test_kicad_actions_without_consent_store_no_events(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from conftest import me

    user = await me(client, alice_headers)
    await _consent(db, user["id"], False)
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=KICAD_XML)
    await sync(client, alice_headers, project_id, source["id"])
    assert [e for e in await _events(db, project_id) if e.event_type.startswith("source.")] == []


SYNC_OUTCOME_EVENTS = {"source.synced", "source.sync_completed", "source.sync_succeeded"}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN GAP (SOLUSDEV-312 audit): ADR-011 lists every sync as a meaningful event, but "
        "runtime._commit_success/_record_failure emit nothing — only source.sync_started exists. "
        "Needs an event-name decision from a human; flip this test when it lands."
    ),
)
async def test_a_finished_kicad_sync_emits_an_outcome_event(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from conftest import me

    user = await me(client, alice_headers)
    await _consent(db, user["id"])
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=KICAD_XML)
    await sync(client, alice_headers, project_id, source["id"])
    assert {e.event_type for e in await _events(db, project_id)} & SYNC_OUTCOME_EVENTS
