"""KiCad acceptance criterion 4 (SOLUSDEV-312 audit): hostile input through the
real HTTP route, per docs/qa/COWORK_QA_kicad-natural-ingestion.md Flows 6 / 6a.

The parser-level guards already have unit coverage (test_kicad_sexpr / _netlist /
_pcb). What was missing is the END-TO-END claim the QA plan makes: whatever a
user (or a compromised export) feeds the route, the sync reaches a TERMINAL state
with a stable, bounded `{code, message}`, the API keeps serving, nothing hostile
is echoed back or stored, and the very next valid sync recovers.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fixtures.kicad_audit import (
    Maker,
    connect_kicad,
    connect_kicad_config,
    entities_by_ref,
    get_source,
    new_project,
    patch_config,
    sync,
)
from fixtures.kicad_project import SOLUS_SAMPLE_LARGE_NETLIST
from fixtures.kicad_sample import KICAD_PCB, KICAD_SEXPR, KICAD_XML
from httpx import AsyncClient
from solus_api.connectors.eda import MAX_EXPORT_BYTES
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

#: A persisted `last_error` message is clipped well below this (runtime.py bounds).
MESSAGE_BOUND = 600
INVALID = "export_invalid"


@pytest.fixture
def maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _assert_alive_and_recovers(
    client: AsyncClient, headers: dict[str, str], project_id: Any, source_id: str
) -> None:
    """The API still serves reads, and a valid file syncs on the SAME source."""
    listed = await client.get(f"/api/v1/projects/{project_id}/sources", headers=headers)
    assert listed.status_code == 200
    # PATCH merges config keys, so a board-borne failure is cleared by a valid pair.
    valid = {"export": KICAD_SEXPR, "board": KICAD_PCB}
    await patch_config(client, headers, project_id, source_id, valid)
    record = await sync(client, headers, project_id, source_id)
    assert record["status"] == "succeeded", record
    detail = await get_source(client, headers, project_id, source_id)
    assert detail["status"] == "connected" and detail["last_error"] is None


# --------------------------------------------------------- refused cleanly

REFUSED: list[tuple[str, dict[str, str], str]] = [
    # deep nesting (200 000 levels, open and balanced) -> the iterative reader's depth guard
    ("deep_nesting_open", {"export": "(export " + "(" * 200_000}, "nesting"),
    (
        "deep_nesting_balanced",
        {"export": "(export " + "(" * 200_000 + ")" * 200_000 + ")"},
        "nesting",
    ),
    ("deep_nesting_board", {"board": "(kicad_pcb " + "(" * 200_000}, "nesting"),
    # control characters: refused before they can reach Postgres (NUL) or a log line
    ("nul_in_sexpr", {"export": '(export (components (comp (ref "U\x00"))))'}, "control character"),
    (
        "c0_in_board",
        {"board": '(kicad_pcb (footprint "x" (property "Reference" "U\x1b1")))'},
        "control character",
    ),
    (
        "nul_in_xml",
        {"export": '<export><components><comp ref="U\x00"/></components></export>'},
        "XML",
    ),
    (
        "nul_charref_in_xml",
        {"export": '<export><components><comp ref="U&#0;"/></components></export>'},
        "XML",
    ),
    # DTD / entity tricks: refused before the parser can expand anything
    (
        "billion_laughs",
        {
            "export": '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
            '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
            '<export><components><comp ref="&lol2;"/></components></export>'
        },
        "DTD",
    ),
    (
        "external_entity_file",
        {
            "export": '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]>'
            '<export><components><comp ref="&a;"/></components></export>'
        },
        "DTD",
    ),
    (
        "parameter_entity_ssrf",
        {"export": '<!DOCTYPE x [<!ENTITY % p SYSTEM "http://127.0.0.1:1/x"> %p;]><export/>'},
        "DTD",
    ),
    ("entity_decl_without_doctype", {"export": '<!ENTITY a "b"><export/>'}, "DTD"),
    # plain malformed / wrong shape
    (
        "unterminated_sexpr",
        {"export": '(export (version "E") (components (comp (ref "U1"'},
        "unterminated",
    ),
    ("truncated_xml", {"export": KICAD_XML[:300]}, "XML"),
    ("wrong_xml_root", {"export": "<html><body/></html>"}, "expected <export>"),
    # 250k tiny components: bytes are legal (<8 MiB) but the node-count guard trips
    (
        "node_count_bomb",
        {"export": "(export (components " + '(comp (ref "U1") (value "x"))' * 250_000 + "))"},
        "node count",
    ),
]


@pytest.mark.parametrize(("label", "config", "needle"), REFUSED, ids=[r[0] for r in REFUSED])
async def test_hostile_input_fails_the_sync_cleanly_and_the_api_recovers(
    label: str,
    config: dict[str, str],
    needle: str,
    client: AsyncClient,
    alice_headers: dict[str, str],
    maker: Maker,
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad_config(client, alice_headers, project_id, config)

    started = time.monotonic()
    record = await sync(client, alice_headers, project_id, source["id"])
    assert time.monotonic() - started < 30  # never a hang

    assert record["status"] == "failed", record  # terminal, not stuck RUNNING
    detail = await get_source(client, alice_headers, project_id, source["id"])
    assert detail["status"] == "error"  # not stuck SYNCING (which would 409 every retry)
    error = detail["last_error"]
    assert error["code"] == INVALID
    assert needle in error["message"]
    assert len(error["message"]) <= MESSAGE_BOUND
    # The hostile text is neither echoed into the record nor half-ingested.
    assert len(str(record["errors"])) < 2_000
    assert "passwd" not in str(record) + str(detail)
    live = await entities_by_ref(maker, project_id)
    assert not [ref for ref, row in live.items() if row.kind in {"component", "net"}]

    await _assert_alive_and_recovers(client, alice_headers, project_id, source["id"])


# --------------------------------------------------- accepted, but inert/bounded


async def test_a_doctype_literal_inside_an_sexpr_value_is_data_not_a_dtd(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    """The DTD refusal is an XML-parser guard; the same bytes inside an S-expression
    string are just text and must not be refused (no false positive)."""
    project_id = await new_project(client, alice_headers)
    text = KICAD_SEXPR.replace(
        '(field (name "Tolerance") "n/a")', '(field (name "Tolerance") "<!DOCTYPE x>")'
    )
    assert "<!DOCTYPE" in text
    source = await connect_kicad(client, alice_headers, project_id, export=text)
    assert (await sync(client, alice_headers, project_id, source["id"]))["status"] == "succeeded"
    attrs = (await entities_by_ref(maker, project_id))["U1"].attrs
    assert "<!DOCTYPE x>" in str(attrs)  # landed as an inert value


async def test_deeply_nested_xml_is_scoped_out_not_a_crash(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    """200k nested elements under `<export>` sit outside every documented position, so
    the scoped traversal never walks them: a clean, empty sync."""
    project_id = await new_project(client, alice_headers)
    text = "<export>" + "<a>" * 200_000 + "</a>" * 200_000 + "</export>"
    source = await connect_kicad(client, alice_headers, project_id, export=text)
    assert (await sync(client, alice_headers, project_id, source["id"]))["status"] == "succeeded"
    live = await entities_by_ref(maker, project_id)
    assert not [r for r, row in live.items() if row.kind in {"component", "net"}]


async def test_a_seven_mib_repeated_component_syncs_in_bounded_time(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    """Flow 6.2: ~7 MiB made of one component repeated syncs in seconds (duplicate
    refdes collapse to one entity) and stays under the 8 MiB byte cap."""
    one = (
        '(comp (ref "U1") (value "x") (footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm") '
        '(datasheet "https://example.test/a-fairly-long-datasheet-url.pdf") '
        '(libsource (lib "Device") (part "R")))'
    )
    count = (7 * 1024 * 1024) // len(one)
    text = "(export (components " + one * count + "))"
    assert 6 * 1024 * 1024 < len(text) <= MAX_EXPORT_BYTES
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=text)
    started = time.monotonic()
    record = await sync(client, alice_headers, project_id, source["id"])
    assert time.monotonic() - started < 60
    assert record["status"] == "succeeded", record
    live = await entities_by_ref(maker, project_id)
    assert [r for r, row in live.items() if row.kind == "component"] == ["U1"]


async def test_a_hundred_kb_net_name_is_stored_without_flooding_the_sync_record(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await new_project(client, alice_headers)
    text = KICAD_XML.replace('name="VCC"', 'name="' + "N" * 100_000 + '"')
    source = await connect_kicad(client, alice_headers, project_id, export=text)
    record = await sync(client, alice_headers, project_id, source["id"])
    assert record["status"] == "succeeded"
    assert len(str(record)) < 70_000  # the response, not the ingest, is what stays bounded


async def test_a_hostile_board_cannot_flood_the_sync_record(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Flow 6a.5: a 70 KB `Value` on a footprint that disagrees with the netlist is
    reported as a mismatch, but the message is clipped and the sync stays small."""
    project_id = await new_project(client, alice_headers)
    assert '(property "Value" "10k"' in KICAD_PCB
    board = KICAD_PCB.replace(
        '(property "Value" "10k"', '(property "Value" "' + "A" * 70_000 + '"', 1
    )
    source = await connect_kicad(client, alice_headers, project_id, export=KICAD_SEXPR, board=board)
    record = await sync(client, alice_headers, project_id, source["id"])
    assert record["status"] == "succeeded"
    mismatches = [e for e in record["errors"] if "R1" in e["message"] and "differs" in e["message"]]
    assert mismatches, record["errors"]
    assert all(len(e["message"]) <= 512 for e in record["errors"])
    assert "…" in mismatches[0]["message"]  # the ingested value was clipped before interpolation
    assert len(str(record["errors"])) < 70_000


async def test_components_smuggled_inside_pruned_board_regions_never_become_entities(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    smuggled = (
        '  (zone (net 1) (footprint "Evil:Z" (property "Reference" "ZONEEVIL")))\n'
        "  (segment (start 0 0) (end 1 1) (net 1) "
        '(footprint "Evil:S" (property "Reference" "SEGEVIL")))\n'
        '  (via (at 1 1) (net 1) (footprint "Evil:V" (property "Reference" "VIAEVIL")))\n'
    )
    board = KICAD_PCB.rstrip()
    assert board.endswith(")")
    board = board[:-1] + smuggled + ")"
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, board=board)
    assert (await sync(client, alice_headers, project_id, source["id"]))["status"] == "succeeded"
    refs = set(await entities_by_ref(maker, project_id))
    assert not {"ZONEEVIL", "SEGEVIL", "VIAEVIL"} & refs
    assert {"U1", "R1", "C1"} <= refs


# ------------------------------------------------------------- size boundary


@pytest.mark.parametrize("key", ["export", "board"])
async def test_an_over_cap_file_is_a_422_at_the_boundary_and_nothing_is_stored(
    key: str, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id = await new_project(client, alice_headers)
    prefix = "(export " if key == "export" else "(kicad_pcb "
    too_big = prefix + "x" * MAX_EXPORT_BYTES + ")"
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "kicad", "name": "big", "config": {key: too_big}},
        headers=alice_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "validation_error"
    assert "x" * 100 not in resp.text  # the payload is not reflected back
    listed = await client.get(f"/api/v1/projects/{project_id}/sources", headers=alice_headers)
    assert listed.json()["data"] == []


async def test_a_multibyte_export_is_measured_in_bytes_not_characters(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """3-byte characters: under the cap in characters, over it in bytes."""
    project_id = await new_project(client, alice_headers)
    chars = MAX_EXPORT_BYTES // 3 + 10
    assert chars < MAX_EXPORT_BYTES
    text = "(export " + "€" * chars + ")"
    resp = await client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"type": "kicad", "name": "mb", "config": {"export": text}},
        headers=alice_headers,
    )
    assert resp.status_code == 422, resp.text


# ------------------------------------------------------------ large fixture


async def test_the_1001_part_fixture_syncs_cleanly_and_a_resync_is_a_noop(
    client: AsyncClient, alice_headers: dict[str, str], maker: Maker
) -> None:
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(
        client, alice_headers, project_id, export=SOLUS_SAMPLE_LARGE_NETLIST.read_text()
    )
    started = time.monotonic()
    first = await sync(client, alice_headers, project_id, source["id"])
    assert time.monotonic() - started < 60
    assert first["status"] == "succeeded"
    assert first["errors"] == []  # the fixture is warning-free by contract
    live = await entities_by_ref(maker, project_id)
    assert len([r for r, row in live.items() if row.kind == "component"]) == 1001

    second = await sync(client, alice_headers, project_id, source["id"])
    assert second["status"] == "succeeded"
    assert (second["entities_created"], second["entities_updated"]) == (0, 0)
    assert (second["relations_created"], second["relations_deleted"]) == (0, 0)
