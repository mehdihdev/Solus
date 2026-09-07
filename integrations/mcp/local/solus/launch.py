"""`open_in_tool` (docs/api/local-folder.md §4): argument-list launches only.

macOS `/usr/bin/open -a <App> -- <path>` (bare `open -- <path>` for `system`),
Linux the resolved binary or `/usr/bin/xdg-open`, Windows the detected
executable or `os.startfile`. The path must resolve inside the workspace
(`workspace.resolve_inside`) or the answer is `launched: false` with the
documented reason. The child is detached (no wait). Never `shell=True`,
never raises.
"""

import logging
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .detect import find_tool
from .workspace import resolve_inside

logger = logging.getLogger("solus.local.launch")

SUPPORTED_TOOLS: frozenset[str] = frozenset({"kicad", "altium", "vscode", "system"})
OUTSIDE_REASON = "path is outside the linked folder"
LAUNCH_FAILED_REASON = "launch failed"

_NOT_INSTALLED: dict[str, str] = {
    "kicad": "KiCad is not installed on this machine",
    "altium": "Altium Designer is not installed on this machine",
    "vscode": "Visual Studio Code is not installed on this machine",
}
_MAC_OPEN = "/usr/bin/open"
_LINUX_XDG_OPEN = "/usr/bin/xdg-open"

Runner = Callable[[list[str]], None]
StartFile = Callable[[str], None]
Finder = Callable[..., str | None]


def spawn_detached(argv: list[str]) -> None:
    """Fire-and-forget: argv list, no shell, own session, no inherited fds."""
    subprocess.Popen(  # noqa: S603 - fixed absolute binary + workspace-confined path
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def _default_startfile(path: str) -> None:
    starter = getattr(os, "startfile", None)
    if starter is None:
        raise OSError("os.startfile is unavailable on this platform")
    starter(path)


def _answer(tool: str, *, launched: bool, reason: str | None = None) -> dict[str, Any]:
    return {"launched": launched, "tool": tool, "reason": reason}


def build_argv(tool: str, target: Path, platform: str, binary: str | None) -> list[str] | None:
    """The argv for a launch, or None when the platform/tool needs `startfile`
    or is unsupported. `binary` is the `find_tool` result (app name on macOS,
    executable elsewhere); `system` needs none."""
    path = str(target)
    if platform == "darwin":
        return (
            [_MAC_OPEN, "--", path]
            if tool == "system"
            else [_MAC_OPEN, "-a", str(binary), "--", path]
        )
    if platform.startswith("linux"):
        return [_LINUX_XDG_OPEN, path] if tool == "system" else [str(binary), path]
    if platform == "win32" and tool != "system":
        return [str(binary), path]
    return None


def open_in_tool(
    root: Path,
    path: str,
    tool: str,
    *,
    platform: str | None = None,
    run: Runner = spawn_detached,
    startfile: StartFile = _default_startfile,
    find: Finder = find_tool,
) -> dict[str, Any]:
    """`{launched, tool, reason}` per §4. Never raises."""
    system = platform or sys.platform
    if tool not in SUPPORTED_TOOLS:
        return _answer(tool, launched=False, reason=f"unsupported tool: {tool}")
    target = resolve_inside(path, root=root)
    if target is None:
        exists_but_missing = _looks_like_missing(root, path)
        reason = f"file not found: {path}" if exists_but_missing else OUTSIDE_REASON
        return _answer(tool, launched=False, reason=reason)
    binary: str | None = None
    if tool != "system":
        binary = find(tool, platform=system)
        if binary is None:
            return _answer(tool, launched=False, reason=_NOT_INSTALLED[tool])
    try:
        argv = build_argv(tool, target, system, binary)
        if argv is not None:
            run(argv)
        elif system == "win32":
            startfile(str(target))
        else:
            return _answer(tool, launched=False, reason=f"unsupported platform: {system}")
    except Exception as exc:  # noqa: BLE001 - the tool answers, never raises
        # The exception text stays in the stderr log: OS errors embed absolute
        # paths and the username, which must not cross the bridge.
        logger.warning("open_in_tool %s failed: %s", tool, exc)
        return _answer(tool, launched=False, reason=LAUNCH_FAILED_REASON)
    return _answer(tool, launched=True)


def _looks_like_missing(root: Path, path: str) -> bool:
    """True when `path` is a well-formed relative path that simply does not
    exist (so the reason can say so instead of implying an escape)."""
    from .workspace import is_safe_relative

    if not is_safe_relative(path):
        return False
    try:
        return not (root / path).exists() and not (root / path).is_symlink()
    except OSError:
        return False
