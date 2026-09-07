"""The suffix→tool table, skip list, and caps (docs/api/local-folder.md §1/§4).

Suffix matching is case-insensitive (`.STEP`, `.PY`) — the table is stored
lowercase and the probe lowercases the candidate.
"""

from pathlib import PurePath

TOOL_SUFFIXES: dict[str, frozenset[str]] = {
    "kicad": frozenset({".kicad_pro", ".kicad_sch", ".kicad_pcb"}),
    "altium": frozenset({".prjpcb", ".schdoc", ".pcbdoc"}),
    "cad": frozenset({".step", ".stp", ".sldprt", ".sldasm", ".iges", ".igs", ".f3d"}),
    "arduino": frozenset({".ino"}),
    "python": frozenset({".py"}),
}

_SUFFIX_TO_TOOL: dict[str, str] = {
    suffix: tool for tool, suffixes in TOOL_SUFFIXES.items() for suffix in suffixes
}

SKIP_DIRS: frozenset[str] = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", "build", "dist", "solus-artifacts"}
)

#: Scan ceiling: past this many tool-relevant files the result is `truncated`.
MAX_FILES = 2000
#: Files larger than this report `hash: null` (the digest uses the size).
MAX_HASH_BYTES = 32 * 1024 * 1024
#: Streaming read size for the per-file blake2b-128 hash.
HASH_CHUNK_BYTES = 1024 * 1024


def tool_for(path: str | PurePath) -> str | None:
    """The tool a file belongs to by suffix, or None when it is not relevant."""
    return _SUFFIX_TO_TOOL.get(PurePath(path).suffix.lower())
