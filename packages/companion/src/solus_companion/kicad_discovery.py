"""Locate the customer's installed `kicad-cli` (SOLUSDEV-100 gap: install discovery).

The kicad fork runs under a scrubbed `PATH=/usr/bin:/bin` and never probes for
installs itself (pinned-binary posture, CLAUDE.md §7), so on macOS and Windows
it could not find KiCad. The companion, which runs as the user, looks in a FIXED
set of absolute, OS-specific locations and hands the result to the fork as
`KICAD_CLI_PATH`. Nothing here reads the ambient environment or a search path:
a hostile `PATH`/`KICAD_CLI_PATH` cannot redirect it.
"""

import os
import sys

KICAD_CLI_ENV = "KICAD_CLI_PATH"

# Newest first; KiCad ships one major per install directory on Windows.
_KICAD_MAJORS = ("10.0", "9.0", "8.0")

_CANDIDATES: dict[str, tuple[str, ...]] = {
    "darwin": ("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",),
    "linux": ("/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli"),
    "win32": tuple(
        f"C:\\Program Files\\KiCad\\{major}\\bin\\kicad-cli.exe" for major in _KICAD_MAJORS
    ),
}


def candidate_paths(platform: str) -> tuple[str, ...]:
    """The fixed install locations probed on *platform* (empty if unsupported)."""
    return _CANDIDATES.get(platform, ())


def _is_pinnable(path: str) -> bool:
    """An absolute path naming a regular, executable file."""
    return os.path.isabs(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def find_kicad_cli(candidates: tuple[str, ...] | None = None) -> str | None:
    """The first installed `kicad-cli`, or None. *candidates* is a test seam."""
    for path in candidate_paths(sys.platform) if candidates is None else candidates:
        if _is_pinnable(path):
            return os.path.realpath(path)
    return None
