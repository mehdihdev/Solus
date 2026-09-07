"""SOLUSDEV-249 — the suffix→tool table, skip list, and caps from
docs/api/local-folder.md §1/§4."""

import pytest

from .local_paths import overlay_module  # isort: skip

toolmap = overlay_module("toolmap")


@pytest.mark.parametrize(
    ("path", "tool"),
    [
        ("hw/main/main.kicad_pro", "kicad"),
        ("hw/main/main.kicad_sch", "kicad"),
        ("hw/main/main.kicad_pcb", "kicad"),
        ("hw/Board.PrjPcb", "altium"),
        ("hw/Sheet1.SchDoc", "altium"),
        ("hw/Board.PcbDoc", "altium"),
        ("mech/frame.step", "cad"),
        ("mech/frame.stp", "cad"),
        ("mech/frame.STEP", "cad"),
        ("mech/bracket.sldprt", "cad"),
        ("mech/asm.sldasm", "cad"),
        ("mech/old.iges", "cad"),
        ("mech/old.igs", "cad"),
        ("mech/fusion.f3d", "cad"),
        ("fw/blink/blink.ino", "arduino"),
        ("tools/flash.py", "python"),
        ("README.md", None),
        ("main.kicad_prl", None),
        ("archive.zip", None),
        ("noext", None),
        ("weird.PY", "python"),
    ],
)
def test_tool_for_maps_suffixes(path: str, tool: str | None) -> None:
    assert toolmap.tool_for(path) == tool


def test_skip_dirs_are_the_documented_eight() -> None:
    assert toolmap.SKIP_DIRS == frozenset(
        {".git", "node_modules", ".venv", "venv", "__pycache__", "build", "dist", "solus-artifacts"}
    )


def test_caps_match_the_route_plan() -> None:
    assert toolmap.MAX_FILES == 2000
    assert toolmap.MAX_HASH_BYTES == 32 * 1024 * 1024


def test_every_table_suffix_is_lowercase_and_dotted() -> None:
    for suffixes in toolmap.TOOL_SUFFIXES.values():
        for suffix in suffixes:
            assert suffix.startswith(".") and suffix == suffix.lower()
