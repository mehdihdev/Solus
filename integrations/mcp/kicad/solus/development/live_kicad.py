"""ADR-040: land a confirmed write in a sheet KiCad has open (macOS).

KiCad 10's IPC API has no schematic item types and Eeschema never reloads a
file changed on disk, so the handshake is: save the open sheet in KiCad,
write (strict stale checks, see `commit_plan`), File -> Revert to reload, then
save once more so the file is in KiCad's canonical form (amendment step d).

Input is a fixed vocabulary run by /usr/bin/osascript with a fixed script; the
sheet stem and path travel as argv values and are never interpolated into the
script. Every click re-checks that the one matching KiCad window is frontmost.
A live write needs a preview that showed the handshake (the approval covers it).
"""

import logging
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from solus.development.commit import commit_plan, editor_lock_present, read_schematic
from solus.development.models import DevelopmentError, fingerprint
from solus.development.plan import MutationPlan

logger = logging.getLogger("solus.kicad.live")

OSASCRIPT = "/usr/bin/osascript"
STEP_TIMEOUT_S = 20.0
LIVE_PREVIEW_TTL_S = 30 * 60
SETTLE_POLL_S = 0.3
SETTLE_LIMIT_S = 5.0
#: Matches the API's execution_policy.APPROVAL_REQUIRED_LABEL: the row makes the
#: Build policy send this call to the approval card instead of running it.
APPROVAL_REQUIRED_LABEL = "Approval required"
KNOWN_REASONS = frozenset(
    {"no_window", "ambiguous", "not_frontmost", "save_unconfirmed", "dirty", "no_confirm"}
)

#: argv: (verb in {available, save, revert}, sheet stem, absolute sheet path).
#: Matches only the KiCad 10 window titled exactly "<stem> — Schematic Editor"
#: ("*" prefix = unsaved), and refuses when more than one window matches.
SCRIPT = """on run argv
	-- Names avoid System Events terms ("action", "sheet") that shadow variables.
	set verb to item 1 of argv
	set wanted to (item 2 of argv) & " " & (character id 8212) & " Schematic Editor"
	set prompt to "Revert '" & (item 3 of argv) & "'"
	tell application "System Events"
		set found to {}
		set targetProc to missing value
		repeat with procRef in {"kicad", "eeschema"}
			set procName to contents of procRef
			if exists process procName then
				repeat with w in (windows of process procName)
					set t to name of w
					if t is wanted or t is ("*" & wanted) then
						set end of found to t
						set targetProc to process procName
					end if
				end repeat
			end if
		end repeat
		if (count of found) is 0 then error "no_window"
		if (count of found) > 1 then error "ambiguous"
		if verb is "available" then return "ok"
		set frontmost of targetProc to true
		perform action "AXRaise" of (first window of targetProc whose name is (item 1 of found))
		delay 0.4
		set fileMenu to menu "File" of menu bar 1 of targetProc
		if verb is "save" then
			my ensureFront(targetProc, wanted)
			click menu item "Save" of fileMenu
			repeat 50 times
				delay 0.2
				if (name of window 1 of targetProc) is wanted then return "ok"
			end repeat
			error "save_unconfirmed"
		else if verb is "revert" then
			my ensureFront(targetProc, wanted)
			if (name of window 1 of targetProc) is not wanted then error "dirty"
			click (first menu item of fileMenu whose name starts with "Revert")
			delay 0.6
			repeat with answer in {"Yes", "No"}
				repeat with d in (windows of targetProc)
					set texts to (value of every static text of d) as list
					repeat with i from 1 to (count of texts)
						set v to (item i of texts) as text
						set reply to contents of answer
						if v starts with "Revert '" and (exists button reply of d) then
							if reply is "Yes" and v starts with prompt then
								click button "Yes" of d
								return "ok"
							else if reply is "No" then
								click button "No" of d
								error "no_confirm"
							end if
						end if
					end repeat
				end repeat
			end repeat
			error "no_confirm"
		else
			error "bad_verb"
		end if
	end tell
end run

on ensureFront(targetProc, wanted)
	tell application "System Events"
		if not (frontmost of targetProc) then error "not_frontmost"
		set t to name of window 1 of targetProc
		if t is not wanted and t is not ("*" & wanted) then error "not_frontmost"
	end tell
end ensureFront
"""

Runner = Callable[[list[str], float], tuple[int, str]]
_ERROR = re.compile(r"execution error: ([a-z_]+) \(-?\d+\)")


class LiveEditError(Exception):
    """A handshake step failed; carries only the step and a known reason code."""

    def __init__(self, step: str, reason: str) -> None:
        self.step = step
        self.reason = reason
        super().__init__(f"{step}: {reason}")


class LiveEditor(Protocol):
    def available(self, sheet: str, path: str) -> bool: ...
    def save(self, sheet: str, path: str) -> None: ...
    def revert(self, sheet: str, path: str) -> None: ...


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

    def _step(self, verb: str, sheet: str, path: str) -> None:
        code, output = self._runner([OSASCRIPT, "-e", SCRIPT, verb, sheet, path], STEP_TIMEOUT_S)
        if code == 0:
            return
        match = _ERROR.search(output)
        reason = match.group(1) if match and match.group(1) in KNOWN_REASONS else "unknown"
        logger.warning("kicad live step=%s failed reason=%s", verb, reason)
        raise LiveEditError(verb, reason)

    def available(self, sheet: str, path: str) -> bool:
        try:
            self._step("available", sheet, path)
        except LiveEditError:
            return False
        return True

    def save(self, sheet: str, path: str) -> None:
        self._step("save", sheet, path)

    def revert(self, sheet: str, path: str) -> None:
        self._step("revert", sheet, path)


def default_live_editor() -> LiveEditor | None:
    return OsascriptEditor() if sys.platform == "darwin" else None


def live_editor() -> LiveEditor | None:
    """Indirection the tests replace; production uses the osascript driver."""
    return default_live_editor()


def wait_until_settled(read: Callable[[], bytes | None]) -> None:
    """KiCad writes asynchronously after Save; wait until two reads agree."""
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
RESAVE_FAILED_NOTE = (
    "KiCad shows the change, but did not re-save it in its own format; the next live "
    "edit may be refused once as stale and need one retry."
)
RELOAD_FAILED_NOTE = (
    "The change is written to disk, but KiCad did not reload it. In KiCad use File → "
    "Revert now, and do not save first — saving would overwrite this change."
)

#: Plans whose preview showed the live handshake: (path, before, after) -> expiry.
_LIVE_PREVIEWS: dict[tuple[str, str | None, str], float] = {}


def _key(plan: MutationPlan) -> tuple[str, str | None, str]:
    return (plan.path, plan.before_fingerprint, plan.after_fingerprint)


def remember_live_preview(plan: MutationPlan) -> None:
    now = time.monotonic()
    for key in [k for k, expiry in _LIVE_PREVIEWS.items() if expiry <= now]:
        del _LIVE_PREVIEWS[key]
    _LIVE_PREVIEWS[_key(plan)] = now + LIVE_PREVIEW_TTL_S


def consume_live_preview(plan: MutationPlan) -> bool:
    expiry = _LIVE_PREVIEWS.pop(_key(plan), None)
    return expiry is not None and expiry > time.monotonic()


def _sheet(relative: str) -> str:
    return PurePosixPath(relative).stem


def open_sheet_editor(root: Path, relative: str) -> LiveEditor | None:
    """The live editor for a sheet KiCad holds open; refuses `open_in_editor`
    when the sheet is open but no driver can reach its window. None = not open."""
    if not editor_lock_present(root, relative):
        return None
    editor = live_editor()
    if editor is None or not editor.available(_sheet(relative), str(root / relative)):
        raise DevelopmentError("open_in_editor")
    return editor


def live_commit(root: Path, plan: MutationPlan, editor: LiveEditor) -> dict[str, Any]:
    """ADR-040 handshake: save in KiCad (confirmed clean) -> strict write -> Revert."""
    if not consume_live_preview(plan):
        raise DevelopmentError("live_preview_required")
    sheet, path = _sheet(plan.path), str(root / plan.path)
    try:
        editor.save(sheet, path)
    except LiveEditError as exc:
        raise DevelopmentError("open_in_editor") from exc
    wait_until_settled(lambda: read_schematic(root, plan.path))
    commit_plan(root, plan, editor_saved=True)
    try:
        editor.revert(sheet, path)
    except LiveEditError as exc:
        return {
            "kicad_reload": "failed",
            "kicad_reload_reason": exc.reason,
            "kicad_reload_note": RELOAD_FAILED_NOTE,
        }
    return {"kicad_reload": "reloaded", **_resave(root, plan, editor)}


def _resave(root: Path, plan: MutationPlan, editor: LiveEditor) -> dict[str, Any]:
    """ADR-040 amendment step (d): re-save the reloaded sheet so the file is in
    KiCad's canonical form; report the fingerprint actually on disk."""
    sheet, path = _sheet(plan.path), str(root / plan.path)
    result: dict[str, Any] = {}
    try:
        editor.save(sheet, path)
    except LiveEditError as exc:
        result = {
            "kicad_resave": "failed",
            "kicad_resave_reason": exc.reason,
            "kicad_resave_note": RESAVE_FAILED_NOTE,
        }

    def read() -> bytes:
        return read_schematic(root, plan.path)

    wait_until_settled(read)
    return {**result, "after_fingerprint": fingerprint(read())}
