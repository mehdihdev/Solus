"""Opt-in acceptance against actual installed symbols and KiCad, without hardware.

This exercises the owned operation layer on a disposable fixture, not the product
confirmation journey. Set SOLUS_TEST_INSTALLED_KICAD=1 to run the native checks.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest

from test_overlay_support import FORK  # isort: skip
from solus.development.erc import check_erc
from solus.development.models import DevelopmentError
from solus.development.schematic import (
    add_symbol,
    create_schematic,
    get_schematic_geometry,
    get_symbol_definition,
)
from solus.development.wiring import add_net_label, add_wire, mark_no_connect
from solus.netlist_export import _cli_export, export_netlist_impl


def test_export_cli_receives_absolute_confined_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    schematic = tmp_path / "relative.kicad_sch"
    schematic.write_text("(kicad_sch)")

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert Path(argv[-1]) == schematic
        Path(argv[-2]).write_bytes(b"<export/>")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    assert _cli_export("/fixed/cli", Path("relative.kicad_sch"), "relative") == b"<export/>"


@pytest.mark.parametrize("cli", [None, "/fixed/failing-cli", "/fixed/native-cli"])
@pytest.mark.parametrize("target_inside", [False, True])
def test_discovered_schematic_symlink_never_reaches_cli_or_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cli: str | None,
    target_inside: bool,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(root))
    project = root / "project.kicad_pro"
    project.write_text("{}")
    target = (root if target_inside else tmp_path) / "other.kicad_sch"
    target.write_text("(kicad_sch)")
    sibling = project.with_suffix(".kicad_sch")
    sibling.symlink_to(target)
    monkeypatch.setattr("solus.netlist_export._find_schematic", lambda project: sibling)
    monkeypatch.setattr("solus.netlist_export.detect_kicad_cli", lambda: cli)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("unconfined discovered schematic reached an export/parser sink")

    monkeypatch.setattr("solus.netlist_export._cli_export", forbidden)
    monkeypatch.setattr("solus.netlist_export._parse_netlist", forbidden)
    with pytest.raises(DevelopmentError, match="path_escapes_workspace"):
        export_netlist_impl(str(project))


def test_cli_failure_cannot_swap_schematic_for_external_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(root))
    project = root / "project.kicad_pro"
    project.write_text("{}")
    schematic = project.with_suffix(".kicad_sch")
    schematic.write_text("(kicad_sch)")
    target = tmp_path / "external.kicad_sch"
    target.write_text("(kicad_sch)")
    monkeypatch.setattr("solus.netlist_export._find_schematic", lambda project: schematic)
    monkeypatch.setattr("solus.netlist_export.detect_kicad_cli", lambda: "/fixed/cli")

    def fail_and_swap(*args: Any) -> None:
        schematic.unlink()
        schematic.symlink_to(target)

    def parse_captured(path: str) -> dict[str, Any]:
        assert Path(path) != schematic
        assert Path(path).read_text() == "(kicad_sch)"
        return {"components": {}, "nets": {}}

    monkeypatch.setattr("solus.netlist_export._cli_export", fail_and_swap)
    monkeypatch.setattr("solus.netlist_export._parse_netlist", parse_captured)
    assert export_netlist_impl(str(project))["degraded"] is True


def build_divider(root: Path) -> dict[str, Any]:
    """Use real library pins; the FSR is an explicitly generic two-pin resistor."""
    name = "uno_fsr_divider.kicad_sch"
    result = create_schematic(name, "Uno A0 - FSR402 generic resistive model", True)
    for library, reference, value, x, y in [
        ("MCU_Module:Arduino_UNO_R3", "A1", "Arduino_UNO_R3", 63.5, 76.2),
        ("Device:R_Variable", "RFSR1", "FSR402 (generic resistive model)", 114.3, 60.96),
        ("Device:R", "R1", "10k", 114.3, 83.82),
        ("power:PWR_FLAG", "FLG1", "USB supply ground assumption", 127, 111.76),
    ]:
        definition = get_symbol_definition(library)
        args = dict(
            schematic_path=name,
            expected_fingerprint=result["after_fingerprint"],
            library_id=library,
            library_fingerprint=definition["library_fingerprint"],
            reference=reference,
            value=value,
            at={"x_mm": x, "y_mm": y},
            rotation_deg=0,
        )
        before = (root / name).read_bytes()
        preview = add_symbol(**args, dry_run=True)
        assert (root / name).read_bytes() == before
        result = add_symbol(**args)
        assert result["after_fingerprint"] == preview["after_fingerprint"]
    result = add_wire(
        name,
        result["after_fingerprint"],
        {"pin": {"reference": "RFSR1", "pin_number": "2"}},
        {"pin": {"reference": "R1", "pin_number": "1"}},
    )
    for start, end in [("29", "6"), ("6", "7")]:
        result = add_wire(
            name,
            result["after_fingerprint"],
            {"pin": {"reference": "A1", "pin_number": start}},
            {"pin": {"reference": "A1", "pin_number": end}},
        )
    for label, ref, pin in [
        ("SENSE_A0", "RFSR1", "2"),
        ("SENSE_A0", "A1", "9"),
        ("+5V", "A1", "5"),
        ("+5V", "RFSR1", "1"),
        ("GND", "R1", "2"),
        ("GND", "A1", "29"),
        ("GND", "FLG1", "1"),
    ]:
        result = add_net_label(
            name,
            result["after_fingerprint"],
            label,
            {"pin": {"reference": ref, "pin_number": pin}},
            180 if label == "GND" and ref != "R1" else 0,
        )
    board = get_schematic_geometry(name, "A1")["symbols"][0]
    for pin in board["pins"]:
        if pin["number"] not in {"1", "5", "6", "7", "9", "29"}:
            result = mark_no_connect(
                name,
                result["after_fingerprint"],
                {"reference": "A1", "pin_number": pin["number"]},
            )
    return result


@pytest.mark.skipif(
    os.environ.get("SOLUS_TEST_INSTALLED_KICAD") != "1",
    reason="requires opt-in installed KiCad and symbol libraries",
)
def test_installed_uno_fsr_divider_has_verified_nets_and_clean_erc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = FORK.parents[2] / "tmp/integration-check-kicad"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="divider-acceptance-", dir=scratch) as directory:
        root = Path(directory)
        monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(root))
        monkeypatch.chdir(root)
        build_divider(root)
        (root / "uno_fsr_divider.kicad_pro").write_text("{}\n")
        exported_result = export_netlist_impl("uno_fsr_divider.kicad_pro")
        assert not exported_result["degraded"], exported_result["reason"]
        raw = exported_result["content"]
        assert isinstance(raw, str), "small native fixture export must be inline"
        exported = ElementTree.fromstring(raw)  # noqa: S314 — owned native CLI fixture output
        nets = {
            net.attrib["name"]: {(node.attrib["ref"], node.attrib["pin"]) for node in net}
            for net in exported.findall("nets/net")
        }
        assert nets["/SENSE_A0"] == {("A1", "9"), ("RFSR1", "2"), ("R1", "1")}
        assert nets["/+5V"] == {("A1", "5"), ("RFSR1", "1")}
        assert nets["/GND"] == {("A1", "6"), ("A1", "7"), ("A1", "29"), ("R1", "2"), ("FLG1", "1")}
        result = check_erc("uno_fsr_divider.kicad_sch")
        assert result["checked"] and result["passed"], json.dumps(result)
