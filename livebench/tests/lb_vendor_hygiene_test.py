"""Phase 6 proof (b) — vendor-hygiene ratchet (docs/architecture/hardware-onboarding.md §Layout).

Everything between the port and the graph is vendor-free: a word-boundary, case-insensitive
sweep over the shared trees reports EVERY hit (no allowlist), only `plugins/` and
`definitions/` may name a product anywhere under `livebench/src`, importing the shared loop in a
fresh interpreter pulls in no plugin, and the plugin roster lives under `livebench.plugins.`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Final

from livebench.plugins import PLUGIN_MODULES

import livebench

SRC: Final = Path(livebench.__file__).resolve().parent
SHARED_TREES: Final = ("hardware", "recognition", "telemetry")
SHARED_FILES: Final = ("local.py",)
VENDOR_TREES: Final = frozenset({"plugins", "definitions"})
VENDOR_WORDS: Final = re.compile(
    r"\b(feetech|dynamixel|lerobot|sts3215|sts3250|scs0009|so-?10[01]|px4|pixhawk|odrive"
    r"|myactuator|mavlink|unitree|ur5e?|arduino|teensy|esp32|ch343|cp210x|ft232|pl2303"
    r"|xl330|xm430|robotis)\b",
    re.IGNORECASE,
)
_SHARED_LOOP_IMPORT: Final = (
    "import sys; import livebench.hardware.detection, livebench.hardware.connection, "
    "livebench.hardware.registries; "
    "sys.exit(1 if any(m.startswith('livebench.plugins') for m in sys.modules) else 0)"
)


def _p6_vendor_hits(paths: list[Path]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            match = VENDOR_WORDS.search(line)
            if match:
                hits.append(f"{path.relative_to(SRC)}:{lineno}: [{match.group(0)}] {line.strip()}")
    return hits


def _p6_shared_files() -> list[Path]:
    files = [p for tree in SHARED_TREES for p in sorted((SRC / tree).rglob("*.py"))]
    files += [SRC / name for name in SHARED_FILES]
    assert len(files) > 20, files
    return files


def test_shared_trees_name_no_vendor() -> None:
    hits = _p6_vendor_hits(_p6_shared_files())
    assert not hits, "vendor names belong in plugins/ or definitions/ only:\n" + "\n".join(hits)


def test_only_plugins_and_definitions_name_vendors() -> None:
    outside = [
        p for p in sorted(SRC.rglob("*.py")) if p.relative_to(SRC).parts[0] not in VENDOR_TREES
    ]
    hits = _p6_vendor_hits(outside)
    assert not hits, "a vendor is named outside plugins/ and definitions/:\n" + "\n".join(hits)
    assert any(_p6_vendor_hits(sorted((SRC / tree).rglob("*.py"))) for tree in VENDOR_TREES)


def test_importing_the_shared_loop_loads_no_plugin_in_a_fresh_interpreter() -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _SHARED_LOOP_IMPORT], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr


def test_the_plugin_roster_lives_under_livebench_plugins() -> None:
    assert PLUGIN_MODULES and all(m.startswith("livebench.plugins.") for m in PLUGIN_MODULES)
