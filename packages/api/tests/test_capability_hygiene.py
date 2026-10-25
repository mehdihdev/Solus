"""SOLUSDEV-320 T4 — capability-hygiene ratchet over the shared reasoning code.

`graph/`, `checkers/`, `impact/` and `agent/context.py` ask the registry for a
*capability*; they never name a vendor or a connector. Word-boundary, case-insensitive.
Unlike the vendor ratchets, a line ending in `# capability-hygiene: allow <reason>` is
exempt (plan resolution 23): the allowed lines are collected and printed so the report
can list them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import solus_api

SRC_ROOT: Final = Path(solus_api.__file__).resolve().parent
SWEEP_TREES: Final = ("graph", "checkers", "impact")
SWEEP_FILES: Final = ("agent/context.py",)
VENDOR_WORDS: Final = re.compile(
    r"\b(onshape|kicad|altium|fusion|solidworks|github|gitlab|isaac|gazebo|mujoco|foxglove)\b",
    re.IGNORECASE,
)
ALLOW: Final = re.compile(r"#\s*capability-hygiene:\s*allow\s+\S.*$")


def sweep(root: Path, trees: tuple[str, ...], files: tuple[str, ...]) -> list[Path]:
    paths = [p for tree in trees for p in sorted((root / tree).rglob("*.py"))]
    paths += [root / f for f in files if (root / f).is_file()]
    return paths


def capability_offenders(root: Path, paths: list[Path]) -> tuple[list[str], list[str]]:
    """(offenders, allowed) as `path:lineno: [word] line`."""
    offenders: list[str] = []
    allowed: list[str] = []
    for path in paths:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = VENDOR_WORDS.search(line)
            if not match:
                continue
            row = f"{path.relative_to(root)}:{lineno}: [{match.group(0)}] {line.strip()}"
            (allowed if ALLOW.search(line) else offenders).append(row)
    return offenders, allowed


def test_shared_reasoning_code_names_no_vendor() -> None:
    paths = sweep(SRC_ROOT, SWEEP_TREES, SWEEP_FILES)
    assert len(paths) > 10, f"nothing to sweep under {SRC_ROOT}"
    offenders, allowed = capability_offenders(SRC_ROOT, paths)
    print("capability-hygiene allowed lines:", allowed or "none")
    assert not offenders, (
        "Shared code asks the registry for a capability, never a vendor. Offenders:\n"
        + "\n".join(offenders)
    )


def test_ratchet_catches_an_injected_vendor_and_honours_the_allow_comment(
    tmp_path: Path,
) -> None:
    (tmp_path / "graph").mkdir()
    (tmp_path / "graph" / "rogue.py").write_text(
        'KIND = "kicad"\n'
        'ALLOWED = "onshape"  # capability-hygiene: allow entity-kind literal\n'
        'BARE = "altium"  # capability-hygiene: allow\n'
        "clean = 1\n"
    )
    offenders, allowed = capability_offenders(tmp_path, sweep(tmp_path, ("graph",), ()))
    assert offenders == [
        'graph/rogue.py:1: [kicad] KIND = "kicad"',
        'graph/rogue.py:3: [altium] BARE = "altium"  # capability-hygiene: allow',
    ]
    assert allowed == [
        'graph/rogue.py:2: [onshape] ALLOWED = "onshape"  '
        "# capability-hygiene: allow entity-kind literal"
    ]
