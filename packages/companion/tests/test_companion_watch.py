"""SOLUSDEV-167: the local design-change sensor."""

from __future__ import annotations

import os
from pathlib import Path

from solus_companion.frames import change_frame
from solus_companion.watch import (
    ARTIFACT_DIR_NAME,
    MAX_FILES,
    fingerprint,
    workspace_from_env,
    workspace_path,
)


def test_an_unchanged_workspace_fingerprints_the_same(tmp_path: Path) -> None:
    (tmp_path / "board.kicad_sch").write_text("v1")

    assert fingerprint(tmp_path) == fingerprint(tmp_path)


def test_editing_a_design_file_changes_the_fingerprint(tmp_path: Path) -> None:
    sch = tmp_path / "board.kicad_sch"
    sch.write_text("v1")
    before = fingerprint(tmp_path)

    sch.write_text("a longer v2")  # changes size, and mtime

    assert fingerprint(tmp_path) != before


def test_adding_a_design_file_changes_the_fingerprint(tmp_path: Path) -> None:
    (tmp_path / "board.kicad_sch").write_text("v1")
    before = fingerprint(tmp_path)

    (tmp_path / "layout.kicad_pcb").write_text("new")

    assert fingerprint(tmp_path) != before


def test_the_forks_own_output_does_not_trigger_the_sensor(tmp_path: Path) -> None:
    """The forks write exports into the artifact directory. Watching it would
    make every export trigger another export — a loop that never settles."""
    (tmp_path / "board.kicad_sch").write_text("v1")
    before = fingerprint(tmp_path)

    artifacts = tmp_path / ARTIFACT_DIR_NAME
    artifacts.mkdir()
    (artifacts / "export.net").write_text("generated")

    assert fingerprint(tmp_path) == before


def test_unrelated_files_do_not_trigger_the_sensor(tmp_path: Path) -> None:
    """A build artifact, a README or an editor swap file moving is not a design
    change, and treating it as one spends a probe for nothing."""
    (tmp_path / "board.kicad_sch").write_text("v1")
    before = fingerprint(tmp_path)

    (tmp_path / "README.md").write_text("docs")
    (tmp_path / "board.kicad_sch~").write_text("editor backup")

    assert fingerprint(tmp_path) == before


def test_a_missing_workspace_fingerprints_empty_rather_than_raising(tmp_path: Path) -> None:
    """The sensor is advisory. One that can crash the companion is worse than one
    that occasionally says nothing."""
    assert fingerprint(None) == ""
    assert fingerprint(tmp_path / "does-not-exist") == ""


def test_the_sweep_is_bounded(tmp_path: Path) -> None:
    """A workspace pointed at a home directory must not turn the sensor into a
    disk crawler."""
    for i in range(MAX_FILES + 50):
        (tmp_path / f"f{i}.kicad_sch").write_text("x")

    assert fingerprint(tmp_path)  # completes, does not hang or raise


def test_workspace_path_rejects_a_non_directory(tmp_path: Path) -> None:
    file = tmp_path / "not-a-dir"
    file.write_text("x")

    assert workspace_path(str(file)) is None
    assert workspace_path("") is None
    assert workspace_path(None) is None
    assert workspace_path(str(tmp_path)) == tmp_path


def test_the_workspace_comes_from_the_documented_env_var(tmp_path: Path) -> None:
    previous = os.environ.get("SOLUS_COMPANION_WORKSPACE")
    os.environ["SOLUS_COMPANION_WORKSPACE"] = str(tmp_path)
    try:
        assert workspace_from_env() == tmp_path
    finally:
        if previous is None:
            del os.environ["SOLUS_COMPANION_WORKSPACE"]
        else:
            os.environ["SOLUS_COMPANION_WORKSPACE"] = previous


def test_the_change_frame_is_empty() -> None:
    """The type IS the message; the cloud rejects one carrying data."""
    import json

    assert json.loads(change_frame()) == {"type": "change", "data": {}}
