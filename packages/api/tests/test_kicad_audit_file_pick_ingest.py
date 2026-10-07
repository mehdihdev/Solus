"""KiCad acceptance criterion 3 (SOLUSDEV-312 audit): file-pick ingestion through
the real HTTP route.

Gaps this file closes (see docs/qa/KICAD_TEST_AUDIT.md):

* the four input shapes — XML netlist, default S-expression `.net`, `.kicad_pcb`
  alone, netlist + board together — all produce the SAME pin-level connectivity
  in the graph for the same design;
* netlist + board through the route: the netlist is authoritative, the board adds
  `layer`, board-only parts surface as `board/netlist mismatch` sync errors;
* a re-sync with CHANGED content diffs correctly (created / updated / deleted),
  not just the identical-content idempotent case;
* the server-side safety net: raw `.kicad_sch` / `.kicad_pro` and misrouted files
  FAIL the sync with a stable code and guidance, leave the prior graph intact and
  never half-parse.
"""

from __future__ import annotations

from typing import Any

import pytest
from fixtures.kicad_audit import (
    SAMPLE_CONNECTIVITY,
    Maker,
    connect_kicad,
    connect_kicad_config,
    connectivity,
    entities_by_ref,
    get_source,
    latest_sync,
    new_project,
    patch_config,
    sync,
)
from fixtures.kicad_project import SOLUS_SAMPLE_PRO, SOLUS_SAMPLE_SCH
from fixtures.kicad_sample import KICAD_PCB, KICAD_SEXPR, KICAD_XML
from httpx import AsyncClient
from solus_api.models import Domain
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

MISMATCH = "board/netlist mismatch: "


@pytest.fixture
def maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


# ----------------------------------------------- the four input shapes agree

INPUT_SHAPES: dict[str, dict[str, str]] = {
    "xml_netlist": {"export": KICAD_XML},
    "sexpr_netlist": {"export": KICAD_SEXPR},
    "board_alone": {"board": KICAD_PCB},
    "netlist_plus_board": {"export": KICAD_SEXPR, "board": KICAD_PCB},
}


@pytest.mark.parametrize("shape", list(INPUT_SHAPES))
async def test_every_input_shape_lands_the_same_pin_level_connectivity(
    shape: str, client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad_config(client, alice_headers, project_id, INPUT_SHAPES[shape])
    record = await sync(client, alice_headers, project_id, source["id"])
    assert record["status"] == "succeeded", record

    entities = await entities_by_ref(maker, project_id)
    components = {ref for ref, row in entities.items() if row.kind == "component"}
    nets = {ref for ref, row in entities.items() if row.kind == "net"}
    # The board adds parts the schematic never had; a netlist (alone or paired) must not.
    expected = {"U1", "R1", "C1"} | ({"H1", "FID1"} if shape == "board_alone" else set())
    assert components == expected
    assert nets == {"net:VCC", "net:GND", "net:SIGNAL"}
    assert all(entities[ref].domain is Domain.ELECTRICAL for ref in components | nets)
    # Same design -> identical (component, net) -> pins edges, whatever file(s) carried it.
    assert await connectivity(maker, project_id) == SAMPLE_CONNECTIVITY


async def test_source_status_reports_a_clean_connected_sync_for_each_shape(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await new_project(client, alice_headers)
    for shape in ("xml_netlist", "sexpr_netlist", "board_alone"):
        source = await connect_kicad_config(client, alice_headers, project_id, INPUT_SHAPES[shape])
        await sync(client, alice_headers, project_id, source["id"])
        detail = await get_source(client, alice_headers, project_id, source["id"])
        assert detail["status"] == "connected"
        assert detail["last_error"] is None
        assert detail["last_synced_at"] is not None


# --------------------------------------------- netlist + board reconciliation


async def test_netlist_plus_board_is_netlist_authoritative_with_board_layer_and_mismatches(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(
        client, alice_headers, project_id, export=KICAD_SEXPR, board=KICAD_PCB
    )
    record = await sync(client, alice_headers, project_id, source["id"])
    assert record["status"] == "succeeded"

    entities = await entities_by_ref(maker, project_id)
    assert (
        "H1" not in entities and "FID1" not in entities
    )  # board-only parts are reported, not added
    for refdes in ("U1", "R1", "C1"):
        assert entities[refdes].attrs.get("layer") in {"F.Cu", "B.Cu"}  # board adds `layer`
    assert entities["R1"].attrs["value"] == "10k"  # the netlist's identity, not the board's
    assert entities["R1"].modality_hints["part_number"] == "RC0603FR-0710KL"

    messages = [str(err.get("message", "")) for err in record["errors"]]
    flagged = " | ".join(messages)
    assert MISMATCH in flagged
    assert "H1" in flagged and "FID1" in flagged
    # Nothing else is flagged for the matching parts.
    assert not any(m.startswith(MISMATCH) and ("U1" in m or "C1" in m) for m in messages)


async def test_a_board_only_change_resyncs_and_surfaces_a_new_mismatch_without_touching_the_graph(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(
        client, alice_headers, project_id, export=KICAD_SEXPR, board=KICAD_PCB
    )
    first = await sync(client, alice_headers, project_id, source["id"])
    before = await entities_by_ref(maker, project_id)

    assert '(property "Value" "10k"' in KICAD_PCB
    changed_board = KICAD_PCB.replace('(property "Value" "10k"', '(property "Value" "22k"', 1)
    assert changed_board != KICAD_PCB
    await patch_config(
        client,
        alice_headers,
        project_id,
        source["id"],
        {"export": KICAD_SEXPR, "board": changed_board},
    )
    second = await sync(client, alice_headers, project_id, source["id"])
    assert second["id"] != first["id"]
    assert second["status"] == "succeeded"
    assert any(
        "R1" in str(err["message"]) and "22k" in str(err["message"]) for err in second["errors"]
    )

    after = await entities_by_ref(maker, project_id)
    assert after["R1"].id == before["R1"].id
    assert after["R1"].attrs["value"] == "10k"  # netlist wins over the board's 22k


# ----------------------------------------------------- re-sync diffs correctly


async def test_resync_with_changed_netlist_creates_updates_and_deletes_exactly_the_diff(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=KICAD_XML)
    first = await sync(client, alice_headers, project_id, source["id"])
    assert first["entities_created"] > 0
    before = await entities_by_ref(maker, project_id)
    assert {"U1", "R1", "C1"} <= set(before)

    # v2: R1 value 10k -> 22k (update), C1 removed with its two pins (delete + 2 relations),
    # new R9 on SIGNAL (create + 1 relation).
    v2 = KICAD_XML.replace("<value>10k</value>", "<value>22k</value>", 1)
    c1_start = v2.index('    <comp ref="C1">')
    c1_end = v2.index("</comp>", c1_start) + len("</comp>\n")
    v2 = (
        v2[:c1_start]
        + (
            '    <comp ref="R9">\n      <value>1k</value>\n'
            "      <footprint>Resistor_SMD:R_0603_1608Metric</footprint>\n"
            '      <libsource lib="Device" part="R"/>\n    </comp>\n'
        )
        + v2[c1_end:]
    )
    v2 = v2.replace('      <node ref="C1" pin="1" pintype="passive"/>\n', "")
    v2 = v2.replace('      <node ref="C1" pin="2" pintype="passive"/>\n', "")
    v2 = v2.replace(
        '      <node ref="R1" pin="2" pintype="passive"/>\n',
        '      <node ref="R1" pin="2" pintype="passive"/>\n'
        '      <node ref="R9" pin="1" pintype="passive"/>\n',
    )
    assert "C1" not in v2.split("<nets>")[1]
    await patch_config(client, alice_headers, project_id, source["id"], {"export": v2})

    second = await sync(client, alice_headers, project_id, source["id"])
    assert second["status"] == "succeeded", second
    assert second["entities_created"] == 1  # R9
    assert second["entities_updated"] >= 1  # R1's value
    assert second["relations_created"] == 1  # R9 -> SIGNAL
    assert second["relations_deleted"] == 2  # C1 -> VCC, C1 -> GND

    live = await entities_by_ref(maker, project_id)
    assert "R9" in live and "C1" not in live
    assert live["R1"].id == before["R1"].id  # identity is stable across the diff
    assert live["U1"].id == before["U1"].id
    gone = await entities_by_ref(maker, project_id, include_deleted=True)
    assert gone["C1"].deleted_at is not None  # soft-deleted, not hard-removed
    pins = await connectivity(maker, project_id)
    assert ("R9", "SIGNAL") in pins and ("C1", "VCC") not in pins and ("C1", "GND") not in pins
    assert pins[("U1", "VCC")] == ["8"]  # untouched edges survive


# ------------------------------- server-side refusal: the safety net, over HTTP

REFUSALS: list[tuple[str, dict[str, str], str, tuple[str, ...]]] = [
    (
        "schematic_as_export",
        {"export": SOLUS_SAMPLE_SCH.read_text()},
        "export_format_unsupported",
        ("netlist", ".kicad_pcb"),
    ),
    (
        "project_as_export",
        {"export": SOLUS_SAMPLE_PRO.read_text()},
        "export_format_unsupported",
        ("netlist", ".kicad_pcb"),
    ),
    (
        "schematic_as_board",
        {"export": KICAD_XML, "board": SOLUS_SAMPLE_SCH.read_text()},
        "export_format_unsupported",
        ("netlist", ".kicad_pcb"),
    ),
    (
        "board_as_export",
        {"export": KICAD_PCB},
        "export_format_unsupported",
        (".kicad_pcb", "board"),
    ),
    (
        "netlist_as_board",
        {"board": KICAD_SEXPR},
        "export_format_unsupported",
        ("netlist",),
    ),
    (
        "random_text",
        {"export": "hello, this is not a design file"},
        "export_format_unsupported",
        (),
    ),
]


@pytest.mark.parametrize(
    ("label", "config", "code", "hints"), REFUSALS, ids=[r[0] for r in REFUSALS]
)
async def test_misrouted_or_design_files_fail_the_sync_with_guidance_and_ingest_nothing(
    label: str,
    config: dict[str, str],
    code: str,
    hints: tuple[str, ...],
    client: AsyncClient,
    alice_headers: dict[str, str],
    maker: Maker,
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad_config(client, alice_headers, project_id, config)
    record = await sync(client, alice_headers, project_id, source["id"])

    assert record["status"] == "failed", record
    detail = await get_source(client, alice_headers, project_id, source["id"])
    assert detail["status"] == "error"
    assert detail["last_error"]["code"] == code  # `last_error` is {code, message}, never a string
    message = str(detail["last_error"]["message"])
    for hint in hints:
        assert hint in message
    # Refused outright: not one component or net from a half-parse.
    assert not [
        r
        for r, row in (await entities_by_ref(maker, project_id)).items()
        if row.kind in {"component", "net"}
    ]


async def test_missing_inputs_name_both_config_keys(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id)
    await sync(client, alice_headers, project_id, source["id"])
    error: dict[str, Any] = (await get_source(client, alice_headers, project_id, source["id"]))[
        "last_error"
    ]
    assert error["code"] == "export_unavailable"
    assert "export" in error["message"] and "board" in error["message"]


async def test_a_refused_resync_keeps_the_previous_good_graph_and_recovers_on_a_valid_file(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=KICAD_XML)
    await sync(client, alice_headers, project_id, source["id"])
    good = await entities_by_ref(maker, project_id)

    await patch_config(
        client, alice_headers, project_id, source["id"], {"export": SOLUS_SAMPLE_SCH.read_text()}
    )
    refused = await sync(client, alice_headers, project_id, source["id"])
    assert refused["status"] == "failed"
    still = await entities_by_ref(maker, project_id)
    assert {r: e.id for r, e in still.items()} == {r: e.id for r, e in good.items()}
    assert (await connectivity(maker, project_id)) == SAMPLE_CONNECTIVITY

    await patch_config(client, alice_headers, project_id, source["id"], {"export": KICAD_SEXPR})
    recovered = await sync(client, alice_headers, project_id, source["id"])
    assert recovered["status"] == "succeeded"
    detail = await get_source(client, alice_headers, project_id, source["id"])
    assert detail["status"] == "connected" and detail["last_error"] is None
    assert (await latest_sync(client, alice_headers, project_id, source["id"]))["id"] == recovered[
        "id"
    ]
