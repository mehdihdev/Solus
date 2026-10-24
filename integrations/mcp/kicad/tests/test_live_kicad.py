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

    def __init__(
        self,
        path: Path,
        *,
        on_save: bytes | None = None,
        revert_ok: bool = True,
        canonical: bytes | None = None,
        resave_ok: bool = True,
    ):
        self.path = path
        self.on_save = on_save
        self.revert_ok = revert_ok
        self.canonical = canonical
        self.resave_ok = resave_ok
        self.reverted = False
        self.calls: list[tuple[str, str, bytes]] = []

    def available(self, sheet: str, path: str) -> bool:
        assert path == str(self.path)
        self.calls.append(("available", sheet, self.path.read_bytes()))
        return True

    def save(self, sheet: str, path: str) -> None:
        self.calls.append(("save", sheet, self.path.read_bytes()))
        if self.reverted:  # step (d): KiCad re-serializes what it reloaded
            if not self.resave_ok:
                raise LiveEditError("save", "save_unconfirmed")
            if self.canonical is not None:
                self.path.write_bytes(self.canonical)
        elif self.on_save is not None:
            self.path.write_bytes(self.on_save)

    def revert(self, sheet: str, path: str) -> None:
        self.calls.append(("revert", sheet, self.path.read_bytes()))
        if not self.revert_ok:
            raise LiveEditError("revert", "no_confirm")
        self.reverted = True


@pytest.fixture
def sheet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from solus.development import schematic

    libraries = tmp_path / "libraries"
    libraries.mkdir()
    (libraries / "Device.kicad_sym").write_bytes(LIBRARY)
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(schematic, "installed_library_root", lambda: libraries)
    monkeypatch.setattr(live_kicad, "live_editor", lambda: None)
    monkeypatch.setattr(live_kicad, "_LIVE_PREVIEWS", {})
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


def _approved(args: dict[str, Any]) -> dict[str, Any]:
    """What the card / Build flow does: preview, then the real call."""
    add_symbol(**args, dry_run=True)
    return add_symbol(**args)


def test_open_sheet_is_saved_then_written_then_reverted(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    path: Path = sheet["path"]
    original = path.read_bytes()
    editor = FakeEditor(path)
    _use(monkeypatch, editor)

    result = _approved(sheet["args"])

    assert [c[0] for c in editor.calls] == ["available", "available", "save", "revert", "save"]
    assert all(c[1] == "live" for c in editor.calls)
    assert editor.calls[2][2] == original
    assert editor.calls[3][2] == path.read_bytes() != original
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

    add_symbol(**sheet["args"], dry_run=True)
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

    result = _approved(sheet["args"])

    assert result["kicad_reload"] == "reloaded"
    assert fingerprint(path.read_bytes()) == result["after_fingerprint"]


def test_failed_revert_keeps_the_write_and_says_how_to_recover(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    editor = FakeEditor(sheet["path"], revert_ok=False)
    _use(monkeypatch, editor)

    result = _approved(sheet["args"])

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
    notes = [row for row in result["preview"] if row["label"] == "Approval required"]
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


def test_live_write_requires_a_preview_that_showed_the_handshake(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lock that appears after approval must not silently save/revert KiCad."""
    original = sheet["path"].read_bytes()
    editor = FakeEditor(sheet["path"])
    _use(monkeypatch, editor)

    with pytest.raises(DevelopmentError, match="live_preview_required"):
        add_symbol(**sheet["args"])

    assert sheet["path"].read_bytes() == original
    assert "save" not in [c[0] for c in editor.calls]


def test_a_live_preview_authorizes_one_write_only(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    editor = FakeEditor(sheet["path"])
    _use(monkeypatch, editor)
    _approved(sheet["args"])
    second = {**sheet["args"], "reference": "R2", "at": {"x_mm": 60, "y_mm": 20}}
    second["expected_fingerprint"] = fingerprint(sheet["path"].read_bytes())

    with pytest.raises(DevelopmentError, match="live_preview_required"):
        add_symbol(**second)


def test_expired_live_preview_is_refused(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, FakeEditor(sheet["path"]))
    add_symbol(**sheet["args"], dry_run=True)
    clock = live_kicad.time.monotonic() + live_kicad.LIVE_PREVIEW_TTL_S + 1
    monkeypatch.setattr(live_kicad.time, "monotonic", lambda: clock)

    with pytest.raises(DevelopmentError, match="live_preview_required"):
        add_symbol(**sheet["args"])


def test_resave_after_revert_returns_the_canonical_fingerprint(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-040 amendment step (d): KiCad's re-save canonicalizes the file, and
    SOL's next edit must plan against what is actually on disk."""
    canonical = b"(kicad_sch (canonical form from KiCad))"
    editor = FakeEditor(sheet["path"], canonical=canonical)
    _use(monkeypatch, editor)

    result = _approved(sheet["args"])

    assert sheet["path"].read_bytes() == canonical
    assert result["after_fingerprint"] == fingerprint(canonical)
    assert result["kicad_reload"] == "reloaded"


def test_failed_resave_keeps_the_edit_and_warns(
    sheet: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    editor = FakeEditor(sheet["path"], resave_ok=False)
    _use(monkeypatch, editor)

    result = _approved(sheet["args"])

    assert result["kicad_reload"] == "reloaded"
    assert result["kicad_resave"] == "failed"
    assert fingerprint(sheet["path"].read_bytes()) == result["after_fingerprint"]


def test_settle_waits_for_bytes_to_stop_changing(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = iter([b"a", b"b", b"c", b"c", b"c"])
    monkeypatch.setattr(live_kicad.time, "sleep", lambda _s: None)
    seen: list[bytes] = []

    def read() -> bytes:
        seen.append(next(reads))
        return seen[-1]

    live_kicad.wait_until_settled(read)
    assert seen[-2:] == [b"c", b"c"]


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

    getattr(OsascriptEditor(runner), action)(hostile, "/w/" + hostile)

    (argv,) = runner.argv
    assert argv[:2] == ["/usr/bin/osascript", "-e"]
    assert argv[2] == live_kicad.SCRIPT
    assert hostile not in argv[2]
    assert argv[3:] == [action, hostile, "/w/" + hostile]


def test_driver_failure_names_the_step_and_known_reason() -> None:
    stderr = "123:456: execution error: save_unconfirmed (-2700)"
    editor = OsascriptEditor(Runner(returncode=1, stdout=stderr))
    with pytest.raises(LiveEditError) as raised:
        editor.save("live", "/w/live.kicad_sch")
    assert (raised.value.step, raised.value.reason) == ("save", "save_unconfirmed")
    assert editor.available("live", "/w/live.kicad_sch") is False


def test_driver_never_echoes_unknown_error_text() -> None:
    editor = OsascriptEditor(Runner(returncode=1, stdout="secret /Users/x/design detail"))
    with pytest.raises(LiveEditError) as raised:
        editor.revert("live", "/w/live.kicad_sch")
    assert raised.value.reason == "unknown"


def test_script_is_a_fixed_vocabulary() -> None:
    script = live_kicad.SCRIPT
    assert "keystroke" not in script and "key code" not in script
    assert "do shell script" not in script
    assert "click at" not in script
    assert 'button "Yes"' in script
    for guard in ("ambiguous", "dirty", "save_unconfirmed", "not_frontmost", "no_confirm"):
        assert f'error "{guard}"' in script


def test_factory_is_off_outside_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert live_kicad.default_live_editor() is None
