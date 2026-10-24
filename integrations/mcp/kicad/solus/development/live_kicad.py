"""ADR-040: land a confirmed write in a sheet KiCad has open (macOS).

KiCad 10's IPC API has no schematic item types and Eeschema never reloads a
file changed on disk, so the handshake is: save the open sheet in KiCad,
write (strict stale checks, see `commit_plan`), then File -> Revert to reload.

Input is a fixed vocabulary run by /usr/bin/osascript with a fixed script; the
sheet name travels as an argv value and is never interpolated into the script.
Every step re-finds the target window and refuses unless it is frontmost.
"""

import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from solus.development.commit import commit_plan, editor_lock_present, read_schematic
from solus.development.models import DevelopmentError
from solus.development.plan import MutationPlan

OSASCRIPT = "/usr/bin/osascript"
STEP_TIMEOUT_S = 15.0
SETTLE_POLL_S = 0.2
SETTLE_LIMIT_S = 5.0

#: argv: (action in {available, save, revert}, sheet stem). Matches only the
#: KiCad 10 window titled exactly "<stem> — Schematic Editor" ("*" prefix = unsaved).
SCRIPT = """on run argv
	-- Names avoid System Events terms ("action", "sheet") that shadow variables.
	set verb to item 1 of argv
	set wanted to (item 2 of argv) & " " & (character id 8212) & " Schematic Editor"
	tell application "System Events"
		set targetProc to missing value
		set targetName to missing value
		repeat with procRef in {"kicad", "eeschema"}
			set procName to contents of procRef
			if exists process procName then
				repeat with w in (windows of process procName)
					set t to name of w
					if t is wanted or t is ("*" & wanted) then
						set targetProc to process procName
						set targetName to t
						exit repeat
					end if
				end repeat
			end if
			if targetProc is not missing value then exit repeat
		end repeat
		if targetProc is missing value then error "no_window"
		if verb is "available" then return "ok"
		set frontmost of targetProc to true
		perform action "AXRaise" of (first window of targetProc whose name is targetName)
		delay 0.4
		if not (frontmost of targetProc) then error "not_frontmost"
		if (name of window 1 of targetProc) is not targetName then error "not_frontmost"
		set fileMenu to menu "File" of menu bar 1 of targetProc
		if verb is "save" then
			click menu item "Save" of fileMenu
		else if verb is "revert" then
			click (first menu item of fileMenu whose name starts with "Revert")
			delay 0.6
			set confirmed to false
			set dialog to window 1 of targetProc
			if exists sheet 1 of dialog then set dialog to sheet 1 of dialog
			if exists button "Revert" of dialog then
				click button "Revert" of dialog
				set confirmed to true
			end if
			if not confirmed then error "no_confirm"
		else
			error "bad_action"
		end if
		return "ok"
	end tell
end run
"""

Runner = Callable[[list[str], float], tuple[int, str]]


class LiveEditError(Exception):
    """A handshake step failed; never carries design contents."""


class LiveEditor(Protocol):
    def available(self, sheet: str) -> bool: ...
    def save(self, sheet: str) -> None: ...
    def revert(self, sheet: str) -> None: ...


def _run(argv: list[str], timeout: float) -> tuple[int, str]:
    try:
        done = subprocess.run(  # noqa: S603 — pinned osascript, fixed script, argv values
            argv, capture_output=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return 1, "osascript_failed"
    return done.returncode, (done.stdout + done.stderr).decode(errors="replace")


class OsascriptEditor:
    def __init__(self, runner: Runner = _run) -> None:
        self._runner = runner

    def _step(self, action: str, sheet: str) -> None:
        code, _ = self._runner([OSASCRIPT, "-e", SCRIPT, action, sheet], STEP_TIMEOUT_S)
        if code != 0:
            raise LiveEditError(f"{action}_failed")

    def available(self, sheet: str) -> bool:
        try:
            self._step("available", sheet)
        except LiveEditError:
            return False
        return True

    def save(self, sheet: str) -> None:
        self._step("save", sheet)

    def revert(self, sheet: str) -> None:
        self._step("revert", sheet)


def default_live_editor() -> LiveEditor | None:
    return OsascriptEditor() if sys.platform == "darwin" else None


def live_editor() -> LiveEditor | None:
    """Indirection the tests replace; production uses the osascript driver."""
    return default_live_editor()


def wait_until_settled(read: Callable[[], bytes | None]) -> None:
    """KiCad writes asynchronously after the menu click; wait for stable bytes."""
    deadline = time.monotonic() + SETTLE_LIMIT_S
    previous = read()
    while time.monotonic() < deadline:
        time.sleep(SETTLE_POLL_S)
        current = read()
        if current == previous:
            return
        previous = current


PREVIEW_NOTE = (
    "This sheet is open in KiCad: Solus will save it in KiCad (saving any in-progress "
    "work), apply this change, then use File → Revert to reload it. The sheet's undo "
    "history in KiCad resets."
)
RELOAD_FAILED_NOTE = (
    "The change is written to disk, but KiCad did not reload it. In KiCad use File → "
    "Revert now, and do not save first — saving would overwrite this change."
)


def _sheet(relative: str) -> str:
    return PurePosixPath(relative).stem


def open_sheet_editor(root: Path, relative: str) -> LiveEditor | None:
    """The live editor for a sheet KiCad holds open; refuses `open_in_editor`
    when the sheet is open but no driver can reach its window. None = not open."""
    if not editor_lock_present(root, relative):
        return None
    editor = live_editor()
    if editor is None or not editor.available(_sheet(relative)):
        raise DevelopmentError("open_in_editor")
    return editor


def live_commit(root: Path, plan: MutationPlan, editor: LiveEditor) -> dict[str, Any]:
    """ADR-040 handshake: save in KiCad -> strict write -> File -> Revert."""
    sheet = _sheet(plan.path)
    try:
        editor.save(sheet)
    except LiveEditError as exc:
        raise DevelopmentError("open_in_editor") from exc
    wait_until_settled(lambda: read_schematic(root, plan.path))
    commit_plan(root, plan, editor_saved=True)
    try:
        editor.revert(sheet)
    except LiveEditError:
        return {"kicad_reload": "failed", "kicad_reload_note": RELOAD_FAILED_NOTE}
    return {"kicad_reload": "reloaded"}
