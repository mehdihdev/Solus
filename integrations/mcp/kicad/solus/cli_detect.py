"""Headless kicad-cli detection under the launcher's pinned posture.

Availability is detected ONCE per process (`functools.cache`) and consulted
by every kicad-cli-backed tool: absent or broken CLI means `degraded: true`
with one of the stable reasons below — never an exception, never a non-zero
exit (SOLUSDEV-100 T1b goal 3).

Deliberately NOT upstream's `kicad_mcp.utils.kicad_cli` prober: that walks
user-influenced "common installation paths", which defeats the launcher's
pinned-binary posture (CLAUDE.md §7). Here the CLI comes only from the
`KICAD_CLI_PATH` the launcher passes through, or from the launcher's fixed
`PATH=/usr/bin:/bin` constant. Tested by tests/test_overlay_headless_degrade.py.
"""

import functools
import os
import shutil
import subprocess
from pathlib import Path

# Stable degradation reasons (asserted verbatim by tests and shown to users).
KICAD_CLI_UNAVAILABLE_REASON = (
    "kicad-cli unavailable (headless posture): "
    "kicadxml synthesized from the KiCad-free schematic file parse"
)
KICAD_CLI_FAILED_REASON = (
    "kicad-cli export failed: kicadxml synthesized from the KiCad-free schematic file parse"
)


@functools.cache
def detect_kicad_cli() -> str | None:
    """The pinned kicad-cli executable, or None on a headless machine.

    Detection order: the launcher-passed `KICAD_CLI_PATH` (must be an
    executable regular file), then the launcher's fixed PATH constant via
    `shutil.which`. Cached for the life of the process — availability is a
    launch-posture fact, not a per-call question.
    """
    pinned = os.environ.get("KICAD_CLI_PATH", "")
    if _trusted_pinned(pinned):
        return pinned
    native = shutil.which("kicad-cli")
    if native is not None:
        return native
    return _flatpak_cli()


def _trusted_pinned(pinned: str) -> bool:
    """An absolute executable regular file that does not live in the (untrusted)
    project workspace — the launcher's cwd — so repo content can never be run."""
    if not (pinned and os.path.isabs(pinned) and os.path.isfile(pinned)):
        return False
    if not os.access(pinned, os.X_OK):
        return False
    workspace = os.environ.get("SOLUS_MCP_WORKSPACE", "")
    if workspace:
        root = os.path.realpath(workspace)
        if os.path.commonpath([root, os.path.realpath(pinned)]) == root:
            return False
    return True


def _flatpak_cli() -> str | None:
    discovered = shutil.which("flatpak")
    if discovered is None or os.path.realpath(discovered) != "/usr/bin/flatpak":
        return None
    try:
        result = subprocess.run(
            ["/usr/bin/flatpak", "info", "--show-ref", "org.kicad.KiCad"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.startswith(b"app/org.kicad.KiCad/"):
        return None
    adapter = Path(__file__).resolve().parents[1] / "bin/kicad-cli-flatpak"
    return str(adapter) if adapter.is_file() and os.access(adapter, os.X_OK) else None
