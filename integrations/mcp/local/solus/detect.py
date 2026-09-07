"""Installed-tool probing (docs/api/local-folder.md §4): probed, never assumed.

macOS: app bundles under /Applications. Linux: `shutil.which`. Windows: the
documented install roots below. Altium Designer is Windows-only and reports
false elsewhere. Every probe is injectable so tests never touch the machine,
and a failing probe reads as "not installed".
"""

import os
import shutil
import sys
from collections.abc import Callable
from typing import TypedDict

TOOLS: tuple[str, ...] = ("kicad", "altium", "vscode")

#: macOS: `open -a <name>` targets, with the bundle paths that prove them.
_DARWIN_APPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "kicad": ("KiCad", ("/Applications/KiCad/KiCad.app", "/Applications/KiCad.app")),
    "vscode": ("Visual Studio Code", ("/Applications/Visual Studio Code.app",)),
}
_LINUX_BINARIES: dict[str, str] = {"kicad": "kicad", "vscode": "code"}

#: Windows documented roots. KiCad installs one versioned directory per
#: release under Program Files; Altium Designer as `AD<yy>`; VS Code either
#: system-wide or per-user under AppData.
_WIN_KICAD_ROOTS = ("C:\\Program Files\\KiCad", "C:\\Program Files (x86)\\KiCad")
_WIN_ALTIUM_ROOT = "C:\\Program Files\\Altium"
_WIN_VSCODE_SYSTEM = "C:\\Program Files\\Microsoft VS Code\\Code.exe"
_WIN_VSCODE_USER_SUFFIX = "AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe"

Exists = Callable[[str], bool]
Which = Callable[[str], str | None]
ListDir = Callable[[str], list[str]]


class ToolsInstalled(TypedDict):
    kicad: bool
    altium: bool
    vscode: bool


def _default_listdir(path: str) -> list[str]:
    return sorted(os.listdir(path)) if os.path.isdir(path) else []


def _first_existing(candidates: list[str], exists: Exists) -> str | None:
    return next((candidate for candidate in candidates if exists(candidate)), None)


def _find_darwin(tool: str, exists: Exists) -> str | None:
    entry = _DARWIN_APPS.get(tool)
    if entry is None:
        return None
    app_name, bundles = entry
    return app_name if _first_existing(list(bundles), exists) else None


def _find_linux(tool: str, which: Which) -> str | None:
    binary = _LINUX_BINARIES.get(tool)
    return which(binary) if binary else None


def _find_windows(tool: str, exists: Exists, listdir: ListDir, home: str) -> str | None:
    if tool == "kicad":
        candidates = [
            f"{root}\\{version}\\bin\\kicad.exe"
            for root in _WIN_KICAD_ROOTS
            for version in sorted(listdir(root), reverse=True)
        ]
    elif tool == "altium":
        candidates = [
            f"{_WIN_ALTIUM_ROOT}\\{name}\\X2.EXE"
            for name in sorted(listdir(_WIN_ALTIUM_ROOT), reverse=True)
            if name.upper().startswith("AD")
        ]
    elif tool == "vscode":
        candidates = [_WIN_VSCODE_SYSTEM]
        if home:
            candidates.append(f"{home}\\{_WIN_VSCODE_USER_SUFFIX}")
    else:
        return None
    return _first_existing(candidates, exists)


def find_tool(
    tool: str,
    *,
    platform: str | None = None,
    exists: Exists = os.path.exists,
    which: Which = shutil.which,
    listdir: ListDir = _default_listdir,
    home: str | None = None,
) -> str | None:
    """The launch target for `tool` on this platform — the `open -a` app name
    on macOS, the resolved binary on Linux, the executable on Windows — or
    None when it is not installed (or the probe fails)."""
    system = platform or sys.platform
    try:
        if system == "darwin":
            return _find_darwin(tool, exists)
        if system.startswith("linux"):
            return _find_linux(tool, which)
        if system == "win32":
            user_home = os.environ.get("HOME", "") if home is None else home
            return _find_windows(tool, exists, listdir, user_home)
    except Exception:  # noqa: BLE001 - a failing probe reads as "not installed"
        return None
    return None


def tools_installed(
    *,
    platform: str | None = None,
    exists: Exists = os.path.exists,
    which: Which = shutil.which,
    listdir: ListDir = _default_listdir,
    home: str | None = None,
) -> ToolsInstalled:
    """`{kicad, altium, vscode}` → bool, probed per platform. Never raises."""
    found = {
        tool: find_tool(
            tool, platform=platform, exists=exists, which=which, listdir=listdir, home=home
        )
        is not None
        for tool in TOOLS
    }
    return {"kicad": found["kicad"], "altium": found["altium"], "vscode": found["vscode"]}
