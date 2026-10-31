"""SOLUSDEV-320 T4 — capability-hygiene ratchet over the shared reasoning code.

`graph/`, `checkers/`, `impact/`, `livebench/findings/`, `simulation/`, `agent/vision/`,
`software/`, `agent/context.py`,
`agent/deterministic.py`, `agent/deterministic_facts.py`, `agent/finding_narration.py`,
`agent/layers.py`, `agent/project_card.py`, `agent/reason.py`, `agent/solus_layer.py`,
`agent/turn_scope.py`, P7's `agent/reasoning_frame.py` and `agent/citations.py`, P8's
`services/outcomes.py` and `services/change_signals.py`, and
the retrieval tools (`agent/tools/read_tool.py`, `search_tools.py`, `finding_tools.py`,
`machine_tools.py`) ask the registry for a *capability*;
they never name a vendor or a connector. Word-boundary, case-insensitive.
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
SWEEP_TREES: Final = (
    "graph",
    "checkers",
    "impact",
    "livebench/findings",
    "simulation",
    "agent/vision",
    "software",
)
SWEEP_FILES: Final = (
    "agent/context.py",
    "agent/layers.py",
    "agent/project_card.py",
    "agent/reason.py",
    "agent/solus_layer.py",
    "agent/turn_scope.py",
    "agent/deterministic.py",
    "agent/deterministic_facts.py",
    "agent/finding_narration.py",
    "agent/reasoning_frame.py",
    "agent/citations.py",
    "services/outcomes.py",
    "services/change_signals.py",
    "agent/tools/read_tool.py",
    "agent/tools/search_tools.py",
    "agent/tools/finding_tools.py",
    "agent/tools/machine_tools.py",
)
VENDOR_WORDS: Final = re.compile(
    r"\b(onshape|kicad|altium|fusion|solidworks|github|gitlab|isaac|gazebo|mujoco|foxglove"
    r"|ngspice)\b",
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


def test_the_findings_package_is_under_the_ratchet() -> None:
    """P2's envelope package is swept from its first file (SOLUSDEV-321 P2-T1): a simulator or a
    product named in `livebench/findings/` fails here, not in review."""
    swept = {p.relative_to(SRC_ROOT).as_posix() for p in sweep(SRC_ROOT, SWEEP_TREES, ())}
    assert "livebench/findings/__init__.py" in swept


def test_the_simulation_package_is_under_the_ratchet() -> None:
    """P4's simulation package is swept from its first file with no exclusion (SOLUSDEV-321
    P4-T1): a simulator or a routing target named in `simulation/` fails here, not in review. The
    yaml names the targets; a provider line that must name a simulator says so with the allow
    comment, and the report lists it."""
    swept = {p.relative_to(SRC_ROOT).as_posix() for p in sweep(SRC_ROOT, SWEEP_TREES, ())}
    assert "simulation/__init__.py" in swept
    assert "simulation" in SWEEP_TREES


def test_the_vision_package_is_under_the_ratchet() -> None:
    """P5's perception package is swept from its first file (SOLUSDEV-321 P5): a renderer is
    picked by what the entity has (a scene model, or a source whose connector declares
    `Capability.RENDER`), so a simulator, a CAD tool or an EDA tool named in `agent/vision/`
    fails here, not in review."""
    swept = {p.relative_to(SRC_ROOT).as_posix() for p in sweep(SRC_ROOT, SWEEP_TREES, ())}
    assert "agent/vision/__init__.py" in swept
    assert "agent/vision" in SWEEP_TREES


def test_the_software_package_is_under_the_ratchet() -> None:
    """P6's software readers are swept from the package's first file (SOLUSDEV-321 P6): a ROS
    workspace and a policy are read by structure, so a code host, a CAD tool or a simulator named
    in `software/` fails here, not in review."""
    swept = {p.relative_to(SRC_ROOT).as_posix() for p in sweep(SRC_ROOT, SWEEP_TREES, ())}
    assert "software/__init__.py" in swept
    assert "software" in SWEEP_TREES


def test_the_circuit_simulator_is_a_word_the_ratchet_catches(tmp_path: Path) -> None:
    """SOLUSDEV-321 P4-T3: rung 3 runs a pinned circuit simulator, and shared code names it only on
    a line that says why (`# capability-hygiene: allow <reason>`), as it does the physics engine.
    The setting `ngspice_bin` is not the word: a name that runs on into `_bin` has no boundary."""
    (tmp_path / "simulation").mkdir()
    (tmp_path / "simulation" / "rung3.py").write_text(
        'TOOL = "ngspice"\n'
        "binary = settings.ngspice_bin\n"
        'PINNED = "ngspice"  # capability-hygiene: allow the binary the setting pins\n'
    )
    offenders, allowed = capability_offenders(tmp_path, sweep(tmp_path, ("simulation",), ()))
    assert offenders == ['simulation/rung3.py:1: [ngspice] TOOL = "ngspice"']
    assert len(allowed) == 1 and allowed[0].startswith("simulation/rung3.py:3: [ngspice]")


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
