"""SOLUSDEV-100 T1b — headless degradation and the plan-locked export_netlist.

kicad-cli availability is detected ONCE per process under the launcher's
pinned posture (KICAD_CLI_PATH or the fixed PATH constant — never upstream's
user-influenced common-location probing). Absent or broken CLI must yield
`degraded: true` with a stable reason — never an exception, never a non-zero
exit. export_netlist honors the 512 KiB inline/artifact branch and confines
every written artifact to the workspace.
"""

import asyncio
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus`/`kicad_mcp` import — keep this line first.
from test_overlay_support import FakeMCP, write_minimal_project  # isort: skip

from solus.cli_detect import (
    KICAD_CLI_FAILED_REASON,
    KICAD_CLI_UNAVAILABLE_REASON,
    detect_kicad_cli,
)
from solus.netlist_export import ARTIFACT_INLINE_MAX_BYTES, export_netlist_impl
from solus.registration import register_allowlisted_tools

RESULT_KEYS = {"format", "filename", "bytes", "content", "artifact_path", "degraded", "reason"}


@pytest.fixture(autouse=True)
def _fresh_detection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Pin the launcher posture per test: scrubbed PATH without kicad-cli, no
    KICAD_CLI_PATH, detection cache cleared on both sides of the test."""
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.delenv("KICAD_CLI_PATH", raising=False)
    detect_kicad_cli.cache_clear()
    yield
    detect_kicad_cli.cache_clear()


def _fake_cli(tmp_path: Path, script_body: str) -> Path:
    cli = tmp_path / "kicad-cli"
    cli.write_text(f"#!/bin/sh\n{script_body}\n")
    cli.chmod(cli.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return cli


def _workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    return workspace


def _assert_exactly_one_payload(result: dict[str, Any]) -> None:
    assert set(result) == RESULT_KEYS
    assert (result["content"] is None) != (result["artifact_path"] is None), (
        "exactly one of content/artifact_path must be non-null"
    )


# --- detection: pinned posture, once per process --------------------------------


def test_detection_returns_none_under_the_scrubbed_headless_posture() -> None:
    assert detect_kicad_cli() is None


def test_detection_ignores_a_non_executable_kicad_cli_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bogus = tmp_path / "not-a-cli"
    bogus.write_text("plain file")
    monkeypatch.setenv("KICAD_CLI_PATH", str(bogus))
    detect_kicad_cli.cache_clear()
    assert detect_kicad_cli() is None


def test_detection_uses_the_pinned_kicad_cli_path_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = _fake_cli(tmp_path, "exit 0")
    monkeypatch.setenv("KICAD_CLI_PATH", str(cli))
    detect_kicad_cli.cache_clear()
    assert detect_kicad_cli() == str(cli)


def test_detection_happens_once_and_is_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert detect_kicad_cli() is None
    cli = _fake_cli(tmp_path, "exit 0")
    monkeypatch.setenv("KICAD_CLI_PATH", str(cli))
    assert detect_kicad_cli() is None, "availability must be detected ONCE per process"
    detect_kicad_cli.cache_clear()
    assert detect_kicad_cli() == str(cli)


# --- export_netlist: degraded path (headless) ------------------------------------


def test_export_netlist_degrades_headless_with_a_stable_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    project = write_minimal_project(tmp_path / "workspace/proj")

    result = export_netlist_impl(str(project))

    _assert_exactly_one_payload(result)
    assert result["degraded"] is True
    assert result["reason"] == KICAD_CLI_UNAVAILABLE_REASON
    assert result["format"] == "kicadxml"
    assert isinstance(result["filename"], str) and result["filename"]
    assert result["bytes"] > 0
    assert result["content"] is not None and "R1" in result["content"]
    assert result["artifact_path"] is None


def test_export_netlist_degrades_when_the_cli_is_present_but_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    project = write_minimal_project(tmp_path / "workspace/proj")
    cli = _fake_cli(tmp_path, "exit 7")
    monkeypatch.setenv("KICAD_CLI_PATH", str(cli))
    detect_kicad_cli.cache_clear()

    result = export_netlist_impl(str(project))

    _assert_exactly_one_payload(result)
    assert result["degraded"] is True
    assert result["reason"] == KICAD_CLI_FAILED_REASON
    assert result["content"] is not None and "R1" in result["content"]


def test_export_netlist_uses_the_cli_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    project = write_minimal_project(tmp_path / "workspace/proj")
    # The overlay's fixed argv is [cli, sch, export, netlist, --format,
    # kicadxml, --output, OUT, SCHEMATIC] — $7 is the output path.
    cli = _fake_cli(tmp_path, 'printf \'<export version="E"><components/></export>\' > "$7"')
    monkeypatch.setenv("KICAD_CLI_PATH", str(cli))
    detect_kicad_cli.cache_clear()

    result = export_netlist_impl(str(project))

    _assert_exactly_one_payload(result)
    assert result["degraded"] is False
    assert result["reason"] is None
    assert result["content"] == '<export version="E"><components/></export>'
    assert result["bytes"] == len(result["content"].encode("utf-8"))


# --- export_netlist: the 512 KiB inline/artifact branch ---------------------------


def _huge_netlist(component_count: int) -> dict[str, Any]:
    components = {
        f"R{i}": {"lib_id": "Device:R", "value": "10k" + "x" * 64} for i in range(component_count)
    }
    nets = {f"NET{i}": [{"component": f"R{i}", "pin": "1"}] for i in range(component_count)}
    return {
        "components": components,
        "nets": nets,
        "component_count": component_count,
        "net_count": component_count,
    }


def test_export_netlist_inlines_content_at_or_below_the_inline_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    project = write_minimal_project(tmp_path / "workspace/proj")

    result = export_netlist_impl(str(project))

    assert result["bytes"] <= ARTIFACT_INLINE_MAX_BYTES
    assert result["content"] is not None
    assert result["artifact_path"] is None
    assert list(workspace.rglob("*.xml")) == [], "small exports must not leave artifacts behind"


def test_export_netlist_writes_a_workspace_artifact_above_the_inline_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert ARTIFACT_INLINE_MAX_BYTES == 512 * 1024, (
        "the inline cap mirrors the cloud artifact_inline_max_bytes constant"
    )
    workspace = _workspace(monkeypatch, tmp_path)
    project = write_minimal_project(tmp_path / "workspace/proj")
    # Synthesize a big netlist through the upstream parse seam so the
    # generated kicadxml crosses the cap.
    monkeypatch.setattr(
        "solus.netlist_export._parse_netlist", lambda schematic_path: _huge_netlist(6000)
    )

    result = export_netlist_impl(str(project))

    _assert_exactly_one_payload(result)
    assert result["bytes"] > ARTIFACT_INLINE_MAX_BYTES
    assert result["content"] is None
    assert isinstance(result["artifact_path"], str)
    artifact_rel = Path(result["artifact_path"])
    assert not artifact_rel.is_absolute(), "artifact_path must be workspace-relative"
    artifact = (workspace / artifact_rel).resolve()
    assert artifact.is_file()
    assert artifact.is_relative_to(workspace.resolve()), "artifact escaped the workspace"
    assert artifact.stat().st_size == result["bytes"]


# --- input hardening ---------------------------------------------------------------


def test_export_netlist_rejects_a_missing_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="not found"):
        export_netlist_impl(str(tmp_path / "ghost.kicad_pro"))


def test_export_netlist_rejects_a_non_project_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _workspace(monkeypatch, tmp_path)
    stray = tmp_path / "notes.txt"
    stray.write_text("not a project")
    with pytest.raises(ValueError, match="kicad_pro"):
        export_netlist_impl(str(stray))


# --- the registered tool surfaces the same behavior --------------------------------


def test_registered_export_netlist_tool_degrades_without_raising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path)
    # H2: the registered tool now goes through the trimming-layer confinement
    # check; the export implementation independently confines discovered files.
    project = write_minimal_project(workspace / "proj")
    fake = FakeMCP()
    register_allowlisted_tools(fake)
    tool = fake.tools["export_netlist"]

    result = asyncio.run(tool(project_path=str(project)))

    _assert_exactly_one_payload(result)
    assert result["degraded"] is True
    assert result["reason"] == KICAD_CLI_UNAVAILABLE_REASON


def test_child_process_path_posture_note() -> None:
    """The launcher pins PATH=/usr/bin:/bin for children; the degraded path
    must not depend on anything outside it. detect_kicad_cli consults ONLY
    KICAD_CLI_PATH and PATH — assert it never imports upstream's
    common-location prober (user-influenced search paths)."""
    import solus.cli_detect as cli_detect

    source = Path(cli_detect.__file__).read_text(encoding="utf-8")
    assert "kicad_api_detection" not in source
    assert "_get_common_installation_paths" not in source
    assert "KICAD_CLI_PATH" in source
    assert os.pathsep == ":", "posture test assumes POSIX PATH semantics"
