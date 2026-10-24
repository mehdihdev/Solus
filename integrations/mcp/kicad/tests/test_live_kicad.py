"""ADR-040: edits land in a sheet KiCad has open via save -> write -> Revert."""

import sys
from pathlib import Path
from typing import Any

import pytest

from test_overlay_support import SOLUS  # noqa: F401  # isort: skip
from solus.development import live_kicad
from solus.development.live_kicad import LiveEditError, OsascriptEditor
from solus.development.models import DevelopmentError, fingerprint
from solus.development.schematic import (
    add_symbol,
    create_schematic,
    get_symbol_definition,
)
from test_development_foundation import LIBRARY

SHEET = "live.kicad_sch"


class FakeEditor:
    """Records the handshake and what the file held at each step."""

    def __init__(self, path: Path, *, on_save: bytes | None = None, revert_ok: bool = True):
        self.path = path
        self.on_save = on_save
        self.revert_ok = revert_ok
        self.calls: list[tuple[str, str, bytes]] = []

    def available(self, sheet: str) -> bool:
        self.calls.append(("available", sheet, self.path.read_bytes()))
        return True

    def save(self, sheet: str) -> None:
        self.calls.append(("save", sheet, self.path.read_bytes()))
        if self.on_save is not None:
            self.path.write_bytes(self.on_save)

    def revert(self, sheet: str) -> None:
        self.calls.append(("revert", sheet, self.path.read_bytes()))
        if not self.revert_ok:
            raise LiveEditError("revert_failed")


@pytest.fixture
def sheet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from solus.development import schematic

    libraries = tmp_path / "libraries"
    libraries.mkdir()
    (libraries / "Device.kicad_sym").write_bytes(LIBRARY)
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(schematic, "installed_library_root", lambda: libraries)
    monkeypatch.setattr(live_kicad, "live_editor", lambda: None)
    created = create_schematic(SHEET, "Live", True)
    (tmp_path / f"~{SHEET}.lck").write_text("user@host")
    return {
        "path": tmp_path / SHEET,
        "args": dict(
            schematic_path=SHEET,
            expected_fingerprint=created["after_fingerprint"],
            library_id="Device:R",
            library_fingerprint=get_symbol_definition("Device:R")["library_fingerprint"],
            reference="R1",
            value="10k",
            at={"x_mm": 20, "y_mm": 20},
            rotation_deg=0,
        ),
    }


def _use(monkeypatch: pytest.MonkeyPatch, editor: FakeEditor | None) -> None:
    monkeypatch.setattr(live_kicad, "live_editor", lambda: editor)


def test_open_sheet_is_saved_then_written_then_reverted(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    path: Path = sheet["path"]
    original = path.read_bytes()
    editor = FakeEditor(path)
    _use(monkeypatch, editor)

    result = add_symbol(**sheet["args"])

    assert [c[0] for c in editor.calls] == ["available", "save", "revert"]
    assert all(c[1] == "live" for c in editor.calls)
    assert editor.calls[1][2] == original
    assert editor.calls[2][2] == path.read_bytes() != original
    assert result["kicad_reload"] == "reloaded"
    assert fingerprint(path.read_bytes()) == result["after_fingerprint"]


def test_unsaved_kicad_edits_make_the_write_stale_and_nothing_is_written(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    path: Path = sheet["path"]
    saved_from_gui = path.read_bytes().replace(b'(title "Live")', b'(title "Edited in KiCad")')
    assert saved_from_gui != path.read_bytes()
    editor = FakeEditor(path, on_save=saved_from_gui)
    _use(monkeypatch, editor)

    with pytest.raises(DevelopmentError, match="stale_plan"):
        add_symbol(**sheet["args"])

    assert path.read_bytes() == saved_from_gui
    assert "revert" not in [c[0] for c in editor.calls]


def test_kicad_reformatting_on_save_still_matches_the_plan(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    path: Path = sheet["path"]
    reformatted = path.read_bytes().replace(b" (", b"\n\t(")
    editor = FakeEditor(path, on_save=reformatted)
    _use(monkeypatch, editor)

    result = add_symbol(**sheet["args"])

    assert result["kicad_reload"] == "reloaded"
    assert fingerprint(path.read_bytes()) == result["after_fingerprint"]


def test_failed_revert_keeps_the_write_and_says_how_to_recover(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    editor = FakeEditor(sheet["path"], revert_ok=False)
    _use(monkeypatch, editor)

    result = add_symbol(**sheet["args"])

    assert result["kicad_reload"] == "failed"
    assert "File" in result["kicad_reload_note"] and "Revert" in result["kicad_reload_note"]
    assert "save" in result["kicad_reload_note"].lower()


def test_no_live_editor_keeps_the_open_in_editor_refusal(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = sheet["path"].read_bytes()
    _use(monkeypatch, None)

    for dry_run in (True, False):
        with pytest.raises(DevelopmentError, match="open_in_editor"):
            add_symbol(**sheet["args"], dry_run=dry_run)
    assert sheet["path"].read_bytes() == original


def test_preview_discloses_the_handshake_without_touching_kicad(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    editor = FakeEditor(sheet["path"])
    _use(monkeypatch, editor)

    result = add_symbol(**sheet["args"], dry_run=True)

    assert [c[0] for c in editor.calls] == ["available"]
    notes = [row for row in result["preview"] if row["label"] == "KiCad"]
    assert len(notes) == 1
    assert "save" in notes[0]["after"] and "Revert" in notes[0]["after"]
    assert "undo" in notes[0]["after"]


def test_closed_sheet_never_touches_kicad(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    (sheet["path"].parent / f"~{SHEET}.lck").unlink()
    editor = FakeEditor(sheet["path"])
    _use(monkeypatch, editor)

    result = add_symbol(**sheet["args"])

    assert editor.calls == []
    assert "kicad_reload" not in result


# --- the osascript driver ------------------------------------------------------


class Runner:
    def __init__(self, returncode: int = 0, stdout: str = "ok") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.argv: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float) -> tuple[int, str]:
        assert timeout <= live_kicad.STEP_TIMEOUT_S
        self.argv.append(argv)
        return self.returncode, self.stdout


@pytest.mark.parametrize("action", ["available", "save", "revert"])
def test_driver_passes_the_sheet_as_argv_never_in_the_script(action: str) -> None:
    runner = Runner()
    hostile = 'x" & (do shell script "id") & "'

    getattr(OsascriptEditor(runner), action)(hostile)

    (argv,) = runner.argv
    assert argv[:2] == ["/usr/bin/osascript", "-e"]
    assert argv[2] == live_kicad.SCRIPT
    assert hostile not in argv[2]
    assert argv[3:] == [action, hostile]


def test_driver_failure_raises() -> None:
    editor = OsascriptEditor(Runner(returncode=1, stdout="not_frontmost"))
    with pytest.raises(LiveEditError):
        editor.save("live")
    assert editor.available("live") is False


def test_script_is_a_fixed_vocabulary() -> None:
    script = live_kicad.SCRIPT
    assert "keystroke" not in script and "key code" not in script
    assert "do shell script" not in script
    assert "click at" not in script
    assert 'starts with "Revert \'"' in script and 'button "Yes"' in script


def test_factory_is_off_outside_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert live_kicad.default_live_editor() is None
