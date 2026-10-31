"""SOLUSDEV-321 P4-T3 — `kicad.export_spice_netlist`, the schematic's SPICE netlist for rung 3.

The export is `kicad-cli sch export netlist --format spice` with a FIXED argv, through the fork's
own native capture, over the same workspace-confined snapshot `export_netlist` reads. The netlist
comes back as data, inline only and bounded, and nothing is written to the workspace. Without a
native CLI, or under the Flatpak adapter, the result is degraded with no content. Every CLI here is
a fake script using only shell builtins: no test launches KiCad.
"""

import re
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus`/`kicad_mcp` import — keep this line first.
from test_overlay_support import write_minimal_project  # isort: skip

from solus import spice_export
from solus.cli_detect import detect_kicad_cli
from solus.development.models import DevelopmentError
from solus.spice_export import (
    MAX_SPICE_BYTES,
    SPICE_CLI_FAILED_REASON,
    SPICE_CLI_UNAVAILABLE_REASON,
    SPICE_FLATPAK_REASON,
    export_spice_netlist_impl,
)

#: What a schematic's export may hold, a directive block among it: the fork passes it on as data.
NETLIST = ".title KiCad schematic\n.control\nshell rm -rf ~\n.endc\nR1 /in /out 10k\n.end\n"


@pytest.fixture(autouse=True)
def _fresh_detection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """The launcher's headless posture per test: a PATH with no kicad-cli and no flatpak, no
    KICAD_CLI_PATH, and the detection cache cleared on both sides."""
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.delenv("KICAD_CLI_PATH", raising=False)
    detect_kicad_cli.cache_clear()
    yield
    detect_kicad_cli.cache_clear()


def _fake_cli(tmp_path: Path, body: str) -> Path:
    """A fake kicad-cli outside the workspace, pinned the way the launcher pins one. It records
    its argv, then runs `body`. The fixed argv is [cli, sch, export, netlist, --format, spice,
    --output, OUT, SCHEMATIC], so `$7` is the output."""
    cli = tmp_path / "bin" / "kicad-cli"
    cli.parent.mkdir()
    cli.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{tmp_path}/argv.txt"\n{body}\n')
    cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
    return cli


def _pin_cli(monkeypatch: pytest.MonkeyPatch, cli: Path) -> None:
    monkeypatch.setenv("KICAD_CLI_PATH", str(cli))
    detect_kicad_cli.cache_clear()


def _spice_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    return workspace, write_minimal_project(workspace / "proj")


def _never(*args: object) -> None:
    raise AssertionError("nothing may run here")


def test_the_export_runs_the_pinned_cli_with_the_fixed_spice_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace, project = _spice_project(monkeypatch, tmp_path)
    written = NETLIST.replace("\n", "\\n")
    _pin_cli(monkeypatch, _fake_cli(tmp_path, f"printf '{written}' > \"$7\""))
    before = sorted(workspace.rglob("*"))

    result = export_spice_netlist_impl(str(project))

    assert result == {
        "format": "spice",
        "filename": "board.cir",
        "bytes": len(NETLIST.encode()),
        "content": NETLIST,
        "degraded": False,
        "reason": None,
    }
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert argv[:6] == ["sch", "export", "netlist", "--format", "spice", "--output"]
    assert re.fullmatch(r"/(proc/self|dev)/fd/\d+", argv[6])
    # the CLI reads a private copy of the schematic, never the workspace's own file
    assert len(argv) == 8 and argv[7].endswith("/proj/board.kicad_sch")
    assert not Path(argv[7]).is_relative_to(workspace)
    # the netlist came back as data, and nothing was written to the workspace
    assert sorted(workspace.rglob("*")) == before


def test_the_paths_an_export_names_never_leave_the_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """KiCad writes one `.include "<full path>"` a simulation library. The API's deck drops every
    `.include` and `.lib` unread, so the fork keeps the directive, which holds the line numbers,
    and withholds its path: a username in it never reaches the cloud."""
    _, project = _spice_project(monkeypatch, tmp_path)
    exported = (
        ".title KiCad schematic\n"
        '.include "/home/alice/kicad/models/diode.lib"\n'
        "  .LIB /opt/alice/corner.lib tt\n"
        ".library_note stays\n"
        "R1 /in /out 10k\n"
        ".end\n"
    )
    written = exported.replace("\n", "\\n")
    _pin_cli(monkeypatch, _fake_cli(tmp_path, f"printf '{written}' > \"$7\""))

    result = export_spice_netlist_impl(str(project))

    assert result["content"] == (
        ".title KiCad schematic\n.include\n  .LIB\n.library_note stays\nR1 /in /out 10k\n.end\n"
    )
    assert result["bytes"] == len(result["content"].encode())
    assert "alice" not in result["content"]


def test_without_a_cli_the_export_is_degraded_with_no_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, project = _spice_project(monkeypatch, tmp_path)

    assert export_spice_netlist_impl(str(project)) == {
        "format": "spice",
        "filename": "board.cir",
        "bytes": 0,
        "content": None,
        "degraded": True,
        "reason": SPICE_CLI_UNAVAILABLE_REASON,
    }


def test_under_the_flatpak_adapter_the_export_is_degraded_and_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The adapter's fixed operations hold no SPICE export, so nothing is launched through it."""
    _, project = _spice_project(monkeypatch, tmp_path)
    adapter = Path(spice_export.__file__).resolve().parents[1] / "bin/kicad-cli-flatpak"
    monkeypatch.setattr(spice_export, "detect_kicad_cli", lambda: str(adapter))
    monkeypatch.setattr(spice_export, "_capture", _never)

    result = export_spice_netlist_impl(str(project))

    assert (result["degraded"], result["reason"], result["content"]) == (
        True,
        SPICE_FLATPAK_REASON,
        None,
    )


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("exit 1", id="the-cli-fails"),
        pytest.param(
            f"i=0; while [ $i -lt {MAX_SPICE_BYTES // 1024 + 1} ]; do printf '%01024d' 0; "
            'i=$((i+1)); done > "$7"',
            id="past-256-kib",
        ),
    ],
)
def test_a_failed_or_oversized_export_is_degraded_with_no_content(
    body: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, project = _spice_project(monkeypatch, tmp_path)
    _pin_cli(monkeypatch, _fake_cli(tmp_path, body))

    result = export_spice_netlist_impl(str(project))

    assert (tmp_path / "argv.txt").is_file()  # the CLI ran, and its output was refused
    assert (result["degraded"], result["reason"], result["content"], result["bytes"]) == (
        True,
        SPICE_CLI_FAILED_REASON,
        None,
        0,
    )


def test_a_schematic_outside_the_workspace_never_reaches_the_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The registrar confines `project_path` before the body runs; the snapshot confines the
    schematic again, so even a direct call reads nothing outside the workspace."""
    _spice_project(monkeypatch, tmp_path)
    outside = write_minimal_project(tmp_path / "outside")
    _pin_cli(monkeypatch, _fake_cli(tmp_path, "exit 0"))

    with pytest.raises(DevelopmentError, match="path_escapes_workspace"):
        export_spice_netlist_impl(str(outside))
    assert not (tmp_path / "argv.txt").exists()


@pytest.mark.parametrize(
    ("name", "why"),
    [
        pytest.param("board.kicad_sch", "expected a .kicad_pro", id="not-a-project"),
        pytest.param("missing.kicad_pro", "project not found", id="missing"),
    ],
)
def test_only_an_existing_project_file_is_exported(
    name: str, why: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, project = _spice_project(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match=why):
        export_spice_netlist_impl(str(project.parent / name))
