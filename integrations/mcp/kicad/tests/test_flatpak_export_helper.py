"""The installed Flatpak cannot forward FDs; create the capability inside it."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from test_overlay_support import FORK  # isort: skip
from solus.development.cli import flatpak_argv


def test_flatpak_export_uses_only_fixed_owned_capture_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    source = tmp_path / "source.kicad_sch"
    source.write_text("(kicad_sch)")
    args = ["sch", "export", "netlist", "--format", "kicadxml", "--output", "-", "-"]
    assert flatpak_argv(args) == [
        "/usr/bin/flatpak",
        "run",
        "--command=/usr/bin/python3",
        "org.kicad.KiCad",
        str(FORK / "solus/development/flatpak_export.py"),
        "netlist",
    ]


@pytest.mark.parametrize("oversized", [False, True])
def test_container_helper_native_writer_uses_anonymous_output_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    oversized: bool,
) -> None:
    from solus.development import flatpak_export

    source = tmp_path / "source.kicad_sch"
    source.write_text("(kicad_sch)")
    monkeypatch.setattr(flatpak_export, "MAX_EXPORT_BYTES", 8)

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert argv[0] == "/app/bin/kicad-cli"
        output = Path(argv[-2])
        assert str(output).startswith("/proc/self/fd/")
        assert int(output.name) in kwargs["pass_fds"]
        assert kwargs["stdout"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL
        output.write_bytes(b"123456789" if oversized else b"<xml/>")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    assert flatpak_export.capture_netlist(str(source)) == (None if oversized else b"<xml/>")


def test_container_erc_preserves_violation_exit_code_and_uses_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus.development import flatpak_export

    source = tmp_path / "source.kicad_sch"
    source.write_text("(kicad_sch)")

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert argv[:3] == ["/app/bin/kicad-cli", "sch", "erc"]
        output = Path(argv[-2])
        assert str(output).startswith("/proc/self/fd/")
        assert int(output.name) in kwargs["pass_fds"]
        output.write_bytes(b'{"violations":[]}')
        return subprocess.CompletedProcess(argv, 5)

    monkeypatch.setattr(subprocess, "run", run)
    assert flatpak_export.capture_erc(str(source)) == (5, b'{"violations":[]}')


def test_container_materializes_captured_hierarchy_outside_workspace(tmp_path, monkeypatch):
    from solus.development import flatpak_export

    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    body = b'(kicad_sch (sheet (property "Sheetfile" "../common/child.kicad_sch")))'
    payload = flatpak_export.encode_snapshot(
        "nested/root.kicad_sch",
        {
            "nested/root.kicad_sch": body,
            "common/child.kicad_sch": b"(kicad_sch)",
        },
    )

    def capture(source):
        path = Path(source)
        assert not path.is_relative_to(tmp_path)
        assert path.read_bytes() == body
        assert (path.parent / "../common/child.kicad_sch").read_bytes() == b"(kicad_sch)"
        return b"<xml/>"

    monkeypatch.setattr(flatpak_export, "capture_netlist", capture)
    assert flatpak_export.capture_snapshot(payload) == (0, b"<xml/>")


@pytest.mark.parametrize(
    "name", ["../escape.kicad_sch", "/escape.kicad_sch", "x/../escape.kicad_sch", "file.txt"]
)
def test_container_rejects_escape_before_native_launch(name, monkeypatch):
    from solus.development import flatpak_export

    def forbidden(source):
        pytest.fail("unsafe input reached native CLI")

    monkeypatch.setattr(flatpak_export, "capture_netlist", forbidden)
    payload = flatpak_export.encode_snapshot(name, {name: b"(kicad_sch)"})
    assert flatpak_export.capture_snapshot(payload) is None
