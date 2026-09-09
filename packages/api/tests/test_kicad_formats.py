"""KiCad content sniffing + refusal guidance tests (SOLUSDEV-252, W0-08 §5.2/§5.2a).

Format is detected from CONTENT, never from a file extension (there is none at
this layer). Raw `.kicad_sch` / `.kicad_pro` files are refused with guidance
naming both accepted routes: a netlist export in any format, or the board file.
"""

from __future__ import annotations

import pytest
from fixtures.kicad_sample import (
    KICAD_PCB,
    KICAD_PROJECT_HEAD,
    KICAD_SCHEMATIC_HEAD,
    KICAD_SEXPR,
    KICAD_XML,
)
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.kicad_formats import (
    ExpectedKind,
    KicadFormat,
    detect_kicad_format,
    refuse_unsupported,
)

# ------------------------------------------------------------- detection


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (KICAD_XML, "xml_netlist"),
        (KICAD_SEXPR, "sexpr_netlist"),
        (KICAD_PCB, "pcb"),
        (KICAD_SCHEMATIC_HEAD, "schematic"),
        (KICAD_PROJECT_HEAD, "project"),
        ('{"meta": {"filename": "x.kicad_pro"}}', "project"),
        ('{"kicad_pro": 1}', "project"),
        ('{"not": "kicad"}', "unknown"),
        ("", "unknown"),
        ("hello world", "unknown"),
        ("(kicad_symbol_lib (version 1))", "unknown"),
        ("(exporter 1)", "unknown"),
        ("(kicad_pcbx 1)", "unknown"),
        ("<html><body/></html>", "xml_netlist"),  # the XML parser validates the root
    ],
)
def test_detects_format_from_content(text: str, expected: str) -> None:
    assert detect_kicad_format(text) == expected


def test_detection_ignores_bom_and_leading_whitespace() -> None:
    assert detect_kicad_format("﻿ \r\n\t(export (version E))") == "sexpr_netlist"
    assert detect_kicad_format("﻿<export/>") == "xml_netlist"
    assert detect_kicad_format("\n\n(kicad_pcb (version 20241229))") == "pcb"
    assert detect_kicad_format('  {\n  "meta": {}}') == "project"


def test_project_hint_must_appear_within_the_first_4_kib() -> None:
    padding = '{"pad": "' + "x" * 5000 + '", '
    assert detect_kicad_format(padding + '"meta": {}}') == "unknown"


# ------------------------------------------------------------- refusal messages


def _refusal(fmt: KicadFormat, expected: ExpectedKind) -> ConnectorError:
    error = refuse_unsupported(fmt, expected=expected)
    assert isinstance(error, ConnectorError)
    assert error.code == "export_format_unsupported"
    assert str(error).startswith("kicad: ")
    return error


def test_schematic_refusal_names_both_routes() -> None:
    message = str(_refusal("schematic", "netlist"))
    assert ".kicad_sch" in message
    assert "kicad-cli sch export netlist" in message
    assert "File → Export → Netlist" in message
    assert ".kicad_pcb" in message
    assert _refusal("schematic", "board").message == message


def test_project_refusal_names_both_routes() -> None:
    message = str(_refusal("project", "netlist"))
    assert ".kicad_pro" in message
    assert "settings, not the design" in message
    assert "Export a netlist" in message
    assert ".kicad_pcb" in message
    assert _refusal("project", "board").message == message


def test_board_given_as_netlist_is_redirected() -> None:
    message = str(_refusal("pcb", "netlist"))
    assert "supply it as the board, not as the netlist export" in message


def test_netlist_given_as_board_is_redirected() -> None:
    for fmt in ("xml_netlist", "sexpr_netlist"):
        message = str(_refusal(fmt, "board"))
        assert "expected a .kicad_pcb board file but received a netlist" in message
        assert "supply it as the netlist export" in message


def test_unknown_content_refusal() -> None:
    message = str(_refusal("unknown", "netlist"))
    assert "unrecognized file" in message
    assert "XML or S-expression" in message
    assert ".kicad_pcb" in message
    assert _refusal("unknown", "board").message == message


# ------------------------------------------------------------- BOM (S6)


def test_bom_prefixed_sexpr_documents_parse_end_to_end() -> None:
    # SOLUSDEV-252 Phase 4 (S6): the sniffer ignores a UTF-8 BOM but the reader
    # saw it as content outside the root list — accepted by one, rejected by the
    # other. Both KiCad S-expression inputs must parse with a BOM.
    from solus_api.connectors.kicad_netlist import parse_kicad_netlist
    from solus_api.connectors.kicad_pcb import parse_kicad_pcb

    bom = "\ufeff"
    assert parse_kicad_netlist(bom + KICAD_SEXPR) == parse_kicad_netlist(KICAD_SEXPR)
    assert parse_kicad_pcb(bom + " \r\n" + KICAD_PCB) == parse_kicad_pcb(KICAD_PCB)
    assert len(parse_kicad_netlist(bom + KICAD_SEXPR).components) == 3
