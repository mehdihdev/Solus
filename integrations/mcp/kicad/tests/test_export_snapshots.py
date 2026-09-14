"""Native and degraded exports consume captured bytes, never mutable source paths."""

import stat
from pathlib import Path
from typing import Any

import pytest

from test_overlay_support import SOLUS  # noqa: F401  # isort: skip
from solus import netlist_export
from solus.development.models import DevelopmentError


@pytest.mark.parametrize("mode", ["absent", "native", "failed"])
def test_post_read_source_replacement_cannot_redirect_either_export_sink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    project = root / "root.kicad_pro"
    project.write_text("{}")
    schematic = project.with_suffix(".kicad_sch")
    verified = b'(kicad_sch (version 20250114) (generator "verified"))'
    schematic.write_bytes(verified)
    external = tmp_path / "external.kicad_sch"
    external.write_text('(kicad_sch (generator "external"))')
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(root))
    monkeypatch.setattr(netlist_export, "_find_schematic", lambda project: schematic)
    original_read = netlist_export.read_schematic
    reads = 0

    def read_then_swap(workspace: Path, relative: str) -> bytes:
        nonlocal reads
        data = original_read(workspace, relative)
        reads += 1
        schematic.unlink()
        schematic.symlink_to(external)
        return data

    monkeypatch.setattr(netlist_export, "read_schematic", read_then_swap)
    monkeypatch.setattr(
        netlist_export, "detect_kicad_cli", lambda: None if mode == "absent" else "/fixed/cli"
    )
    paths = []

    def inspect(path: str | Path) -> None:
        candidate = Path(path)
        assert candidate != schematic
        assert not candidate.is_relative_to(root)
        assert candidate.read_bytes() == verified
        assert stat.S_IMODE(candidate.parent.stat().st_mode) & 0o077 == 0
        paths.append(candidate)

    def cli(binary: str, path: Path, filename: str) -> bytes | None:
        inspect(path)
        return b"<export/>" if mode == "native" else None

    def parse(path: str) -> dict[str, Any]:
        inspect(path)
        return {"components": {}, "nets": {}}

    monkeypatch.setattr(netlist_export, "_cli_export", cli)
    monkeypatch.setattr(netlist_export, "_parse_netlist", parse)
    result = netlist_export.export_netlist_impl(str(project))
    assert result["degraded"] is (mode != "native")
    assert reads == 1
    assert paths and all(not path.exists() for path in paths)


def test_relative_hierarchical_sheets_keep_layout_in_verified_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    (root / "nested").mkdir(parents=True)
    (root / "common").mkdir()
    project = root / "nested/root.kicad_pro"
    project.write_text("{}")
    schematic = project.with_suffix(".kicad_sch")
    schematic.write_text('(kicad_sch (sheet (property "Sheetfile" "../common/child.kicad_sch")))')
    child = root / "common/child.kicad_sch"
    child.write_text('(kicad_sch (generator "child"))')
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(root))
    monkeypatch.setattr(netlist_export, "_find_schematic", lambda project: schematic)
    monkeypatch.setattr(netlist_export, "detect_kicad_cli", lambda: "/fixed/cli")

    def cli(binary: str, path: Path, filename: str) -> bytes:
        assert path != schematic
        assert path.read_bytes() == schematic.read_bytes()
        snapshot_child = path.parent / "../common/child.kicad_sch"
        assert snapshot_child.read_bytes() == child.read_bytes()
        assert snapshot_child.resolve() != child
        return b"<export/>"

    monkeypatch.setattr(netlist_export, "_cli_export", cli)
    assert not netlist_export.export_netlist_impl(str(project))["degraded"]


@pytest.mark.parametrize(
    "reference",
    ["../outside.kicad_sch", "/outside.kicad_sch", "${KIPRJMOD}/child.kicad_sch", "root.kicad_sch"],
)
def test_unconfined_or_cyclic_sheet_reference_never_reaches_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference: str,
) -> None:
    project = tmp_path / "root.kicad_pro"
    project.write_text("{}")
    schematic = project.with_suffix(".kicad_sch")
    schematic.write_text(f'(kicad_sch (sheet (property "Sheetfile" "{reference}")))')
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(netlist_export, "_find_schematic", lambda project: schematic)
    monkeypatch.setattr(netlist_export, "detect_kicad_cli", lambda: "/fixed/cli")

    def forbidden(*args: Any) -> Any:
        pytest.fail("unverified hierarchy reached the CLI")

    monkeypatch.setattr(netlist_export, "_cli_export", forbidden)
    with pytest.raises(DevelopmentError):
        netlist_export.export_netlist_impl(str(project))


@pytest.mark.parametrize("limit", ["_MAX_SNAPSHOT_BYTES", "_MAX_SNAPSHOT_SHEETS"])
def test_snapshot_closure_limits_refuse_before_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit: str,
) -> None:
    project = tmp_path / "root.kicad_pro"
    project.write_text("{}")
    schematic = project.with_suffix(".kicad_sch")
    schematic.write_text('(kicad_sch (sheet (property "Sheetfile" "child.kicad_sch")))')
    (tmp_path / "child.kicad_sch").write_text("(kicad_sch)")
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(netlist_export, "_find_schematic", lambda project: schematic)
    monkeypatch.setattr(netlist_export, "detect_kicad_cli", lambda: "/fixed/cli")
    monkeypatch.setattr(netlist_export, limit, 1, raising=False)

    def forbidden(*args: Any) -> Any:
        pytest.fail("oversized sheet closure reached native CLI")

    monkeypatch.setattr(netlist_export, "_cli_export", forbidden)
    with pytest.raises(DevelopmentError):
        netlist_export.export_netlist_impl(str(project))


def test_hierarchical_child_symlink_is_refused_before_any_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    project = root / "root.kicad_pro"
    project.write_text("{}")
    schematic = project.with_suffix(".kicad_sch")
    schematic.write_text('(kicad_sch (sheet (property "Sheetfile" "child.kicad_sch")))')
    external = tmp_path / "external.kicad_sch"
    external.write_text("(kicad_sch)")
    (root / "child.kicad_sch").symlink_to(external)
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(root))
    monkeypatch.setattr(netlist_export, "_find_schematic", lambda project: schematic)
    monkeypatch.setattr(netlist_export, "detect_kicad_cli", lambda: "/fixed/cli")

    def forbidden(*args: Any) -> Any:
        pytest.fail("symlinked child sheet reached native CLI")

    monkeypatch.setattr(netlist_export, "_cli_export", forbidden)
    with pytest.raises(DevelopmentError):
        netlist_export.export_netlist_impl(str(project))
