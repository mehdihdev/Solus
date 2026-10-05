"""An export must not follow mutable output aliases or delete external files."""

import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from test_overlay_support import SOLUS  # noqa: F401  # isort: skip
from solus import netlist_export
from solus.development.models import DevelopmentError


@pytest.mark.parametrize("swap", ["directory", "file"])
def test_cli_output_alias_swap_cannot_write_read_or_delete_external_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swap: str,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    schematic = root / "sheet.kicad_sch"
    schematic.write_text("(kicad_sch)")
    external = tmp_path / "external"
    external.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(root))
    sentinel = external / "netlist.part"
    sentinel.write_bytes(b"EXTERNAL_SENTINEL")
    descriptor_seen = False

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        nonlocal descriptor_seen
        output = Path(argv[-2])
        if str(output).startswith(("/proc/self/fd/", "/dev/fd/")):
            descriptor = int(output.name)
            assert descriptor in kwargs["pass_fds"]
            descriptor_seen = True
        else:
            if swap == "directory":
                output.parent.rename(output.parent.with_name(output.parent.name + "-moved"))
                output.parent.symlink_to(external, target_is_directory=True)
            else:
                output.symlink_to(sentinel)
        # Model the real native writer AFTER its output parent/file is replaced.
        output.write_bytes(b"<verified/>")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    result = netlist_export._cli_export("/fixed/cli", schematic, "report.xml")
    assert sentinel.read_bytes() == b"EXTERNAL_SENTINEL"
    assert descriptor_seen, "a pathname precheck is not a bound write destination"
    assert result == b"<verified/>"


def test_cli_output_has_a_hard_read_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(netlist_export, "_MAX_EXPORT_BYTES", 8, raising=False)

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        Path(argv[-2]).write_bytes(b"123456789")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(DevelopmentError, match="file_too_large"):
        netlist_export._cli_export("/fixed/cli", tmp_path / "sheet.kicad_sch", "report.xml")


@pytest.mark.parametrize("swap", ["directory", "file"])
def test_large_artifact_publication_is_descriptor_confined(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swap: str,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    directory = root / "solus-artifacts"
    directory.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "report.xml"
    sentinel.write_bytes(b"EXTERNAL_SENTINEL")
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(root))
    original_fsync = os.fsync
    swapped = False

    def swap_after_staging(fd: int) -> None:
        nonlocal swapped
        original_fsync(fd)
        if swapped or not stat.S_ISREG(os.fstat(fd).st_mode):
            return
        swapped = True
        if swap == "directory":
            directory.rename(root / "moved-artifacts")
            directory.symlink_to(external, target_is_directory=True)
        else:
            (directory / "report.xml").symlink_to(sentinel)

    monkeypatch.setattr(os, "fsync", swap_after_staging)
    payload = b"x" * (netlist_export.ARTIFACT_INLINE_MAX_BYTES + 1)
    if swap == "directory":
        with pytest.raises(DevelopmentError, match="path_escapes_workspace"):
            netlist_export._package_result(payload, "report.xml", False, None)
    else:
        result = netlist_export._package_result(payload, "report.xml", False, None)
        assert (root / result["artifact_path"]).read_bytes() == payload
        assert not (directory / "report.xml").is_symlink()
    assert swapped, "publication must stage and sync before replacing its destination"
    assert sentinel.read_bytes() == b"EXTERNAL_SENTINEL"
