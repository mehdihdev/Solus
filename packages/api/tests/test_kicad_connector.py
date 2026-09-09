"""KiCad connector tests (SOLUSDEV-100 / SOLUSDEV-252, SOLUS-EDA-01).

The connector ingests a committed KiCad netlist in EITHER format (XML or the
default S-expression, content-detected — W0-08 §5.2) on `config["export"]`
and/or a `.kicad_pcb` board on `config["board"]` (§5.2a), into the shared
electrical graph shape (components + first-class nets + `connected_to` edges),
mirroring the EDA family exactly as Altium does. Raw schematics are refused
with guidance. Proves the fingerprint channels the ticket names (MPN/value →
FP-01) actually flow, the cross-format identity invariant, netlist/board
reconciliation through `sync`, and runs the package conformance suite.
Pure unit — no DB, no network.
"""

from __future__ import annotations

import pytest
from fixtures.kicad_sample import KICAD_PCB, KICAD_SCHEMATIC_HEAD, KICAD_SEXPR, KICAD_XML
from solus_api.connectors import assert_connector_contract
from solus_api.connectors.contracts import (
    AuthKind,
    ConnectorError,
    Credentials,
    Domain,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.kicad import KicadConnector


def _ctx(
    export: str | None = KICAD_XML,
    *,
    board: str | None = None,
    cursor: dict[str, str] | None = None,
) -> SyncContext:
    config = {key: text for key, text in (("export", export), ("board", board)) if text}
    return SyncContext(credentials=Credentials(token="unused"), config=config, cursor=cursor or {})


def _keys_by_type(result: SyncResult) -> dict[str, set[str]]:
    by_type: dict[str, set[str]] = {}
    for entity in result.entities:
        by_type.setdefault(entity.type, set()).add(entity.source_key)
    return by_type


def test_provider_metadata() -> None:
    connector = KicadConnector()
    assert connector.provider == "kicad"
    # A committed export carries no tool credential of its own.
    assert connector.auth_kind is AuthKind.NONE
    assert connector.supports_token_connect is False
    # The netlist export and the board file are the two design inputs (§5.2/§5.2a).
    assert connector.config_fields == ("export", "board")


async def test_sync_maps_components_nets_and_connectivity() -> None:
    result = await KicadConnector().sync(_ctx())
    by_type = _keys_by_type(result)
    assert by_type["component"] == {"U1", "R1", "C1"}
    assert by_type["net"] == {"net:VCC", "net:GND", "net:SIGNAL"}

    # Every entity is electrical; every relation is an intra-source connected_to.
    assert all(e.domain is Domain.ELECTRICAL for e in result.entities)
    vcc = {r.from_key for r in result.relations if r.to_key == "net:VCC"}
    assert vcc == {"U1", "C1"}
    edge = next(r for r in result.relations if r.to_key == "net:VCC" and r.from_key == "U1")
    assert edge.type == "connected_to"
    assert edge.properties == {"net": "VCC", "pins": ["8"]}


async def test_sync_carries_the_fingerprint_channels() -> None:
    # The ticket's acceptance: MPN/value flow so FP-01 can match (W0-08 §5.2).
    result = await KicadConnector().sync(_ctx())
    components = {e.source_key: e for e in result.entities if e.type == "component"}
    u1 = components["U1"]
    assert u1.modality_hints["part_number"] == "LM358DR"
    assert u1.modality_hints["schematic_symbol_name"] == "LM358"
    assert u1.modality_hints["datasheet_ref"] == "https://www.ti.com/lit/ds/symlink/lm358.pdf"
    assert u1.properties["value"] == "LM358"
    # R1's MPN arrives via a <property> alias; C1 has none — absent, not empty.
    assert components["R1"].modality_hints["part_number"] == "RC0603FR-0710KL"
    assert "part_number" not in components["C1"].modality_hints


async def test_passes_connector_conformance_suite() -> None:
    result = await assert_connector_contract(KicadConnector(), _ctx())
    assert result.entities  # produced a graph


async def test_detect_changes_tracks_the_export_content() -> None:
    connector = KicadConnector()
    first = await connector.sync(_ctx())
    assert await connector.detect_changes(_ctx(cursor=first.cursor)) is False
    edited = _ctx(KICAD_XML.replace("10k", "22k"), cursor=first.cursor)
    assert await connector.detect_changes(edited) is True


async def test_validate_credentials_reports_synthetic_identity() -> None:
    account = await KicadConnector().validate_credentials(Credentials(token="x"))
    assert account.login == "kicad-export"


# ------------------------------------------------------------- formats (§5.2)


async def test_sexpr_export_syncs_to_the_same_graph_as_xml() -> None:
    # Both netlist formats are first-class equals: the acquisition-path identity
    # invariant (§2.1 invariant 2) now also holds ACROSS formats — same design,
    # same entities, same relations, same errors.
    via_xml = await KicadConnector().sync(_ctx(KICAD_XML))
    via_sexpr = await KicadConnector().sync(_ctx(KICAD_SEXPR))
    assert via_sexpr.entities == via_xml.entities
    assert via_sexpr.relations == via_xml.relations
    assert via_sexpr.errors == via_xml.errors == []


async def test_schematic_in_export_is_refused_naming_both_routes() -> None:
    with pytest.raises(ConnectorError) as excinfo:
        await KicadConnector().sync(_ctx(KICAD_SCHEMATIC_HEAD))
    assert excinfo.value.code == "export_format_unsupported"
    assert "Export a netlist" in excinfo.value.message
    assert ".kicad_pcb" in excinfo.value.message


async def test_board_in_export_is_redirected_to_the_board_key() -> None:
    with pytest.raises(ConnectorError) as excinfo:
        await KicadConnector().sync(_ctx(KICAD_PCB))
    assert excinfo.value.code == "export_format_unsupported"
    assert "supply it as the board" in excinfo.value.message


async def test_netlist_in_board_is_redirected_to_the_export_key() -> None:
    with pytest.raises(ConnectorError) as excinfo:
        await KicadConnector().sync(_ctx(None, board=KICAD_XML))
    assert excinfo.value.code == "export_format_unsupported"
    assert "supply it as the netlist export" in excinfo.value.message


# ------------------------------------------------------------ board (§5.2a)


async def test_board_only_sync_uses_the_board_as_the_connectivity_source() -> None:
    result = await KicadConnector().sync(_ctx(None, board=KICAD_PCB))
    by_type = _keys_by_type(result)
    # The board-only mounting hole and fiducial land as components…
    assert by_type["component"] == {"U1", "R1", "C1", "H1", "FID1"}
    assert by_type["net"] == {"net:VCC", "net:GND", "net:SIGNAL"}
    # …with no connectivity of their own.
    assert not any(r.from_key in {"H1", "FID1"} for r in result.relations)
    assert {r.from_key for r in result.relations if r.to_key == "net:SIGNAL"} == {"U1", "R1"}
    # A board carries no libsource: the hint is absent by design, never guessed.
    components = [e for e in result.entities if e.type == "component"]
    assert all("schematic_symbol_name" not in e.modality_hints for e in components)
    u1 = next(e for e in components if e.source_key == "U1")
    assert u1.modality_hints["part_number"] == "LM358DR"
    assert u1.properties["layer"] == "F.Cu"
    # The board parser's own leniency note (the reference-less logo) is surfaced.
    assert any("without a reference designator" in e.message for e in result.errors)


async def test_both_inputs_merge_with_the_netlist_authoritative() -> None:
    board = KICAD_PCB.replace('(property "Value" "10k"', '(property "Value" "22k"')
    result = await KicadConnector().sync(_ctx(KICAD_XML, board=board))
    by_type = _keys_by_type(result)
    # Netlist identity: H1/FID1 are reported, not added; R1 keeps the netlist value.
    assert by_type["component"] == {"U1", "R1", "C1"}
    components = {e.source_key: e for e in result.entities if e.type == "component"}
    assert components["R1"].properties["value"] == "10k"
    assert components["R1"].properties["layer"] == "F.Cu"
    assert components["U1"].modality_hints["schematic_symbol_name"] == "LM358"
    # Every disagreement is a per-item SyncError on the sync record (§5.2a).
    messages = {e.message for e in result.errors}
    assert "board/netlist mismatch: H1: placed on board but not in netlist" in messages
    assert "board/netlist mismatch: FID1: placed on board but not in netlist" in messages
    assert "board/netlist mismatch: R1: value differs (netlist '10k', board '22k')" in messages
    # Items are labeled with the refdes/net (the parser prefix is `parse`).
    labels = {e.item for e in result.errors}
    assert {"H1", "FID1", "R1"} <= labels


async def test_neither_input_is_a_clear_error_naming_both_keys() -> None:
    with pytest.raises(ConnectorError) as excinfo:
        await KicadConnector().sync(_ctx(None))
    assert excinfo.value.code == "export_unavailable"
    assert "config['export']" in excinfo.value.message
    assert "config['board']" in excinfo.value.message


async def test_oversized_board_is_refused() -> None:
    from solus_api.connectors.eda import MAX_EXPORT_BYTES

    huge = "(kicad_pcb " + "x" * MAX_EXPORT_BYTES + ")"
    with pytest.raises(ConnectorError) as excinfo:
        await KicadConnector().sync(_ctx(KICAD_XML, board=huge))
    assert excinfo.value.code == "export_too_large"


async def test_non_text_board_is_refused() -> None:
    ctx = SyncContext(credentials=Credentials(token="x"), config={"export": KICAD_XML, "board": 42})
    with pytest.raises(ConnectorError) as excinfo:
        await KicadConnector().sync(ctx)
    assert excinfo.value.code == "export_invalid"


async def test_detect_changes_covers_both_files() -> None:
    connector = KicadConnector()
    first = await connector.sync(_ctx(KICAD_XML, board=KICAD_PCB))
    assert await connector.detect_changes(
        _ctx(KICAD_XML, board=KICAD_PCB, cursor=first.cursor)
    ) is (False)
    # Only the board changed → a sync is due (§5.2a: the hash covers both files).
    moved = KICAD_PCB.replace('(layer "B.Cu")', '(layer "F.Cu")')
    assert await connector.detect_changes(_ctx(KICAD_XML, board=moved, cursor=first.cursor)) is True
    # Dropping the board is a change too; an unreadable input is a safe True.
    assert await connector.detect_changes(_ctx(KICAD_XML, cursor=first.cursor)) is True
    assert await connector.detect_changes(_ctx(None, cursor=first.cursor)) is True


async def test_board_only_cursor_differs_from_netlist_only_cursor() -> None:
    connector = KicadConnector()
    netlist_only = await connector.sync(_ctx(KICAD_XML))
    board_only = await connector.sync(_ctx(None, board=KICAD_PCB))
    assert netlist_only.cursor.keys() == {"content_sha"}
    assert netlist_only.cursor["content_sha"] != board_only.cursor["content_sha"]
