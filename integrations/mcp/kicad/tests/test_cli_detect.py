"""The Flatpak adapter accepts only fixed supported CLI operations."""

from pathlib import Path

import pytest

from test_overlay_support import SOLUS  # noqa: F401  # isort: skip
from solus.development.cli import flatpak_argv
from solus.development.models import DevelopmentError


def test_fixed_flatpak_version() -> None:
    assert flatpak_argv(["version"]) == [
        "/usr/bin/flatpak",
        "run",
        "--command=kicad-cli",
        "org.kicad.KiCad",
        "version",
    ]


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--help"],
        ["run", "evil.app"],
        ["sch", "erc", "--define-var", "X=1"],
        ["version", "--command=sh"],
    ],
)
def test_adapter_refuses_arbitrary_argv(args: list[str]) -> None:
    with pytest.raises(DevelopmentError):
        flatpak_argv(args)


def test_adapter_confines_both_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    source = tmp_path / "a.kicad_sch"
    source.write_text("(kicad_sch)")
    output = tmp_path / "report.json"
    args = [
        "sch",
        "erc",
        "--format",
        "json",
        "--units",
        "mm",
        "--severity-all",
        "--exit-code-violations",
        "--output",
        str(output),
        str(source),
    ]
    with pytest.raises(DevelopmentError):
        flatpak_argv(args)
    args[-2] = str(tmp_path.parent / "escape.json")
    with pytest.raises(DevelopmentError):
        flatpak_argv(args)


def test_adapter_never_overwrites_an_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    source = tmp_path / "a.kicad_sch"
    source.write_text("(kicad_sch)")
    destination = tmp_path / "existing.json"
    destination.write_text("must survive")
    args = [
        "sch",
        "erc",
        "--format",
        "json",
        "--units",
        "mm",
        "--severity-all",
        "--exit-code-violations",
        "--output",
        str(destination),
        str(source),
    ]
    with pytest.raises(DevelopmentError):
        flatpak_argv(args)


def test_default_detection_finds_fixed_flatpak_installation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    from solus.cli_detect import detect_kicad_cli

    monkeypatch.delenv("KICAD_CLI_PATH", raising=False)
    monkeypatch.setattr(
        "solus.cli_detect.shutil.which",
        lambda name: "/usr/bin/flatpak" if name == "flatpak" else None,
    )
    calls: list[list[str]] = []

    def probe(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b"app/org.kicad.KiCad/aarch64/stable\n")

    monkeypatch.setattr(subprocess, "run", probe)
    detect_kicad_cli.cache_clear()
    try:
        path = detect_kicad_cli()
        assert path is not None and path.endswith("/bin/kicad-cli-flatpak")
        assert calls == [["/usr/bin/flatpak", "info", "--show-ref", "org.kicad.KiCad"]]
    finally:
        detect_kicad_cli.cache_clear()


def test_default_detection_does_not_trust_arbitrary_flatpak_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus.cli_detect import detect_kicad_cli

    monkeypatch.delenv("KICAD_CLI_PATH", raising=False)
    monkeypatch.setattr(
        "solus.cli_detect.shutil.which", lambda name: "/tmp/flatpak" if name == "flatpak" else None
    )
    detect_kicad_cli.cache_clear()
    try:
        assert detect_kicad_cli() is None
    finally:
        detect_kicad_cli.cache_clear()


def test_relative_or_workspace_kicad_cli_path_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from solus.cli_detect import detect_kicad_cli

    workspace = tmp_path / "ws"
    workspace.mkdir()
    planted = workspace / "kicad-cli"
    planted.write_text("#!/bin/sh\nexit 0\n")
    planted.chmod(0o755)
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    monkeypatch.setattr("solus.cli_detect.shutil.which", lambda name: None)
    for hostile in (str(planted), "./kicad-cli", "kicad-cli"):
        monkeypatch.setenv("KICAD_CLI_PATH", hostile)
        monkeypatch.chdir(workspace)
        detect_kicad_cli.cache_clear()
        try:
            assert detect_kicad_cli() is None, hostile
        finally:
            detect_kicad_cli.cache_clear()
